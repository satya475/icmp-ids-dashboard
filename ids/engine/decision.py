"""
ids/engine/decision.py
=======================
Decision Engine — combines Signature IDS and ML IDS results.
Makes final call on whether traffic is malicious or not.
"""

from scapy.all import defaultdict

from ids.signature.engine import run_signature_ids
from ids.ml.ids_model      import run_ml_ids
from datetime              import datetime
# ─────────────────────────────────────────
# Real-time stats tracker
# ─────────────────────────────────────────

from datetime import datetime
import time

# Network stats
stats_tracker = {
    "total_packets"     : 0,
    "packets_per_sec"   : 0,
    "active_ips"        : set(),
    "bytes_sent"        : 0,
    "bytes_received"    : 0,
    "alerts_last_hour"  : 0,
    "last_alert_time"   : None,
    "last_alert_type"   : None,
    "most_suspicious_ip": None,
    "ids_start_time"    : datetime.now().isoformat(),
    "signature_status"  : "ACTIVE",
    "ml_status"         : "ACTIVE",
    "rules_loaded"      : 5,
}

# For packets per second calculation
_pps_counter    = 0
_pps_last_reset = time.time()

# IP alert counter
ip_alert_count  = defaultdict(int)

# ─────────────────────────────────────────
# Alert storage (in memory)
# ─────────────────────────────────────────

# Stores all alerts generated so far
all_alerts = []
MAX_ALERTS = 1000  # keep last 1000 alerts


# ─────────────────────────────────────────
# Severity scoring
# ─────────────────────────────────────────

SEVERITY_SCORE = {
    "critical" : 4,
    "high"     : 3,
    "medium"   : 2,
    "low"      : 1,
}


# ─────────────────────────────────────────
# Decision Engine
# ─────────────────────────────────────────

def process_packet(features, on_alert=None):
    """
    Main function — processes every captured packet.
    Runs both Signature IDS and ML IDS.
    Combines results and fires alerts.
    """
    global _pps_counter, _pps_last_reset
    collected_alerts = []

    # ── Update real time stats ──
    src_ip   = features.get("src_ip", "")
    dst_ip   = features.get("dst_ip", "")
    pkt_size = features.get("packet_size", 0)

    stats_tracker["total_packets"] += 1
    stats_tracker["active_ips"].add(src_ip)
    stats_tracker["active_ips"].add(dst_ip)

    # Bytes sent/received (your IP = 192.168.x.x)
    if src_ip.startswith("192.168."):
        stats_tracker["bytes_sent"] += pkt_size
    else:
        stats_tracker["bytes_received"] += pkt_size

    # Packets per second
    _pps_counter += 1
    now = time.time()
    if now - _pps_last_reset >= 1.0:
        stats_tracker["packets_per_sec"] = _pps_counter
        _pps_counter    = 0
        _pps_last_reset = now

    # ── Run Signature IDS ──
    def on_signature_alert(alert):
        alert["source"] = "signature"
        collected_alerts.append(alert)

    # ── Run ML IDS ──
    def on_ml_alert(alert):
        alert["source"] = "ml"
        collected_alerts.append(alert)

    run_signature_ids(features, on_signature_alert)
    run_ml_ids(features, on_ml_alert)

    # No alerts from either IDS
    if not collected_alerts:
        return None

    # Pick highest severity alert
    final_alert = max(
        collected_alerts,
        key=lambda a: SEVERITY_SCORE.get(a["severity"], 0)
    )

    # Add extra info
    final_alert["detected_by"]      = [a["source"] for a in collected_alerts]
    final_alert["total_detections"] = len(collected_alerts)

    # ── Update alert stats ──
    stats_tracker["last_alert_time"] = datetime.now().isoformat()
    stats_tracker["last_alert_type"] = final_alert.get("rule")

    # Track alerts in last hour
    stats_tracker["alerts_last_hour"] += 1

    # Track most suspicious IP
    ip_alert_count[src_ip] += 1
    stats_tracker["most_suspicious_ip"] = max(
        ip_alert_count, key=ip_alert_count.get
    )

    # Store alert
    all_alerts.append(final_alert)
    if len(all_alerts) > MAX_ALERTS:
        all_alerts.pop(0)

    # Fire callback
    if on_alert:
        on_alert(final_alert)

    return final_alert


# ─────────────────────────────────────────
# Get real time stats
# ─────────────────────────────────────────

def get_realtime_stats():
    """Returns current network and IDS stats."""

    def fmt_bytes(b):
        if b >= 1e9: return f"{b/1e9:.1f} GB"
        if b >= 1e6: return f"{b/1e6:.1f} MB"
        if b >= 1e3: return f"{b/1e3:.1f} KB"
        return f"{int(b)} B"

    # Time since last alert
    last_alert_ago = "Never"
    if stats_tracker["last_alert_time"]:
        diff = datetime.now() - datetime.fromisoformat(
            stats_tracker["last_alert_time"])
        secs = int(diff.total_seconds())
        if secs < 60:
            last_alert_ago = f"{secs} seconds ago"
        elif secs < 3600:
            last_alert_ago = f"{secs//60} minutes ago"
        else:
            last_alert_ago = f"{secs//3600} hours ago"

    # IDS uptime
    start = datetime.fromisoformat(stats_tracker["ids_start_time"])
    diff  = datetime.now() - start
    secs  = int(diff.total_seconds())
    if secs < 60:
        uptime = f"{secs} seconds"
    elif secs < 3600:
        uptime = f"{secs//60} minutes"
    else:
        uptime = f"{secs//3600}h {(secs%3600)//60}m"

    # Network status
    recent_alerts = [
        a for a in all_alerts
        if a.get("severity") in ("critical", "high")
    ]
    is_safe = len(recent_alerts) == 0

    return {
        # Group 1 — Traffic
        "total_packets"     : stats_tracker["total_packets"],
        "packets_per_sec"   : stats_tracker["packets_per_sec"],
        "active_ips"        : len(stats_tracker["active_ips"]),
        "bytes_sent"        : fmt_bytes(stats_tracker["bytes_sent"]),
        "bytes_received"    : fmt_bytes(stats_tracker["bytes_received"]),

        # Group 2 — Alerts
        "alerts_last_hour"  : stats_tracker["alerts_last_hour"],
        "last_alert_ago"    : last_alert_ago,
        "last_alert_type"   : stats_tracker["last_alert_type"] or "None",
        "most_suspicious_ip": stats_tracker["most_suspicious_ip"] or "None",

        # Group 3 — IDS Engine
        "signature_status"  : stats_tracker["signature_status"],
        "ml_status"         : stats_tracker["ml_status"],
        "ids_uptime"        : uptime,
        "rules_loaded"      : stats_tracker["rules_loaded"],

        # Overall status
        "is_safe"           : is_safe,
        "status"            : "SAFE" if is_safe else "UNDER ATTACK",
    }

# ─────────────────────────────────────────
# Alert retrieval
# ─────────────────────────────────────────

def get_recent_alerts(limit=50):
    """Get most recent alerts."""
    return all_alerts[-limit:]


def get_alert_stats():
    """Get summary statistics of all alerts."""
    if not all_alerts:
        return {
            "total"    : 0,
            "critical" : 0,
            "high"     : 0,
            "medium"   : 0,
            "low"      : 0,
        }

    return {
        "total"    : len(all_alerts),
        "critical" : sum(1 for a in all_alerts
                        if a["severity"] == "critical"),
        "high"     : sum(1 for a in all_alerts
                        if a["severity"] == "high"),
        "medium"   : sum(1 for a in all_alerts
                        if a["severity"] == "medium"),
        "low"      : sum(1 for a in all_alerts
                        if a["severity"] == "low"),
    }