"""
ids/alerts.py
==============
Alert system for our IDS.
Connects to existing email alert system.
Saves alerts to log file.
"""

import os
import json
from datetime import datetime
from loguru import logger

# ─────────────────────────────────────────
# Log file setup
# ─────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.dirname(
           os.path.abspath(__file__)))

LOG_DIR  = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "ids_alerts.log")

os.makedirs(LOG_DIR, exist_ok=True)

# Setup loguru logger
logger.add(
    LOG_FILE,
    format    = "{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    level     = "INFO",
    rotation  = "10 MB",   # new file after 10MB
    retention = "7 days",  # keep logs for 7 days
)

# ─────────────────────────────────────────
# Severity colors for terminal
# ─────────────────────────────────────────

SEVERITY_PREFIX = {
    "critical" : "🚨 [CRITICAL]",
    "high"     : "🔴 [HIGH]    ",
    "medium"   : "🟡 [MEDIUM]  ",
    "low"      : "🟢 [LOW]     ",
}

# ─────────────────────────────────────────
# Main alert handler
# ─────────────────────────────────────────

def handle_alert(alert):
    """
    Main function called when attack detected.
    1. Prints to terminal
    2. Saves to log file
    3. Sends email for critical/high alerts
    """
    severity = alert.get("severity", "low")
    prefix   = SEVERITY_PREFIX.get(severity, "⚪ [INFO]   ")
    src_ip   = alert.get("src_ip",  "unknown")
    dst_ip   = alert.get("dst_ip",  "unknown")
    rule     = alert.get("rule",    "unknown")
    message  = alert.get("message", "")
    source   = alert.get("source",  "unknown")
    ts       = alert.get("timestamp", datetime.now().isoformat())

    # ── 1. Print to terminal ──
    print(f"\n{prefix} {message}")
    print(f"         Rule: {rule} | "
          f"Source: {source} | "
          f"From: {src_ip} → {dst_ip}")

    # ── 2. Save to log file ──
    log_entry = {
        "timestamp" : ts,
        "severity"  : severity,
        "rule"      : rule,
        "src_ip"    : src_ip,
        "dst_ip"    : dst_ip,
        "message"   : message,
        "source"    : source,
    }
    logger.info(json.dumps(log_entry))

    # ── 3. Send email for critical/high ──
    if severity in ("critical", "high"):
        _send_email_alert(alert)


# ─────────────────────────────────────────
# Email alert
# ─────────────────────────────────────────

def _send_email_alert(alert):
    """
    Connect to friend's existing email system.
    Reuses core/alerts.py to send email.
    """
    try:
        from core.alerts import _send_email

        severity = alert.get("severity", "").upper()
        rule     = alert.get("rule",     "UNKNOWN")
        src_ip   = alert.get("src_ip",   "unknown")
        message  = alert.get("message",  "")

        subject  = (f"[IDS ALERT] {severity}: "
                    f"{rule} from {src_ip}")

        body_html = f"""
        <html>
        <body style="font-family:system-ui;padding:20px">
        <div style="background:#1a1d27;color:#e2e8f0;
             border-radius:8px;padding:20px;max-width:500px">

          <h3 style="color:#ef4444;margin:0 0 12px">
            🚨 IDS Attack Detected!</h3>

          <p style="margin:0 0 8px;font-size:14px">
            <b>Rule:</b> {rule}</p>
          <p style="margin:0 0 8px;font-size:14px">
            <b>Severity:</b> {severity}</p>
          <p style="margin:0 0 8px;font-size:14px">
            <b>Source IP:</b> {src_ip}</p>
          <p style="margin:0 0 16px;font-size:14px">
            <b>Details:</b> {message}</p>

          <div style="margin-top:16px;padding:12px;
               background:#2d1f1f;border-radius:6px">
            <p style="margin:0;font-size:12px;color:#94a3b8">
              Detected by: Hybrid IDS System<br>
              Time: {alert.get('timestamp', '')}
            </p>
          </div>
        </div>
        </body>
        </html>
        """

        body_text = (f"IDS ALERT: {severity} - {rule}\n"
                    f"From: {src_ip}\n"
                    f"Details: {message}")

        _send_email(subject, body_html, body_text)
        print(f"         📧 Email alert sent!")

    except Exception as e:
        print(f"         [EMAIL ERROR] {e}")


# ─────────────────────────────────────────
# Alert statistics
# ─────────────────────────────────────────

def get_log_alerts(limit=50):
    """
    Read recent alerts from log file.
    Returns list of alert dictionaries.
    """
    alerts = []

    if not os.path.exists(LOG_FILE):
        return alerts

    try:
        with open(LOG_FILE, "r") as f:
            lines = f.readlines()

        # Read last N lines
        for line in lines[-limit:]:
            try:
                # Extract JSON part from log line
                json_start = line.index("{")
                json_str   = line[json_start:]
                alert      = json.loads(json_str)
                alerts.append(alert)
            except Exception:
                continue

    except Exception as e:
        print(f"[ALERTS] Log read error: {e}")

    return list(reversed(alerts))