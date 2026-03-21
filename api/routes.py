import os
"""
api/routes.py
==============
All Flask API routes. Registered as a Blueprint.
"""

from flask import Blueprint, jsonify, request
from db.queries import (get_devices_with_status, get_topology, get_stats,
                        get_rtt_history, get_state_changes,
                        get_bandwidth_live, get_bandwidth_history,
                        get_bandwidth_totals)
from utils.network import validate_ip

api = Blueprint("api", __name__, url_prefix="/api")


# ── Monitor control ───────────────────────

@api.route("/control/start", methods=["POST"])
def control_start():
    from flask import current_app
    from utils.network import validate_router_ip
    pm        = current_app.config["PROCESS_MANAGER"]
    data      = request.json or {}
    router_ip = data.get("router_ip", "").strip()
    if not router_ip:
        return jsonify({"ok": False, "msg": "Please enter your router IP address."})
    # Validate against actual current network
    validation = validate_router_ip(router_ip)
    if not validation["ok"]:
        return jsonify({"ok": False, "msg": validation["message"],
                        "suggested_ip": validation.get("suggested_ip"),
                        "error": validation.get("error")})
    # Allow with warning
    if validation.get("warning"):
        result = pm.start(router_ip)
        result["warning"] = validation["message"]
        return jsonify(result)
    return jsonify(pm.start(router_ip))

@api.route("/control/stop", methods=["POST"])
def control_stop():
    from flask import current_app
    return jsonify(current_app.config["PROCESS_MANAGER"].stop())

@api.route("/control/status")
def control_status():
    from flask import current_app
    return jsonify(current_app.config["PROCESS_MANAGER"].status())

@api.route("/control/logs")
def control_logs():
    from flask import current_app
    since = int(request.args.get("since", 0))
    return jsonify(current_app.config["PROCESS_MANAGER"].get_logs(since))


# ── Network data ──────────────────────────

@api.route("/stats")
def stats():
    try:
        from core.network_manager import get_current_network
        from db.queries import get_devices_with_status
        net     = get_current_network()
        base    = net.get("base")
        devices = get_devices_with_status(subnet_base=base)
        total   = len(devices)
        up      = sum(1 for d in devices if d["is_alive"]==1)
        down    = sum(1 for d in devices if d["is_alive"]==0)
        unknown = total - up - down
        rtts    = [d["rtt_avg_ms"] for d in devices if d["rtt_avg_ms"]]
        return jsonify({
            "total":   total, "up": up, "down": down,
            "unknown": unknown,
            "avg_rtt": round(sum(rtts)/len(rtts),1) if rtts else None,
            "gateway": net.get("gateway"),
            "subnet":  net.get("subnet"),
        })
    except Exception:
        return jsonify(get_stats())

@api.route("/devices")
def devices():
    try:
        from core.network_manager import get_current_network
        net = get_current_network()
        base = net.get("base")
        return jsonify(get_devices_with_status(subnet_base=base))
    except Exception:
        return jsonify(get_devices_with_status())

@api.route("/topology")
def topology():
    return jsonify(get_topology())

@api.route("/history/<ip>")
def history(ip):
    return jsonify(get_rtt_history(ip))

@api.route("/alerts")
def alerts():
    return jsonify(get_state_changes())


# ── Bandwidth ─────────────────────────────

@api.route("/bandwidth/live")
def bw_live():
    return jsonify(get_bandwidth_live())

@api.route("/bandwidth/history/<ip>")
def bw_history(ip):
    return jsonify(get_bandwidth_history(ip))

@api.route("/bandwidth/totals")
def bw_totals():
    return jsonify(get_bandwidth_totals())

@api.route("/bandwidth/start", methods=["POST"])
def bw_start():
    from flask import current_app
    return jsonify(current_app.config["PROCESS_MANAGER"].start_bandwidth())

@api.route("/bandwidth/stop", methods=["POST"])
def bw_stop():
    from flask import current_app
    return jsonify(current_app.config["PROCESS_MANAGER"].stop_bandwidth())


# ── Reports ───────────────────────────────

@api.route("/report/<period>")
def generate_report(period):
    from flask import Response
    if period not in ("daily", "weekly"):
        return jsonify({"error": "Invalid period. Use daily or weekly"}), 400
    try:
        from core.reports import generate_report as gen
        pdf   = gen(period)
        fname = f"network_report_{period}_{__import__('datetime').datetime.now().strftime('%Y%m%d')}.pdf"
        return Response(
            pdf,
            mimetype="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={fname}"}
        )
    except ImportError:
        return jsonify({"error": "reportlab not installed. Run: pip install reportlab"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api.route("/alerts/config", methods=["GET"])
def alerts_config():
    from config import (ALERT_EMAIL_ENABLED, ALERT_EMAIL_FROM,
                        ALERT_EMAIL_TO, ALERT_EMAIL_SMTP)
    return jsonify({
        "email_enabled": ALERT_EMAIL_ENABLED,
        "email_from":    ALERT_EMAIL_FROM,
        "email_to":      ALERT_EMAIL_TO,
        "smtp":          ALERT_EMAIL_SMTP,
    })

@api.route("/alerts/save", methods=["POST"])
def alerts_save():
    import re
    data     = request.json or {}
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    updates  = {
        "ALERT_EMAIL_FROM":     data.get("from", ""),
        "ALERT_EMAIL_TO":       data.get("to", ""),
        "ALERT_EMAIL_PASSWORD": data.get("password", ""),
        "ALERT_EMAIL_SMTP":     data.get("smtp", "smtp.gmail.com"),
        "ALERT_EMAIL_PORT":     str(data.get("port", "587")),
        "RTT_ALERT_THRESHOLD_MS": str(data.get("rtt_threshold", "200")),
        "ALERT_COOLDOWN_MINUTES": str(data.get("cooldown", "10")),
    }
    try:
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                lines = f.readlines()
        else:
            lines = []
        existing_keys = set()
        new_lines = []
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
        with open(env_path, "w") as f:
            f.writelines(new_lines)
        return jsonify({"ok": True, "msg": "Configuration saved to .env — restart the monitor for changes to take effect."})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})


# ── Traceroute ────────────────────────────

@api.route("/hops")
def all_hops():
    from db.queries import get_hop_routes
    return jsonify(get_hop_routes())

@api.route("/hops/<ip>")
def hops_for_ip(ip):
    from db.queries import get_hop_route
    return jsonify(get_hop_route(ip))


# ── Health & sessions ─────────────────────

@api.route("/health/current")
def health_current():
    try:
        from db.database import get_connection
        from utils.network import get_current_gateway
        from config import DB_FILE

        conn = get_connection(DB_FILE)
        current_gw = get_current_gateway()

        # Find session for CURRENT gateway first
        session = None
        if current_gw:
            sess_row = conn.execute("""
                SELECT * FROM router_sessions
                WHERE gateway_ip=?
                ORDER BY started_at DESC LIMIT 1
            """, (current_gw,)).fetchone()
            if sess_row:
                session = dict(sess_row)
                # Get latest snapshot for this session
                row = conn.execute("""
                    SELECT * FROM health_snapshots
                    WHERE session_id=?
                    ORDER BY timestamp DESC LIMIT 1
                """, (session["id"],)).fetchone()
                if row:
                    conn.close()
                    return jsonify({
                        "session": session,
                        "latest":  dict(row)
                    })

        # No session for current gateway yet —
        # return empty so health page shows "waiting"
        # with correct current gateway info
        conn.close()
        return jsonify({
            "session": {
                "gateway_ip": current_gw,
                "subnet":     ".".join((current_gw or "").split(".")[:3]) + ".0/24",
                "label":      f"Router ({current_gw})",
                "started_at": None,
            } if current_gw else None,
            "latest": None,
            "waiting": True,
            "message": f"Collecting health data for {current_gw}... check back in 1 minute"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api.route("/health/sessions")
def health_sessions():
    try:
        from core.health import get_all_sessions
        return jsonify(get_all_sessions())
    except Exception as e:
        return jsonify([])

@api.route("/health/session/<int:session_id>")
def health_session_history(session_id):
    try:
        from core.health import get_session_history
        return jsonify(get_session_history(session_id))
    except Exception as e:
        return jsonify([])

@api.route("/health/session/<int:session_id>/label", methods=["POST"])
def health_session_label(session_id):
    try:
        from core.health import update_session_label
        label = (request.json or {}).get("label", "")
        update_session_label(session_id, label)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})


# ── Phase 2: classifier + advisor ────────

@api.route("/classify")
def classify():
    try:
        from core.classifier import get_classifications, DEVICE_TYPE_META
        data = get_classifications()
        # Attach meta (icon, color, label) to each result
        for ip, info in data.items():
            dt   = info.get("device_type", "unknown")
            meta = DEVICE_TYPE_META.get(dt, DEVICE_TYPE_META["unknown"])
            info["meta"] = meta
        return jsonify(data)
    except Exception as e:
        return jsonify({})

@api.route("/health/recommendation")
def health_recommendation():
    try:
        from core.health import get_router_recommendation
        return jsonify(get_router_recommendation())
    except Exception as e:
        return jsonify({"error": str(e)})

@api.route("/health/trend/<int:session_id>")
def health_trend(session_id):
    try:
        from core.health import compute_trend_weighted_score
        from db.database import get_connection
        from utils.network import get_current_gateway
        from config import DB_FILE
        conn = get_connection(DB_FILE)
        # Always use session for current gateway
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
        return jsonify(compute_trend_weighted_score(session_id))
    except Exception as e:
        return jsonify({"error": str(e)})


# ── Network state ─────────────────────────

@api.route("/network")
def network_state():
    try:
        from core.network_manager import get_current_network
        return jsonify(get_current_network())
    except Exception:
        from utils.network import detect_network
        subnet, gateway = detect_network()
        from utils.network import subnet_base as sb
        return jsonify({"gateway": gateway, "subnet": subnet,
                        "base": sb(subnet)})


# ── Network info (dynamic, always fresh) ──

@api.route("/network/info")
def network_info():
    from utils.network import get_network_info
    from db.database import get_connection
    from config import DB_FILE
    info = get_network_info()
    # Also include saved gateway to detect changes
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
    return jsonify(info)

@api.route("/network/validate", methods=["POST"])
def network_validate():
    from utils.network import validate_router_ip
    data = request.json or {}
    ip   = data.get("ip", "").strip()
    if not ip:
        return jsonify({"ok": False, "error": "empty",
                        "message": "Please enter your router IP address."})
    return jsonify(validate_router_ip(ip))


# ── Phase 3: Anomaly detection ────────────

@api.route("/anomalies")
def anomalies():
    try:
        from core.anomaly import get_recent_anomalies
        from utils.network import get_current_gateway
        hours   = int(request.args.get("hours", 24))
        events  = get_recent_anomalies(hours)
        gateway = get_current_gateway()
        base    = ".".join((gateway or "").split(".")[:3]) + "."
        events  = [e for e in events
                   if e.get("host","").startswith(base)
                   or e.get("host") in ("8.8.8.8","1.1.1.1")]
        return jsonify(events)
    except Exception as e:
        return jsonify([])

@api.route("/anomalies/summary")
def anomaly_summary():
    try:
        from core.anomaly import get_recent_anomalies
        from utils.network import get_current_gateway
        events  = get_recent_anomalies(24)
        gateway = get_current_gateway()
        base    = ".".join((gateway or "").split(".")[:3]) + "."
        # Filter to current subnet only
        events  = [e for e in events
                   if e.get("host","").startswith(base)
                   or e.get("host") in ("8.8.8.8","1.1.1.1")]
        by_type = {}
        by_severity = {"critical":0,"high":0,"medium":0}
        for e in events:
            t = e["anomaly_type"]
            by_type[t] = by_type.get(t, 0) + 1
            s = e.get("severity","medium")
            by_severity[s] = by_severity.get(s,0) + 1
        return jsonify({
            "total": len(events),
            "by_type": by_type,
            "by_severity": by_severity,
            "latest": events[:5] if events else []
        })
    except Exception as e:
        return jsonify({"total":0,"by_type":{},"by_severity":{},"latest":[]})


# ── Real-time activity feed ───────────────

@api.route("/activity")
def activity():
    """
    Returns a live activity feed — what is happening RIGHT NOW.
    Combines: recent state changes, anomalies, new discoveries.
    """
    try:
        from db.database import get_connection
        from config import DB_FILE
        from datetime import datetime, timedelta
        conn  = get_connection(DB_FILE)
        since = (datetime.now() - timedelta(minutes=5)).isoformat()
        events = []

        # Recent state changes
        rows = conn.execute("""
            SELECT 'state' as type, timestamp, name, host,
                   old_status, new_status, NULL as message
            FROM state_changes WHERE timestamp > ?
            ORDER BY timestamp DESC LIMIT 20
        """, (since,)).fetchall()
        for r in rows:
            d = dict(r)
            status = d["new_status"]
            color  = ("#ef4444" if status=="DOWN" else
                      "#f59e0b" if status=="DEGRADED" else
                      "#22c55e" if status=="UP" else "#64748b")
            events.append({
                "type":      "status",
                "timestamp": d["timestamp"],
                "title":     f"{d['name']} → {status}",
                "detail":    f"{d['host']} was {d['old_status'] or 'unknown'}",
                "color":     color,
            })

        # Recent anomalies
        try:
            rows2 = conn.execute("""
                SELECT timestamp, name, host, anomaly_type, severity, message
                FROM anomaly_events WHERE timestamp > ?
                ORDER BY timestamp DESC LIMIT 10
            """, (since,)).fetchall()
            for r in rows2:
                d = dict(r)
                color = ("#ef4444" if d["severity"]=="critical" else
                         "#f59e0b" if d["severity"]=="high" else "#3b82f6")
                events.append({
                    "type":      "anomaly",
                    "timestamp": d["timestamp"],
                    "title":     f"Anomaly: {d['anomaly_type']} on {d['name']}",
                    "detail":    d["message"],
                    "color":     color,
                })
        except Exception:
            pass

        # Recent discoveries
        rows3 = conn.execute("""
            SELECT timestamp, ip, vendor, method
            FROM discovered_devices
            WHERE last_seen > ? ORDER BY last_seen DESC LIMIT 5
        """, (since,)).fetchall()
        for r in rows3:
            d = dict(r)
            events.append({
                "type":      "discovery",
                "timestamp": d["timestamp"] or d.get("last_seen",""),
                "title":     f"Device found: {d['vendor'] or d['ip']}",
                "detail":    f"{d['ip']} via {d['method']}",
                "color":     "#22c55e",
            })

        conn.close()
        # Sort all events by timestamp descending
        events.sort(key=lambda x: x["timestamp"], reverse=True)
        return jsonify(events[:30])
    except Exception as e:
        return jsonify([])
