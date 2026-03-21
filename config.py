"""
config.py
==========
Central configuration for the entire project.
Values are loaded from .env if present, with sensible defaults.
"""

import os
from dotenv import load_dotenv

# Load .env file if it exists
load_dotenv()

# ─────────────────────────────────────────
# Database
# ─────────────────────────────────────────
DB_FILE = os.getenv("DB_FILE", "network_monitor.db")

# ─────────────────────────────────────────
# Probe engine
# ─────────────────────────────────────────
PROBE_INTERVAL   = int(os.getenv("PROBE_INTERVAL",   "10"))   # seconds
PROBE_COUNT      = int(os.getenv("PROBE_COUNT",       "3"))    # ICMP packets per probe
PROBE_TIMEOUT    = int(os.getenv("PROBE_TIMEOUT",     "2"))    # seconds per reply
DOWN_THRESHOLD   = int(os.getenv("DOWN_THRESHOLD",    "3"))    # failures → DOWN
UP_THRESHOLD     = int(os.getenv("UP_THRESHOLD",      "2"))    # successes → UP
DATA_RETENTION_H = int(os.getenv("DATA_RETENTION_H",  "24"))   # hours to keep probe data

# ─────────────────────────────────────────
# Discovery
# ─────────────────────────────────────────
SCAN_INTERVAL    = int(os.getenv("SCAN_INTERVAL",    "60"))    # seconds between scans
ARP_TIMEOUT      = int(os.getenv("ARP_TIMEOUT",       "3"))    # scapy ARP timeout
TCP_PORTS        = [80, 443, 8080, 8443, 22, 23, 554, 7, 9]   # ports to try
TCP_TIMEOUT      = float(os.getenv("TCP_TIMEOUT",    "0.5"))   # per-port timeout
PING_TIMEOUT_MS  = int(os.getenv("PING_TIMEOUT_MS", "1000"))   # ms
PING_BATCH_SIZE  = int(os.getenv("PING_BATCH_SIZE",   "30"))

# ─────────────────────────────────────────
# Bandwidth
# ─────────────────────────────────────────
BW_SAMPLE_INTERVAL  = int(os.getenv("BW_SAMPLE_INTERVAL",  "5"))   # seconds
BW_RETENTION_DAYS   = int(os.getenv("BW_RETENTION_DAYS",   "7"))   # days

# ─────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────
DASHBOARD_HOST   = os.getenv("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT   = int(os.getenv("DASHBOARD_PORT", "5000"))
SECRET_KEY       = os.getenv("SECRET_KEY", "dev-secret-change-in-production")

# ─────────────────────────────────────────
# Alerts — Email
# ─────────────────────────────────────────
ALERT_EMAIL_ENABLED  = os.getenv("ALERT_EMAIL_FROM", "") != ""
ALERT_EMAIL_FROM     = os.getenv("ALERT_EMAIL_FROM",     "")
ALERT_EMAIL_TO       = os.getenv("ALERT_EMAIL_TO",       "")
ALERT_EMAIL_PASSWORD = os.getenv("ALERT_EMAIL_PASSWORD", "")
ALERT_EMAIL_SMTP     = os.getenv("ALERT_EMAIL_SMTP",     "smtp.gmail.com")
ALERT_EMAIL_PORT     = int(os.getenv("ALERT_EMAIL_PORT", "587"))

# ─────────────────────────────────────────
# Alerts — Telegram
# ─────────────────────────────────────────
ALERT_TELEGRAM_ENABLED  = os.getenv("TELEGRAM_BOT_TOKEN", "") != ""
TELEGRAM_BOT_TOKEN      = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID        = os.getenv("TELEGRAM_CHAT_ID",   "")

# ─────────────────────────────────────────
# MAC vendor prefix table
# ─────────────────────────────────────────
VENDOR_PREFIXES = {
    "00:00:0c": "Cisco",       "00:1a:11": "Google",
    "00:17:88": "Philips Hue", "00:18:0a": "TP-Link",
    "18:d6:c7": "TP-Link",     "50:c7:bf": "TP-Link",
    "b0:be:76": "TP-Link",     "00:50:f2": "Microsoft",
    "00:15:5d": "Microsoft",   "08:00:27": "VirtualBox",
    "00:0c:29": "VMware",      "00:50:56": "VMware",
    "b8:27:eb": "Raspberry Pi","dc:a6:32": "Raspberry Pi",
    "e4:5f:01": "Raspberry Pi","00:11:32": "Synology NAS",
    "3c:84:6a": "Asus",        "ac:9e:17": "Asus",
    "f8:32:e4": "Asus",        "00:26:b9": "Dell",
    "f8:db:88": "Dell",        "8c:8d:28": "Intel",
    "fc:f8:ae": "Apple",       "a8:86:dd": "Apple",
    "28:cf:da": "Apple",       "3c:22:fb": "Apple",
    "48:d6:d5": "Apple TV",    "40:cb:c0": "Samsung",
    "8c:77:12": "Samsung",     "b8:bc:1b": "Samsung",
    "f4:9f:54": "Samsung",     "00:1d:25": "Huawei",
    "04:f9:38": "Huawei",      "50:68:0a": "Xiaomi",
    "28:6c:07": "Xiaomi",      "68:72:51": "D-Link",
    "cc:40:d0": "Netgear",     "00:14:6c": "Netgear",
    "ac:84:c6": "LG",          "78:4f:43": "LG",
    "f0:5c:19": "Sony",        "bc:30:7d": "Sonos",
    "94:9f:3e": "Amazon Echo", "68:37:e9": "Amazon Echo",
    "fc:a1:83": "Amazon Fire", "7c:bb:8a": "Google Nest",
    "f4:f5:d8": "Chromecast",  "54:60:09": "Chromecast",
}
