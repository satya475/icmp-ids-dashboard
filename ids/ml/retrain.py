"""
ids/ml/retrain.py
==================
Retrains Isolation Forest using:
1. YOUR real normal traffic (normal_traffic.csv)
2. NSL-KDD attack patterns (KDDTrain+.txt)
Best of both worlds!
"""

import os
import pickle
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import csv

# ─────────────────────────────────────────
# Paths
# ─────────────────────────────────────────

BASE_DIR      = os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))))
NORMAL_FILE   = os.path.join(BASE_DIR, "ids", "data", "normal_traffic.csv")
NSLKDD_FILE   = os.path.join(BASE_DIR, "ids", "data", "KDDTrain+.txt")
MODEL_PATH    = os.path.join(BASE_DIR, "models", "ids_isolation_forest.pkl")

# ─────────────────────────────────────────
# Attack labels from NSL-KDD
# ─────────────────────────────────────────

ATTACK_LABELS = {
    "neptune", "back", "land", "pod", "smurf",
    "teardrop", "mailbomb", "processtable",
    "udpstorm", "apache2", "worm",
    "ipsweep", "nmap", "portsweep", "satan",
    "mscan", "saint",
    "ftp_write", "guess_passwd", "imap", "multihop",
    "phf", "spy", "warezclient", "warezmaster",
    "sendmail", "named", "snmpgetattack",
    "snmpguess", "xlock", "xsnoop", "httptunnel",
    "buffer_overflow", "loadmodule", "perl",
    "rootkit", "sqlattack", "xterm", "ps",
}

PROTOCOL_MAP = {"tcp": 6, "udp": 17, "icmp": 1}


# ─────────────────────────────────────────
# Load YOUR real normal traffic
# ─────────────────────────────────────────

def load_normal_traffic():
    print("[RETRAIN] Loading your real normal traffic...")
    X = []
    with open(NORMAL_FILE, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                features = [
                    float(row["duration"]),
                    float(row["protocol"]),
                    float(row["src_bytes"]),
                    float(row["dst_bytes"]),
                    float(row["count"]),
                    float(row["srv_count"]),
                    float(row["serror_rate"]),
                    float(row["dst_host_count"]),
                    float(row["dst_host_srv_count"]),
                    float(row["dst_host_same_srv_rate"]),
                ]
                X.append(features)
            except Exception:
                continue
    print(f"[RETRAIN] Loaded {len(X)} real normal samples ✅")
    return np.array(X)


# ─────────────────────────────────────────
# Load NSL-KDD attack patterns
# ─────────────────────────────────────────

def load_nslkdd_attacks():
    print("[RETRAIN] Loading NSL-KDD attack patterns...")
    X_attack = []
    with open(NSLKDD_FILE, "r") as f:
        for line in f:
            row = line.strip().split(",")
            if len(row) < 42:
                continue
            label = row[41].strip().lower()
            if label not in ATTACK_LABELS:
                continue
            try:
                features = [
                    float(row[0]),
                    float(PROTOCOL_MAP.get(row[1], 0)),
                    float(row[4]),
                    float(row[5]),
                    float(row[22]),
                    float(row[23]),
                    float(row[24]),
                    float(row[30]),
                    float(row[31]),
                    float(row[32]),
                ]
                X_attack.append(features)
            except Exception:
                continue
    print(f"[RETRAIN] Loaded {len(X_attack)} attack samples ✅")
    return np.array(X_attack)


# ─────────────────────────────────────────
# Retrain
# ─────────────────────────────────────────

def retrain():
    # Load both datasets
    X_normal = load_normal_traffic()
    X_attack = load_nslkdd_attacks()

    print(f"\n[RETRAIN] Summary:")
    print(f"  Normal samples  : {len(X_normal)}")
    print(f"  Attack samples  : {len(X_attack)}")

    # Scale features on normal traffic
    print(f"\n[RETRAIN] Scaling features...")
    scaler          = StandardScaler()
    X_normal_scaled = scaler.fit_transform(X_normal)

    # Train ONLY on normal traffic
    print(f"[RETRAIN] Training Isolation Forest on "
          f"real normal traffic...")
    model = IsolationForest(
        n_estimators  = 200,
        contamination = 0.02,
        random_state  = 42,
        n_jobs        = -1
    )
    model.fit(X_normal_scaled)

    # ── Test on attack samples ──
    print(f"\n[RETRAIN] Testing on attack samples...")

    # Clip attack features to match live traffic scale
    X_attack_clipped = np.clip(
        X_attack, 0,
        np.percentile(X_normal, 99, axis=0)
    )
    X_attack_scaled  = scaler.transform(X_attack_clipped)
    attack_preds     = model.predict(X_attack_scaled)
    attacks_caught   = sum(1 for p in attack_preds if p == -1)
    attack_catch_rate = attacks_caught / len(X_attack) * 100

    # ── Test false positives on normal samples ──
    normal_preds    = model.predict(X_normal_scaled)
    false_positives = sum(1 for p in normal_preds if p == -1)
    fp_rate         = false_positives / len(X_normal) * 100

    print(f"\n[RETRAIN] Results:")
    print(f"  Attack detection rate : {attack_catch_rate:.1f}%")
    print(f"  False positive rate   : {fp_rate:.1f}%")

    if fp_rate > 10:
        print(f"  ⚠️  False positive rate high!")
        print(f"     Consider collecting more normal traffic")
    else:
        print(f"  ✅ False positive rate acceptable!")

    if attack_catch_rate < 10:
        print(f"  ⚠️  Attack detection low!")
        print(f"     This is expected — Isolation Forest")
        print(f"     works best on YOUR network's attacks")
        print(f"     Signature IDS covers known attacks! ✅")
    else:
        print(f"  ✅ Attack detection acceptable!")

    # Save model + scaler together
    bundle = {"model": model, "scaler": scaler}
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(bundle, f)

    print(f"\n[RETRAIN] Model saved to {MODEL_PATH}")
    print(f"[RETRAIN] Done! IDS ready with improved model.")


# ─────────────────────────────────────────
# Run
# ─────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("  IDS Model Retrainer")
    print("=" * 50)
    retrain()