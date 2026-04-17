"""
ids/ml/ids_model.py
====================
ML-based IDS using Isolation Forest.
Learns what NORMAL traffic looks like.
Flags anything unusual as suspicious.

NOTE: This is separate from friend's Isolation Forest
      which is used for device health monitoring.
      This one is purely for ATTACK detection.
"""

import os
import pickle
import numpy as np
from datetime import datetime
from collections import defaultdict

# ─────────────────────────────────────────
# Model storage
# ─────────────────────────────────────────

MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))),
    "models", "ids_isolation_forest.pkl"
)

# ─────────────────────────────────────────
# Traffic buffer
# Stores recent packets for training
# ─────────────────────────────────────────

# We collect packets here before training
traffic_buffer = []
BUFFER_LIMIT   = 1000  # train after 1000 packets

# ─────────────────────────────────────────
# Feature extraction for ML
# ─────────────────────────────────────────

# Track packet counts per IP for rate features
ip_packet_count = defaultdict(int)
ip_byte_count   = defaultdict(int)

# Cooldown tracker — don't alert same IP twice within N seconds
from datetime import datetime, timedelta
ml_last_alert   = {}
ML_COOLDOWN_SEC = 30


def extract_ml_features(features):
    """
    Convert raw packet features into ML feature vector
    .
    Must match exactly what trainer.py used!
    10 features matching NSL-KDD columns.
    """
    src_ip = features.get("src_ip", "")

    # Update counters for this IP
    ip_packet_count[src_ip] += 1
    ip_byte_count[src_ip]   += features.get("packet_size", 0)

    vector = [
        0,                                    # duration (live packets = 0)
        features.get("protocol",    0) or 0,  # protocol
        features.get("packet_size", 0) or 0,  # src_bytes (approx)
        0,                                    # dst_bytes (unknown live)
        ip_packet_count[src_ip],              # count
        ip_packet_count[src_ip],              # srv_count (approx)
        0,                                    # serror_rate
        ip_packet_count[src_ip],              # dst_host_count
        ip_packet_count[src_ip],              # dst_host_srv_count
        1.0,                                  # dst_host_same_srv_rate
    ]

    return vector


# ─────────────────────────────────────────
# Model save / load
# ─────────────────────────────────────────

def save_model(model):
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(model, f)
    print(f"[ML IDS] Model saved to {MODEL_PATH}")


def load_model():
    if os.path.exists(MODEL_PATH):
        with open(MODEL_PATH, "rb") as f:
            bundle = pickle.load(f)
            # bundle contains model AND scaler
            return bundle["model"], bundle["scaler"]
    return None, None


# ─────────────────────────────────────────
# Training
# ─────────────────────────────────────────

def train_model():
    """
    Train Isolation Forest on collected traffic.
    Called automatically after BUFFER_LIMIT packets collected.
    """
    from sklearn.ensemble import IsolationForest

    if len(traffic_buffer) < 100:
        print(f"[ML IDS] Not enough data yet "
              f"({len(traffic_buffer)}/100 packets)")
        return False

    print(f"[ML IDS] Training on {len(traffic_buffer)} packets...")

    X     = np.array(traffic_buffer)
    model = IsolationForest(
        n_estimators  = 100,
        contamination = 0.05,  # expect 5% anomalies
        random_state  = 42,
        n_jobs        = -1
    )
    model.fit(X)
    save_model(model)

    print(f"[ML IDS] Training complete! Model ready.")
    return True


# ─────────────────────────────────────────
# Prediction
# ─────────────────────────────────────────

def predict(features):
    """
    Predict if a packet is an anomaly.
    Returns alert dict if anomaly, None if normal.
    """
    global traffic_buffer

    # Extract ML features
    vector = extract_ml_features(features)

    # Load model safely
    try:
        model, scaler = load_model()
    except Exception as e:
        return None

    # No model yet
    if model is None or scaler is None:
        return None

    # Make prediction safely
    try:
        X          = np.array([vector])
        X_scaled   = scaler.transform(X)
        prediction = model.predict(X_scaled)[0]
        score      = model.decision_function(X_scaled)[0]
    except Exception as e:
        return None

    # Only alert if significantly anomalous
    if prediction == -1 and score < -0.1:
        # Check cooldown
        src_ip = features.get("src_ip", "")
        now    = datetime.now()
        last   = ml_last_alert.get(src_ip)

        if last and now - last < timedelta(seconds=ML_COOLDOWN_SEC):
            return None

        ml_last_alert[src_ip] = now

        severity = "high" if score < -0.3 else "medium"
        return {
            "timestamp" : datetime.now().isoformat(),
            "rule"      : "ML_ANOMALY",
            "severity"  : severity,
            "src_ip"    : features.get("src_ip"),
            "dst_ip"    : features.get("dst_ip"),
            "message"   : (f"ML anomaly detected from "
                          f"{features.get('src_ip')}! "
                          f"Anomaly score: {score:.3f}"),
            "score"     : round(float(score), 4),
            "type"      : "ml",
        }

    return None


# ─────────────────────────────────────────
# Run ML IDS on a packet
# ─────────────────────────────────────────

def run_ml_ids(features, on_alert):
    """
    Check packet using ML model.
    If anomaly detected → send to on_alert callback.
    """
    result = predict(features)

    if result:
        severity = result["severity"].upper()
        print(f"[ML IDS] [{severity}] {result['message']}")
        on_alert(result)