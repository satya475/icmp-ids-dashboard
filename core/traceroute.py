"""
core/traceroute.py
==================
TTL-based traceroute using Windows tracert command.
Parses output to extract hop IPs and RTTs.
Runs every 60s and stores results in DB.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
import subprocess
import time
from datetime import datetime

from config import DB_FILE
from db.database import get_connection
from db.queries import load_active_targets
from utils.network import detect_network

# ─────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────
MAX_HOPS       = 15
TRACE_INTERVAL = 60    # seconds between full runs
TRACE_TIMEOUT  = 30    # seconds max per traceroute

# ─────────────────────────────────────────
# Database
# ─────────────────────────────────────────

def init_hop_table(db_file: str = DB_FILE):
    conn = get_connection(db_file)
    conn.execute("""CREATE TABLE IF NOT EXISTS hop_routes (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        target_ip  TEXT NOT NULL,
        hop_number INTEGER NOT NULL,
        hop_ip     TEXT,
        hop_name   TEXT,
        rtt_ms     REAL,
        timestamp  TEXT NOT NULL
    )""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_hop_target
        ON hop_routes(target_ip, timestamp)""")
    conn.commit()
    conn.close()


def save_hops(target_ip: str, hops: list, db_file: str = DB_FILE):
    conn = get_connection(db_file)
    ts   = datetime.now().isoformat()
    conn.execute("DELETE FROM hop_routes WHERE target_ip=?", (target_ip,))
    for hop in hops:
        conn.execute("""INSERT INTO hop_routes
            (target_ip, hop_number, hop_ip, hop_name, rtt_ms, timestamp)
            VALUES (?,?,?,?,?,?)""",
            (target_ip, hop["number"], hop.get("ip"),
             hop.get("name"), hop.get("rtt"), ts))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────
# Parse Windows tracert output
# ─────────────────────────────────────────

def _parse_tracert(output: str) -> list:
    """
    Parse Windows tracert output into list of hop dicts.

    Example tracert line:
      1    <1 ms    <1 ms    <1 ms  192.168.201.1
      2     *        *        *     Request timed out.
      3    12 ms    11 ms    10 ms  8.8.8.8
    """
    hops   = []
    # Match lines like:  1    1 ms    1 ms    1 ms  192.168.x.x
    # or:                1    <1 ms   <1 ms   <1 ms  hostname [192.168.x.x]
    pattern = re.compile(
        r'^\s*(\d+)'                          # hop number
        r'(?:\s+[<\d]+\s*ms){1,3}'           # 1-3 RTT values
        r'\s+([\w\.\-]+)'                     # hostname or IP
        r'(?:\s+\[([\d\.]+)\])?'              # optional [IP] if hostname shown
    )
    timeout_pattern = re.compile(r'^\s*(\d+)\s+\*\s+\*\s+\*')

    for line in output.splitlines():
        # Check for timeout hop
        tm = timeout_pattern.match(line)
        if tm:
            hops.append({
                "number": int(tm.group(1)),
                "ip":     None,
                "name":   None,
                "rtt":    None,
            })
            continue

        m = pattern.match(line)
        if not m:
            continue

        num      = int(m.group(1))
        host     = m.group(2)
        bracket  = m.group(3)

        # If bracket IP exists, host is a hostname
        if bracket:
            ip   = bracket
            name = host
        else:
            # Check if host looks like an IP
            if re.match(r'^\d+\.\d+\.\d+\.\d+$', host):
                ip   = host
                name = None
            else:
                ip   = None
                name = host

        # Extract first numeric RTT
        rtt_match = re.search(r'(\d+)\s*ms', line)
        rtt = float(rtt_match.group(1)) if rtt_match else None

        hops.append({
            "number": num,
            "ip":     ip,
            "name":   name,
            "rtt":    rtt,
        })

    return hops


# ─────────────────────────────────────────
# Run tracert for one target
# ─────────────────────────────────────────

def traceroute(target_ip: str) -> list:
    """Run Windows tracert and return parsed hops list."""
    try:
        result = subprocess.run(
            ["tracert", "-d", "-h", str(MAX_HOPS), "-w", "1000", target_ip],
            capture_output=True,
            text=True,
            timeout=TRACE_TIMEOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        )
        hops = _parse_tracert(result.stdout)
        return hops
    except subprocess.TimeoutExpired:
        print(f"  [TRACEROUTE] Timeout for {target_ip}")
        return []
    except Exception as e:
        print(f"  [TRACEROUTE] Error for {target_ip}: {e}")
        return []


# ─────────────────────────────────────────
# Trace all active targets
# ─────────────────────────────────────────

def trace_all():
    targets        = load_active_targets()
    subnet, _      = detect_network()
    base           = ".".join(subnet.split(".")[:3])
    local_targets  = [t for t in targets if t["host"].startswith(base)]
    ext_targets    = [t for t in targets if not t["host"].startswith(base)]

    # Trace local subnet devices + a couple of external ones
    to_trace = local_targets + ext_targets[:2]

    print(f"  [TRACEROUTE] Tracing {len(to_trace)} targets on {subnet}")

    for target in to_trace:
        ip   = target["host"]
        name = target["name"]
        try:
            hops     = traceroute(ip)
            valid    = [h for h in hops if h["ip"]]
            save_hops(ip, hops)
            path_str = " -> ".join(h["ip"] for h in valid)
            print(f"  [TRACEROUTE] {name:<20} {len(hops)} hops: {path_str or 'no reply'}")
        except Exception as e:
            print(f"  [TRACEROUTE] {name} failed: {e}")


# ─────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────

def run():
    init_hop_table()
    print(f"  Traceroute engine started (using tracert).")
    print(f"  Interval: {TRACE_INTERVAL}s\n")

    while True:
        try:
            trace_all()
        except Exception as e:
            print(f"  [TRACEROUTE ERROR] {e}")
        time.sleep(TRACE_INTERVAL)


if __name__ == "__main__":
    run()
