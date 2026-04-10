"""
ids/ml/trainer.py
==================
Trains Isolation Forest on NSL-KDD dataset.
Converts raw dataset into ML features and trains model.
"""

import os
import pickle
import numpy as np

# ─────────────────────────────────────────
# Paths
# ─────────────────────────────────────────

BASE_DIR   = os.path.dirname(os.path.dirname(
             os.path.dirname(os.path.abspath(__file__))))
TRAIN_FILE = os.path.join(BASE_DIR, "ids", "data", "KDDTrain+.txt")
TEST_FILE  = os.path.join(BASE_DIR, "ids", "data", "KDDTest+.txt")
MODEL_PATH = os.path.join(BASE_DIR, "models", "ids_isolation_forest.pkl")

# ─────────────────────────────────────────
# NSL-KDD protocol mapping
# ─────────────────────────────────────────

# Convert protocol name to number
PROTOCOL_MAP = {
    "tcp"  : 6,
    "udp"  : 17,
    "icmp" : 1,
}

# These are all attack types in NSL-KDD
ATTACK_LABELS = {
    # DoS attacks
    "neptune", "back", "land", "pod", "smurf",
    "teardrop", "mailbomb", "processtable",
    "udpstorm", "apache2", "worm",
    # Port scan
    "ipsweep", "nmap", "portsweep", "satan",
    "mscan", "saint",
    # R2L
    "ftp_write", "guess_passwd", "imap", "multihop",
    "phf", "spy", "warezclient", "warezmaster",
    "sendmail", "named", "snmpgetattack",
    "snmpguess", "xlock", "xsnoop", "httptunnel",
    # U2R
    "buffer_overflow", "loadmodule", "perl",
    "rootkit", "sqlattack", "xterm", "ps",
}


# ─────────────────────────────────────────
# Feature extraction from NSL-KDD row
# ─────────────────────────────────────────

def extract_features(row):
    """
    Extract numerical features from one NSL-KDD row.
    We pick the most useful columns for our IDS.

    NSL-KDD columns we use:
    0  → duration
    1  → protocol (tcp/udp/icmp)
    4  → src_bytes
    5  → dst_bytes
    22 → count (connections to same host)
    23 → srv_count
    24 → serror_rate
    30 → dst_host_count
    31 → dst_host_srv_count
    32 → dst_host_same_srv_rate
    """
    try:
        features = [
            float(row[0]),                              # duration
            float(PROTOCOL_MAP.get(row[1], 0)),         # protocol
            float(row[4]),                              # src_bytes
            float(row[5]),                              # dst_bytes
            float(row[22]),                             # count
            float(row[23]),                             # srv_count
            float(row[24]),                             # serror_rate
            float(row[30]),                             # dst_host_count
            float(row[31]),                             # dst_host_srv_count
            float(row[32]),                             # dst_host_same_srv_rate
        ]
        return features
    except Exception:
        return None


# ─────────────────────────────────────────
# Load dataset
# ─────────────────────────────────────────

def load_dataset(filepath):
    """
    Load NSL-KDD dataset from txt file.
    Returns:
        X      → feature matrix
        y      → labels (0=normal, 1=attack)
        labels → original label strings
    """
    X      = []
    y      = []
    labels = []
    errors = 0

    print(f"[TRAINER] Loading {filepath}...")

    with open(filepath, "r") as f:
        for line in f:
            row = line.strip().split(",")

            if len(row) < 42:
                errors += 1
                continue

            features = extract_features(row)
            if features is None:
                errors += 1
                continue

            # Get label (second to last column)
            label     = row[41].strip().lower()
            is_attack = 1 if label in ATTACK_LABELS else 0

            X.append(features)
            y.append(is_attack)
            labels.append(label)

    print(f"[TRAINER] Loaded {len(X)} samples "
          f"({errors} skipped)")
    print(f"[TRAINER] Normal: {y.count(0)} | "
          f"Attack: {y.count(1)}")

    return np.array(X), np.array(y), labels


# ─────────────────────────────────────────
# Train model
# ─────────────────────────────────────────

def train():
    """
    Train Isolation Forest on NSL-KDD training data.
    Evaluate on test data.
    """
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import classification_report

    # Load training data
    X_train, y_train, _ = load_dataset(TRAIN_FILE)

    # Load test data
    X_test, y_test, _   = load_dataset(TEST_FILE)

    print(f"\n[TRAINER] Training Isolation Forest...")

    # Scale features
    scaler   = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled  = scaler.transform(X_test)

    # Train only on NORMAL traffic
    # This is how Isolation Forest works best —
    # learn what normal looks like, flag everything else
    X_normal = X_train_scaled[y_train == 0]
    print(f"[TRAINER] Training on {len(X_normal)} "
          f"normal samples only...")

    model = IsolationForest(
        n_estimators  = 100,
        contamination = 0.05,
        random_state  = 42,
        n_jobs        = -1
    )
    model.fit(X_normal)

    # Evaluate on test data
    print(f"\n[TRAINER] Evaluating on test data...")
    predictions = model.predict(X_test_scaled)

    # Convert sklearn output to our format
    # sklearn: -1=anomaly, 1=normal
    # our format: 1=attack, 0=normal
    pred_binary = [1 if p == -1 else 0 for p in predictions]

    print("\n[TRAINER] Results:")
    print(classification_report(
        y_test, pred_binary,
        target_names=["Normal", "Attack"]
    ))

    # Save model and scaler together
    bundle = {"model": model, "scaler": scaler}
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(bundle, f)

    print(f"[TRAINER] Model saved to {MODEL_PATH}")
    return True


# ─────────────────────────────────────────
# Run
# ─────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("  NSL-KDD Isolation Forest Trainer")
    print("=" * 50)
    train()
    print("\n[TRAINER] Done! Model ready for IDS.")