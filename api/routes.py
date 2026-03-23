"""
api/routes.py
==============
FastAPI router — replaces Flask Blueprint.
All endpoints identical to before, now using FastAPI.
Auto-docs available at: http://localhost:5000/docs
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, Response
from typing import Optional
from datetime import datetime, timedelta

router = APIRouter()

# ── Helper ────────────────────────────────
def js(data):
    return JSONResponse(content=data)


# ── Network info ──────────────────────────

@router.get("/api/network/info")
def network_info():
    from utils.network import get_network_info
    from db.database import get_connection
    from config import DB_FILE
    info = get_network_info()
    try:
        conn = get_connection(DB_FILE)
        conn.execute("""CREATE TABLE IF NOT EXISTS network_state (
            key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)""")
        row = conn.execute(
            "SELECT value FROM network_state WHERE key='current_gateway'"
        ).fetchone()
        info["saved_gateway"] = row["value"] if row else None
        info["gateway_changed"] = (
            info["saved_gateway"] is not None and
            info["gateway"] != info["saved_gateway"]
        )
        conn.close()
    except Exception:
        pass
    return js(info)


@router.post("/api/network/validate")
async def network_validate(request: Request):
    from utils.network import validate_router_ip
    data = await request.json()
    ip   = data.get("ip", "").strip()
    if not ip:
        return js({"ok": False, "error": "empty",
                   "message": "Please enter your router IP address."})
    return js(validate_router_ip(ip))


# ── Control ───────────────────────────────

@router.post("/api/control/start")
async def control_start(request: Request):
    from utils.network import validate_router_ip
    app_state  = request.app.state
    pm         = app_state.process_manager
    data       = await request.json()
    router_ip  = data.get("router_ip", "").strip()
    if not router_ip:
        return js({"ok": False, "msg": "Please enter your router IP address."})
    validation = validate_router_ip(router_ip)
    if not validation["ok"]:
        return js({"ok": False, "msg": validation["message"],
                   "suggested_ip": validation.get("suggested_ip"),
                   "error": validation.get("error")})
    if validation.get("warning"):
        result = pm.start(router_ip)
        result["warning"] = validation["message"]
        return js(result)
    return js(pm.start(router_ip))


@router.post("/api/control/stop")
def control_stop(request: Request):
    pm = request.app.state.process_manager
    return js(pm.stop())


@router.get("/api/control/status")
def control_status(request: Request):
    pm = request.app.state.process_manager
    return js(pm.status())


@router.get("/api/control/logs")
def control_logs(request: Request, since: int = 0):
    pm = request.app.state.process_manager
    return js(pm.get_logs(since))


# ── Stats ─────────────────────────────────

@router.get("/api/stats")
def stats():
    from db.queries import get_devices_with_status
    from db.database import get_connection
    from config import DB_FILE
    devices = get_devices_with_status()
    total   = len(devices)
    up      = sum(1 for d in devices if d["is_alive"] == 1)
    down    = sum(1 for d in devices if d["is_alive"] == 0)
    unknown = total - up - down
    rtts    = [d["rtt_avg_ms"] for d in devices if d["rtt_avg_ms"]]
    avg_rtt = round(sum(rtts)/len(rtts), 1) if rtts else None
    return js({"total": total, "up": up, "down": down,
               "unknown": unknown, "avg_rtt": avg_rtt})


# ── Devices ───────────────────────────────

@router.get("/api/devices")
def devices():
    from db.queries import get_devices_with_status
    from db.queries import get_all_uptimes
    devices = get_devices_with_status()
    uptimes = get_all_uptimes(hours=24)
    for d in devices:
        d["uptime"] = uptimes.get(d["ip"])
    return js(devices)


@router.get("/api/topology")
def topology():
    from db.queries import get_devices_with_status
    from utils.network import get_current_gateway
    devices = get_devices_with_status()
    gateway = get_current_gateway()
    nodes, edges = [], []
    for d in devices:
        status = ("up" if d["is_alive"]==1 else
                  "down" if d["is_alive"]==0 else "unknown")
        nodes.append({
            "id":        d["ip"],
            "ip":        d["ip"],
            "label":     d["name"] or d["ip"],
            "status":    status,
            "rtt":       d["rtt_avg_ms"],
            "loss":      d["packet_loss"],
            "uptime":    d.get("uptime"),
            "vendor":    d.get("vendor"),
            "mac":       d.get("mac"),
            "is_router": d["ip"] == gateway,
        })
        if d["ip"] != gateway:
            edges.append({"from": gateway, "to": d["ip"]})
    return js({"nodes": nodes, "edges": edges})


@router.get("/api/history/{ip}")
def history(ip: str):
    from db.database import get_connection
    from config import DB_FILE
    conn = get_connection(DB_FILE)
    rows = conn.execute("""
        SELECT timestamp, rtt_avg_ms, rtt_med_ms,
               packet_loss, jitter_ms, is_alive
        FROM probe_results WHERE host=?
        ORDER BY timestamp DESC LIMIT 200
    """, (ip,)).fetchall()
    conn.close()
    return js([dict(r) for r in rows])


# ── Alerts ────────────────────────────────

@router.get("/api/alerts")
def alerts():
    from db.database import get_connection
    from config import DB_FILE
    from utils.network import get_current_gateway
    conn    = get_connection(DB_FILE)
    gateway = get_current_gateway()
    base    = ".".join((gateway or "").split(".")[:3]) + "."
    rows    = conn.execute("""
        SELECT * FROM state_changes
        ORDER BY timestamp DESC LIMIT 100
    """).fetchall()
    conn.close()
    result = [dict(r) for r in rows
              if dict(r).get("host","").startswith(base)
              or dict(r).get("host") in ("8.8.8.8","1.1.1.1")]
    return js(result)


@router.get("/api/alerts/config")
def alerts_config():
    from config import (ALERT_EMAIL_ENABLED, ALERT_EMAIL_FROM,
                        ALERT_EMAIL_TO, ALERT_EMAIL_SMTP)
    return js({
        "email_enabled": ALERT_EMAIL_ENABLED,
        "email_from":    ALERT_EMAIL_FROM,
        "email_to":      ALERT_EMAIL_TO,
        "smtp":          ALERT_EMAIL_SMTP,
    })


@router.post("/api/alerts/save")
async def alerts_save(request: Request):
    data     = await request.json()
    env_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    updates  = {
        "ALERT_EMAIL_FROM":       data.get("from", ""),
        "ALERT_EMAIL_TO":         data.get("to", ""),
        "ALERT_EMAIL_PASSWORD":   data.get("password", ""),
        "ALERT_EMAIL_SMTP":       data.get("smtp", "smtp.gmail.com"),
        "ALERT_EMAIL_PORT":       str(data.get("port", "587")),
        "RTT_ALERT_THRESHOLD_MS": str(data.get("rtt_threshold", "200")),
        "ALERT_COOLDOWN_MINUTES": str(data.get("cooldown", "10")),
        "ALERT_EMAIL_ENABLED":    "true",
    }
    try:
        lines = open(env_path).readlines() if os.path.exists(env_path) else []
        existing_keys, new_lines = set(), []
        for line in lines:
            key = line.split("=")[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}\n")
                existing_keys.add(key)
            else:
                new_lines.append(line)
        for key, val in updates.items():
            if key not in existing_keys:
                new_lines.append(f"{key}={val}\n")
        open(env_path, "w").writelines(new_lines)
        return js({"ok": True,
                   "msg": "Configuration saved — restart to apply."})
    except Exception as e:
        return js({"ok": False, "msg": str(e)})


# ── Bandwidth ─────────────────────────────

@router.post("/api/bandwidth/start")
def bandwidth_start(request: Request):
    pm = request.app.state.process_manager
    return js(pm.start_bandwidth())

@router.post("/api/bandwidth/stop")
def bandwidth_stop(request: Request):
    pm = request.app.state.process_manager
    return js(pm.stop_bandwidth())

@router.get("/api/bandwidth/live")
def bandwidth_live():
    from db.queries import get_bandwidth_live
    try:
        return js(get_bandwidth_live())
    except Exception:
        return js([])

@router.get("/api/bandwidth/totals")
def bandwidth_totals():
    from db.queries import get_bandwidth_totals
    try:
        return js(get_bandwidth_totals())
    except Exception:
        return js({})

@router.get("/api/bandwidth/history/{ip}")
def bandwidth_history(ip: str):
    from db.database import get_connection
    from config import DB_FILE
    try:
        conn = get_connection(DB_FILE)
        rows = conn.execute("""
            SELECT timestamp,
                   bytes_in * 1.0 / 5 as rate_in,
                   bytes_out * 1.0 / 5 as rate_out
            FROM bandwidth_samples
            WHERE ip=?
            ORDER BY timestamp DESC LIMIT 100
        """, (ip,)).fetchall()
        conn.close()
        return js([dict(r) for r in reversed(rows)])
    except Exception:
        return js([])
# ── Reports ───────────────────────────────

@router.get("/api/report/{period}")
def generate_report(period: str):
    if period not in ("daily", "weekly"):
        raise HTTPException(400, "Invalid period. Use daily or weekly")
    try:
        from core.reports import generate_report as gen
        pdf   = gen(period)
        fname = (f"network_report_{period}_"
                 f"{datetime.now().strftime('%Y%m%d')}.pdf")
        return Response(content=pdf, media_type="application/pdf",
                        headers={"Content-Disposition":
                                 f"attachment; filename={fname}"})
    except ImportError:
        raise HTTPException(500, "reportlab not installed")
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Health ────────────────────────────────

@router.get("/api/health/current")
def health_current():
    try:
        from db.database import get_connection
        from utils.network import get_current_gateway
        from config import DB_FILE
        conn       = get_connection(DB_FILE)
        current_gw = get_current_gateway()
        session    = None
        if current_gw:
            sess_row = conn.execute("""
                SELECT * FROM router_sessions
                WHERE gateway_ip=?
                ORDER BY started_at DESC LIMIT 1
            """, (current_gw,)).fetchone()
            if sess_row:
                session = dict(sess_row)
                row = conn.execute("""
                    SELECT * FROM health_snapshots
                    WHERE session_id=?
                    ORDER BY timestamp DESC LIMIT 1
                """, (session["id"],)).fetchone()
                if row:
                    conn.close()
                    return js({"session": session, "latest": dict(row)})
        conn.close()
        return js({
            "session": {
                "gateway_ip": current_gw,
                "subnet": ".".join((current_gw or "").split(".")[:3])+".0/24",
                "label": f"Router ({current_gw})",
                "started_at": None,
            } if current_gw else None,
            "latest":  None,
            "waiting": True,
            "message": f"Collecting health data for {current_gw}..."
        })
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/health/sessions")
def health_sessions():
    try:
        from core.health import get_all_sessions
        return js(get_all_sessions())
    except Exception:
        return js([])


@router.get("/api/health/session/{session_id}")
def health_session_history(session_id: int):
    try:
        from core.health import get_session_history
        return js(get_session_history(session_id))
    except Exception:
        return js([])


@router.post("/api/health/session/{session_id}/label")
async def health_session_label(session_id: int, request: Request):
    try:
        from core.health import update_session_label
        data  = await request.json()
        label = data.get("label", "")
        update_session_label(session_id, label)
        return js({"ok": True})
    except Exception as e:
        return js({"ok": False, "msg": str(e)})


@router.get("/api/health/recommendation")
def health_recommendation():
    try:
        from core.health import get_router_recommendation
        return js(get_router_recommendation())
    except Exception as e:
        return js({"error": str(e)})


@router.get("/api/health/trend/{session_id}")
def health_trend(session_id: int):
    try:
        from core.health import compute_trend_weighted_score
        from db.database import get_connection
        from utils.network import get_current_gateway
        from config import DB_FILE
        conn       = get_connection(DB_FILE)
        current_gw = get_current_gateway()
        if current_gw:
            row = conn.execute("""
                SELECT id FROM router_sessions
                WHERE gateway_ip=?
                ORDER BY started_at DESC LIMIT 1
            """, (current_gw,)).fetchone()
            if row:
                session_id = row["id"]
        conn.close()
        return js(compute_trend_weighted_score(session_id))
    except Exception as e:
        return js({"error": str(e)})


# ── Hops ──────────────────────────────────

@router.get("/api/hops")
def all_hops():
    from db.queries import get_hop_routes
    return js(get_hop_routes())


@router.get("/api/hops/{ip}")
def hops_for_ip(ip: str):
    from db.queries import get_hop_route
    return js(get_hop_route(ip))


# ── Classify ──────────────────────────────

@router.get("/api/classify")
def classify():
    try:
        from core.classifier import get_classifications, DEVICE_TYPE_META
        data = get_classifications()
        for ip, info in data.items():
            dt   = info.get("device_type", "unknown")
            meta = DEVICE_TYPE_META.get(dt, DEVICE_TYPE_META["unknown"])
            info["meta"] = meta
        return js(data)
    except Exception:
        return js({})


# ── Anomalies ─────────────────────────────

@router.get("/api/anomalies")
def anomalies(hours: int = 24):
    try:
        from core.anomaly import get_recent_anomalies
        from utils.network import get_current_gateway
        events  = get_recent_anomalies(hours)
        gateway = get_current_gateway()
        base    = ".".join((gateway or "").split(".")[:3]) + "."
        events  = [e for e in events
                   if e.get("host","").startswith(base)
                   or e.get("host") in ("8.8.8.8","1.1.1.1")]
        return js(events)
    except Exception:
        return js([])


@router.get("/api/anomalies/summary")
def anomaly_summary():
    try:
        from core.anomaly import get_recent_anomalies
        from utils.network import get_current_gateway
        events  = get_recent_anomalies(24)
        gateway = get_current_gateway()
        base    = ".".join((gateway or "").split(".")[:3]) + "."
        events  = [e for e in events
                   if e.get("host","").startswith(base)
                   or e.get("host") in ("8.8.8.8","1.1.1.1")]
        by_type     = {}
        by_severity = {"critical": 0, "high": 0, "medium": 0}
        for e in events:
            t = e["anomaly_type"]
            by_type[t] = by_type.get(t, 0) + 1
            s = e.get("severity", "medium")
            by_severity[s] = by_severity.get(s, 0) + 1
        return js({"total": len(events), "by_type": by_type,
                   "by_severity": by_severity,
                   "latest": events[:5] if events else []})
    except Exception:
        return js({"total": 0, "by_type": {}, "by_severity": {}, "latest": []})


# ── Activity feed ─────────────────────────

@router.get("/api/activity")
def activity():
    try:
        from db.database import get_connection
        from config import DB_FILE
        conn  = get_connection(DB_FILE)
        since = (datetime.now() - timedelta(minutes=5)).isoformat()
        events = []
        rows = conn.execute("""
            SELECT 'state' as type, timestamp, name, host,
                   old_status, new_status
            FROM state_changes WHERE timestamp > ?
            ORDER BY timestamp DESC LIMIT 20
        """, (since,)).fetchall()
        for r in rows:
            d      = dict(r)
            status = d["new_status"]
            color  = ("#ef4444" if status=="DOWN" else
                      "#f59e0b" if status=="DEGRADED" else
                      "#22c55e" if status=="UP" else "#64748b")
            events.append({
                "type": "status", "timestamp": d["timestamp"],
                "title": f"{d['name']} -> {status}",
                "detail": f"{d['host']} was {d['old_status'] or 'unknown'}",
                "color": color,
            })
        try:
            rows2 = conn.execute("""
                SELECT timestamp, name, host, anomaly_type, severity, message
                FROM anomaly_events WHERE timestamp > ?
                ORDER BY timestamp DESC LIMIT 10
            """, (since,)).fetchall()
            for r in rows2:
                d     = dict(r)
                color = ("#ef4444" if d["severity"]=="critical" else
                         "#f59e0b" if d["severity"]=="high" else "#3b82f6")
                events.append({
                    "type": "anomaly", "timestamp": d["timestamp"],
                    "title": f"Anomaly: {d['anomaly_type']} on {d['name']}",
                    "detail": d["message"], "color": color,
                })
        except Exception:
            pass
        conn.close()
        events.sort(key=lambda x: x["timestamp"], reverse=True)
        return js(events[:30])
    except Exception:
        return js([])


# ── Device history & degradation ──────────

@router.get("/api/device/history/{ip}")
def device_history(ip: str, days: int = 30):
    try:
        from core.device_health import get_device_history
        return js(get_device_history(ip, days))
    except Exception:
        return js([])


@router.get("/api/device/degradation")
def device_degradation():
    try:
        from core.device_health import get_all_degradation
        return js(get_all_degradation())
    except Exception:
        return js([])


@router.get("/api/device/baseline/{ip}")
def device_baseline(ip: str):
    try:
        from core.device_health import get_device_baseline
        return js(get_device_baseline(ip))
    except Exception:
        return js({})


# ── ML Engine ─────────────────────────────

@router.get("/api/ml/status")
def ml_status():
    try:
        from core.ml_engine import get_model_status
        return js(get_model_status())
    except Exception as e:
        return js({"error": str(e)})


@router.get("/api/ml/predict/{ip}")
def ml_predict(ip: str):
    try:
        from core.ml_engine import predict_trend_ml
        return js(predict_trend_ml(ip))
    except Exception as e:
        return js({"error": str(e)})


@router.get("/api/ml/degradation/{ip}")
def ml_degradation(ip: str):
    try:
        from db.database import get_connection
        from config import DB_FILE
        from core.synthetic_data import predict_degradation_score
        conn = get_connection(DB_FILE)
        row  = conn.execute("""
            SELECT rtt_avg_ms, jitter_ms, packet_loss
            FROM probe_results WHERE host=?
            AND is_alive=1 ORDER BY timestamp DESC LIMIT 1
        """, (ip,)).fetchone()
        conn.close()
        if not row:
            return js({"score": None, "label": "no_data"})
        return js(predict_degradation_score(
            row["rtt_avg_ms"]   or 0,
            row["jitter_ms"]    or 0,
            (row["packet_loss"] or 0) * 100,
            100.0, 70.0
        ))
    except Exception as e:
        return js({"error": str(e)})


# ── Health sessions extra ─────────────────

@router.get("/api/health/sessions/all")
def health_all_sessions():
    try:
        from core.health import get_all_sessions
        return js(get_all_sessions())
    except Exception:
        return js([])


# ── Device rename ─────────────────────────

@router.post("/api/device/rename")
async def device_rename(request: Request):
    """Set a custom name for a device."""
    try:
        from db.database import get_connection
        from config import DB_FILE
        data = await request.json()
        ip   = data.get("ip", "").strip()
        name = data.get("name", "").strip()
        if not ip or not name:
            return js({"ok": False, "msg": "IP and name required"})
        conn = get_connection(DB_FILE)
        conn.execute(
            "UPDATE active_targets SET name=? WHERE ip=?", (name, ip))
        conn.commit()
        conn.close()
        return js({"ok": True, "msg": f"Renamed to {name}"})
    except Exception as e:
        return js({"ok": False, "msg": str(e)})