"""
Run this in your Network_Monitoring folder: python check_ml.py
Checks if ML models are training with existing data.
"""
import sys, os
sys.path.insert(0, '.')

from db.database import get_connection

conn = get_connection('network_monitor.db')

# Check probe data available
probe = conn.execute("""
    SELECT COUNT(*) as cnt,
           AVG(rtt_avg_ms) as avg_rtt,
           AVG(jitter_ms) as avg_jitter,
           AVG(packet_loss) as avg_loss
    FROM probe_results
    WHERE is_alive=1 AND rtt_avg_ms IS NOT NULL
""").fetchone()

print(f"Probe samples available: {probe['cnt']}")
print(f"Avg RTT: {probe['avg_rtt']:.1f}ms" if probe['avg_rtt'] else "Avg RTT: None")
print(f"Avg Jitter: {probe['avg_jitter']:.1f}ms" if probe['avg_jitter'] else "Avg Jitter: None")
print(f"Avg Loss: {probe['avg_loss']*100:.1f}%" if probe['avg_loss'] else "Avg Loss: 0%")

# Check if models directory exists
models_dir = os.path.join('.', 'models')
print(f"\nModels directory exists: {os.path.exists(models_dir)}")
if os.path.exists(models_dir):
    files = os.listdir(models_dir)
    print(f"Model files: {files if files else 'empty'}")

# Check classifier data
try:
    cls = conn.execute("""
        SELECT COUNT(*) as cnt FROM device_classifications
        WHERE confidence >= 70 AND device_type != 'unknown'
    """).fetchone()
    print(f"\nLabeled devices for Random Forest: {cls['cnt']}")
except:
    print("\nNo device_classifications table yet")

conn.close()
print("\nDone.")