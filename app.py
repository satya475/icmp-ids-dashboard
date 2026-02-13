from flask import Flask, render_template, jsonify
import pandas as pd
import joblib
import os
import speedtest
import threading
import time

app = Flask(__name__)

# --- Speed Test Setup ---
network_speed = {"download": 0, "upload": 0}

def check_speed_periodically():
    st = speedtest.Speedtest()
    while True:
        try:
            st.get_best_server()
            network_speed["download"] = st.download() / 1_000_000 
            network_speed["upload"] = st.upload() / 1_000_000
        except:
            pass
        time.sleep(300) 

threading.Thread(target=check_speed_periodically, daemon=True).start()

# --- Paths ---
MODEL_PATH = "model/icmp_model.pkl"
DATA_PATH = "data/icmp_live.csv"

if os.path.exists(MODEL_PATH):
    model = joblib.load(MODEL_PATH)
else:
    model = None

@app.route("/")
def dashboard():
    return render_template("dashboard.html")

@app.route("/api/metrics")
def metrics():
    if not os.path.exists(DATA_PATH):
        return jsonify({"error": "No data found"}), 404

    try:
        df = pd.read_csv(DATA_PATH).tail(50)
        if df.empty:
            return jsonify({"network_status": "Waiting for traffic..."})

        features = ['rtt', 'packet_loss', 'icmp_rate', 'ttl', 'ttl_variance']
        
        anomaly_count = 0
        if model:
            predictions = model.predict(df[features])
            anomaly_count = (predictions == -1).sum()

        rtt_mean = df['rtt'].mean()
        loss_mean = df['packet_loss'].mean()
        rate_mean = df['icmp_rate'].mean()
        ttl_std = df['ttl'].std()
        ttl_mean = df['ttl'].mean()

        ttl_alert = False
        ttl_reason = "Normal TTL Behavior"
        if ttl_std > 10 and ttl_mean < 45:
            ttl_alert = True
            ttl_reason = "High variance & TTL drop → Possible spoofing"

        # --- REFINED STATUS HIERARCHY ---
        if loss_mean > 80:
            status = "❌ Host Unreachable"
        elif rate_mean > 100 and anomaly_count > 10:
            status = "🚨 ICMP Flood Detected"
        elif ttl_alert and anomaly_count > 5:
            status = "🚨 Multiple Threats Detected"
        elif ttl_alert:
            status = "🚨 TTL-Based Spoofing Detected"
        elif anomaly_count > 10:
            status = "🟠 Suspicious Activity"
        elif rtt_mean > 150:
            if network_speed["download"] > 0 and network_speed["download"] < 5:
                status = "⚠️ Degraded Performance: Low Bandwidth (ISP)"
            else:
                status = "⚠️ Degraded Performance: Network Congestion"
        else:
            status = "✅ Network Status: Normal"

        return jsonify({
            "network_status": status,
            "rtt": df["rtt"].tolist(),
            "packet_loss": df["packet_loss"].tolist(),
            "icmp_rate": df["icmp_rate"].tolist(),
            "ttl": df["ttl"].tolist(),
            "anomalies": int(anomaly_count),
            "ttl_alert": ttl_alert,
            "ttl_reason": ttl_reason,
            "download": network_speed["download"],
            "upload": network_speed["upload"]
        })
    except Exception as e:
        return jsonify({"error": "Syncing data..."}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)