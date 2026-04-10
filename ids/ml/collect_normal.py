"""
ids/ml/collect_normal.py
=========================
Collects YOUR real normal network traffic
and saves it for retraining the IDS model.

Run this for 10 minutes while using PC normally.
Browse YouTube, open websites, let Windows sync.
"""

import os
import csv
import time
import numpy as np
from scapy.all import sniff, IP, TCP, UDP, ICMP
from datetime import datetime
from collections import defaultdict

# ─────────────────────────────────────────
# Config
# ─────────────────────────────────────────

BASE_DIR    = os.path.dirname(os.path.dirname(
              os.path.dirname(os.path.abspath(__file__))))
OUTPUT_FILE = os.path.join(BASE_DIR, "ids", "data", "normal_traffic.csv")
CAPTURE_SECONDS = 600  # 10 minutes

# ─────────────────────────────────────────
# Tracking
# ─────────────────────────────────────────

ip_packet_count = defaultdict(int)
ip_byte_count   = defaultdict(int)
collected       = []

# ─────────────────────────────────────────
# Feature extraction
# ─────────────────────────────────────────

def extract_features(packet):
    if not packet.haslayer(IP):
        return None

    src_ip = packet[IP].src
    size   = len(packet)

    ip_packet_count[src_ip] += 1
    ip_byte_count[src_ip]   += size

    protocol = packet[IP].proto
    src_port = 0
    dst_port = 0

    if packet.haslayer(TCP):
        src_port = packet[TCP].sport
        dst_port = packet[TCP].dport
    elif packet.haslayer(UDP):
        src_port = packet[UDP].sport
        dst_port = packet[UDP].dport

    return [
        0,                          # duration
        float(protocol),            # protocol
        float(size),                # src_bytes
        0.0,                        # dst_bytes
        float(ip_packet_count[src_ip]),  # count
        float(ip_packet_count[src_ip]),  # srv_count
        0.0,                        # serror_rate
        float(ip_packet_count[src_ip]),  # dst_host_count
        float(ip_packet_count[src_ip]),  # dst_host_srv_count
        1.0,                        # dst_host_same_srv_rate
    ]

# ─────────────────────────────────────────
# Packet handler
# ─────────────────────────────────────────

def on_packet(packet):
    features = extract_features(packet)
    if features:
        collected.append(features)
        if len(collected) % 100 == 0:
            print(f"  Collected {len(collected)} packets...")

# ─────────────────────────────────────────
# Save to CSV
# ─────────────────────────────────────────

def save_to_csv():
    with open(OUTPUT_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        # Header
        writer.writerow([
            "duration", "protocol", "src_bytes",
            "dst_bytes", "count", "srv_count",
            "serror_rate", "dst_host_count",
            "dst_host_srv_count", "dst_host_same_srv_rate"
        ])
        writer.writerows(collected)
    print(f"\n[COLLECTOR] Saved {len(collected)} "
          f"normal traffic samples to:")
    print(f"  {OUTPUT_FILE}")

# ─────────────────────────────────────────
# Main
# ─────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("  Normal Traffic Collector")
    print("=" * 50)
    print(f"\nCapturing for {CAPTURE_SECONDS//60} minutes...")
    print("Use your PC normally:")
    print("  → Browse YouTube")
    print("  → Open websites")
    print("  → Let Windows do its thing")
    print("\nPress Ctrl+C to stop early\n")

    start = time.time()

    try:
        sniff(
            filter   = "ip",
            prn      = on_packet,
            store    = False,
            timeout  = CAPTURE_SECONDS
        )
    except KeyboardInterrupt:
        print("\n[COLLECTOR] Stopped early by user")

    elapsed = round(time.time() - start)
    print(f"\n[COLLECTOR] Captured for {elapsed} seconds")
    print(f"[COLLECTOR] Total packets: {len(collected)}")

    if len(collected) < 100:
        print("[COLLECTOR] Too few packets! "
              "Please run longer.")
    else:
        save_to_csv()
        print("[COLLECTOR] Done! Ready to retrain.")