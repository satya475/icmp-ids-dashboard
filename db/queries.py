"""
db/queries.py
==============
All database read/write operations in one place.
No SQL lives outside this file.
"""

import sqlite3
from datetime import datetime, timedelta
from typing import Optional
from db.database import get_connection
from config import DB_FILE, DATA_RETENTION_H, BW_RETENTION_DAYS


# ─────────────────────────────────────────
# Targets
# ─────────────────────────────────────────

def load_active_targets(db_file: str = DB_FILE) -> list:
    conn = get_connection(db_file)
    rows = conn.execute(
        "SELECT ip, name FROM active_targets WHERE active=1"
    ).fetchall()
    conn.close()
    return [{"host": r["ip"], "name": r["name"]} for r in rows]


def upsert_target(ip: str, name: str, db_file: str = DB_FILE):
    conn = get_connection(db_file)
    conn.execute("""INSERT INTO active_targets (ip, name, added_at, active)
        VALUES (?, ?, ?, 1)
        ON CONFLICT(ip) DO UPDATE SET
            name = CASE
                WHEN excluded.name != excluded.ip
                    THEN excluded.name   -- new name is a real name, use it
                WHEN active_targets.name != active_targets.ip
                    THEN active_targets.name  -- keep existing real name
                ELSE excluded.name       -- both are just IPs, use new one
            END,
            active = 1""",
        (ip, name, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def deactivate_subnet_targets(subnet_base: str, found_ips: set, db_file: str = DB_FILE):
    if not found_ips:
        return
    conn = get_connection(db_file)
    placeholders = ",".join("?" * len(found_ips))
    conn.execute(f"""UPDATE active_targets SET active=0
        WHERE ip LIKE ?
          AND ip NOT IN ({placeholders})
          AND ip NOT IN ('8.8.8.8','1.1.1.1','8.8.4.4','1.0.0.1')""",
        [subnet_base + "%"] + list(found_ips))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────
# Probe results
# ─────────────────────────────────────────

def save_probe_result(host: str, name: str, is_alive: bool,
                      rtt_avg: Optional[float], rtt_min: Optional[float],
                      rtt_max: Optional[float], packet_loss: float,rtt_med: Optional[float] = None, jitter: Optional[float] = None, quality: Optional[str] = None,
                      db_file: str = DB_FILE):
    conn = get_connection(db_file)
    conn.execute("""INSERT INTO probe_results
        (host, name, timestamp, is_alive, rtt_avg_ms, rtt_min_ms, rtt_max_ms, packet_loss, rtt_med_ms, jitter_ms, quality)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (host, name, datetime.now().isoformat(), int(is_alive),
         rtt_avg, rtt_min, rtt_max, packet_loss, rtt_med, jitter, quality))
    conn.commit()
    conn.close()


def prune_probe_results(db_file: str = DB_FILE):
    cutoff = (datetime.now() - timedelta(hours=DATA_RETENTION_H)).isoformat()
    conn   = get_connection(db_file)
    conn.execute("DELETE FROM probe_results WHERE timestamp < ?", (cutoff,))
    conn.commit()
    conn.close()


def get_devices_with_status(db_file: str = DB_FILE,
                            subnet_base: str = None) -> list:
    """
    Get all active devices with latest probe result.
    If subnet_base provided, also includes external IPs (8.8.8.8 etc)
    but filters to only current subnet local devices.
    """
    conn = get_connection(db_file)

    # Always include external monitoring targets
    external_ips = ("8.8.8.8", "1.1.1.1", "8.8.4.4", "1.0.0.1")

    if subnet_base:
        rows = conn.execute("""
            SELECT t.ip, t.name, d.vendor, d.mac, d.method, d.first_seen,
                   p.is_alive, p.rtt_avg_ms, p.rtt_min_ms, p.rtt_max_ms,
                   p.packet_loss, p.timestamp as last_seen,
                   p.rtt_med_ms, p.jitter_ms, p.quality
            FROM active_targets t
            LEFT JOIN discovered_devices d ON d.ip = t.ip
            LEFT JOIN probe_results p ON p.host = t.ip
                AND p.timestamp = (
                    SELECT MAX(timestamp) FROM probe_results WHERE host = t.ip)
            WHERE t.active = 1
              AND (t.ip LIKE ? OR t.ip IN (?,?,?,?))
            ORDER BY t.name
        """, (f"{subnet_base}.%",) + external_ips).fetchall()
    else:
        rows = conn.execute("""
            SELECT t.ip, t.name, d.vendor, d.mac, d.method, d.first_seen,
                   p.is_alive, p.rtt_avg_ms, p.rtt_min_ms, p.rtt_max_ms,
                   p.packet_loss, p.timestamp as last_seen,
                   p.rtt_med_ms, p.jitter_ms, p.quality
            FROM active_targets t
            LEFT JOIN discovered_devices d ON d.ip = t.ip
            LEFT JOIN probe_results p ON p.host = t.ip
                AND p.timestamp = (
                    SELECT MAX(timestamp) FROM probe_results WHERE host = t.ip)
            WHERE t.active = 1
            ORDER BY t.name
        """).fetchall()

    conn.close()
    return [dict(r) for r in rows]


def get_rtt_history(ip: str, minutes: int = 30, db_file: str = DB_FILE) -> list:
    conn  = get_connection(db_file)
    since = (datetime.now() - timedelta(minutes=minutes)).isoformat()
    rows  = conn.execute("""
        SELECT timestamp, rtt_avg_ms, packet_loss
        FROM probe_results
        WHERE host=? AND timestamp>?
        ORDER BY timestamp ASC LIMIT 200
    """, (ip, since)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_uptime_pct(ip: str, hours: int = 24, db_file: str = DB_FILE) -> Optional[float]:
    conn  = get_connection(db_file)
    since = (datetime.now() - timedelta(hours=hours)).isoformat()
    row   = conn.execute("""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN is_alive=1 THEN 1 ELSE 0 END) as up_count
        FROM probe_results WHERE host=? AND timestamp>?
    """, (ip, since)).fetchone()
    conn.close()
    if row and row["total"] > 0:
        return round((row["up_count"] / row["total"]) * 100, 1)
    return None


def get_all_uptimes(hours: int = 24, db_file: str = DB_FILE) -> dict:
    conn  = get_connection(db_file)
    since = (datetime.now() - timedelta(hours=hours)).isoformat()
    rows  = conn.execute("""
        SELECT host, COUNT(*) as total,
               SUM(CASE WHEN is_alive=1 THEN 1 ELSE 0 END) as up_count
        FROM probe_results WHERE timestamp>? GROUP BY host
    """, (since,)).fetchall()
    conn.close()
    return {r["host"]: round((r["up_count"]/r["total"])*100, 1)
            for r in rows if r["total"] > 0}


# ─────────────────────────────────────────
# State changes
# ─────────────────────────────────────────

def save_state_change(host: str, name: str, old_status: str,
                      new_status: str, db_file: str = DB_FILE):
    conn = get_connection(db_file)
    conn.execute("""INSERT INTO state_changes (host, name, timestamp, old_status, new_status)
        VALUES (?, ?, ?, ?, ?)""",
        (host, name, datetime.now().isoformat(), old_status, new_status))
    conn.commit()
    conn.close()


def get_state_changes(limit: int = 50, db_file: str = DB_FILE) -> list:
    conn = get_connection(db_file)
    try:
        rows = conn.execute("""
            SELECT host, name, timestamp, old_status, new_status
            FROM state_changes ORDER BY timestamp DESC LIMIT ?
        """, (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        conn.close()
        return []


# ─────────────────────────────────────────
# Discovered devices
# ─────────────────────────────────────────

def upsert_device(ip: str, mac: str, vendor: str, hostname: Optional[str],
                  method: str, db_file: str = DB_FILE):
    now  = datetime.now().isoformat()
    conn = get_connection(db_file)
    conn.execute("""INSERT INTO discovered_devices
        (ip, mac, vendor, hostname, method, first_seen, last_seen)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ip) DO UPDATE SET
            mac=excluded.mac, vendor=excluded.vendor,
            hostname=excluded.hostname, method=excluded.method,
            last_seen=excluded.last_seen""",
        (ip, mac, vendor, hostname, method, now, now))
    conn.commit()
    conn.close()


def get_known_ips(db_file: str = DB_FILE) -> set:
    conn = get_connection(db_file)
    rows = conn.execute("SELECT ip FROM discovered_devices").fetchall()
    conn.close()
    return {r["ip"] for r in rows}


# ─────────────────────────────────────────
# Bandwidth
# ─────────────────────────────────────────

def save_bandwidth_sample(ip: str, bytes_in: int, bytes_out: int,
                          pkts_in: int, pkts_out: int, db_file: str = DB_FILE):
    conn = get_connection(db_file)
    conn.execute("""INSERT INTO bandwidth_samples
        (ip, timestamp, bytes_in, bytes_out, pkts_in, pkts_out)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (ip, datetime.now().isoformat(), bytes_in, bytes_out, pkts_in, pkts_out))
    conn.commit()
    conn.close()


def get_bandwidth_live(db_file: str = DB_FILE) -> list:
    conn  = get_connection(db_file)
    since = (datetime.now() - timedelta(seconds=30)).isoformat()
    rows  = conn.execute("""
        SELECT b.ip, COALESCE(t.name, b.ip) as name,
               SUM(b.bytes_in)  as total_in,
               SUM(b.bytes_out) as total_out,
               SUM(b.pkts_in)   as pkts_in,
               SUM(b.pkts_out)  as pkts_out
        FROM bandwidth_samples b
        LEFT JOIN active_targets t ON t.ip = b.ip
        WHERE b.timestamp > ?
        GROUP BY b.ip
        ORDER BY (total_in + total_out) DESC
    """, (since,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_bandwidth_history(ip: str, hours: int = 1, db_file: str = DB_FILE) -> list:
    conn  = get_connection(db_file)
    since = (datetime.now() - timedelta(hours=hours)).isoformat()
    rows  = conn.execute("""
        SELECT timestamp,
               bytes_in  / 5.0 as rate_in,
               bytes_out / 5.0 as rate_out
        FROM bandwidth_samples
        WHERE ip=? AND timestamp>?
        ORDER BY timestamp ASC LIMIT 500
    """, (ip, since)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_bandwidth_totals(db_file: str = DB_FILE) -> dict:
    conn       = get_connection(db_file)
    day_since  = (datetime.now() - timedelta(hours=24)).isoformat()
    week_since = (datetime.now() - timedelta(days=7)).isoformat()
    def query(since):
        rows = conn.execute("""
            SELECT b.ip, COALESCE(t.name, b.ip) as name,
                   SUM(b.bytes_in)  as total_in,
                   SUM(b.bytes_out) as total_out
            FROM bandwidth_samples b
            LEFT JOIN active_targets t ON t.ip = b.ip
            WHERE b.timestamp > ?
            GROUP BY b.ip
            ORDER BY (total_in + total_out) DESC
        """, (since,)).fetchall()
        return [dict(r) for r in rows]
    result = {"daily": query(day_since), "weekly": query(week_since)}
    conn.close()
    return result


def prune_bandwidth(db_file: str = DB_FILE):
    cutoff = (datetime.now() - timedelta(days=BW_RETENTION_DAYS)).isoformat()
    conn   = get_connection(db_file)
    conn.execute("DELETE FROM bandwidth_samples WHERE timestamp < ?", (cutoff,))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────
# Dashboard stats
# ─────────────────────────────────────────

def get_stats(db_file: str = DB_FILE) -> dict:
    devices = get_devices_with_status(db_file)
    total   = len(devices)
    up      = sum(1 for d in devices if d["is_alive"] == 1)
    down    = sum(1 for d in devices if d["is_alive"] == 0)
    unknown = total - up - down
    rtts    = [d["rtt_avg_ms"] for d in devices if d["rtt_avg_ms"]]
    return {
        "total":   total,
        "up":      up,
        "down":    down,
        "unknown": unknown,
        "avg_rtt": round(sum(rtts)/len(rtts), 1) if rtts else None
    }


def get_topology(db_file: str = DB_FILE) -> dict:
    devices = get_devices_with_status(db_file)
    uptimes = get_all_uptimes(db_file=db_file)
    if not devices:
        return {"nodes": [], "edges": []}

    router_ip = None
    for d in devices:
        if "router" in (d["name"] or "").lower() or "gateway" in (d["name"] or "").lower():
            router_ip = d["ip"]
            break
    if not router_ip:
        router_ip = sorted(devices, key=lambda x: list(map(int, x["ip"].split("."))))[0]["ip"]

    nodes, edges = [], []
    for d in devices:
        status = "up" if d["is_alive"]==1 else ("down" if d["is_alive"]==0 else "unknown")
        nodes.append({
            "id":       d["ip"], "label": d["name"], "ip": d["ip"],
            "vendor":   d["vendor"] or "Unknown", "mac": d["mac"] or "—",
            "rtt":      round(d["rtt_avg_ms"], 1) if d["rtt_avg_ms"] else None,
            "loss":     round((d["packet_loss"] or 0)*100, 1),
            "status":   status,
            "uptime":   uptimes.get(d["ip"]),
            "is_router":d["ip"] == router_ip
        })
        if d["ip"] != router_ip:
            edges.append({"from": router_ip, "to": d["ip"]})
    return {"nodes": nodes, "edges": edges}


# ─────────────────────────────────────────
# Hop routes (traceroute)
# ─────────────────────────────────────────

def get_hop_routes(db_file: str = DB_FILE) -> dict:
    """Get latest traceroute hop routes for all targets."""
    try:
        conn = get_connection(db_file)
        targets = conn.execute(
            "SELECT DISTINCT target_ip FROM hop_routes"
        ).fetchall()
        result = {}
        for t in targets:
            ip   = t["target_ip"]
            rows = conn.execute("""
                SELECT hop_number, hop_ip, hop_name, rtt_ms
                FROM hop_routes WHERE target_ip=?
                ORDER BY hop_number ASC
            """, (ip,)).fetchall()
            result[ip] = [dict(r) for r in rows]
        conn.close()
        return result
    except Exception:
        return {}


def get_hop_route(target_ip: str, db_file: str = DB_FILE) -> list:
    """Get hop route for a single target IP."""
    try:
        conn = get_connection(db_file)
        rows = conn.execute("""
            SELECT hop_number, hop_ip, hop_name, rtt_ms
            FROM hop_routes WHERE target_ip=?
            ORDER BY hop_number ASC
        """, (target_ip,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []
