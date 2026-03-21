"""
core/anomaly.py
================
Phase 3 — Anomaly detection and predictive alerting.

Three detection methods:
  1. RTT anomaly      — Z-score on per-device RTT baseline
  2. Bandwidth spike  — rolling average comparison
  3. Predictive alert — linear regression trend extrapolation

All results saved to anomaly_events table.
Fires alerts via core/alerts.py when anomalies detected.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math
import time
from datetime import datetime, timedelta
from db.database import get_connection
from db.queries import load_active_targets
from config import DB_FILE

# ─────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────
ANOMALY_INTERVAL     = 60      # seconds between anomaly checks
Z_SCORE_THRESHOLD    = 2.5     # std deviations above mean = anomaly
MIN_BASELINE_SAMPLES = 20      # need at least 20 readings for baseline
SPIKE_MULTIPLIER     = 3.0     # current traffic > 3x average = spike
SPIKE_MIN_BYTES      = 100_000 # ignore spikes below 100KB (noise)
PREDICTION_MINUTES   = 5       # predict this many minutes ahead
REGRESSION_SAMPLES   = 20      # use last N samples for regression
RTT_ALERT_THRESHOLD  = float(os.getenv("RTT_ALERT_THRESHOLD_MS", "200"))

# Cooldown — don't fire same anomaly type for same device within N minutes
ANOMALY_COOLDOWN_MIN = 5

# ─────────────────────────────────────────
# Database
# ─────────────────────────────────────────

def init_anomaly_table(db_file: str = DB_FILE):
    conn = get_connection(db_file)
    conn.execute("""CREATE TABLE IF NOT EXISTS anomaly_events (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp    TEXT NOT NULL,
        host         TEXT NOT NULL,
        name         TEXT NOT NULL,
        anomaly_type TEXT NOT NULL,
        severity     TEXT NOT NULL,
        value        REAL,
        baseline     REAL,
        deviation    REAL,
        message      TEXT,
        alerted      INTEGER DEFAULT 0
    )""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_anomaly_host
        ON anomaly_events(host, timestamp)""")
    conn.commit()
    conn.close()


def save_anomaly(host: str, name: str, anomaly_type: str,
                 severity: str, value: float, baseline: float,
                 deviation: float, message: str,
                 db_file: str = DB_FILE):
    conn = get_connection(db_file)
    conn.execute("""INSERT INTO anomaly_events
        (timestamp, host, name, anomaly_type, severity,
         value, baseline, deviation, message)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (datetime.now().isoformat(), host, name,
         anomaly_type, severity, value, baseline, deviation, message))
    conn.commit()
    conn.close()


def get_recent_anomalies(hours: int = 24,
                         db_file: str = DB_FILE) -> list:
    conn = get_connection(db_file)
    since = (datetime.now() - timedelta(hours=hours)).isoformat()
    rows  = conn.execute("""
        SELECT * FROM anomaly_events
        WHERE timestamp > ?
        ORDER BY timestamp DESC
        LIMIT 100
    """, (since,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _was_recently_alerted(host: str, anomaly_type: str,
                           db_file: str = DB_FILE) -> bool:
    """Check cooldown — don't repeat same anomaly within N minutes."""
    conn   = get_connection(db_file)
    since  = (datetime.now() -
               timedelta(minutes=ANOMALY_COOLDOWN_MIN)).isoformat()
    row    = conn.execute("""
        SELECT COUNT(*) as cnt FROM anomaly_events
        WHERE host=? AND anomaly_type=? AND timestamp>?
    """, (host, anomaly_type, since)).fetchone()
    conn.close()
    return (row["cnt"] if row else 0) > 0


# ─────────────────────────────────────────
# Statistics helpers
# ─────────────────────────────────────────

def _mean(values: list) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list, mean: float) -> float:
    if len(values) < 2:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def _z_score(value: float, mean: float, std: float) -> float:
    return (value - mean) / std if std > 0 else 0.0


def _linear_regression(x: list, y: list) -> tuple:
    """
    Simple linear regression.
    Returns (slope, intercept) where y = slope*x + intercept.
    """
    n = len(x)
    if n < 2:
        return 0.0, y[0] if y else 0.0

    mean_x = _mean(x)
    mean_y = _mean(y)

    num   = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    denom = sum((xi - mean_x) ** 2 for xi in x)

    slope     = num / denom if denom != 0 else 0.0
    intercept = mean_y - slope * mean_x
    return slope, intercept


# ─────────────────────────────────────────
# Detection 1: RTT anomaly (Z-score)
# ─────────────────────────────────────────

def detect_rtt_anomaly(host: str, name: str,
                        conn) -> dict | None:
    """
    Compare latest RTT against device's own historical baseline.
    Z-score > 2.5 = anomaly.
    """
    # Get last 50 RTT readings as baseline
    rows = conn.execute("""
        SELECT rtt_avg_ms FROM probe_results
        WHERE host=? AND is_alive=1
          AND timestamp > datetime('now', '-6 hours')
        ORDER BY timestamp DESC
        LIMIT 50
    """, (host,)).fetchall()

    values = [r["rtt_avg_ms"] for r in rows if r["rtt_avg_ms"]]

    if len(values) < MIN_BASELINE_SAMPLES:
        return None  # not enough data

    # Latest reading is values[0] (most recent)
    latest   = values[0]
    baseline = values[1:]  # exclude latest from baseline

    mean     = _mean(baseline)
    std      = _std(baseline, mean)
    z        = _z_score(latest, mean, std)

    if z < Z_SCORE_THRESHOLD:
        return None  # normal

    # Determine severity
    if z >= 4.0:   severity = "critical"
    elif z >= 3.0: severity = "high"
    else:          severity = "medium"

    return {
        "type":     "rtt_anomaly",
        "severity": severity,
        "value":    round(latest, 1),
        "baseline": round(mean, 1),
        "deviation":round(z, 2),
        "message":  (f"RTT spike detected on {name}: "
                     f"{latest:.1f}ms vs baseline {mean:.1f}ms "
                     f"(Z-score: {z:.1f})"),
    }


# ─────────────────────────────────────────
# Detection 2: RTT trend prediction
# ─────────────────────────────────────────

def detect_rtt_prediction(host: str, name: str,
                           conn) -> dict | None:
    """
    Linear regression on recent RTT readings.
    If predicted RTT in N minutes exceeds threshold — fire predictive alert.
    """
    rows = conn.execute("""
        SELECT rtt_avg_ms, timestamp FROM probe_results
        WHERE host=? AND is_alive=1
          AND timestamp > datetime('now', '-30 minutes')
        ORDER BY timestamp ASC
        LIMIT ?
    """, (host, REGRESSION_SAMPLES)).fetchall()

    values = [(i, r["rtt_avg_ms"]) for i, r in enumerate(rows)
              if r["rtt_avg_ms"]]

    if len(values) < 10:
        return None  # not enough recent data

    x = [v[0] for v in values]
    y = [v[1] for v in values]

    slope, intercept = _linear_regression(x, y)

    # Predict value N minutes ahead
    # Each sample ≈ 10 seconds, so N minutes = N*6 samples
    future_x    = x[-1] + (PREDICTION_MINUTES * 6)
    predicted   = slope * future_x + intercept
    current_rtt = y[-1]

    # Only alert if:
    # 1. RTT is trending up (positive slope)
    # 2. Predicted RTT exceeds threshold
    # 3. Current RTT is not already above threshold
    if (slope <= 0.5 or
        predicted <= RTT_ALERT_THRESHOLD or
        current_rtt >= RTT_ALERT_THRESHOLD):
        return None

    severity = "high" if predicted > RTT_ALERT_THRESHOLD * 2 else "medium"

    return {
        "type":     "rtt_prediction",
        "severity": severity,
        "value":    round(predicted, 1),
        "baseline": round(current_rtt, 1),
        "deviation":round(slope, 3),
        "message":  (f"Predicted degradation on {name}: "
                     f"RTT trending up at {slope:.1f}ms/sample. "
                     f"Predicted {predicted:.0f}ms in {PREDICTION_MINUTES} min "
                     f"(current: {current_rtt:.1f}ms)."),
    }


# ─────────────────────────────────────────
# Detection 3: Bandwidth spike
# ─────────────────────────────────────────

def detect_bandwidth_spike(host: str, name: str,
                            conn) -> dict | None:
    """
    Compare recent traffic against rolling 30-minute average.
    Current > 3x average AND above minimum threshold = spike.
    """
    try:
        # Last 60 seconds (recent)
        recent = conn.execute("""
            SELECT SUM(bytes_in + bytes_out) as total
            FROM bandwidth_samples
            WHERE ip=? AND timestamp > datetime('now', '-1 minute')
        """, (host,)).fetchone()

        # Last 30 minutes average per minute
        avg = conn.execute("""
            SELECT AVG(minute_total) as avg_per_min FROM (
                SELECT strftime('%Y-%m-%d %H:%M', timestamp) as minute,
                       SUM(bytes_in + bytes_out) as minute_total
                FROM bandwidth_samples
                WHERE ip=?
                  AND timestamp > datetime('now', '-30 minutes')
                  AND timestamp < datetime('now', '-1 minute')
                GROUP BY minute
            )
        """, (host,)).fetchone()

        recent_total = recent["total"] if recent and recent["total"] else 0
        avg_per_min  = avg["avg_per_min"] if avg and avg["avg_per_min"] else 0

        if recent_total < SPIKE_MIN_BYTES or avg_per_min == 0:
            return None

        ratio = recent_total / avg_per_min

        if ratio < SPIKE_MULTIPLIER:
            return None

        def fmt(b):
            if b >= 1e6: return f"{b/1e6:.1f}MB"
            if b >= 1e3: return f"{b/1e3:.1f}KB"
            return f"{int(b)}B"

        severity = "high" if ratio > 10 else "medium"

        return {
            "type":     "bandwidth_spike",
            "severity": severity,
            "value":    round(recent_total, 0),
            "baseline": round(avg_per_min, 0),
            "deviation":round(ratio, 1),
            "message":  (f"Bandwidth spike on {name}: "
                         f"{fmt(recent_total)}/min vs "
                         f"avg {fmt(avg_per_min)}/min "
                         f"({ratio:.1f}x normal)"),
        }
    except Exception:
        return None


# ─────────────────────────────────────────
# Main detection loop
# ─────────────────────────────────────────

def run_detection():
    """Run all detectors on all active targets."""
    targets = load_active_targets()
    conn    = get_connection(DB_FILE)
    found   = 0

    for t in targets:
        host = t["host"]
        name = t["name"]

        detectors = [
            ("rtt_anomaly",   detect_rtt_anomaly),
            ("rtt_prediction",detect_rtt_prediction),
            ("bandwidth_spike",detect_bandwidth_spike),
        ]

        for atype, detector in detectors:
            try:
                result = detector(host, name, conn)
                if result is None:
                    continue
                if _was_recently_alerted(host, atype):
                    continue

                # Save anomaly
                save_anomaly(
                    host, name,
                    result["type"], result["severity"],
                    result["value"], result["baseline"],
                    result["deviation"], result["message"])

                found += 1
                sev_prefix = {
                    "critical": "[CRITICAL]",
                    "high":     "[HIGH]    ",
                    "medium":   "[MEDIUM]  ",
                }.get(result["severity"], "[INFO]    ")

                print(f"  {sev_prefix} {result['message']}")

                # Send email alert for high/critical
                if result["severity"] in ("critical", "high"):
                    try:
                        from core.alerts import _send_email
                        subj = (f"[Network Monitor] {result['severity'].upper()}: "
                                f"{result['type']} on {name}")
                        body_text = result["message"]
                        body_html = f"""
                        <html><body style="font-family:system-ui;padding:20px">
                        <div style="background:#1a1d27;color:#e2e8f0;
                             border-radius:8px;padding:20px;max-width:500px">
                          <h3 style="color:#ef4444;margin:0 0 12px">
                            Anomaly Detected</h3>
                          <p style="margin:0;font-size:14px">{result['message']}</p>
                          <div style="margin-top:16px;font-size:12px;
                               color:#64748b">
                            Severity: {result['severity']} ·
                            Type: {result['type']}
                          </div>
                        </div></body></html>"""
                        _send_email(subj, body_html, body_text)
                    except Exception:
                        pass

            except Exception as e:
                print(f"  [ANOMALY ERROR] {name} {atype}: {e}")

    conn.close()
    if found:
        print(f"  [ANOMALY] {found} anomalies detected this cycle")
    else:
        print(f"  [ANOMALY] No anomalies detected — network looks normal")


# ─────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────

def run():
    init_anomaly_table()
    print("  Anomaly detector started.")
    print(f"  RTT Z-score threshold: {Z_SCORE_THRESHOLD}")
    print(f"  Bandwidth spike threshold: {SPIKE_MULTIPLIER}x average")
    print(f"  Prediction window: {PREDICTION_MINUTES} minutes ahead\n")

    while True:
        try:
            run_detection()
        except Exception as e:
            print(f"  [ANOMALY ERROR] {e}")
        time.sleep(ANOMALY_INTERVAL)


if __name__ == "__main__":
    run()
