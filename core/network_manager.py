"""
core/network_manager.py
========================
Central network switch detector.

Monitors the current gateway/subnet and coordinates
all modules when you switch routers:
  - Deactivates ALL devices from old subnet
  - Triggers fresh discovery on new subnet
  - Starts new health session
  - Notifies all other modules

This makes the project fully portable across any router.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import threading
from datetime import datetime
from db.database import get_connection
from utils.network import detect_network, subnet_base
from config import DB_FILE

# ─────────────────────────────────────────
# State
# ─────────────────────────────────────────
_current_gateway = None
_current_subnet  = None
_switch_callbacks = []   # functions called on network switch
_lock = threading.Lock()


# ─────────────────────────────────────────
# Register callbacks
# ─────────────────────────────────────────

def on_network_switch(callback):
    """Register a function to call when network changes.
    callback(old_gateway, new_gateway, new_subnet)
    """
    _switch_callbacks.append(callback)


# ─────────────────────────────────────────
# Core switch handler
# ─────────────────────────────────────────

def _handle_switch(old_gateway: str, new_gateway: str, new_subnet: str):
    """Called when a router switch is detected."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n  [NETWORK] Router switch detected at {ts}")
    print(f"  [NETWORK] {old_gateway or 'none'} → {new_gateway}")
    print(f"  [NETWORK] New subnet: {new_subnet}\n")

    # Step 1: Deactivate ALL devices not on new subnet
    _deactivate_old_subnet(new_subnet)

    # Step 2: Notify all registered modules
    for cb in _switch_callbacks:
        try:
            cb(old_gateway, new_gateway, new_subnet)
        except Exception as e:
            print(f"  [NETWORK] Callback error: {e}")


def _deactivate_old_subnet(new_subnet: str, db_file: str = DB_FILE):
    """
    Mark all devices NOT on the new subnet as inactive.
    This cleans the dashboard when you switch routers.
    """
    base = subnet_base(new_subnet)
    conn = get_connection(db_file)
    try:
        # Count how many will be deactivated
        old_count = conn.execute("""
            SELECT COUNT(*) as cnt FROM active_targets
            WHERE active=1 AND ip NOT LIKE ?
              AND ip NOT IN ('8.8.8.8', '1.1.1.1', '8.8.4.4', '1.0.0.1')
        """, (f"{base}.%",)).fetchone()["cnt"]

        if old_count > 0:
            # Deactivate old subnet devices
            conn.execute("""
                UPDATE active_targets SET active=0
                WHERE ip NOT LIKE ?
                  AND ip NOT IN ('8.8.8.8','1.1.1.1','8.8.4.4','1.0.0.1')
            """, (f"{base}.%",))
            conn.commit()
            print(f"  [NETWORK] Deactivated {old_count} devices "
                  f"from old subnet")

        # Also ensure external targets are always active
        for ext_ip, ext_name in [
            ("8.8.8.8",  "Google DNS"),
            ("1.1.1.1",  "Cloudflare"),
        ]:
            conn.execute("""
                INSERT INTO active_targets (ip, name, added_at, active)
                VALUES (?,?,?,1)
                ON CONFLICT(ip) DO UPDATE SET active=1
            """, (ext_ip, ext_name, datetime.now().isoformat()))
        conn.commit()

    except Exception as e:
        print(f"  [NETWORK] Deactivation error: {e}")
    finally:
        conn.close()


# ─────────────────────────────────────────
# Network state API
# ─────────────────────────────────────────

def get_current_network() -> dict:
    """Get current network info."""
    with _lock:
        return {
            "gateway": _current_gateway,
            "subnet":  _current_subnet,
            "base":    subnet_base(_current_subnet) if _current_subnet else None,
        }


def save_network_state(gateway: str, subnet: str, db_file: str = DB_FILE):
    """Persist current network state to DB."""
    conn = get_connection(db_file)
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS network_state (
            key   TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT
        )""")
        for k, v in [("gateway", gateway), ("subnet", subnet)]:
            conn.execute("""INSERT INTO network_state (key, value, updated_at)
                VALUES (?,?,?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    updated_at=excluded.updated_at""",
                (k, v, datetime.now().isoformat()))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def load_network_state(db_file: str = DB_FILE) -> dict:
    """Load last known network state from DB."""
    conn = get_connection(db_file)
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS network_state (
            key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)""")
        rows = conn.execute(
            "SELECT key, value FROM network_state"
        ).fetchall()
        conn.close()
        return {r["key"]: r["value"] for r in rows}
    except Exception:
        conn.close()
        return {}


# ─────────────────────────────────────────
# Monitor loop
# ─────────────────────────────────────────

def run():
    """
    Continuously monitors the current network.
    Detects router switches and coordinates all modules.
    """
    global _current_gateway, _current_subnet

    print("  Network manager started.")
    print("  Monitoring for router switches every 15s.\n")

    # Load last known state
    last_state = load_network_state()
    _current_gateway = last_state.get("gateway")
    _current_subnet  = last_state.get("subnet")

    if _current_gateway:
        print(f"  [NETWORK] Last known: {_current_gateway} ({_current_subnet})")

    while True:
        try:
            subnet, gateway = detect_network()

            with _lock:
                if gateway != _current_gateway:
                    old_gw           = _current_gateway
                    _current_gateway = gateway
                    _current_subnet  = subnet
                    save_network_state(gateway, subnet)
                    _handle_switch(old_gw, gateway, subnet)
                elif _current_subnet != subnet:
                    # Same gateway but subnet changed (rare but possible)
                    _current_subnet = subnet
                    save_network_state(gateway, subnet)

        except Exception as e:
            print(f"  [NETWORK ERROR] {e}")

        time.sleep(15)   # check every 15 seconds


if __name__ == "__main__":
    run()
