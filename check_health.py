"""Run this in your Network_Monitoring folder: python check_health.py"""
import sys, sqlite3
sys.path.insert(0, '.')
conn = sqlite3.connect('network_monitor.db')

tables = [t[0] for t in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("Tables:", tables)

if 'device_health_daily' in tables:
    count = conn.execute(
        "SELECT COUNT(*) as c FROM device_health_daily").fetchone()[0]
    print("Daily health rows:", count)
    if count > 0:
        rows = conn.execute(
            "SELECT * FROM device_health_daily LIMIT 3").fetchall()
        for r in rows:
            print("  Sample:", dict(r))
else:
    print("device_health_daily table NOT found - engine not running yet")

if 'device_degradation' in tables:
    count = conn.execute(
        "SELECT COUNT(*) as c FROM device_degradation").fetchone()[0]
    print("Degradation rows:", count)
else:
    print("device_degradation table NOT found")

conn.close()