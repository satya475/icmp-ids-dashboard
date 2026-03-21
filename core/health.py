"""
core/health.py
===============
Router session tracking and network health scoring.

Every time you switch routers, a new session is recorded.
Each session is scored 0-100 across 4 dimensions:
  - RTT score      (lower is better)
  - Loss score     (lower packet loss is better)
  - Stability      (fewer state changes = more stable)
  - Device health  (more devices UP = healthier)

Sessions are compared side by side so you can see
which router performs better.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
from datetime import datetime, timedelta
from db.database import get_connection
from db.queries import load_active_targets
from utils.network import detect_network
from config import DB_FILE

# ─────────────────────────────────────────
# Database schema
# ─────────────────────────────────────────

def init_health_tables(db_file: str = DB_FILE):
    conn = get_connection(db_file)

    # Track each router session
    conn.execute("""CREATE TABLE IF NOT EXISTS router_sessions (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        gateway_ip  TEXT NOT NULL,
        subnet      TEXT NOT NULL,
        started_at  TEXT NOT NULL,
        ended_at    TEXT,
        label       TEXT
    )""")

    # Health snapshots — scored every 60s during a session
    conn.execute("""CREATE TABLE IF NOT EXISTS health_snapshots (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id  INTEGER NOT NULL,
        timestamp   TEXT NOT NULL,
        rtt_avg_ms  REAL,
        packet_loss REAL,
        devices_up  INTEGER,
        devices_total INTEGER,
        state_changes INTEGER DEFAULT 0,
        rtt_score   REAL,
        loss_score  REAL,
        stability_score REAL,
        device_score REAL,
        health_score REAL,
        FOREIGN KEY(session_id) REFERENCES router_sessions(id)
    )""")

    conn.execute("""CREATE INDEX IF NOT EXISTS idx_health_session
        ON health_snapshots(session_id, timestamp)""")
    conn.commit()
    conn.close()


# ─────────────────────────────────────────
# Session management
# ─────────────────────────────────────────

def get_current_session(db_file: str = DB_FILE) -> dict:
    """Get the currently active router session."""
    conn = get_connection(db_file)
    row  = conn.execute("""
        SELECT * FROM router_sessions
        WHERE ended_at IS NULL
        ORDER BY started_at DESC LIMIT 1
    """).fetchone()
    conn.close()
    return dict(row) if row else None


def start_session(gateway_ip: str, subnet: str,
                  db_file: str = DB_FILE) -> int:
    """
    Start or resume a router session.
    If there is already an open session for this gateway,
    reuse it instead of creating a new one.
    Returns session ID.
    """
    conn = get_connection(db_file)

    # Check if there is already an open session for this gateway
    existing = conn.execute("""
        SELECT id FROM router_sessions
        WHERE gateway_ip=? AND ended_at IS NULL
        ORDER BY started_at DESC LIMIT 1
    """, (gateway_ip,)).fetchone()

    if existing:
        session_id = existing["id"]
        conn.close()
        print(f"  [HEALTH] Resuming session #{session_id} — {gateway_ip}")
        return session_id

    # End any open sessions for OTHER gateways
    conn.execute("""UPDATE router_sessions SET ended_at=?
        WHERE ended_at IS NULL AND gateway_ip!=?""",
        (datetime.now().isoformat(), gateway_ip))

    # Create new session
    cur = conn.execute("""INSERT INTO router_sessions
        (gateway_ip, subnet, started_at, label)
        VALUES (?,?,?,?)""",
        (gateway_ip, subnet, datetime.now().isoformat(),
         f"Router {gateway_ip}"))
    session_id = cur.lastrowid
    conn.commit()
    conn.close()
    print(f"  [HEALTH] New session #{session_id} — {gateway_ip} ({subnet})")
    return session_id


def get_all_sessions(db_file: str = DB_FILE) -> list:
    """Get all router sessions with their average health scores."""
    conn = get_connection(db_file)
    rows = conn.execute("""
        SELECT s.*,
               COUNT(h.id)          as snapshot_count,
               AVG(h.health_score)  as avg_health,
               AVG(h.rtt_avg_ms)    as avg_rtt,
               AVG(h.packet_loss)   as avg_loss,
               AVG(h.rtt_score)     as avg_rtt_score,
               AVG(h.loss_score)    as avg_loss_score,
               AVG(h.stability_score) as avg_stability,
               AVG(h.device_score)  as avg_device_score
        FROM router_sessions s
        LEFT JOIN health_snapshots h ON h.session_id = s.id
        GROUP BY s.id
        ORDER BY s.started_at DESC
        LIMIT 20
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_session_history(session_id: int,
                        db_file: str = DB_FILE) -> list:
    """Get health snapshot history for a session."""
    conn = get_connection(db_file)
    rows = conn.execute("""
        SELECT * FROM health_snapshots
        WHERE session_id=?
        ORDER BY timestamp ASC
        LIMIT 500
    """, (session_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_session_label(session_id: int, label: str,
                         db_file: str = DB_FILE):
    conn = get_connection(db_file)
    conn.execute("UPDATE router_sessions SET label=? WHERE id=?",
                 (label, session_id))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────
# Health scoring
# ─────────────────────────────────────────

def _score_rtt(rtt_ms: float) -> float:
    """
    Score RTT 0-100. Lower RTT = higher score.
    <5ms=100, 10ms=95, 50ms=80, 100ms=60, 200ms=30, 500ms=0
    """
    if rtt_ms is None: return 50.0
    if rtt_ms <   5:   return 100.0
    if rtt_ms <  10:   return 95.0
    if rtt_ms <  20:   return 90.0
    if rtt_ms <  50:   return 80.0
    if rtt_ms < 100:   return 65.0
    if rtt_ms < 150:   return 50.0
    if rtt_ms < 200:   return 35.0
    if rtt_ms < 300:   return 20.0
    if rtt_ms < 500:   return 10.0
    return 0.0


def _score_loss(loss_pct: float) -> float:
    """
    Score packet loss 0-100. 0% loss = 100.
    0%=100, 1%=90, 5%=70, 10%=50, 25%=20, 50%+=0
    """
    if loss_pct is None: return 50.0
    if loss_pct == 0:    return 100.0
    if loss_pct <  1:    return 92.0
    if loss_pct <  2:    return 85.0
    if loss_pct <  5:    return 70.0
    if loss_pct < 10:    return 50.0
    if loss_pct < 25:    return 25.0
    if loss_pct < 50:    return 10.0
    return 0.0


def _score_stability(state_changes: int) -> float:
    """
    Score stability 0-100. Fewer state changes = more stable.
    0 changes=100, 1=85, 2=70, 3=50, 5+=20
    """
    if state_changes == 0: return 100.0
    if state_changes == 1: return 85.0
    if state_changes == 2: return 70.0
    if state_changes == 3: return 55.0
    if state_changes == 4: return 40.0
    if state_changes == 5: return 25.0
    return max(0.0, 25.0 - (state_changes - 5) * 3)


def _score_devices(devices_up: int, devices_total: int) -> float:
    """Score device availability 0-100."""
    if devices_total == 0: return 50.0
    pct = (devices_up / devices_total) * 100
    if pct >= 90: return 100.0
    if pct >= 75: return 80.0
    if pct >= 50: return 60.0
    if pct >= 25: return 35.0
    return 15.0


def _grade(score: float) -> str:
    if score >= 90: return "A"
    if score >= 80: return "B"
    if score >= 65: return "C"
    if score >= 50: return "D"
    return "F"


def compute_health_score(rtt_avg: float, loss_pct: float,
                         state_changes: int,
                         devices_up: int,
                         devices_total: int) -> dict:
    """
    Compute weighted health score from all dimensions.
    Weights: RTT 30%, Loss 30%, Stability 20%, Devices 20%
    """
    rtt_s   = _score_rtt(rtt_avg)
    loss_s  = _score_loss(loss_pct * 100 if loss_pct else 0)
    stab_s  = _score_stability(state_changes)
    dev_s   = _score_devices(devices_up, devices_total)

    score = (rtt_s * 0.30 + loss_s * 0.30 +
             stab_s * 0.20 + dev_s * 0.20)

    return {
        "rtt_score":       round(rtt_s,   1),
        "loss_score":      round(loss_s,  1),
        "stability_score": round(stab_s,  1),
        "device_score":    round(dev_s,   1),
        "health_score":    round(score,   1),
        "grade":           _grade(score),
    }


# ─────────────────────────────────────────
# Snapshot collection
# ─────────────────────────────────────────

def take_snapshot(session_id: int, db_file: str = DB_FILE):
    """Collect current network metrics and save a health snapshot."""
    from utils.network import get_current_gateway
    conn = get_connection(db_file)
    ts   = datetime.now().isoformat()

    # Get current subnet to filter probe results
    gateway     = get_current_gateway()
    subnet_base = ".".join(gateway.split(".")[:3]) + "." if gateway else None

    # Get latest probe results — filter to current subnet only
    rows = conn.execute("""
        SELECT p.host, p.is_alive, p.rtt_avg_ms, p.packet_loss
        FROM active_targets t
        LEFT JOIN probe_results p ON p.host = t.ip
            AND p.timestamp = (
                SELECT MAX(timestamp) FROM probe_results WHERE host = t.ip
            )
        WHERE t.active = 1
    """).fetchall()

    # Filter to current subnet
    if subnet_base:
        rows = [r for r in rows if
                dict(r)["host"].startswith(subnet_base) or
                dict(r)["host"] in ("8.8.8.8", "1.1.1.1")]

    devices_total = len(rows)
    devices_up    = sum(1 for r in rows if r["is_alive"] == 1)
    rtts          = [r["rtt_avg_ms"] for r in rows
                     if r["rtt_avg_ms"] is not None]
    losses        = [r["packet_loss"] for r in rows
                     if r["packet_loss"] is not None]
    rtt_avg       = sum(rtts)/len(rtts) if rtts else None
    loss_avg      = sum(losses)/len(losses) if losses else 0

    # If no probe data yet — still save snapshot with defaults
    # so health page shows something immediately
    if devices_total == 0:
        rtt_avg       = None
        loss_avg      = 0
        devices_up    = 0
        devices_total = 1  # avoid division by zero

    # Count state changes in last 60 seconds
    since = (datetime.now() - timedelta(seconds=70)).isoformat()
    sc_row = conn.execute("""
        SELECT COUNT(*) as cnt FROM state_changes
        WHERE timestamp > ?
    """, (since,)).fetchone()
    state_changes = sc_row["cnt"] if sc_row else 0

    # Compute scores using adaptive model if trained
    scores = compute_adaptive_health_score(
        rtt_avg, loss_avg, state_changes,
        devices_up, devices_total, db_file)

    conn.execute("""INSERT INTO health_snapshots
        (session_id, timestamp, rtt_avg_ms, packet_loss,
         devices_up, devices_total, state_changes,
         rtt_score, loss_score, stability_score, device_score, health_score)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (session_id, ts, rtt_avg, loss_avg,
         devices_up, devices_total, state_changes,
         scores["rtt_score"], scores["loss_score"],
         scores["stability_score"], scores["device_score"],
         scores["health_score"]))
    conn.commit()
    conn.close()

    return scores


# ─────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────

def run():
    init_health_tables()
    print("  Health monitor started.")
    print("  Scores every 60s | Detects router switches automatically.\n")

    current_gateway = None
    session_id      = None

    while True:
        try:
            subnet, gateway = detect_network()

            # Detect router switch
            if gateway != current_gateway:
                print(f"  [HEALTH] Router changed: "
                      f"{current_gateway or 'none'} -> {gateway}")
                session_id      = start_session(gateway, subnet)
                current_gateway = gateway

            # Ensure we have a session
            if session_id is None:
                existing = get_current_session()
                if existing and existing["gateway_ip"] == gateway:
                    session_id = existing["id"]
                else:
                    session_id = start_session(gateway, subnet)

            # Take health snapshot
            scores = take_snapshot(session_id)
            print(f"  [HEALTH] Score: {scores['health_score']:.0f}/100 "
                  f"({scores['grade']}) | "
                  f"RTT:{scores['rtt_score']:.0f} "
                  f"Loss:{scores['loss_score']:.0f} "
                  f"Stability:{scores['stability_score']:.0f} "
                  f"Devices:{scores['device_score']:.0f}")

        except Exception as e:
            print(f"  [HEALTH ERROR] {e}")

        time.sleep(60)


if __name__ == "__main__":
    run()


# ─────────────────────────────────────────
# Phase 2: Trend-weighted health scoring
# ─────────────────────────────────────────

def compute_trend_weighted_score(session_id: int,
                                  db_file: str = DB_FILE) -> dict:
    """
    Smarter health score that weights recent snapshots more heavily.

    A score falling from 90→70 over 10 minutes is worse than
    a stable score of 70. This function detects that.

    Returns:
      - weighted_score: trend-aware overall score
      - trend:         'improving' | 'stable' | 'declining'
      - trend_rate:    points per minute (positive=improving)
      - prediction_10m: predicted score in 10 minutes
    """
    conn = get_connection(db_file)
    rows = conn.execute("""
        SELECT health_score, timestamp FROM health_snapshots
        WHERE session_id=?
        ORDER BY timestamp DESC LIMIT 20
    """, (session_id,)).fetchall()
    conn.close()

    if not rows:
        return {"weighted_score": None, "trend": "unknown",
                "trend_rate": 0, "prediction_10m": None}

    scores = [r["health_score"] for r in rows if r["health_score"]]
    if len(scores) < 2:
        return {"weighted_score": scores[0] if scores else None,
                "trend": "unknown", "trend_rate": 0,
                "prediction_10m": None}

    # Exponential weighting — recent snapshots count more
    # Weight = 2^i where i=0 is most recent
    weights = [2 ** i for i in range(len(scores))]
    total_w = sum(weights)
    weighted = sum(s * w for s, w in zip(scores, weights)) / total_w

    # Trend — compare last 5 vs previous 5
    recent   = scores[:5]
    previous = scores[5:10] if len(scores) >= 10 else scores[5:]
    if previous:
        avg_recent   = sum(recent)   / len(recent)
        avg_previous = sum(previous) / len(previous)
        diff = avg_recent - avg_previous

        if diff > 3:      trend = "improving"
        elif diff < -3:   trend = "declining"
        else:             trend = "stable"

        # Rate of change in points per minute (each snapshot = ~1 min)
        trend_rate = diff / max(len(previous), 1)
    else:
        trend      = "stable"
        trend_rate = 0.0

    # Predict score in 10 minutes
    prediction = min(100, max(0, weighted + trend_rate * 10))

    return {
        "weighted_score": round(weighted, 1),
        "trend":          trend,
        "trend_rate":     round(trend_rate, 2),
        "prediction_10m": round(prediction, 1),
    }


# ─────────────────────────────────────────
# Phase 2: Router advisor
# ─────────────────────────────────────────

def get_router_recommendation(db_file: str = DB_FILE) -> dict:
    """
    Analyzes all recorded router sessions and recommends
    the best performing router with detailed reasoning.

    Returns:
      - recommendation: gateway IP of best router
      - confidence:     how certain we are (0-100)
      - reasoning:      list of human-readable reasons
      - sessions:       all sessions with scores
      - comparison:     dimension-by-dimension comparison
    """
    sessions = get_all_sessions(db_file)

    # Filter sessions with enough data (at least 5 snapshots)
    valid = [s for s in sessions if (s.get("snapshot_count") or 0) >= 5]

    if len(valid) < 2:
        return {
            "recommendation": None,
            "confidence":     0,
            "reasoning":      [
                "Need at least 2 router sessions with 5+ minutes of data each.",
                f"Currently have {len(valid)} valid session(s).",
                "Switch routers and monitor for 5+ minutes each to compare."
            ],
            "sessions": sessions,
            "comparison": None,
        }

    # Score each session across all dimensions
    def session_score(s):
        return {
            "id":          s["id"],
            "label":       s.get("label") or s["gateway_ip"],
            "gateway":     s["gateway_ip"],
            "subnet":      s["subnet"],
            "overall":     round(s.get("avg_health") or 0, 1),
            "rtt":         round(s.get("avg_rtt_score") or 0, 1),
            "loss":        round(s.get("avg_loss_score") or 0, 1),
            "stability":   round(s.get("avg_stability") or 0, 1),
            "devices":     round(s.get("avg_device_score") or 0, 1),
            "avg_rtt_ms":  round(s.get("avg_rtt") or 0, 1),
            "snapshots":   s.get("snapshot_count") or 0,
            "duration":    s.get("started_at"),
        }

    scored    = [session_score(s) for s in valid]
    best      = max(scored, key=lambda x: x["overall"])
    runner_up = min(scored, key=lambda x: x["overall"]) \
                if len(scored) > 1 else None

    # Build reasoning
    reasoning = []
    diff      = 0
    confidence= 50

    if runner_up:
        diff = best["overall"] - runner_up["overall"]

        if diff > 20:
            confidence = 95
            reasoning.append(
                f"{best['label']} is significantly better "
                f"(+{diff:.0f} points overall score).")
        elif diff > 10:
            confidence = 80
            reasoning.append(
                f"{best['label']} performs better "
                f"(+{diff:.0f} points overall score).")
        elif diff > 3:
            confidence = 65
            reasoning.append(
                f"{best['label']} has a slight edge "
                f"(+{diff:.0f} points overall score).")
        else:
            confidence = 40
            reasoning.append(
                "Both routers perform very similarly. "
                "Difference is within margin of error.")

        # Dimension-specific reasons
        rtt_diff  = best["rtt"]      - runner_up["rtt"]
        loss_diff = best["loss"]     - runner_up["loss"]
        stab_diff = best["stability"]- runner_up["stability"]

        if rtt_diff > 10:
            reasoning.append(
                f"Lower latency: {best['avg_rtt_ms']:.0f}ms vs "
                f"{runner_up['avg_rtt_ms']:.0f}ms average RTT.")
        if loss_diff > 10:
            reasoning.append("Better packet delivery — fewer dropped packets.")
        if stab_diff > 10:
            reasoning.append("More stable — fewer device state changes.")
        if best["snapshots"] < 10:
            reasoning.append(
                "Note: Limited data — use each router for longer "
                "to increase recommendation confidence.")

    return {
        "recommendation": best["gateway"],
        "best_label":     best["label"],
        "confidence":     confidence,
        "score_diff":     round(diff, 1),
        "reasoning":      reasoning,
        "sessions":       scored,
        "best":           best,
        "runner_up":      runner_up,
    }


# ─────────────────────────────────────────
# Self-training model
# Continuously learns from ALL historical data
# and improves its own scoring thresholds
# ─────────────────────────────────────────

def train_model(db_file: str = DB_FILE) -> dict:
    """
    Reads ALL historical health snapshots across ALL sessions
    and derives optimal scoring thresholds from the data.

    This runs every 10 minutes and updates the model automatically.
    The more data collected, the more accurate the thresholds become.

    Returns learned thresholds dict.
    """
    conn = get_connection(db_file)
    try:
        # Get all historical snapshots
        rows = conn.execute("""
            SELECT rtt_avg_ms, packet_loss, state_changes,
                   devices_up, devices_total, health_score
            FROM health_snapshots
            WHERE health_score IS NOT NULL
            ORDER BY timestamp DESC
            LIMIT 2000
        """).fetchall()

        if len(rows) < 10:
            conn.close()
            return {}

        rtts    = [r["rtt_avg_ms"]   for r in rows if r["rtt_avg_ms"]]
        losses  = [r["packet_loss"]  for r in rows if r["packet_loss"] is not None]
        changes = [r["state_changes"]for r in rows if r["state_changes"] is not None]

        def percentile(data, pct):
            if not data: return None
            s = sorted(data)
            i = int(len(s) * pct / 100)
            return s[min(i, len(s)-1)]

        # Learn RTT thresholds from actual network behavior
        # What IS normal for THIS network specifically
        rtt_p25  = percentile(rtts, 25)   # excellent threshold
        rtt_p50  = percentile(rtts, 50)   # good threshold
        rtt_p75  = percentile(rtts, 75)   # fair threshold
        rtt_p90  = percentile(rtts, 90)   # poor threshold

        # Learn normal packet loss for this network
        loss_p75 = percentile(losses, 75)
        loss_p90 = percentile(losses, 90)

        # Learn normal state change rate
        avg_changes = sum(changes)/len(changes) if changes else 0

        # Learn average health score baseline
        scores   = [r["health_score"] for r in rows if r["health_score"]]
        avg_score= sum(scores)/len(scores) if scores else 50
        std_score= (sum((s-avg_score)**2 for s in scores)/len(scores))**0.5 if scores else 10

        thresholds = {
            "rtt_excellent":  round(rtt_p25  or 10,  1),
            "rtt_good":       round(rtt_p50  or 50,  1),
            "rtt_fair":       round(rtt_p75  or 100, 1),
            "rtt_poor":       round(rtt_p90  or 200, 1),
            "loss_normal":    round(loss_p75 or 0.1, 3),
            "loss_high":      round(loss_p90 or 0.3, 3),
            "avg_changes":    round(avg_changes, 2),
            "baseline_score": round(avg_score,   1),
            "score_std":      round(std_score,   1),
            "sample_count":   len(rows),
            "trained_at":     datetime.now().isoformat(),
        }

        # Save learned thresholds to DB
        conn.execute("""CREATE TABLE IF NOT EXISTS model_state (
            key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)""")
        import json
        conn.execute("""INSERT INTO model_state (key, value, updated_at)
            VALUES ('thresholds', ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value=excluded.value, updated_at=excluded.updated_at""",
            (json.dumps(thresholds), datetime.now().isoformat()))
        conn.commit()
        conn.close()
        return thresholds

    except Exception as e:
        conn.close()
        print(f"  [MODEL] Training error: {e}")
        return {}


def get_model_thresholds(db_file: str = DB_FILE) -> dict:
    """Get the latest learned thresholds from the model."""
    try:
        import json
        conn = get_connection(db_file)
        conn.execute("""CREATE TABLE IF NOT EXISTS model_state (
            key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)""")
        row = conn.execute(
            "SELECT value FROM model_state WHERE key='thresholds'"
        ).fetchone()
        conn.close()
        return json.loads(row["value"]) if row else {}
    except Exception:
        return {}


def compute_adaptive_health_score(rtt_avg: float, loss_pct: float,
                                   state_changes: int,
                                   devices_up: int,
                                   devices_total: int,
                                   db_file: str = DB_FILE) -> dict:
    """
    Compute health score using LEARNED thresholds from training data.
    Falls back to default thresholds if not enough training data yet.
    """
    thresholds = get_model_thresholds(db_file)

    if thresholds and thresholds.get("sample_count", 0) >= 50:
        # Use learned thresholds — adapted to THIS network
        def score_rtt_adaptive(rtt):
            if rtt is None: return 50.0
            t = thresholds
            if rtt <= t["rtt_excellent"]: return 100.0
            if rtt <= t["rtt_good"]:      return 85.0
            if rtt <= t["rtt_fair"]:      return 65.0
            if rtt <= t["rtt_poor"]:      return 40.0
            return max(0, 40 - (rtt - t["rtt_poor"]) / t["rtt_poor"] * 40)

        def score_loss_adaptive(loss):
            if loss is None: return 50.0
            t = thresholds
            if loss <= 0:                  return 100.0
            if loss <= t["loss_normal"]:   return 85.0
            if loss <= t["loss_high"]:     return 55.0
            return max(0, 55 - (loss - t["loss_high"]) * 100)

        rtt_s  = score_rtt_adaptive(rtt_avg)
        loss_s = score_loss_adaptive(loss_pct)
    else:
        # Fall back to default scoring
        scores = compute_health_score(rtt_avg, loss_pct,
                                       state_changes, devices_up,
                                       devices_total)
        return {**scores, "adaptive": False,
                "training_samples": thresholds.get("sample_count", 0)}

    stab_s = _score_stability(state_changes)
    dev_s  = _score_devices(devices_up, devices_total)
    score  = rtt_s*0.30 + loss_s*0.30 + stab_s*0.20 + dev_s*0.20

    return {
        "rtt_score":       round(rtt_s,  1),
        "loss_score":      round(loss_s, 1),
        "stability_score": round(stab_s, 1),
        "device_score":    round(dev_s,  1),
        "health_score":    round(score,  1),
        "grade":           _grade(score),
        "adaptive":        True,
        "training_samples":thresholds.get("sample_count", 0),
        "baseline_score":  thresholds.get("baseline_score"),
    }


def training_loop(db_file: str = DB_FILE):
    """
    Background training loop — runs every 10 minutes.
    Continuously improves model thresholds from accumulated data.
    """
    import time
    while True:
        try:
            thresholds = train_model(db_file)
            if thresholds:
                print(f"  [MODEL] Trained on {thresholds['sample_count']} samples | "
                      f"Baseline score: {thresholds['baseline_score']} | "
                      f"RTT thresholds: "
                      f"{thresholds['rtt_excellent']}/{thresholds['rtt_good']}/"
                      f"{thresholds['rtt_fair']}ms")
        except Exception as e:
            print(f"  [MODEL ERROR] {e}")
        time.sleep(600)  # retrain every 10 minutes
