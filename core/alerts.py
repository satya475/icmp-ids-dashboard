"""
core/alerts.py
===============
Email alert system for network events.
Triggers on: device DOWN, high RTT.
Configure via .env file.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import smtplib
import threading
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

from config import (
    ALERT_EMAIL_ENABLED,
    ALERT_EMAIL_FROM,
    ALERT_EMAIL_TO,
    ALERT_EMAIL_PASSWORD,
    ALERT_EMAIL_SMTP,
    ALERT_EMAIL_PORT,
)

# ─────────────────────────────────────────
# RTT alert threshold (ms)
# ─────────────────────────────────────────
RTT_ALERT_THRESHOLD_MS = float(os.getenv("RTT_ALERT_THRESHOLD_MS", "200"))

# Cooldown — don't re-alert same device within N minutes
ALERT_COOLDOWN_MINUTES = int(os.getenv("ALERT_COOLDOWN_MINUTES", "10"))

# Track last alert time per device per event type
_last_alert: dict = {}
_lock = threading.Lock()


# ─────────────────────────────────────────
# Cooldown check
# ─────────────────────────────────────────

def _can_alert(device_ip: str, event: str) -> bool:
    """Return True if enough time has passed since last alert for this device+event."""
    key = f"{device_ip}:{event}"
    with _lock:
        last = _last_alert.get(key)
        if last is None:
            _last_alert[key] = datetime.now()
            return True
        if datetime.now() - last > timedelta(minutes=ALERT_COOLDOWN_MINUTES):
            _last_alert[key] = datetime.now()
            return True
        return False


# ─────────────────────────────────────────
# Email sender
# ─────────────────────────────────────────

def _send_email(subject: str, body_html: str, body_text: str):
    """Send email alert in a background thread so it never blocks monitoring."""
    if not ALERT_EMAIL_ENABLED:
        return

    def _send():
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = ALERT_EMAIL_FROM
            msg["To"]      = ALERT_EMAIL_TO
            msg.attach(MIMEText(body_text, "plain"))
            msg.attach(MIMEText(body_html,  "html"))

            with smtplib.SMTP(ALERT_EMAIL_SMTP, ALERT_EMAIL_PORT) as server:
                server.ehlo()
                server.starttls()
                server.login(ALERT_EMAIL_FROM, ALERT_EMAIL_PASSWORD)
                server.sendmail(ALERT_EMAIL_FROM, ALERT_EMAIL_TO, msg.as_string())
            print(f"[ALERT] Email sent: {subject}")
        except Exception as e:
            print(f"[ALERT ERROR] Email failed: {e}")

    threading.Thread(target=_send, daemon=True).start()


# ─────────────────────────────────────────
# HTML email templates
# ─────────────────────────────────────────

def _device_down_email(name: str, ip: str, ts: str) -> tuple[str, str]:
    html = f"""
    <html><body style="font-family:system-ui,sans-serif;background:#f8fafc;padding:24px">
    <div style="max-width:520px;margin:0 auto;background:#fff;border-radius:12px;
                border:1px solid #e2e8f0;overflow:hidden">
      <div style="background:#ef4444;padding:20px 24px">
        <h2 style="color:#fff;margin:0;font-size:18px">Device Offline</h2>
      </div>
      <div style="padding:24px">
        <p style="margin:0 0 16px;color:#374151;font-size:15px">
          A device on your network has stopped responding.
        </p>
        <table style="width:100%;border-collapse:collapse;font-size:14px">
          <tr><td style="padding:8px 0;color:#6b7280;width:120px">Device</td>
              <td style="padding:8px 0;font-weight:600;color:#111827">{name}</td></tr>
          <tr><td style="padding:8px 0;color:#6b7280">IP Address</td>
              <td style="padding:8px 0;font-family:monospace;color:#111827">{ip}</td></tr>
          <tr><td style="padding:8px 0;color:#6b7280">Time</td>
              <td style="padding:8px 0;color:#111827">{ts}</td></tr>
          <tr><td style="padding:8px 0;color:#6b7280">Status</td>
              <td style="padding:8px 0"><span style="background:#fee2e2;color:#991b1b;
                padding:2px 10px;border-radius:20px;font-size:12px;font-weight:600">
                DOWN</span></td></tr>
        </table>
        <div style="margin-top:20px;padding:12px 16px;background:#fef2f2;
                    border-radius:8px;border-left:3px solid #ef4444">
          <p style="margin:0;color:#7f1d1d;font-size:13px">
            Open your dashboard to investigate: 
            <a href="http://localhost:5000" style="color:#dc2626">localhost:5000</a>
          </p>
        </div>
      </div>
      <div style="padding:16px 24px;background:#f9fafb;border-top:1px solid #e2e8f0">
        <p style="margin:0;color:#9ca3af;font-size:12px">
          Network Monitor — auto-alert system
        </p>
      </div>
    </div>
    </body></html>
    """
    text = f"ALERT: {name} ({ip}) is DOWN at {ts}. Check your dashboard at localhost:5000"
    return html, text


def _high_rtt_email(name: str, ip: str, rtt: float, ts: str) -> tuple[str, str]:
    html = f"""
    <html><body style="font-family:system-ui,sans-serif;background:#f8fafc;padding:24px">
    <div style="max-width:520px;margin:0 auto;background:#fff;border-radius:12px;
                border:1px solid #e2e8f0;overflow:hidden">
      <div style="background:#f59e0b;padding:20px 24px">
        <h2 style="color:#fff;margin:0;font-size:18px">High Latency Detected</h2>
      </div>
      <div style="padding:24px">
        <p style="margin:0 0 16px;color:#374151;font-size:15px">
          A device on your network has unusually high response time.
        </p>
        <table style="width:100%;border-collapse:collapse;font-size:14px">
          <tr><td style="padding:8px 0;color:#6b7280;width:120px">Device</td>
              <td style="padding:8px 0;font-weight:600;color:#111827">{name}</td></tr>
          <tr><td style="padding:8px 0;color:#6b7280">IP Address</td>
              <td style="padding:8px 0;font-family:monospace;color:#111827">{ip}</td></tr>
          <tr><td style="padding:8px 0;color:#6b7280">RTT</td>
              <td style="padding:8px 0;font-weight:600;color:#b45309">{rtt:.1f} ms</td></tr>
          <tr><td style="padding:8px 0;color:#6b7280">Threshold</td>
              <td style="padding:8px 0;color:#111827">{RTT_ALERT_THRESHOLD_MS:.0f} ms</td></tr>
          <tr><td style="padding:8px 0;color:#6b7280">Time</td>
              <td style="padding:8px 0;color:#111827">{ts}</td></tr>
        </table>
      </div>
      <div style="padding:16px 24px;background:#f9fafb;border-top:1px solid #e2e8f0">
        <p style="margin:0;color:#9ca3af;font-size:12px">
          Network Monitor — auto-alert system
        </p>
      </div>
    </div>
    </body></html>
    """
    text = f"WARNING: {name} ({ip}) has high RTT of {rtt:.1f}ms at {ts} (threshold: {RTT_ALERT_THRESHOLD_MS}ms)"
    return html, text


# ─────────────────────────────────────────
# Public API — called from core/state.py
# ─────────────────────────────────────────

def alert_device_down(name: str, ip: str):
    """Send alert when a device goes DOWN."""
    if not _can_alert(ip, "down"):
        return
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subj = f"[Network Monitor] {name} is DOWN"
    html, text = _device_down_email(name, ip, ts)
    _send_email(subj, html, text)


def alert_high_rtt(name: str, ip: str, rtt: float):
    """Send alert when RTT exceeds threshold."""
    if not _can_alert(ip, "high_rtt"):
        return
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subj = f"[Network Monitor] High latency on {name} ({rtt:.0f}ms)"
    html, text = _high_rtt_email(name, ip, rtt, ts)
    _send_email(subj, html, text)


def check_rtt_alert(name: str, ip: str, rtt: Optional[float]):
    """Check if RTT exceeds threshold and send alert if needed."""
    if rtt is not None and rtt > RTT_ALERT_THRESHOLD_MS:
        alert_high_rtt(name, ip, rtt)
