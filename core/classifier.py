"""
core/classifier.py
==================
AI device classifier — identifies device type from behavior.

Uses 4 signals:
  1. Active hours pattern    (when does it respond?)
  2. RTT fingerprint         (how fast does it respond?)
  3. Packet loss pattern     (how often does it drop?)
  4. Traffic volume pattern  (how much bandwidth does it use?)

Device types:
  router    — gateway device, very low RTT, always up
  server    — always on, low RTT, high traffic
  laptop    — active during day, medium RTT, medium traffic
  phone     — irregular hours, medium RTT, sleeps often
  iot       — always on but drops packets, very low traffic
  tv        — active evenings, high traffic bursts
  printer   — rarely active, very low traffic
  unknown   — not enough data yet
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import sqlite3
from datetime import datetime, timedelta
from db.database import get_connection
from db.queries import load_active_targets
from config import DB_FILE

# ─────────────────────────────────────────
# Database
# ─────────────────────────────────────────

def init_classifier_table(db_file: str = DB_FILE):
    conn = get_connection(db_file)
    conn.execute("""CREATE TABLE IF NOT EXISTS device_classifications (
        ip           TEXT PRIMARY KEY,
        device_type  TEXT NOT NULL,
        confidence   REAL NOT NULL,
        signals      TEXT,
        classified_at TEXT NOT NULL,
        sample_count INTEGER DEFAULT 0
    )""")
    conn.commit()
    conn.close()


def save_classification(ip: str, device_type: str,
                        confidence: float, signals: dict,
                        sample_count: int,
                        db_file: str = DB_FILE):
    import json
    conn = get_connection(db_file)
    conn.execute("""INSERT INTO device_classifications
        (ip, device_type, confidence, signals, classified_at, sample_count)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(ip) DO UPDATE SET
            device_type=excluded.device_type,
            confidence=excluded.confidence,
            signals=excluded.signals,
            classified_at=excluded.classified_at,
            sample_count=excluded.sample_count""",
        (ip, device_type, confidence,
         json.dumps(signals), datetime.now().isoformat(), sample_count))
    conn.commit()
    conn.close()


def get_classifications(db_file: str = DB_FILE) -> dict:
    """Returns {ip: {type, confidence, signals}} dict."""
    import json
    conn = get_connection(db_file)
    try:
        rows = conn.execute(
            "SELECT * FROM device_classifications"
        ).fetchall()
        conn.close()
        result = {}
        for r in rows:
            result[r["ip"]] = {
                "device_type":  r["device_type"],
                "confidence":   r["confidence"],
                "signals":      json.loads(r["signals"] or "{}"),
                "sample_count": r["sample_count"],
                "classified_at":r["classified_at"],
            }
        return result
    except Exception:
        conn.close()
        return {}


# ─────────────────────────────────────────
# Signal collectors
# ─────────────────────────────────────────

def _collect_rtt_signal(ip: str, conn) -> dict:
    """Analyze RTT patterns over last 24h."""
    rows = conn.execute("""
        SELECT rtt_avg_ms FROM probe_results
        WHERE host=? AND is_alive=1
          AND timestamp > datetime('now', '-24 hours')
        ORDER BY timestamp DESC LIMIT 200
    """, (ip,)).fetchall()

    if not rows:
        return {"avg_rtt": None, "rtt_consistency": None, "sample_count": 0}

    rtts = [r["rtt_avg_ms"] for r in rows if r["rtt_avg_ms"]]
    if not rtts:
        return {"avg_rtt": None, "rtt_consistency": None, "sample_count": 0}

    avg  = sum(rtts) / len(rtts)
    variance = sum((r - avg)**2 for r in rtts) / len(rtts)
    std  = variance ** 0.5
    consistency = max(0, 100 - (std / avg * 100)) if avg > 0 else 0

    return {
        "avg_rtt":        round(avg, 1),
        "rtt_consistency":round(consistency, 1),
        "sample_count":   len(rtts),
    }


def _collect_availability_signal(ip: str, conn) -> dict:
    """Analyze availability and sleep patterns."""
    rows = conn.execute("""
        SELECT is_alive,
               strftime('%H', timestamp) as hour
        FROM probe_results
        WHERE host=?
          AND timestamp > datetime('now', '-48 hours')
        ORDER BY timestamp DESC LIMIT 500
    """, (ip,)).fetchall()

    if len(rows) < 10:
        return {"availability": None, "sleeps_at_night": None,
                "always_on": None}

    total    = len(rows)
    alive    = sum(1 for r in rows if r["is_alive"] == 1)
    avail    = (alive / total) * 100

    # Check night hours (22:00 - 07:00)
    night_rows  = [r for r in rows if int(r["hour"] or 0) >= 22
                   or int(r["hour"] or 0) < 7]
    day_rows    = [r for r in rows if 7 <= int(r["hour"] or 0) < 22]

    night_avail = (sum(1 for r in night_rows if r["is_alive"]==1) /
                   len(night_rows) * 100) if night_rows else None
    day_avail   = (sum(1 for r in day_rows if r["is_alive"]==1) /
                   len(day_rows) * 100) if day_rows else None

    sleeps_night = (night_avail is not None and
                    day_avail is not None and
                    night_avail < day_avail - 20)

    return {
        "availability":   round(avail, 1),
        "night_avail":    round(night_avail, 1) if night_avail else None,
        "day_avail":      round(day_avail, 1)   if day_avail   else None,
        "sleeps_at_night":sleeps_night,
        "always_on":      avail > 95,
    }


def _collect_traffic_signal(ip: str, conn) -> dict:
    """Analyze bandwidth usage patterns."""
    try:
        rows = conn.execute("""
            SELECT SUM(bytes_in) as total_in,
                   SUM(bytes_out) as total_out,
                   COUNT(*) as samples
            FROM bandwidth_samples
            WHERE ip=?
              AND timestamp > datetime('now', '-24 hours')
        """, (ip,)).fetchone()

        if not rows or not rows["samples"]:
            return {"total_traffic": None, "traffic_level": "unknown"}

        total = (rows["total_in"] or 0) + (rows["total_out"] or 0)
        if total > 1_000_000_000:   level = "very_high"   # >1GB
        elif total > 100_000_000:   level = "high"         # >100MB
        elif total > 10_000_000:    level = "medium"       # >10MB
        elif total > 1_000_000:     level = "low"          # >1MB
        else:                       level = "very_low"

        return {
            "total_traffic": total,
            "traffic_level": level,
        }
    except Exception:
        return {"total_traffic": None, "traffic_level": "unknown"}


# ─────────────────────────────────────────
# Classification logic
# ─────────────────────────────────────────

def _classify(ip: str, name: str,
              rtt_sig: dict,
              avail_sig: dict,
              traffic_sig: dict,
              vendor: str = None,
              mac: str = None) -> tuple[str, float, dict]:
    """
    Rule-based classifier using all signals.
    Returns (device_type, confidence, signals_summary).
    """
    signals = {**rtt_sig, **avail_sig, **traffic_sig}
    name_l  = (name or "").lower()
    vendor_l= (vendor or "").lower()
    avg_rtt = rtt_sig.get("avg_rtt")
    avail   = avail_sig.get("availability")
    always  = avail_sig.get("always_on", False)
    sleeps  = avail_sig.get("sleeps_at_night", False)
    traffic = traffic_sig.get("traffic_level", "unknown")

    # ── Router detection ──────────────────
    # Routers: very low RTT, always on, gateway keywords
    # Exclude devices with Intel/laptop MACs — those are PCs not routers
    laptop_mac_vendors = ["intel","dell","hp inc","lenovo","acer",
                          "asus","realtek","d8:b3","d8:b3:2f"]
    is_laptop_mac = any(k in vendor_l for k in laptop_mac_vendors)

    if avg_rtt is not None and avg_rtt < 10 and always and not is_laptop_mac:
        if any(k in name_l for k in ["router","gateway","gw"]):
            return "router", 98.0, signals
        if avg_rtt < 5:
            return "router", 92.0, signals
    # Also detect by name
    if any(k in name_l for k in ["router","gateway","gw"]):
        return "router", 90.0, signals

    # ── External DNS/Server detection ─────
    if ip in ("8.8.8.8", "1.1.1.1", "8.8.4.4", "1.0.0.1"):
        return "server", 95.0, signals

    # ── Server detection ──────────────────
    # Servers: always on, low RTT, high traffic
    if always and avg_rtt is not None and avg_rtt < 30:
        if traffic in ("high", "very_high"):
            return "server", 85.0, signals
        if any(k in name_l for k in ["server","nas","pi","host","desktop"]):
            return "server", 80.0, signals

    # ── Vendor-based detection ────────────
    if "apple tv" in vendor_l or "chromecast" in vendor_l:
        return "tv", 85.0, signals
    if "sonos" in vendor_l:
        return "tv", 80.0, signals
    if any(k in vendor_l for k in ["amazon echo","google nest","philips hue"]):
        return "iot", 85.0, signals
    if "raspberry pi" in vendor_l:
        return "server", 75.0, signals

    # ── Phone detection ───────────────────
    # Phones: identified by vendor MAC prefix or sleep pattern
    phone_vendors = ["apple","samsung","xiaomi","huawei","oppo",
                     "vivo","oneplus","realme","nokia","motorola",
                     "lg electronics","sony mobile"]
    if any(k in vendor_l for k in phone_vendors):
        return "phone", 88.0, signals
    # Phone by behavior — sleeps at night
    if sleeps:
        if avg_rtt is not None and avg_rtt < 300:
            return "phone", 78.0, signals

    # ── Laptop detection ──────────────────
    # Laptops: identified by vendor or intermittent availability
    laptop_vendors = ["intel","dell","hp inc","hewlett","lenovo",
                      "acer","asus","microsoft","toshiba","razer"]
    if any(k in vendor_l for k in laptop_vendors):
        return "laptop", 85.0, signals
    # Laptop by behavior — available during day, offline sometimes
    if not always and avail is not None and 30 < avail < 90:
        day_a  = avail_sig.get("day_avail", 50)
        night_a= avail_sig.get("night_avail", 50)
        if day_a > 60:  # more active during day
            return "laptop", 72.0, signals

    # ── TV/Media detection ─────────────────
    tv_vendors = ["samsung electronics","lg innotek","sony",
                  "apple tv","chromecast","amazon","roku"]
    if any(k in vendor_l for k in tv_vendors):
        return "tv", 85.0, signals
    if traffic in ("high", "very_high") and not always:
        return "tv", 70.0, signals

    # ── Printer detection ─────────────────
    printer_vendors = ["hp inc","seiko epson","canon","brother",
                       "xerox","lexmark","ricoh"]
    if any(k in name_l + vendor_l
           for k in ["printer","print","epson","canon","brother"]):
        return "printer", 82.0, signals
    if any(k in vendor_l for k in printer_vendors):
        return "printer", 80.0, signals

    # ── IoT detection ─────────────────────
    # IoT: always on, very low traffic, not identified above
    iot_vendors = ["espressif","raspberry pi","arduino",
                   "shenzhen","tuya","hikvision","dahua",
                   "philips","ikea","belkin","tp-link"]
    if any(k in vendor_l for k in iot_vendors):
        return "iot", 85.0, signals
    if always and traffic in ("very_low", "low"):
        return "iot", 68.0, signals

    # ── Unknown ───────────────────────────
    if rtt_sig.get("sample_count", 0) < 5:
        return "unknown", 0.0, signals   # not enough data

    return "unknown", 40.0, signals


# ─────────────────────────────────────────
# Device type icons and colors
# ─────────────────────────────────────────

DEVICE_TYPE_META = {
    "router":  {"icon": "R", "color": "#3b82f6", "label": "Router"},
    "server":  {"icon": "S", "color": "#22c55e", "label": "Server"},
    "laptop":  {"icon": "L", "color": "#a855f7", "label": "Laptop"},
    "phone":   {"icon": "P", "color": "#f59e0b", "label": "Phone"},
    "iot":     {"icon": "I", "color": "#06b6d4", "label": "IoT Device"},
    "tv":      {"icon": "T", "color": "#f97316", "label": "TV/Media"},
    "printer": {"icon": "P", "color": "#64748b", "label": "Printer"},
    "unknown": {"icon": "?", "color": "#374151", "label": "Unknown"},
}


# ─────────────────────────────────────────
# Main classification runner
# ─────────────────────────────────────────

def classify_all(db_file: str = DB_FILE):
    """Classify all active devices using Random Forest if available."""
    conn     = get_connection(db_file)
    targets  = load_active_targets(db_file)

    # Get vendor info
    vendors  = {}
    try:
        rows = conn.execute(
            "SELECT ip, vendor FROM discovered_devices"
        ).fetchall()
        vendors = {r["ip"]: r["vendor"] for r in rows}
    except Exception:
        pass

    macs = {}
    try:
        mac_rows = conn.execute(
            "SELECT ip, mac FROM discovered_devices"
        ).fetchall()
        macs = {r["ip"]: r["mac"] for r in mac_rows}
    except Exception:
        pass

    results = []
    for t in targets:
        ip   = t["host"]
        name = t["name"]

        rtt_sig    = _collect_rtt_signal(ip, conn)
        avail_sig  = _collect_availability_signal(ip, conn)
        traffic_sig= _collect_traffic_signal(ip, conn)

        # Use rule-based classifier as primary
        # RF used only when confidence is very high (>85%)
# Get MAC address for this device
        macs = {}
        try:
            mac_rows = conn.execute(
                "SELECT ip, mac FROM discovered_devices"
            ).fetchall()
            macs = {r["ip"]: r["mac"] for r in mac_rows}
        except Exception:
            pass

        device_type, confidence, signals = _classify(
            ip, name, rtt_sig, avail_sig, traffic_sig,
            vendors.get(ip, ""), macs.get(ip, ""))

        # Try RF as secondary — only override if RF is very confident
        try:
            from core.ml_engine import classify_device_rf
            rf_result = classify_device_rf(ip, db_file)
            if (rf_result["method"] == "random_forest" and
                rf_result["confidence"] > 85 and
                rf_result["device_type"] != "unknown"):
                # RF is very confident — use its result
                device_type = rf_result["device_type"]
                confidence  = rf_result["confidence"]
                signals     = {**rtt_sig, "method": "random_forest_confirmed"}
        except Exception:
            pass  # stick with rule-based result

        save_classification(ip, device_type, confidence,
                            signals, rtt_sig.get("sample_count", 0),
                            db_file)
        results.append({
            "ip": ip, "name": name,
            "device_type": device_type,
            "confidence":  confidence,
        })
        print(f"  [CLASSIFY] {name:<20} → {device_type:<10} "
              f"({confidence:.0f}% confidence)")

    conn.close()
    return results


# ─────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────

def run():
    init_classifier_table()
    print("  Device classifier started.")
    print("  Re-classifies every 5 minutes as data accumulates.\n")

    while True:
        try:
            classify_all()
        except Exception as e:
            print(f"  [CLASSIFIER ERROR] {e}")
        time.sleep(300)   # re-classify every 5 minutes


if __name__ == "__main__":
    run()