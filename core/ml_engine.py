"""
core/ml_engine.py
==================
Real ML models replacing statistical methods.

1. Isolation Forest    — anomaly detection (replaces Z-score)
2. Random Forest       — device classification (replaces if/else rules)
3. Adaptive Scaler     — health scoring (replaces weighted average)
4. Trend Predictor     — degradation prediction (enhanced linear regression)

Models are saved to disk and retrained automatically every 24 hours.
Falls back to statistical methods if not enough training data yet.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pickle
import threading
import time
import numpy as np
from datetime import datetime, timedelta
from db.database import get_connection
from config import DB_FILE

# ─────────────────────────────────────────
# Model storage path
# ─────────────────────────────────────────
MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "models")

os.makedirs(MODEL_DIR, exist_ok=True)

ISOLATION_FOREST_PATH = os.path.join(MODEL_DIR, "isolation_forest.pkl")
RANDOM_FOREST_PATH    = os.path.join(MODEL_DIR, "random_forest.pkl")
SCALER_PATH           = os.path.join(MODEL_DIR, "scaler.pkl")
MODEL_META_PATH       = os.path.join(MODEL_DIR, "model_meta.pkl")

# Minimum samples needed to train
MIN_SAMPLES_ANOMALY    = 50
MIN_SAMPLES_CLASSIFIER = 5   # works for home/test networks
RETRAIN_INTERVAL       = 86400   # 24 hours


# ─────────────────────────────────────────
# Model persistence
# ─────────────────────────────────────────

def save_model(model, path: str):
    with open(path, "wb") as f:
        pickle.dump(model, f)

def load_model(path: str):
    if os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f)
    return None

def get_model_meta() -> dict:
    meta = load_model(MODEL_META_PATH)
    return meta if meta else {}

def save_model_meta(meta: dict):
    save_model(meta, MODEL_META_PATH)


# ─────────────────────────────────────────
# 1. Isolation Forest — Anomaly Detection
# ─────────────────────────────────────────

def train_isolation_forest(db_file: str = DB_FILE) -> bool:
    """
    Train Isolation Forest on historical probe data.
    Features: [rtt_avg_ms, rtt_min_ms, rtt_max_ms, packet_loss, jitter_ms]
    """
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler

    conn = get_connection(db_file)
    rows = conn.execute("""
        SELECT rtt_avg_ms, rtt_min_ms, rtt_max_ms,
               packet_loss, jitter_ms
        FROM probe_results
        WHERE is_alive=1
          AND rtt_avg_ms IS NOT NULL
          AND timestamp > datetime('now', '-7 days')
        ORDER BY timestamp DESC
        LIMIT 5000
    """).fetchall()
    conn.close()

    if len(rows) < MIN_SAMPLES_ANOMALY:
        print(f"  [ML] Not enough data for Isolation Forest "
              f"({len(rows)}/{MIN_SAMPLES_ANOMALY} samples)")
        return False

    # Build feature matrix — replace None with 0
    X = []
    for r in rows:
        X.append([
            r["rtt_avg_ms"]  or 0,
            r["rtt_min_ms"]  or 0,
            r["rtt_max_ms"]  or 0,
            (r["packet_loss"] or 0) * 100,
            r["jitter_ms"]   or 0,
        ])
    X = np.array(X)

    # Scale features
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Train Isolation Forest
    # contamination=0.05 means we expect 5% of data to be anomalies
    model = IsolationForest(
        n_estimators=100,
        contamination=0.05,
        random_state=42,
        n_jobs=-1
    )
    model.fit(X_scaled)

    save_model(model,  ISOLATION_FOREST_PATH)
    save_model(scaler, SCALER_PATH)

    meta = get_model_meta()
    meta["isolation_forest_trained"] = datetime.now().isoformat()
    meta["isolation_forest_samples"] = len(rows)
    save_model_meta(meta)

    print(f"  [ML] Isolation Forest trained on {len(rows)} samples")
    return True


def predict_anomaly_if(host: str, rtt_avg: float, rtt_min: float,
                        rtt_max: float, packet_loss: float,
                        jitter: float, db_file: str = DB_FILE) -> dict:
    """
    Use Isolation Forest to detect anomalies.
    Returns {is_anomaly, score, method}
    Score: -1 = anomaly, 1 = normal (sklearn convention)
    Anomaly score: closer to -1 = more anomalous
    """
    model  = load_model(ISOLATION_FOREST_PATH)
    scaler = load_model(SCALER_PATH)

    if model is None or scaler is None:
        # Fall back to Z-score
        return _zscore_fallback(host, rtt_avg, db_file)

    features = np.array([[
        rtt_avg      or 0,
        rtt_min      or 0,
        rtt_max      or 0,
        (packet_loss or 0) * 100,
        jitter       or 0,
    ]])

    X_scaled     = scaler.transform(features)
    prediction   = model.predict(X_scaled)[0]       # -1=anomaly, 1=normal
    anomaly_score= model.decision_function(X_scaled)[0]  # negative = anomalous

    is_anomaly = prediction == -1
    severity   = "high" if anomaly_score < -0.3 else "medium"

    return {
        "is_anomaly":   is_anomaly,
        "score":        round(float(anomaly_score), 4),
        "severity":     severity if is_anomaly else "none",
        "method":       "isolation_forest",
        "features_used": 5,
    }


def _zscore_fallback(host: str, rtt_avg: float,
                      db_file: str = DB_FILE) -> dict:
    """Z-score fallback when IF model not trained yet."""
    conn = get_connection(db_file)
    rows = conn.execute("""
        SELECT rtt_avg_ms FROM probe_results
        WHERE host=? AND is_alive=1
          AND timestamp > datetime('now', '-6 hours')
        ORDER BY timestamp DESC LIMIT 50
    """, (host,)).fetchall()
    conn.close()

    values = [r["rtt_avg_ms"] for r in rows if r["rtt_avg_ms"]]
    if len(values) < 10 or not rtt_avg:
        return {"is_anomaly": False, "score": 0,
                "severity": "none", "method": "zscore_fallback"}

    mean = sum(values) / len(values)
    std  = (sum((v-mean)**2 for v in values) / len(values)) ** 0.5
    z    = (rtt_avg - mean) / std if std > 0 else 0

    return {
        "is_anomaly": z > 2.5,
        "score":      round(z, 3),
        "severity":   "high" if z > 4 else "medium" if z > 2.5 else "none",
        "method":     "zscore_fallback",
    }


# ─────────────────────────────────────────
# 2. Random Forest — Device Classification
# ─────────────────────────────────────────

# Device type labels
DEVICE_TYPES = ["router", "server", "laptop", "phone",
                "iot", "tv", "printer", "unknown"]
TYPE_TO_INT  = {t: i for i, t in enumerate(DEVICE_TYPES)}
INT_TO_TYPE  = {i: t for i, t in enumerate(DEVICE_TYPES)}


def _build_classifier_features(ip: str, conn) -> list:
    """
    Build feature vector for device classification.
    Features: [avg_rtt, rtt_consistency, availability, sleeps_at_night,
               always_on, traffic_level, day_avail, night_avail]
    """
    # RTT features
    rtt_rows = conn.execute("""
        SELECT AVG(rtt_avg_ms) as avg_rtt,
               MIN(rtt_avg_ms) as min_rtt,
               MAX(rtt_avg_ms) as max_rtt,
               COUNT(*) as cnt
        FROM probe_results
        WHERE host=? AND is_alive=1
          AND timestamp > datetime('now', '-48 hours')
    """, (ip,)).fetchone()

    avg_rtt  = rtt_rows["avg_rtt"] or 100
    rtt_range= (rtt_rows["max_rtt"] or 0) - (rtt_rows["min_rtt"] or 0)

    # Availability features
    avail_rows = conn.execute("""
        SELECT is_alive,
               CAST(strftime('%H', timestamp) AS INTEGER) as hour
        FROM probe_results
        WHERE host=?
          AND timestamp > datetime('now', '-48 hours')
        LIMIT 500
    """, (ip,)).fetchall()

    total      = len(avail_rows) or 1
    alive      = sum(1 for r in avail_rows if r["is_alive"] == 1)
    availability = alive / total * 100

    night = [r for r in avail_rows if r["hour"] >= 22 or r["hour"] < 7]
    day   = [r for r in avail_rows if 7 <= r["hour"] < 22]

    night_avail = (sum(1 for r in night if r["is_alive"]==1) /
                   len(night) * 100) if night else 50
    day_avail   = (sum(1 for r in day   if r["is_alive"]==1) /
                   len(day)   * 100) if day   else 50

    sleeps_night = 1 if (night_avail < day_avail - 20) else 0
    always_on    = 1 if availability > 95 else 0

    # Traffic features
    try:
        traffic = conn.execute("""
            SELECT SUM(bytes_in + bytes_out) as total
            FROM bandwidth_samples
            WHERE ip=? AND timestamp > datetime('now', '-24 hours')
        """, (ip,)).fetchone()
        total_traffic = traffic["total"] or 0
    except Exception:
        total_traffic = 0

    # Normalize traffic to 0-10 scale
    if total_traffic > 1e9:   traffic_level = 10
    elif total_traffic > 1e8: traffic_level = 8
    elif total_traffic > 1e7: traffic_level = 6
    elif total_traffic > 1e6: traffic_level = 4
    elif total_traffic > 1e5: traffic_level = 2
    else:                     traffic_level = 0

    return [
        min(avg_rtt, 500),
        min(rtt_range, 500),
        availability,
        sleeps_night,
        always_on,
        traffic_level,
        day_avail,
        night_avail,
    ]


def _get_training_labels(db_file: str = DB_FILE) -> list:
    """
    Get training data from device_classifications table.
    If not enough labels exist, run rule-based classifier first
    to generate initial labels for Random Forest training.
    """
    conn = get_connection(db_file)
    try:
        rows = conn.execute("""
            SELECT ip, device_type, confidence
            FROM device_classifications
            WHERE confidence >= 60
              AND device_type != 'unknown'
        """).fetchall()
    except Exception:
        rows = []

    # Always run classifier first to ensure fresh labels
    try:
        from core.classifier import classify_all
        classify_all(db_file)
    except Exception as e:
        print(f"  [ML] Classifier error: {e}")

    # Re-read ALL labels including unknown
    try:
        rows = conn.execute("""
            SELECT ip, device_type, confidence
            FROM device_classifications
        """).fetchall()
        print(f"  [ML] Found {len(rows)} total device labels")
        # Show breakdown
        from collections import Counter
        types = Counter(r["device_type"] for r in rows)
        for t, cnt in types.items():
            print(f"    {t}: {cnt}")
    except Exception as e:
        rows = []
        print(f"  [ML] Label read error: {e}")
    
    # If still no classifications, use active targets with rule-based features
    if not rows:
        print("  [ML] No classifications found - using active targets directly")
        try:
            targets = conn.execute(
                "SELECT ip, name FROM active_targets WHERE active=1"
            ).fetchall()
            print(f"  [ML] Found {len(targets)} active targets")
            rows = [{"ip": t["ip"], "device_type": "unknown", 
                     "confidence": 40} for t in targets]
        except Exception as e:
            print(f"  [ML] Active targets error: {e}")

    training = []
    for r in rows:
        ip          = r["ip"]
        device_type = r["device_type"]
        if device_type not in TYPE_TO_INT:
            continue
        try:
            features = _build_classifier_features(ip, conn)
            training.append((features, TYPE_TO_INT[device_type]))
        except Exception as e:
            print(f"  [ML] Feature error for {ip}: {e}")

    print(f"  [ML] Built {len(training)} training samples")
    conn.close()
    return training


def train_random_forest(db_file: str = DB_FILE) -> bool:
    """
    Train Random Forest classifier on labeled device data.
    Uses existing rule-based classifications as training labels.
    """
    from sklearn.ensemble import RandomForestClassifier

    training = _get_training_labels(db_file)

    if len(training) < MIN_SAMPLES_CLASSIFIER:
        print(f"  [ML] Not enough labeled devices for Random Forest "
              f"({len(training)}/{MIN_SAMPLES_CLASSIFIER})")
        return False

    X = np.array([t[0] for t in training])
    y = np.array([t[1] for t in training])

    model = RandomForestClassifier(
        n_estimators=100,
        max_depth=10,
        random_state=42,
        n_jobs=-1,
        class_weight="balanced"
    )
    model.fit(X, y)

    save_model(model, RANDOM_FOREST_PATH)

    meta = get_model_meta()
    meta["random_forest_trained"] = datetime.now().isoformat()
    meta["random_forest_samples"] = len(training)
    meta["random_forest_classes"]  = list(model.classes_)
    save_model_meta(meta)

    print(f"  [ML] Random Forest trained on {len(training)} devices "
          f"({len(set(t[1] for t in training))} device types)")
    return True


def classify_device_rf(ip: str,
                        db_file: str = DB_FILE) -> dict:
    """
    Classify device type using Random Forest.
    Falls back to rule-based if model not trained.
    """
    model = load_model(RANDOM_FOREST_PATH)

    conn     = get_connection(db_file)
    features = _build_classifier_features(ip, conn)
    conn.close()

    if model is None:
        # Fall back to rule-based classifier
        from core.classifier import _classify, _collect_rtt_signal
        from core.classifier import _collect_availability_signal
        from core.classifier import _collect_traffic_signal
        conn2    = get_connection(db_file)
        rtt_sig  = _collect_rtt_signal(ip, conn2)
        avail    = _collect_availability_signal(ip, conn2)
        traffic  = _collect_traffic_signal(ip, conn2)
        conn2.close()
        dtype, conf, _ = _classify(ip, ip, rtt_sig, avail, traffic)
        return {"device_type": dtype, "confidence": conf,
                "method": "rule_based_fallback"}

    X          = np.array([features])
    pred       = model.predict(X)[0]
    proba      = model.predict_proba(X)[0]
    confidence = round(float(proba[pred]) * 100, 1)
    device_type= INT_TO_TYPE.get(pred, "unknown")

    return {
        "device_type": device_type,
        "confidence":  confidence,
        "method":      "random_forest",
        "probabilities": {
            INT_TO_TYPE[i]: round(float(p)*100, 1)
            for i, p in enumerate(proba)
        }
    }


# ─────────────────────────────────────────
# 3. Adaptive Health Scorer
# ─────────────────────────────────────────

def compute_ml_health_score(rtt_avg: float, packet_loss: float,
                             state_changes: int,
                             devices_up: int, devices_total: int,
                             db_file: str = DB_FILE) -> dict:
    """
    Compute health score using learned thresholds from historical data.
    More accurate than fixed weighted average — adapts to your network.
    """
    from sklearn.preprocessing import MinMaxScaler

    conn = get_connection(db_file)

    # Get historical RTT and loss for this network
    rows = conn.execute("""
        SELECT rtt_avg_ms, packet_loss
        FROM probe_results
        WHERE is_alive=1
          AND rtt_avg_ms IS NOT NULL
          AND timestamp > datetime('now', '-30 days')
        LIMIT 10000
    """).fetchall()
    conn.close()

    if len(rows) < 100:
        # Fall back to standard scoring
        from core.health import compute_health_score
        return {**compute_health_score(rtt_avg, packet_loss,
                                        state_changes,
                                        devices_up, devices_total),
                "method": "weighted_fallback"}

    # Learn network-specific percentiles
    rtts   = [r["rtt_avg_ms"]  for r in rows if r["rtt_avg_ms"]]
    losses = [r["packet_loss"] for r in rows if r["packet_loss"] is not None]

    rtts_arr   = np.array(rtts)
    losses_arr = np.array(losses) * 100

    # RTT score — where does current RTT sit in historical distribution?
    rtt_pct = np.mean(rtts_arr <= (rtt_avg or 0)) * 100
    rtt_score = max(0, 100 - rtt_pct)  # lower RTT = higher score

    # Loss score
    loss_pct_val = (packet_loss or 0) * 100
    loss_pct     = np.mean(losses_arr <= loss_pct_val) * 100
    loss_score   = max(0, 100 - loss_pct)

    # Stability score
    stab_score = max(0, 100 - state_changes * 15)

    # Device score
    dev_score = (devices_up / devices_total * 100) if devices_total > 0 else 50

    # Weighted combination
    health_score = (rtt_score   * 0.30 +
                    loss_score  * 0.30 +
                    stab_score  * 0.20 +
                    dev_score   * 0.20)

    grade = ("A" if health_score >= 90 else
             "B" if health_score >= 80 else
             "C" if health_score >= 65 else
             "D" if health_score >= 50 else "F")

    return {
        "rtt_score":       round(rtt_score,   1),
        "loss_score":      round(loss_score,  1),
        "stability_score": round(stab_score,  1),
        "device_score":    round(dev_score,   1),
        "health_score":    round(health_score,1),
        "grade":           grade,
        "method":          "adaptive_ml",
        "training_samples":len(rows),
    }


# ─────────────────────────────────────────
# 4. Enhanced Trend Predictor
# ─────────────────────────────────────────

def predict_trend_ml(ip: str, metric: str = "rtt_avg_ms",
                      predict_minutes: int = 30,
                      db_file: str = DB_FILE) -> dict:
    """
    Enhanced trend prediction using polynomial regression.
    Better than linear regression for RTT which has daily cycles.
    Falls back to linear when data is sparse.
    """
    from sklearn.preprocessing import PolynomialFeatures
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import Pipeline

    conn = get_connection(db_file)
    rows = conn.execute(f"""
        SELECT {metric}, timestamp FROM probe_results
        WHERE host=? AND is_alive=1
          AND {metric} IS NOT NULL
          AND timestamp > datetime('now', '-2 hours')
        ORDER BY timestamp ASC
        LIMIT 100
    """, (ip,)).fetchall()
    conn.close()

    values = [r[metric] for r in rows if r[metric]]
    if len(values) < 10:
        return {"predicted": None, "trend": "unknown",
                "method": "insufficient_data"}

    x = np.arange(len(values)).reshape(-1, 1)
    y = np.array(values)

    if len(values) >= 20:
        # Use polynomial regression for better fit
        model = Pipeline([
            ("poly", PolynomialFeatures(degree=2)),
            ("ridge", Ridge(alpha=1.0))
        ])
        model.fit(x, y)
        # Predict N minutes ahead (each sample ~10s, so N min = N*6 samples)
        future_x    = np.array([[len(values) + predict_minutes * 6]])
        predicted   = float(model.predict(future_x)[0])
        method      = "polynomial_regression"
    else:
        # Linear regression fallback
        coeffs    = np.polyfit(x.flatten(), y, 1)
        future_x  = len(values) + predict_minutes * 6
        predicted = coeffs[0] * future_x + coeffs[1]
        method    = "linear_regression"

    # Determine trend direction
    recent  = np.mean(y[-5:])
    earlier = np.mean(y[:5])
    diff    = recent - earlier

    if diff > 5:    trend = "rising"
    elif diff < -5: trend = "falling"
    else:           trend = "stable"

    return {
        "predicted":       round(max(0, predicted), 2),
        "current":         round(float(y[-1]), 2),
        "trend":           trend,
        "trend_magnitude": round(float(diff), 2),
        "method":          method,
        "samples_used":    len(values),
    }


# ─────────────────────────────────────────
# Model status
# ─────────────────────────────────────────

def get_model_status() -> dict:
    """Get status of all ML models."""
    meta = get_model_meta()
    degradation_path = os.path.join(MODEL_DIR, "degradation_model.pkl")
    return {
        "isolation_forest": {
            "trained":    os.path.exists(ISOLATION_FOREST_PATH),
            "trained_at": meta.get("isolation_forest_trained"),
            "samples":    meta.get("isolation_forest_samples", 0),
        },
        "random_forest": {
            "trained":    os.path.exists(RANDOM_FOREST_PATH) and
                          meta.get("random_forest_trained") is not None,
            "trained_at": meta.get("random_forest_trained"),
            "samples":    meta.get("random_forest_samples", 0),
        },
        "degradation_model": {
            "trained":    os.path.exists(degradation_path),
            "trained_at": meta.get("synthetic_trained"),
            "samples":    meta.get("synthetic_samples", 0),
            "mae":        meta.get("degradation_mae"),
            "baseline":   meta.get("baseline", {}),
        },
        "model_dir": MODEL_DIR,
    }


# ─────────────────────────────────────────
# Training loop
# ─────────────────────────────────────────

def run_training_loop(db_file: str = DB_FILE):
    """
    Retrain all models every 24 hours.
    Runs as background thread in main process.
    """
    print("  [ML] Training engine started.")
    # Wait 30s for classifier to generate device labels first
    time.sleep(30)
    while True:
        try:
            print("  [ML] Training Isolation Forest...")
            trained_if = train_isolation_forest(db_file)

            # Run classifier first to generate labels for RF
            print("  [ML] Generating device labels for Random Forest...")
            try:
                from core.classifier import classify_all
                classify_all(db_file)
            except Exception as ce:
                print(f"  [ML] Classifier error: {ce}")

            print("  [ML] Training Random Forest classifier...")
            trained_rf = train_random_forest(db_file)

            print(f"  [ML] Models ready — "
                  f"IF: {'yes' if trained_if else 'waiting for data'} | "
                  f"RF: {'yes' if trained_rf else 'waiting for data'}")
        except Exception as e:
            print(f"  [ML ERROR] {e}")

        time.sleep(RETRAIN_INTERVAL)


def start_ml_engine():
    """Start ML training loop as background thread."""
    t = threading.Thread(target=run_training_loop, daemon=True)
    t.name = "ml-engine"
    t.start()
    print("  [ML] Engine started — models retrain every 24 hours")