"""
core/network_watchdog.py
=========================
Watches for network/router changes every 10 seconds.
When gateway changes:
  1. Deactivates all old subnet devices from live view
  2. Seeds new router IP into active targets
  3. Starts new health session for new router
  4. Triggers immediate discovery scan
  5. Notifies all other engines via DB flag
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
from datetime import datetime
from utils.network import get_network_info, subnet_base
from db.database import get_connection
from config import DB_FILE

WATCH_INTERVAL = 10  # seconds between checks


def get_saved_gateway(db_file: str = DB_FILE) -> str:
    """Get the last known gateway from DB."""
    try:
        conn = get_connection(db_file)
        conn.execute("""CREATE TABLE IF NOT EXISTS network_state (
            key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)""")
        row = conn.execute(
            "SELECT value FROM network_state WHERE key='current_gateway'"
        ).fetchone()
        conn.close()
        return row["value"] if row else None
    except Exception:
        return None


def save_gateway(gateway: str, subnet: str, db_file: str = DB_FILE):
    """Save current gateway to DB."""
    conn = get_connection(db_file)
    conn.execute("""CREATE TABLE IF NOT EXISTS network_state (
        key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)""")
    conn.execute("""INSERT INTO network_state (key,value,updated_at)
        VALUES ('current_gateway',?,?)
        ON CONFLICT(key) DO UPDATE SET
        value=excluded.value, updated_at=excluded.updated_at""",
        (gateway, datetime.now().isoformat()))
    conn.execute("""INSERT INTO network_state (key,value,updated_at)
        VALUES ('current_subnet',?,?)
        ON CONFLICT(key) DO UPDATE SET
        value=excluded.value, updated_at=excluded.updated_at""",
        (subnet, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def on_network_change(old_gateway: str, new_gateway: str,
                      new_subnet: str, db_file: str = DB_FILE):
    """Handle router switch — reset live state for new network."""
    print(f"\n  [WATCHDOG] Router changed: {old_gateway} → {new_gateway}")
    print(f"  [WATCHDOG] New subnet: {new_subnet}\n")

    conn = get_connection(db_file)
    base = subnet_base(new_subnet) + "."

    # 1. Deactivate ALL old subnet devices from live view
    rows = conn.execute(
        "SELECT ip FROM active_targets WHERE active=1"
    ).fetchall()
    deactivated = 0
    for r in rows:
        ip = r["ip"]
        if not ip.startswith(base) and ip not in ("8.8.8.8", "1.1.1.1"):
            conn.execute(
                "UPDATE active_targets SET active=0 WHERE ip=?", (ip,))
            deactivated += 1

    print(f"  [WATCHDOG] Deactivated {deactivated} old devices")

    # 2. Seed new router as first target
    conn.execute("""INSERT INTO active_targets (ip,name,added_at,active)
        VALUES (?,?,?,1)
        ON CONFLICT(ip) DO UPDATE SET
        name=excluded.name, active=1""",
        (new_gateway, f"Router ({new_gateway})",
         datetime.now().isoformat()))

    # 3. Start new health session for new router
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS router_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gateway_ip TEXT NOT NULL, subnet TEXT NOT NULL,
            started_at TEXT NOT NULL, ended_at TEXT, label TEXT)""")
        # End any open sessions
        conn.execute("""UPDATE router_sessions SET ended_at=?
            WHERE ended_at IS NULL AND gateway_ip!=?""",
            (datetime.now().isoformat(), new_gateway))
        # Create new session if none exists for this gateway
        existing = conn.execute("""SELECT id FROM router_sessions
            WHERE gateway_ip=? AND ended_at IS NULL""",
            (new_gateway,)).fetchone()
        if not existing:
            conn.execute("""INSERT INTO router_sessions
                (gateway_ip,subnet,started_at,label) VALUES (?,?,?,?)""",
                (new_gateway, new_subnet, datetime.now().isoformat(),
                 f"Router {new_gateway}"))
            print(f"  [WATCHDOG] New health session started for {new_gateway}")
    except Exception as e:
        print(f"  [WATCHDOG] Session error: {e}")

    # 4. Set flag for discovery to do immediate scan
    conn.execute("""CREATE TABLE IF NOT EXISTS network_state (
        key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)""")
    conn.execute("""INSERT INTO network_state (key,value,updated_at)
        VALUES ('rescan_needed','1',?)
        ON CONFLICT(key) DO UPDATE SET
        value='1', updated_at=excluded.updated_at""",
        (datetime.now().isoformat(),))

    conn.commit()
    conn.close()

    # 5. Save new gateway
    save_gateway(new_gateway, new_subnet)
    print(f"  [WATCHDOG] Network switch complete. "
          f"Discovery will scan {new_subnet} shortly.\n")


def run():
    """Main watchdog loop."""
    print("  Network watchdog started.")
    print(f"  Checking for router changes every {WATCH_INTERVAL}s\n")

    # Initialize
    info = get_network_info()
    if info["connected"]:
        current_gateway = info["gateway"]
        current_subnet  = info["subnet"]
        save_gateway(current_gateway, current_subnet)
        print(f"  [WATCHDOG] Current network: {current_gateway} ({current_subnet})")
    else:
        current_gateway = None
        current_subnet  = None
        print("  [WATCHDOG] Not connected to any network")

    while True:
        time.sleep(WATCH_INTERVAL)
        try:
            info = get_network_info()
            if not info["connected"]:
                if current_gateway:
                    print("  [WATCHDOG] Network disconnected")
                    current_gateway = None
                continue

            new_gateway = info["gateway"]
            new_subnet  = info["subnet"]

            if new_gateway != current_gateway:
                on_network_change(
                    current_gateway or "none",
                    new_gateway, new_subnet)
                current_gateway = new_gateway
                current_subnet  = new_subnet

        except Exception as e:
            print(f"  [WATCHDOG ERROR] {e}")
    
if __name__ == "__main__":
    run()
