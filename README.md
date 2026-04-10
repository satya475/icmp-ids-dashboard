# PingGuard — Enterprise Network Intelligence Platform

> **Predict. Prevent. Perform.**
> Know which routers are failing before they fail.

PingGuard is a professional network monitoring and intelligence platform that monitors all devices on your network using ICMP probing, auto-discovery, bandwidth analysis, and AI-powered health scoring. It detects router degradation over time and predicts which routers need replacement before they fail.

---

## Table of Contents

1. [Project Vision](#project-vision)
2. [Features](#features)
3. [Project Structure](#project-structure)
4. [Requirements](#requirements)
5. [Installation](#installation)
6. [Environment Setup](#environment-setup)
7. [Running the Project](#running-the-project)
8. [Dashboard Pages](#dashboard-pages)
9. [How It Works](#how-it-works)
10. [Configuration](#configuration)
11. [Roadmap](#roadmap)

---

## Project Vision

PingGuard is built for large companies with many routers across multiple locations. It solves a specific problem — old routers degrade slowly over weeks and months. IT teams only notice when they fail completely, causing expensive downtime. PingGuard tracks every router's health score over time, calculates its degradation rate, and tells you exactly which ones need replacement before they fail.

---

## Features

### Core Monitoring
- **Adaptive ICMP Probing** — sends 3 to 15 packets per device based on device state. Stable devices get 3 packets, degraded devices get 15 for maximum accuracy
- **Median RTT** — uses median instead of average to resist outlier packets
- **Jitter Calculation** — standard deviation of RTT samples shows connection stability
- **Smart Packet Loss** — distinguishes real failures from devices in sleep mode
- **Quality Scoring** — rates each device as excellent / good / fair / poor / bad

### Auto Discovery
- **ARP Broadcast** — finds all devices including phones and IoT that block ping
- **TCP Port Scan** — finds devices that block ICMP using common ports
- **Ping Sweep + ARP Cache** — fallback method using Windows built-in tools
- **MAC Vendor Lookup** — identifies device manufacturer from MAC address
- **Reverse DNS** — resolves hostnames automatically

### AI & Intelligence
- **Device Classifier** — identifies device type (router/phone/laptop/IoT/TV/server) from behavior patterns
- **Anomaly Detection** — Z-score analysis detects RTT spikes against device's own baseline
- **Predictive Alerts** — linear regression predicts RTT threshold breach before it happens
- **Bandwidth Spike Detection** — flags traffic 3x above rolling 30-minute average
- **Self-Training Model** — learns your network's normal RTT thresholds every 10 minutes

### Network Health
- **Health Scoring** — 4-dimension score: RTT (30%) + Packet Loss (30%) + Stability (20%) + Devices (20%)
- **Trend Analysis** — detects if health is improving, stable, or declining
- **Router Sessions** — every router gets its own tracked session
- **Router Advisor** — compares sessions and recommends best performing router
- **Radar Chart Comparison** — side-by-side visual comparison of two routers

### Bandwidth Monitoring
- **Per-device Traffic** — captures bandwidth usage per device
- **Daily/Weekly Totals** — tracks usage over time
- **Top Devices** — identifies highest bandwidth consumers

### Alerts & Reports
- **Email Alerts** — Gmail SMTP notifications on device DOWN and high RTT
- **PDF Reports** — daily and weekly reports with uptime, RTT history, bandwidth
- **Alert History** — full log of all state changes and anomalies

### Infrastructure
- **Network Watchdog** — detects router switches within 10 seconds
- **Auto Network Detection** — reads current gateway from ipconfig automatically
- **IP Validation** — warns if entered IP doesn't match current network
- **Traceroute Mapping** — maps hop paths using Windows tracert
- **No Popup Terminals** — all subprocesses run silently in background

---

## Project Structure

```
Network_Monitoring/
│
├── main.py                          # Single entry point — run this
├── config.py                        # All settings, loads from .env
├── requirements.txt                 # Python dependencies
├── .env                             # Your secrets (create from .env.example)
├── .env.example                     # Template for .env file
├── .gitignore                       # Git ignore rules
├── cleanup.py                       # One-time cleanup for stale devices
│
├── core/                            # All monitoring engines
│   ├── probe.py                     # Adaptive ICMP engine — median RTT + jitter
│   ├── discovery.py                 # Multi-method device discovery
│   ├── bandwidth.py                 # Packet capture bandwidth monitoring
│   ├── health.py                    # Health scoring + self-training + router advisor
│   ├── state.py                     # State machine — UP/DEGRADED/DOWN
│   ├── alerts.py                    # Email alert system
│   ├── classifier.py                # Device type identification by behavior
│   ├── anomaly.py                   # Anomaly detection + prediction engine
│   ├── traceroute.py                # Hop mapping using Windows tracert
│   ├── network_watchdog.py          # Router switch detection every 10s
│   └── reports.py                   # PDF report generator
│
├── db/
│   ├── database.py                  # SQLite connection + schema init
│   └── queries.py                   # All SQL queries (never write SQL elsewhere)
│
├── api/
│   ├── routes.py                    # All Flask API endpoints
│   └── process_manager.py          # Subprocess lifecycle management
│
├── utils/
│   ├── network.py                   # Dynamic network detection + IP validation
│   └── formatters.py               # Byte formatting, vendor lookup
│
└── web/
    ├── templates/
    │   ├── dashboard.html           # Main dashboard
    │   ├── health.html              # Router health comparison
    │   ├── insights.html            # AI insights page
    │   ├── bandwidth.html           # Bandwidth monitoring
    │   └── reports.html            # PDF reports page
    └── static/
        ├── css/
        │   └── style.css            # All styles
        └── js/
            ├── dashboard.js         # Dashboard JavaScript
            └── bandwidth.js         # Bandwidth JavaScript
```

---

## Requirements

### System Requirements

| Requirement | Version | Notes |
|---|---|---|
| Windows | 10 or 11 | Raw sockets require Windows |
| Python | 3.10 or higher | Must be run as Administrator |
| npcap | Latest | Required for ARP broadcast and packet capture |
| Node.js | 18+ | Only needed for PDF generation (optional) |

### Python Version

```
Python 3.10+
```

Check your version:
```bash
python --version
```

### Why Administrator?

Raw ICMP sockets require Administrator privileges on Windows. Always run VS Code or your terminal as Administrator before starting the project.

---

## Installation

### Step 1 — Install Python 3.10+

Download from [python.org](https://www.python.org/downloads/). During installation check **Add Python to PATH**.

Verify:
```bash
python --version
```

### Step 2 — Install npcap

Download from [npcap.com](https://npcap.com/#download) and install with:
- Check **Install Npcap in WinPcap API-compatible Mode**
- Check **Support raw 802.11 traffic**

npcap is required for ARP broadcast device discovery and packet capture bandwidth monitoring.

### Step 3 — Clone or download the project

Place the project in a folder. Example:
```
C:\Users\yourname\Documents\Network_Monitoring\
```

### Step 4 — Create virtual environment

Open terminal **as Administrator** in the project folder:

```bash
python -m venv .venv
.venv\Scripts\activate
```

You should see `(.venv)` at the start of your terminal prompt.

### Step 5 — Install Python dependencies

```bash
pip install -r requirements.txt
```

This installs all required packages. See full list below.

### Step 6 — Create .env file

```bash
copy .env.example .env
```

Edit `.env` with your settings (see Environment Setup section).

### Step 7 — Verify installation

```bash
python -c "import flask, icmplib, scapy, colorama, psutil, reportlab; print('All packages OK')"
```

---

## Python Dependencies

Full `requirements.txt`:

```
flask>=2.3.0
icmplib>=3.0.0
scapy>=2.5.0
colorama>=0.4.6
psutil>=5.9.0
python-dotenv>=1.0.0
reportlab>=4.0.0
```

| Package | Version | Purpose |
|---|---|---|
| flask | 2.3.0+ | Web dashboard and REST API |
| icmplib | 3.0.0+ | Raw ICMP socket probing |
| scapy | 2.5.0+ | ARP broadcast discovery and packet capture |
| colorama | 0.4.6+ | Colored terminal output on Windows |
| psutil | 5.9.0+ | System and network interface info |
| python-dotenv | 1.0.0+ | Load settings from .env file |
| reportlab | 4.0.0+ | PDF report generation |

Install individually if needed:
```bash
pip install flask>=2.3.0
pip install icmplib>=3.0.0
pip install scapy>=2.5.0
pip install colorama>=0.4.6
pip install psutil>=5.9.0
pip install python-dotenv>=1.0.0
pip install reportlab>=4.0.0
```

---

## Environment Setup

Copy `.env.example` to `.env` and fill in your values:

```env
# ── Dashboard ─────────────────────────────
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=5000
SECRET_KEY=change-this-to-a-random-string

# ── Database ──────────────────────────────
DB_FILE=network_monitor.db

# ── Probe settings ────────────────────────
PROBE_INTERVAL=10
PROBE_TIMEOUT=2

# ── Alert thresholds ──────────────────────
RTT_ALERT_THRESHOLD_MS=200
ALERT_COOLDOWN_MINUTES=10

# ── Email alerts (Gmail) ──────────────────
ALERT_EMAIL_ENABLED=false
ALERT_EMAIL_FROM=your@gmail.com
ALERT_EMAIL_TO=alerts@gmail.com
ALERT_EMAIL_PASSWORD=your-gmail-app-password
ALERT_EMAIL_SMTP=smtp.gmail.com
ALERT_EMAIL_PORT=587
```

### Setting up Gmail alerts

Gmail requires an **App Password** — not your regular password.

1. Go to [myaccount.google.com](https://myaccount.google.com)
2. Click **Security**
3. Enable **2-Step Verification** (required)
4. Go to **App passwords**
5. Select **Mail** and **Windows Computer**
6. Copy the 16-character password
7. Paste into `ALERT_EMAIL_PASSWORD` in your `.env`
8. Set `ALERT_EMAIL_ENABLED=true`

---

## Running the Project

**Always run as Administrator.**

### Start the dashboard

```bash
python main.py
```

Open your browser at:
```
http://localhost:5000
```

### First time setup

1. Open `http://localhost:5000`
2. The router IP field auto-fills your current gateway
3. Click **Start**
4. Wait 30 seconds for devices to appear
5. Click any device row to load RTT and packet loss graphs

### Switching routers

1. Physically connect to the new router
2. Click **Stop** on the dashboard
3. The IP field automatically shows the new router IP
4. Click **Start**
5. Old network devices disappear, new network is discovered automatically

### Cleanup stale devices (one-time)

If you have old network devices showing in the table:
```bash
python cleanup.py
```

---

## Dashboard Pages

| URL | Page | Description |
|---|---|---|
| `localhost:5000` | Dashboard | Device table, topology map, RTT graphs, activity feed |
| `localhost:5000/health` | Network Health | Router session comparison, health trend, router advisor |
| `localhost:5000/insights` | AI Insights | Anomaly feed, device classification, predictions |
| `localhost:5000/bandwidth` | Bandwidth | Per-device traffic, daily and weekly totals |
| `localhost:5000/reports` | Reports | Download daily or weekly PDF report |

---

## How It Works

### Engines running in background

When you click Start, these engines launch silently (no popup windows):

| Engine | Interval | What it does |
|---|---|---|
| Network Watchdog | Every 10s | Detects router changes, cleans stale devices |
| Discovery | Every 60s | Scans subnet, finds new devices |
| Probe | Every 10s | ICMP pings all devices, records RTT and loss |
| Traceroute | Every 60s | Maps hop paths to all devices |
| Health | Every 60s | Calculates network health score (runs in main process) |
| Classifier | Every 5min | Identifies device types from behavior |
| Anomaly Detector | Every 60s | Checks for RTT spikes, bandwidth spikes, predicted failures |

### Database tables

All data is stored in `network_monitor.db` (SQLite):

| Table | Contents |
|---|---|
| `active_targets` | Devices currently being monitored |
| `discovered_devices` | All discovered devices with MAC and vendor |
| `probe_results` | RTT, jitter, packet loss per device per probe |
| `state_changes` | UP/DEGRADED/DOWN transition history |
| `bandwidth_samples` | Per-device traffic every 5 seconds |
| `health_snapshots` | Network health score every 60 seconds |
| `router_sessions` | One session per router with start/end time |
| `device_classifications` | Learned device type per IP |
| `anomaly_events` | All detected anomalies and predictions |
| `model_state` | Self-trained threshold values |
| `hop_routes` | Traceroute hop paths per device |
| `network_state` | Current gateway and network info |

### Health scoring formula

```
Health Score = RTT Score × 30%
             + Loss Score × 30%
             + Stability Score × 20%
             + Device Score × 20%
```

After 50+ snapshots the model adapts thresholds to your specific network's normal behavior.

---

## Configuration

All configuration is in `config.py` and loaded from `.env`.

Key settings:

| Setting | Default | Description |
|---|---|---|
| `PROBE_INTERVAL` | 10s | How often to probe all devices |
| `PROBE_TIMEOUT` | 2s | Max wait per ICMP packet |
| `SCAN_INTERVAL` | 60s | How often to scan for new devices |
| `DOWN_THRESHOLD` | 3 | Consecutive failures before marking DOWN |
| `UP_THRESHOLD` | 2 | Consecutive successes before marking UP |
| `RTT_ALERT_THRESHOLD_MS` | 200ms | RTT above this triggers email alert |
| `ALERT_COOLDOWN_MINUTES` | 10 | Min minutes between repeat alerts |

---

## Roadmap

| Phase | Status | Description |
|---|---|---|
| Phase 1 — Core Monitoring | Complete | ICMP probe, discovery, bandwidth, state machine |
| Phase 2 — AI & Health | Complete | Health scoring, classifier, anomaly detection, router advisor |
| Phase 3 — Long-term Tracking | Next | Per-device health over months, degradation rate |
| Phase 4 — Replacement Prediction | Planned | LSTM prediction, survival analysis, failure date |
| Phase 5 — Enterprise Scale | Planned | Multi-site, agent architecture, SNMP |
| Phase 6 — Authentication & Deploy | Planned | Login, AWS EC2, Docker, HTTPS |
| Phase 7 — SaaS Product | Future | Multi-tenant, billing, enterprise features |

---

## Troubleshooting

**Probe stopped / NameError**
```bash
# Verify probe.py has EXTERNAL_TARGETS defined
python -c "from core.probe import EXTERNAL_TARGETS; print('OK')"
```

**Permission denied on ICMP**
Run your terminal as Administrator.

**npcap not found**
Install npcap from npcap.com with WinPcap compatibility mode enabled.

**Old network devices showing**
```bash
python cleanup.py
```

**Health page shows nothing**
Wait 60 seconds after clicking Start for first health snapshot.

**Popup terminals when clicking Start**
Ensure you're using the latest `api/process_manager.py` with `CREATE_NO_WINDOW` flag.

---

## Built With

- **Python 3.10** — core language
- **Flask** — web framework and REST API
- **icmplib** — raw ICMP socket probing
- **Scapy** — ARP broadcast and packet capture
- **SQLite** — local database
- **ReportLab** — PDF generation
- **Chart.js** — RTT and bandwidth graphs
- **npcap** — Windows packet capture driver

---

*PingGuard — Built for enterprise network intelligence.*



## Installation

### Requirements
- Python 3.10+
- Windows (uses icmplib, tracert)
- Npcap (for bandwidth monitoring) — https://npcap.com

### First time setup
```bash
git clone https://github.com/yourname/pingguard
cd pingguard
pip install -r requirements.txt
python setup.py        # creates DB, downloads vendor data, trains models
python main.py         # start the dashboard
```

Open http://localhost:5000 — enter your router IP and click Start.

### Note
The database (`network_monitor.db`) is not included in the repo intentionally.
`setup.py` creates a fresh one for your network automatically.