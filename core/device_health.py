"""
core/device_health.py
======================
Phase 3 — Per-device long-term health tracking.

Runs every hour and:
  1. Aggregates today's probe results into daily health snapshot per device
  2. Calculates degradation rate (pts/week decline) per device
  3. Predicts replacement date based on decline rate
  4. Prunes old data according to retention policy:
       - probe_results:      7 days
       - health_snapshots:   30 days
       - device_health_daily: 6 months (180 days)
       - bandwidth_samples:  7 days
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import math
from datetime import datetime, timedelta
from db.database import get_connection
from config import DB_FILE

# ─────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────
AGGREGATION_INTERVAL = 3600   # run every 1 hour
CRITICAL_SCORE       = 30.0   # below this = critical, needs replacement
DEGRADED_SCORE       = 50.0   # below this = degraded

# Data retention
RETAIN_PROBE_DAYS      = 7
RETAIN_SNAPSHOT_DAYS   = 30
RETAIN_DAILY_DAYS      = 180   # 6 months
RETAIN_BANDWIDTH_DAYS  = 7
RETAIN_ANOMALY_DAYS    = 90


# ─────────────────────────────────────────
# Database schema
# ─────────────────────────────────────────

def init_device_health_tables(db_file: str = DB_FILE):
    conn = get_connection(db_file)

    # Daily health snapshot per device
    conn.execute("""CREATE TABLE IF NOT EXISTS device_health_daily (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        date          TEXT NOT NULL,
        ip            TEXT NOT NULL,
        name          TEXT,
        avg_rtt_ms    REAL,
        min_rtt_ms    REAL,
        max_rtt_ms    REAL,
        avg_jitter_ms REAL,
        packet_loss   REAL,
        uptime_pct    REAL,
        probe_count   INTEGER DEFAULT 0,
        health_score  REAL,
        UNIQUE(date, ip)
    )""")

    # Degradation analysis per device
    conn.execute("""CREATE TABLE IF NOT EXISTS device_degradation (
        ip                  TEXT PRIMARY KEY,
        name                TEXT,
        first_seen_date     TEXT,
        days_monitored      INTEGER DEFAULT 0,
        baseline_score      REAL,
        current_score       REAL,
        decline_rate_per_week REAL,
        predicted_critical_date TEXT,
        replacement_priority TEXT,
        confidence          REAL,
        last_calculated     TEXT
    )""")

    # Per-device RTT baseline
    conn.execute("""CREATE TABLE IF NOT EXISTS device_baselines (
        ip              TEXT PRIMARY KEY,
        name            TEXT,
        baseline_rtt_ms REAL,
        baseline_loss   REAL,
        baseline_jitter REAL,
        std_rtt_ms      REAL,
        sample_count    INTEGER DEFAULT 0,
        last_updated    TEXT
    )""")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_dhd_ip_date ON device_health_daily(ip, date)")
    conn.commit()
    conn.close()


# ─────────────────────────────────────────
# Daily aggregation
# ─────────────────────────────────────────

def aggregate_daily(db_file: str = DB_FILE):
    """
    Aggregate today's probe results into device_health_daily.
    Called every hour — uses UPSERT so running multiple times is safe.
    """
    conn  = get_connection(db_file)
    today = datetime.now().strftime("%Y-%m-%d")

    # Get all devices that have probe results today
    rows = conn.execute("""
        SELECT
            host as ip,
            name,
            AVG(rtt_avg_ms)   as avg_rtt,
            MIN(rtt_min_ms)   as min_rtt,
            MAX(rtt_max_ms)   as max_rtt,
            AVG(jitter_ms)    as avg_jitter,
            AVG(packet_loss)  as avg_loss,
            SUM(CASE WHEN is_alive=1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as uptime_pct,
            COUNT(*)          as probe_count
        FROM probe_results
        WHERE date(timestamp) = ?
        GROUP BY host, name
    """, (today,)).fetchall()

    saved = 0
    for r in rows:
        d = dict(r)

        # Calculate health score for this device for today
        rtt_score  = _score_rtt(d["avg_rtt"])
        loss_score = _score_loss((d["avg_loss"] or 0) * 100)
        up_score   = min(100, d["uptime_pct"] or 0)
        score      = rtt_score * 0.35 + loss_score * 0.35 + up_score * 0.30

        conn.execute("""
            INSERT INTO device_health_daily
                (date, ip, name, avg_rtt_ms, min_rtt_ms, max_rtt_ms,
                 avg_jitter_ms, packet_loss, uptime_pct, probe_count, health_score)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(date, ip) DO UPDATE SET
                avg_rtt_ms    = excluded.avg_rtt_ms,
                min_rtt_ms    = excluded.min_rtt_ms,
                max_rtt_ms    = excluded.max_rtt_ms,
                avg_jitter_ms = excluded.avg_jitter_ms,
                packet_loss   = excluded.packet_loss,
                uptime_pct    = excluded.uptime_pct,
                probe_count   = excluded.probe_count,
                health_score  = excluded.health_score
        """, (today, d["ip"], d["name"], d["avg_rtt"], d["min_rtt"],
              d["max_rtt"], d["avg_jitter"], d["avg_loss"],
              d["uptime_pct"], d["probe_count"], round(score, 1)))
        saved += 1

    conn.commit()
    conn.close()
    if saved:
        print(f"  [DEVICE HEALTH] Aggregated {saved} devices for {today}")
    return saved


def _score_rtt(rtt_ms):
    if rtt_ms is None: return 50.0
    if rtt_ms < 5:     return 100.0
    if rtt_ms < 10:    return 95.0
    if rtt_ms < 20:    return 90.0
    if rtt_ms < 50:    return 80.0
    if rtt_ms < 100:   return 65.0
    if rtt_ms < 150:   return 50.0
    if rtt_ms < 200:   return 35.0
    return max(0, 35 - (rtt_ms - 200) / 10)


def _score_loss(loss_pct):
    if loss_pct is None: return 50.0
    if loss_pct == 0:    return 100.0
    if loss_pct < 1:     return 90.0
    if loss_pct < 5:     return 70.0
    if loss_pct < 10:    return 50.0
    if loss_pct < 25:    return 25.0
    return max(0, 25 - loss_pct)


# ─────────────────────────────────────────
# Per-device baseline
# ─────────────────────────────────────────

def update_baselines(db_file: str = DB_FILE):
    """
    Calculate each device's normal RTT baseline from last 7 days.
    Used for per-device anomaly detection instead of global thresholds.
    """
    conn = get_connection(db_file)
    rows = conn.execute("""
        SELECT ip, name,
               AVG(avg_rtt_ms)  as baseline_rtt,
               AVG(packet_loss) as baseline_loss,
               AVG(avg_jitter_ms) as baseline_jitter,
               COUNT(*)         as sample_count
        FROM device_health_daily
        WHERE date >= date('now', '-7 days')
          AND avg_rtt_ms IS NOT NULL
        GROUP BY ip, name
        HAVING COUNT(*) >= 3
    """).fetchall()

    for r in rows:
        d = dict(r)

        # Calculate RTT standard deviation
        rtt_rows = conn.execute("""
            SELECT avg_rtt_ms FROM device_health_daily
            WHERE ip=? AND date >= date('now', '-7 days')
              AND avg_rtt_ms IS NOT NULL
        """, (d["ip"],)).fetchall()

        rtts = [r["avg_rtt_ms"] for r in rtt_rows]
        mean = sum(rtts) / len(rtts) if rtts else 0
        std  = math.sqrt(sum((x-mean)**2 for x in rtts)/len(rtts)) if len(rtts)>1 else 0

        conn.execute("""
            INSERT INTO device_baselines
                (ip, name, baseline_rtt_ms, baseline_loss,
                 baseline_jitter, std_rtt_ms, sample_count, last_updated)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(ip) DO UPDATE SET
                baseline_rtt_ms = excluded.baseline_rtt_ms,
                baseline_loss   = excluded.baseline_loss,
                baseline_jitter = excluded.baseline_jitter,
                std_rtt_ms      = excluded.std_rtt_ms,
                sample_count    = excluded.sample_count,
                last_updated    = excluded.last_updated
        """, (d["ip"], d["name"], d["baseline_rtt"], d["baseline_loss"],
              d["baseline_jitter"], std, d["sample_count"],
              datetime.now().isoformat()))

    conn.commit()
    conn.close()
    print(f"  [DEVICE HEALTH] Updated baselines for {len(rows)} devices")


# ─────────────────────────────────────────
# Degradation calculator
# ─────────────────────────────────────────

def _linear_regression(x, y):
    """Simple linear regression. Returns (slope, intercept)."""
    n = len(x)
    if n < 2: return 0.0, y[0] if y else 50.0
    mx = sum(x) / n
    my = sum(y) / n
    num   = sum((xi-mx)*(yi-my) for xi,yi in zip(x,y))
    denom = sum((xi-mx)**2 for xi in x)
    slope = num/denom if denom else 0.0
    return slope, my - slope*mx


def _replacement_priority(decline_rate, current_score, days_monitored):
    """
    Determine replacement priority based on decline rate and current score.
    Returns: urgent / soon / monitor / healthy
    """
    if current_score < CRITICAL_SCORE:
        return "urgent"
    if decline_rate < -2.0 and current_score < 60:
        return "urgent"
    if decline_rate < -1.0 and current_score < 70:
        return "soon"
    if decline_rate < -0.5:
        return "monitor"
    return "healthy"


def calculate_degradation(db_file: str = DB_FILE):
    """
    Calculate degradation rate for each device using linear regression
    on daily health scores over the monitoring period.

    Decline rate is in points per week (negative = declining).
    Predicts date when score will hit CRITICAL_SCORE.
    """
    conn = get_connection(db_file)

    # Get all devices with daily health data
    devices = conn.execute("""
        SELECT DISTINCT ip, name FROM device_health_daily
        ORDER BY ip
    """).fetchall()

    calculated = 0
    for dev in devices:
        ip   = dev["ip"]
        name = dev["name"]

        # Get all daily scores ordered by date
        rows = conn.execute("""
            SELECT date, health_score FROM device_health_daily
            WHERE ip=? AND health_score IS NOT NULL
            ORDER BY date ASC
        """, (ip,)).fetchall()

        if len(rows) < 3:
            continue  # need at least 3 days

        dates  = [r["date"] for r in rows]
        scores = [r["health_score"] for r in rows]

        # Convert dates to numeric (days since first date)
        first_date = datetime.strptime(dates[0], "%Y-%m-%d")
        x = [(datetime.strptime(d, "%Y-%m-%d") - first_date).days for d in dates]
        y = scores

        slope, intercept = _linear_regression(x, y)

        # Convert daily slope to weekly rate
        decline_rate_per_week = slope * 7

        baseline_score = scores[0]       # first recorded score
        current_score  = scores[-1]      # most recent score
        days_monitored = x[-1]           # total days monitored

        # Predict when score hits CRITICAL_SCORE
        predicted_date = None
        confidence     = 0.0
        if slope < 0 and current_score > CRITICAL_SCORE:
            days_to_critical = (CRITICAL_SCORE - current_score) / slope
            if 0 < days_to_critical < 365:
                pred_dt        = datetime.now() + timedelta(days=days_to_critical)
                predicted_date = pred_dt.strftime("%Y-%m-%d")
                # Confidence based on data points and consistency
                confidence = min(95, 40 + len(rows) * 2)

        priority = _replacement_priority(
            decline_rate_per_week, current_score, days_monitored)

        conn.execute("""
            INSERT INTO device_degradation
                (ip, name, first_seen_date, days_monitored,
                 baseline_score, current_score,
                 decline_rate_per_week, predicted_critical_date,
                 replacement_priority, confidence, last_calculated)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(ip) DO UPDATE SET
                name                    = excluded.name,
                days_monitored          = excluded.days_monitored,
                current_score           = excluded.current_score,
                decline_rate_per_week   = excluded.decline_rate_per_week,
                predicted_critical_date = excluded.predicted_critical_date,
                replacement_priority    = excluded.replacement_priority,
                confidence              = excluded.confidence,
                last_calculated         = excluded.last_calculated
        """, (ip, name, dates[0], days_monitored,
              round(baseline_score, 1), round(current_score, 1),
              round(decline_rate_per_week, 3), predicted_date,
              priority, round(confidence, 1),
              datetime.now().isoformat()))

        calculated += 1
        if predicted_date:
            print(f"  [DEGRADATION] {name:<20} "
                  f"score:{current_score:.0f} "
                  f"rate:{decline_rate_per_week:+.2f}pts/wk "
                  f"priority:{priority} "
                  f"predicted:{predicted_date}")

    conn.commit()
    conn.close()
    print(f"  [DEGRADATION] Calculated for {calculated} devices")
    return calculated


# ─────────────────────────────────────────
# Data retention pruning
# ─────────────────────────────────────────

def prune_old_data(db_file: str = DB_FILE):
    """
    Enforce data retention policy.
    Keeps the right amount of data for each table.
    """
    conn = get_connection(db_file)

    # probe_results — 7 days
    r1 = conn.execute("""DELETE FROM probe_results
        WHERE timestamp < datetime('now', ? )""",
        (f"-{RETAIN_PROBE_DAYS} days",)).rowcount

    # health_snapshots — 30 days
    r2 = conn.execute("""DELETE FROM health_snapshots
        WHERE timestamp < datetime('now', ?)""",
        (f"-{RETAIN_SNAPSHOT_DAYS} days",)).rowcount

    # device_health_daily — 6 months
    r3 = conn.execute("""DELETE FROM device_health_daily
        WHERE date < date('now', ?)""",
        (f"-{RETAIN_DAILY_DAYS} days",)).rowcount

    # bandwidth_samples — 7 days
    try:
        r4 = conn.execute("""DELETE FROM bandwidth_samples
            WHERE timestamp < datetime('now', ?)""",
            (f"-{RETAIN_BANDWIDTH_DAYS} days",)).rowcount
    except Exception:
        r4 = 0

    # anomaly_events — 90 days
    try:
        r5 = conn.execute("""DELETE FROM anomaly_events
            WHERE timestamp < datetime('now', ?)""",
            (f"-{RETAIN_ANOMALY_DAYS} days",)).rowcount
    except Exception:
        r5 = 0

    conn.commit()
    conn.close()

    total = r1 + r2 + r3 + r4 + r5
    if total > 0:
        print(f"  [PRUNING] Removed {r1} probe rows, {r2} snapshots, "
              f"{r3} daily rows, {r4} bandwidth rows, {r5} anomaly rows")


# ─────────────────────────────────────────
# Public API
# ─────────────────────────────────────────

def get_device_history(ip: str, days: int = 30,
                       db_file: str = DB_FILE) -> list:
    """Get daily health history for a device."""
    conn = get_connection(db_file)
    rows = conn.execute("""
        SELECT date, avg_rtt_ms, min_rtt_ms, max_rtt_ms,
               avg_jitter_ms, packet_loss, uptime_pct,
               probe_count, health_score
        FROM device_health_daily
        WHERE ip=? AND date >= date('now', ?)
        ORDER BY date ASC
    """, (ip, f"-{days} days")).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_degradation(db_file: str = DB_FILE) -> list:
    """Get degradation analysis for all devices, sorted by priority."""
    conn = get_connection(db_file)
    priority_order = "CASE replacement_priority " \
                     "WHEN 'urgent' THEN 1 " \
                     "WHEN 'soon' THEN 2 " \
                     "WHEN 'monitor' THEN 3 " \
                     "ELSE 4 END"
    rows = conn.execute(f"""
        SELECT * FROM device_degradation
        ORDER BY {priority_order}, decline_rate_per_week ASC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_device_baseline(ip: str,
                        db_file: str = DB_FILE) -> dict:
    """Get RTT baseline for a specific device."""
    conn = get_connection(db_file)
    row  = conn.execute(
        "SELECT * FROM device_baselines WHERE ip=?", (ip,)
    ).fetchone()
    conn.close()
    return dict(row) if row else {}


# ─────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────

def run():
    init_device_health_tables()
    print("  Device health tracker started.")
    print(f"  Aggregates daily data every hour.")
    print(f"  Retention: {RETAIN_PROBE_DAYS}d probe / "
          f"{RETAIN_SNAPSHOT_DAYS}d snapshots / "
          f"{RETAIN_DAILY_DAYS}d daily\n")

    while True:
        try:
            aggregate_daily()
            update_baselines()
            calculate_degradation()
            prune_old_data()
        except Exception as e:
            print(f"  [DEVICE HEALTH ERROR] {e}")
        time.sleep(AGGREGATION_INTERVAL)


if __name__ == "__main__":
    run()