"""
core/synthetic_data.py
=======================
Synthetic training data generator for ML models.

Generates realistic network degradation patterns based on
your real network's baseline values.

Patterns generated:
  1. Healthy router      — stable, low RTT, low jitter, 0% loss
  2. Early degradation   — RTT slowly rising, jitter increasing
  3. Active degradation  — clear decline, packet loss appearing
  4. Pre-failure         — high RTT, high jitter, significant loss
  5. Failure event       — spikes, high loss, unstable

All values generated around YOUR real baseline so the model
understands what's normal for your specific network.
"""

import sys, os

from core.ml_engine import MODEL_DIR
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pickle
from datetime import datetime, timedelta
from db.database import get_connection
from config import DB_FILE

# ─────────────────────────────────────────
# Read real baseline from your network
# ─────────────────────────────────────────

def get_real_baseline(db_file: str = DB_FILE) -> dict:
    """Read actual baseline values from your probe data."""
    conn = get_connection(db_file)
    row  = conn.execute("""
        SELECT
            AVG(rtt_avg_ms)   as avg_rtt,
            MIN(rtt_avg_ms)   as min_rtt,
            AVG(jitter_ms)    as avg_jitter,
            AVG(packet_loss)  as avg_loss,
            COUNT(*)          as samples
        FROM probe_results
        WHERE is_alive=1
          AND rtt_avg_ms IS NOT NULL
          AND timestamp > datetime('now', '-7 days')
    """).fetchone()
    conn.close()

    if row and row["avg_rtt"]:
        return {
            "rtt":     round(row["avg_rtt"],    2),
            "jitter":  round(row["avg_jitter"] or 5.0, 2),
            "loss":    round((row["avg_loss"]  or 0.0) * 100, 3),
            "samples": row["samples"]
        }
    # Default if no data yet
    return {"rtt": 20.0, "jitter": 5.0, "loss": 0.5, "samples": 0}


# ─────────────────────────────────────────
# Pattern generators
# ─────────────────────────────────────────

def _healthy(baseline: dict, n: int, rng) -> np.ndarray:
    """
    Healthy router — stable metrics around baseline.
    Small random variation, no trend.
    """
    rtt    = rng.normal(baseline["rtt"],    baseline["rtt"]    * 0.05, n)
    jitter = rng.normal(baseline["jitter"], baseline["jitter"] * 0.10, n)
    loss   = rng.uniform(0, baseline["loss"] * 0.5, n)
    uptime = rng.uniform(98, 100, n)
    score  = rng.uniform(80, 100, n)
    label  = np.zeros(n)  # 0 = healthy
    return np.column_stack([
        np.clip(rtt,    1,   500),
        np.clip(jitter, 0.1, 200),
        np.clip(loss,   0,   100),
        np.clip(uptime, 0,   100),
        np.clip(score,  0,   100),
        label
    ])


def _early_degradation(baseline: dict, n: int, rng) -> np.ndarray:
    """
    Early degradation — slow upward trend in RTT and jitter.
    Packet loss still near zero. Hard to notice without monitoring.
    """
    # RTT rising slowly — 1.2x to 1.8x baseline over time
    trend  = np.linspace(1.2, 1.8, n)
    rtt    = rng.normal(baseline["rtt"] * trend,
                         baseline["rtt"] * 0.08, n)
    jitter = rng.normal(baseline["jitter"] * trend * 1.3,
                         baseline["jitter"] * 0.15, n)
    loss   = rng.uniform(0, baseline["loss"] * 2, n)
    uptime = rng.uniform(95, 99.5, n)
    score  = rng.uniform(65, 82, n)
    label  = np.ones(n) * 0.3  # 0.3 = early degradation
    return np.column_stack([
        np.clip(rtt,    1,   500),
        np.clip(jitter, 0.1, 200),
        np.clip(loss,   0,   100),
        np.clip(uptime, 0,   100),
        np.clip(score,  0,   100),
        label
    ])


def _active_degradation(baseline: dict, n: int, rng) -> np.ndarray:
    """
    Active degradation — clear decline visible.
    RTT 2-4x baseline, jitter high, packet loss appearing.
    """
    trend  = np.linspace(2.0, 4.0, n)
    rtt    = rng.normal(baseline["rtt"] * trend,
                         baseline["rtt"] * 0.15, n)
    jitter = rng.normal(baseline["jitter"] * trend * 1.8,
                         baseline["jitter"] * 0.25, n)
    loss   = rng.uniform(baseline["loss"] * 2,
                          baseline["loss"] * 10 + 3, n)
    uptime = rng.uniform(88, 96, n)
    score  = rng.uniform(40, 65, n)
    label  = np.ones(n) * 0.6  # 0.6 = active degradation
    return np.column_stack([
        np.clip(rtt,    1,   500),
        np.clip(jitter, 0.1, 200),
        np.clip(loss,   0,   100),
        np.clip(uptime, 0,   100),
        np.clip(score,  0,   100),
        label
    ])


def _pre_failure(baseline: dict, n: int, rng) -> np.ndarray:
    """
    Pre-failure state — high RTT spikes, significant packet loss.
    Router struggling, needs immediate replacement.
    """
    trend  = np.linspace(4.0, 8.0, n)
    rtt    = rng.normal(baseline["rtt"] * trend,
                         baseline["rtt"] * 0.30, n)
    jitter = rng.normal(baseline["jitter"] * trend * 2.5,
                         baseline["jitter"] * 0.40, n)
    loss   = rng.uniform(5, 25, n)
    uptime = rng.uniform(70, 90, n)
    score  = rng.uniform(20, 42, n)
    label  = np.ones(n) * 0.85  # 0.85 = pre-failure
    return np.column_stack([
        np.clip(rtt,    1,   2000),
        np.clip(jitter, 0.1, 500),
        np.clip(loss,   0,   100),
        np.clip(uptime, 0,   100),
        np.clip(score,  0,   100),
        label
    ])


def _failure_event(baseline: dict, n: int, rng) -> np.ndarray:
    """
    Active failure — extreme spikes, very high loss, router failing.
    """
    rtt    = rng.uniform(baseline["rtt"] * 8,
                          baseline["rtt"] * 20, n)
    jitter = rng.uniform(baseline["jitter"] * 5,
                          baseline["jitter"] * 15, n)
    loss   = rng.uniform(25, 100, n)
    uptime = rng.uniform(20, 72, n)
    score  = rng.uniform(0, 22, n)
    label  = np.ones(n)  # 1.0 = failure
    return np.column_stack([
        np.clip(rtt,    1,   5000),
        np.clip(jitter, 0.1, 1000),
        np.clip(loss,   0,   100),
        np.clip(uptime, 0,   100),
        np.clip(score,  0,   100),
        label
    ])


# ─────────────────────────────────────────
# Main generator
# ─────────────────────────────────────────

def generate_synthetic_dataset(db_file: str = DB_FILE,
                                 total_samples: int = 10000,
                                 seed: int = 42) -> dict:
    """
    Generate complete synthetic training dataset.
    Returns dict with X (features) and y (labels).
    """
    rng      = np.random.default_rng(seed)
    baseline = get_real_baseline(db_file)

    print(f"  [SYNTHETIC] Real baseline detected:")
    print(f"    RTT:    {baseline['rtt']:.1f}ms")
    print(f"    Jitter: {baseline['jitter']:.1f}ms")
    print(f"    Loss:   {baseline['loss']:.2f}%")
    print(f"    Source: {baseline['samples']} real probe samples")
    print()

    # Distribution: more healthy samples than failure
    # (reflects real world — most time routers are healthy)
    n_healthy    = int(total_samples * 0.40)  # 4000
    n_early      = int(total_samples * 0.20)  # 2000
    n_active     = int(total_samples * 0.20)  # 2000
    n_prefail    = int(total_samples * 0.15)  # 1500
    n_failure    = int(total_samples * 0.05)  # 500

    print(f"  [SYNTHETIC] Generating {total_samples} samples:")
    print(f"    Healthy:           {n_healthy}")
    print(f"    Early degradation: {n_early}")
    print(f"    Active degradation:{n_active}")
    print(f"    Pre-failure:       {n_prefail}")
    print(f"    Failure events:    {n_failure}")

    data = np.vstack([
        _healthy(baseline,           n_healthy, rng),
        _early_degradation(baseline, n_early,   rng),
        _active_degradation(baseline,n_active,  rng),
        _pre_failure(baseline,       n_prefail, rng),
        _failure_event(baseline,     n_failure, rng),
    ])

    # Shuffle
    rng.shuffle(data)

    X = data[:, :5]   # features: rtt, jitter, loss, uptime, score
    y = data[:, 5]    # label: 0=healthy, 0.3=early, 0.6=active,
                      #        0.85=prefail, 1=failure

    # Binary anomaly labels for Isolation Forest
    # (anything above early degradation = anomaly)
    y_binary = (y >= 0.6).astype(int)

    print(f"\n  [SYNTHETIC] Dataset ready:")
    print(f"    Normal samples:  {np.sum(y_binary == 0)}")
    print(f"    Anomaly samples: {np.sum(y_binary == 1)}")

    return {
        "X":         X,
        "y":         y,
        "y_binary":  y_binary,
        "baseline":  baseline,
        "features":  ["rtt_avg_ms", "jitter_ms",
                       "packet_loss_pct", "uptime_pct",
                       "health_score"],
        "generated_at": datetime.now().isoformat(),
        "total_samples": total_samples,
    }


# ─────────────────────────────────────────
# Train models on synthetic data
# ─────────────────────────────────────────

def train_on_synthetic(db_file: str = DB_FILE) -> bool:
    """
    Train Isolation Forest and degradation predictor
    on synthetic data, then fine-tune with real data.
    """
    from sklearn.ensemble import IsolationForest, GradientBoostingRegressor
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import mean_absolute_error

    MODEL_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "models")
    os.makedirs(MODEL_DIR, exist_ok=True)

    # Generate synthetic dataset
    dataset = generate_synthetic_dataset(db_file)
    X       = dataset["X"]
    y       = dataset["y"]
    y_bin   = dataset["y_binary"]

    # ── 1. Train Isolation Forest ──────────
    print("\n  [SYNTHETIC] Training Isolation Forest...")
    scaler   = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Mix with real data if available
    real_X = _get_real_features(db_file)
    if len(real_X) >= 50:
        print(f"  [SYNTHETIC] Mixing with {len(real_X)} real samples...")
        real_scaled = scaler.transform(real_X)
        X_combined  = np.vstack([X_scaled, real_scaled])
    else:
        X_combined = X_scaled

    # Contamination = ratio of anomalies in dataset
    contamination = float(np.mean(y_bin))
    iso_forest = IsolationForest(
        n_estimators=200,
        contamination=max(0.01, min(0.5, contamination)),
        random_state=42,
        n_jobs=-1
    )
    iso_forest.fit(X_combined)

    with open(os.path.join(MODEL_DIR, "synthetic_isolation_forest.pkl"), "wb") as f:
        pickle.dump(iso_forest, f)
    with open(os.path.join(MODEL_DIR, "synthetic_scaler.pkl"), "wb") as f:
        pickle.dump(scaler, f)
    print("  [SYNTHETIC] Isolation Forest trained and saved")

    # ── 2. Train degradation predictor ────
    print("\n  [SYNTHETIC] Training degradation predictor...")
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42)

    degradation_model = GradientBoostingRegressor(
        n_estimators=100,
        max_depth=4,
        learning_rate=0.1,
        random_state=42
    )
    degradation_model.fit(X_train, y_train)

    y_pred = degradation_model.predict(X_test)
    mae    = mean_absolute_error(y_test, y_pred)
    print(f"  [SYNTHETIC] Degradation model MAE: {mae:.3f}")

    with open(os.path.join(MODEL_DIR, "synthetic_degradation_model.pkl"), "wb") as f:
        pickle.dump(degradation_model, f)

    # Save metadata
    meta = {
        "synthetic_trained":           datetime.now().isoformat(),
        "synthetic_samples":           len(X),
        "real_samples_mixed":          len(real_X),
        "baseline":                    dataset["baseline"],
        "synthetic_if_trained":        datetime.now().isoformat(),
        "synthetic_if_samples":        len(X_combined),
        "degradation_mae":             round(mae, 4),
        "features":                    dataset["features"],
    }
    with open(os.path.join(MODEL_DIR, "synthetic_model_meta.pkl"), "wb") as f:
        pickle.dump(meta, f)

    print("\n  [SYNTHETIC] All models trained successfully!")
    print(f"  Models saved to: {MODEL_DIR}")
    return True


def _get_real_features(db_file: str = DB_FILE) -> np.ndarray:
    """Get real probe features for mixing with synthetic data."""
    conn = get_connection(db_file)

    # Join probe_results with device_health_daily for real uptime + score
    rows = conn.execute("""
        SELECT p.rtt_avg_ms, p.jitter_ms, p.packet_loss,
               COALESCE(d.uptime_pct, 95.0)    as uptime,
               COALESCE(d.health_score, 70.0)  as score
        FROM probe_results p
        LEFT JOIN device_health_daily d
            ON d.ip = p.host
            AND d.date = date(p.timestamp)
        WHERE p.is_alive=1 AND p.rtt_avg_ms IS NOT NULL
          AND p.timestamp > datetime('now', '-7 days')
        ORDER BY RANDOM()
        LIMIT 2000
    """).fetchall()
    conn.close()

    if not rows:
        return np.array([]).reshape(0, 5)

    X = []
    for r in rows:
        X.append([
            r["rtt_avg_ms"]   or 0,
            r["jitter_ms"]    or 0,
            (r["packet_loss"] or 0) * 100,
            r["uptime"]       or 95.0,
            r["score"]        or 70.0,
        ])
    return np.array(X)


# ─────────────────────────────────────────
# Predict degradation score for a device
# ─────────────────────────────────────────

def predict_degradation_score(rtt: float, jitter: float,
                               loss: float, uptime: float,
                               health_score: float,
                               db_file: str = DB_FILE) -> dict:
    """
    Predict degradation level for a device using trained model.
    Returns score 0-1 where:
      0.0 = perfectly healthy
      0.3 = early degradation
      0.6 = active degradation
      0.85 = pre-failure
      1.0 = failing
    """
    MODEL_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "models")
    model_path = os.path.join(MODEL_DIR, "synthetic_degradation_model.pkl")

    if not os.path.exists(model_path):
        return {"score": None, "label": "unknown",
                "method": "model_not_trained"}

    with open(model_path, "rb") as f:
        model = pickle.load(f)

    X      = np.array([[rtt, jitter, loss, uptime, health_score]])
    score  = float(model.predict(X)[0])
    score  = max(0.0, min(1.0, score))

    if score < 0.2:     label = "healthy"
    elif score < 0.45:  label = "early_degradation"
    elif score < 0.70:  label = "active_degradation"
    elif score < 0.90:  label = "pre_failure"
    else:               label = "failing"

    return {
        "score":  round(score, 3),
        "label":  label,
        "pct":    round(score * 100, 1),
        "method": "gradient_boosting",
    }


# ─────────────────────────────────────────
# Run once to train
# ─────────────────────────────────────────

def run():
    """Train all models on synthetic + real data."""
    print("  Synthetic data generator started.")
    print("  Training models now...\n")
    success = train_on_synthetic()
    if success:
        print("\n  Done. Models ready for use.")
        print("  Retraining every 24 hours with accumulated real data.")

    # Retrain every 24 hours
    import time
    while True:
        time.sleep(86400)
        print("\n  [SYNTHETIC] Daily retrain starting...")
        try:
            train_on_synthetic()
        except Exception as e:
            print(f"  [SYNTHETIC ERROR] {e}")


if __name__ == "__main__":
    run()