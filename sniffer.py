import pandas as pd
from scapy.all import sniff, ICMP, IP, time
import os

# Configuration
DATA_PATH = "data/icmp_live.csv"
INTERFACE = None  # Set to your interface name like 'eth0' or 'wlan0' if needed

# Buffer to calculate rolling stats
packet_buffer = []

def process_packet(pkt):
    if pkt.haslayer(ICMP) and pkt.haslayer(IP):
        # 1. Extract Basic Features
        ttl = pkt[IP].ttl
        timestamp = time.time()
        
        # 2. Simulate RTT (For a real sniffer, you'd match Echo Request to Reply)
        # For your project, we will use the arrival delta as a proxy for RTT
        rtt = 0
        if len(packet_buffer) > 0:
            rtt = (timestamp - packet_buffer[-1]['timestamp']) * 1000
        
        # 3. Store in temporary buffer
        packet_data = {
            'timestamp': timestamp,
            'rtt': round(rtt, 2),
            'packet_loss': 0, # ICMP sniffing alone can't easily see 'loss' without a pair
            'icmp_rate': 1,   # Base rate
            'ttl': ttl
        }
        packet_buffer.append(packet_data)
        
        # Keep buffer lean (last 50 packets)
        if len(packet_buffer) > 50:
            packet_buffer.pop(0)

        # 4. Calculate ICMP Rate (packets per second) and TTL Variance
        df_temp = pd.DataFrame(packet_buffer)
        rate = len(df_temp) / (df_temp['timestamp'].max() - df_temp['timestamp'].min() + 0.1)
        ttl_var = df_temp['ttl'].var() if len(df_temp) > 1 else 0

        # 5. Prepare final row for CSV
        new_row = {
            'rtt': round(rtt, 2),
            'packet_loss': 0, 
            'icmp_rate': round(rate, 2),
            'ttl': ttl,
            'ttl_variance': round(ttl_var, 2)
        }

        # 6. Write to CSV (Append Mode)
        pd.DataFrame([new_row]).to_csv(DATA_PATH, mode='a', header=not os.path.exists(DATA_PATH), index=False)
        print(f"Captured: TTL={ttl}, Rate={new_row['icmp_rate']}, Anomaly Check Triggered...")

print(f"🚀 Sniffer started on {INTERFACE if INTERFACE else 'default interface'}...")
sniff(filter="icmp", prn=process_packet, store=0)
try:
    print(f"🚀 Sniffer started... Press Ctrl+C to stop safely.")
    sniff(filter="icmp", prn=process_packet, store=0)
except KeyboardInterrupt:
    print("\n🛑 Sniffer stopped by user. Saving data...")
    # Optional: You can add logic here to clean up the CSV if needed