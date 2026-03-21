"""
core/probe.py
==============
ICMP probe engine — Phase 1 improvements:
  - 5 packets per probe (was 3) for better accuracy
  - Median RTT as primary value (resistant to outliers)
  - Jitter = standard deviation of RTT samples
  - Smart packet loss — distinguishes sleep from real failure
  - Consecutive loss tracking per device
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import math
import threading
from datetime import datetime, timedelta
from typing import Dict, Optional

from icmplib import ping, SocketPermissionError
from colorama import init, Fore, Style

from config import (DB_FILE, PROBE_INTERVAL, PROBE_TIMEOUT)
from core.state import HostState, update_host_state
from db.queries import load_active_targets, save_probe_result, prune_probe_results
from db.database import get_connection

init(autoreset=True)

# ─────────────────────────────────────────
# Adaptive packet configuration
# ─────────────────────────────────────────
# Packet counts per device state — adapts automatically
PROBE_COUNT_STABLE   = 3    # stable UP device — save bandwidth
PROBE_COUNT_DEFAULT  = 5    # new/unknown device — baseline
PROBE_COUNT_UNSTABLE = 10   # recent packet loss — more accuracy
PROBE_COUNT_DEGRADED = 15   # degraded/just recovered — maximum accuracy

DOWN_THRESHOLD   = 3      # consecutive failures → DOWN
UP_THRESHOLD     = 2      # consecutive successes → UP

def _adaptive_packet_count(state) -> int:
    """
    Choose packet count based on device state.
    Stable devices use fewer packets — unstable get more scrutiny.
    """
    if state is None:
        return PROBE_COUNT_DEFAULT

    status = getattr(state, 'status', 'UNKNOWN')
    consec_fail = getattr(state, 'consecutive_fail', 0)
    consec_ok   = getattr(state, 'consecutive_ok',   0)
    last_loss   = getattr(state, 'last_loss', None)

    # Maximum accuracy — device is degraded or just recovered
    if status == "DEGRADED":
        return PROBE_COUNT_DEGRADED
    if status == "UP" and consec_ok <= 3:
        return PROBE_COUNT_DEGRADED  # just recovered — verify it's truly stable

    # High accuracy — recent packet loss detected
    if last_loss is not None and last_loss > 0.1:
        return PROBE_COUNT_UNSTABLE
    if consec_fail > 0:
        return PROBE_COUNT_UNSTABLE

    # Minimum packets — device is stable and consistently UP
    if status == "UP" and consec_ok >= 10 and (last_loss or 0) == 0:
        return PROBE_COUNT_STABLE

    # Default for unknown/new devices
    return PROBE_COUNT_DEFAULT


# Sleep detection — how many consecutive losses before we
# consider it a real failure vs idle device
SLEEP_THRESHOLD  = 6      # 6 × 10s = 1 minute of no reply = likely sleeping
SLEEP_HOURS      = {      # hours when devices commonly sleep (11pm - 7am)
    "night_start": 23,
    "night_end":   7,
}

# RTT thresholds for quality classification
RTT_EXCELLENT_MS = 10
RTT_GOOD_MS      = 50
RTT_FAIR_MS      = 100
RTT_POOR_MS      = 200

STATUS_COLOR = {
    "UP":      Fore.GREEN,
    "DOWN":    Fore.RED,
    "DEGRADED":Fore.YELLOW,
    "UNKNOWN": Fore.WHITE,
    "SLEEP":   Fore.CYAN,
}

# ─────────────────────────────────────────
# RTT statistics
# ─────────────────────────────────────────

def _median(values: list) -> float:
    """Median is more resistant to outliers than mean."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid-1] + s[mid]) / 2


def _std_deviation(values: list, mean: float) -> float:
    """Standard deviation = jitter measurement."""
    if len(values) < 2:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def _rtt_quality(rtt_ms: float) -> str:
    """Classify RTT quality."""
    if rtt_ms <= RTT_EXCELLENT_MS: return "excellent"
    if rtt_ms <= RTT_GOOD_MS:      return "good"
    if rtt_ms <= RTT_FAIR_MS:      return "fair"
    if rtt_ms <= RTT_POOR_MS:      return "poor"
    return "bad"


# ─────────────────────────────────────────
# Sleep detection
# ─────────────────────────────────────────

def _is_night_hours() -> bool:
    """Return True if current time is within typical sleep hours."""
    hour = datetime.now().hour
    start = SLEEP_HOURS["night_start"]
    end   = SLEEP_HOURS["night_end"]
    if start > end:  # spans midnight
        return hour >= start or hour < end
    return start <= hour < end


def _is_likely_sleeping(host: str, consecutive_fail: int) -> bool:
    """
    Decide if a device is sleeping vs actually down.
    A device is likely sleeping if:
    - It has been unreachable for less than SLEEP_THRESHOLD cycles
    - It's currently night hours
    - It has responded successfully before (not a new unknown device)
    """
    if consecutive_fail < SLEEP_THRESHOLD:
        return False
    if not _is_night_hours():
        return False
    # Check if device has a history of responding
    try:
        conn = get_connection(DB_FILE)
        row  = conn.execute("""
            SELECT COUNT(*) as cnt FROM probe_results
            WHERE host=? AND is_alive=1
        """, (host,)).fetchone()
        conn.close()
        return (row["cnt"] if row else 0) > 0
    except Exception:
        return False


# ─────────────────────────────────────────
# Core probe function
# ─────────────────────────────────────────

def probe_host(host: str, name: str,
               packet_count: int = PROBE_COUNT_DEFAULT) -> dict:
    """
    Send ICMP probes and return detailed metrics.
    Packet count adapts to device state for optimal accuracy.
    """
    timestamp = datetime.now()
    try:
        result = ping(
            address=host,
            count=packet_count,
            timeout=PROBE_TIMEOUT,
            privileged=True
        )

        if result.is_alive:
            rtts    = result.rtts          # list of individual RTT values
            avg_rtt = result.avg_rtt
            min_rtt = result.min_rtt
            max_rtt = result.max_rtt
            med_rtt = _median(rtts)        # median — our primary value
            jitter  = _std_deviation(rtts, avg_rtt)  # std deviation = jitter
            quality = _rtt_quality(med_rtt)

            return {
                "host":        host,
                "name":        name,
                "timestamp":   timestamp,
                "is_alive":    True,
                "rtt_avg_ms":  round(avg_rtt, 2),
                "rtt_min_ms":  round(min_rtt, 2),
                "rtt_max_ms":  round(max_rtt, 2),
                "rtt_med_ms":  round(med_rtt, 2),
                "jitter_ms":   round(jitter,  2),
                "packet_loss": result.packet_loss,
                "quality":     quality,
                "packets_sent": packet_count,
            }
        else:
            return {
                "host":        host,
                "name":        name,
                "timestamp":   timestamp,
                "is_alive":    False,
                "rtt_avg_ms":  None,
                "rtt_min_ms":  None,
                "rtt_max_ms":  None,
                "rtt_med_ms":  None,
                "jitter_ms":   None,
                "packet_loss": result.packet_loss,
                "quality":     "no-reply",
                "packets_sent": packet_count,
            }

    except SocketPermissionError:
        print(f"\n{Fore.RED}[ERROR] Run as Administrator.{Style.RESET_ALL}\n")
        raise
    except Exception:
        return {
            "host":        host,
            "name":        name,
            "timestamp":   timestamp,
            "is_alive":    False,
            "rtt_avg_ms":  None,
            "rtt_min_ms":  None,
            "rtt_max_ms":  None,
            "rtt_med_ms":  None,
            "jitter_ms":   None,
            "packet_loss": 1.0,
            "quality":     "error",
            "packets_sent": packet_count,
        }


# ─────────────────────────────────────────
# Probe all targets in parallel
# ─────────────────────────────────────────

def probe_all(targets: list,
              states: dict = None) -> list:
    """Probe all targets in parallel with adaptive packet counts."""
    results, lock = [], threading.Lock()

    def worker(target):
        host  = target["host"]
        state = states.get(host) if states else None
        count = _adaptive_packet_count(state)
        r     = probe_host(target["host"], target["name"], count)
        with lock:
            results.append(r)

    threads = [
        threading.Thread(target=worker, args=(t,), daemon=True)
        for t in targets
    ]
    for t in threads: t.start()
    for t in threads: t.join()
    return results


# ─────────────────────────────────────────
# Save improved probe result to DB
# ─────────────────────────────────────────

def save_improved_result(r: dict):
    """
    Save probe result with jitter and median RTT.
    Extends the standard save_probe_result with extra fields.
    """
    try:
        conn = get_connection(DB_FILE)
        # Check if jitter columns exist, add if not
        cols = [c[1] for c in conn.execute(
            "PRAGMA table_info(probe_results)").fetchall()]
        if "jitter_ms" not in cols:
            conn.execute("ALTER TABLE probe_results ADD COLUMN jitter_ms REAL")
        if "rtt_med_ms" not in cols:
            conn.execute("ALTER TABLE probe_results ADD COLUMN rtt_med_ms REAL")
        if "quality" not in cols:
            conn.execute("ALTER TABLE probe_results ADD COLUMN quality TEXT")

        conn.execute("""INSERT INTO probe_results
            (host, name, timestamp, is_alive,
             rtt_avg_ms, rtt_min_ms, rtt_max_ms, rtt_med_ms,
             jitter_ms, packet_loss, quality)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (r["host"], r["name"], r["timestamp"].isoformat(),
             int(r["is_alive"]),
             r["rtt_avg_ms"], r["rtt_min_ms"], r["rtt_max_ms"],
             r["rtt_med_ms"], r["jitter_ms"],
             r["packet_loss"], r["quality"]))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB ERROR] {e}")
        # Fallback to standard save
        save_probe_result(
            r["host"], r["name"], r["is_alive"],
            r["rtt_avg_ms"], r["rtt_min_ms"], r["rtt_max_ms"],
            r["packet_loss"])


# ─────────────────────────────────────────
# Display
# ─────────────────────────────────────────

def _quality_color(quality: str) -> str:
    return {
        "excellent": Fore.GREEN,
        "good":      Fore.GREEN,
        "fair":      Fore.YELLOW,
        "poor":      Fore.RED,
        "bad":       Fore.RED,
        "no-reply":  Fore.WHITE,
        "error":     Fore.RED,
    }.get(quality, Fore.WHITE)


def display_status(states: Dict[str, HostState], targets: list):
    import os as _os
    _os.system("cls" if _os.name == "nt" else "clear")
    ts      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    up      = sum(1 for s in states.values() if s.status == "UP")
    down    = sum(1 for s in states.values() if s.status == "DOWN")
    unknown = sum(1 for s in states.values() if s.status == "UNKNOWN")

    print(f"  ICMP Network Monitor  -  {ts}")
    print(f"  {len(targets)} targets | "
          f"{Fore.GREEN}{up} UP{Style.RESET_ALL} | "
          f"{Fore.RED}{down} DOWN{Style.RESET_ALL} | "
          f"{Fore.WHITE}{unknown} UNKNOWN{Style.RESET_ALL}")
    print()
    print(f"  {'NAME':<20} {'HOST':<18} {'STATUS':<10} "
          f"{'RTT(med)':>9} {'JITTER':>8} {'LOSS':>6}  {'QUALITY':<10} {'PKTS'}")
    print(f"  {'-'*20} {'-'*18} {'-'*10} "
          f"{'-'*9} {'-'*8} {'-'*6}  {'-'*10} {'-'*4}")

    for host, state in sorted(states.items(), key=lambda x: x[1].name):
        color   = STATUS_COLOR.get(state.status, Fore.WHITE)
        rtt     = f"{state.last_rtt:>8.1f}" if state.last_rtt else "       -"
        jitter  = f"{state.last_jitter:>7.1f}" if hasattr(state, 'last_jitter') and state.last_jitter else "      -"
        loss    = f"{state.last_loss*100:>5.0f}%" if hasattr(state, 'last_loss') and state.last_loss is not None else "     -"
        quality = state.last_quality if hasattr(state, 'last_quality') and state.last_quality else "-"
        qcolor  = _quality_color(quality)

        pkts = getattr(state, 'last_packets', '?')
        print(f"  {state.name:<20} {state.host:<18} "
              f"{color}{state.status:<10}{Style.RESET_ALL} "
              f"{rtt}  {jitter}  {loss}  "
              f"{qcolor}{quality:<10}{Style.RESET_ALL} {pkts}")

    print(f"\n  Dashboard: http://localhost:5000")


# ─────────────────────────────────────────
# Extended HostState with new fields
# ─────────────────────────────────────────

class ImprovedHostState(HostState):
    def __init__(self, name: str, host: str):
        super().__init__(name=name, host=host)
        self.last_jitter:  Optional[float] = None
        self.last_loss:    Optional[float] = None
        self.last_quality: Optional[str]   = None
        self.last_packets: Optional[int]   = None
        self.is_sleeping:  bool            = False


def update_improved_state(state: ImprovedHostState, result: dict):
    """Update state with smart sleep detection."""
    # Update extra fields
    state.last_jitter  = result.get("jitter_ms")
    state.last_loss    = result.get("packet_loss")
    state.last_quality = result.get("quality")
    state.last_packets = result.get("packets_sent")

    # Smart sleep detection — override DOWN with SLEEP
    if not result["is_alive"]:
        sleeping = _is_likely_sleeping(result["host"], state.consecutive_fail + 1)
        if sleeping:
            state.is_sleeping = True
            state.consecutive_fail += 1
            state.consecutive_ok   = 0
            # Don't mark as DOWN if sleeping
            if state.status not in ("DOWN",):
                state.status = "DEGRADED"
            return

    state.is_sleeping = False
    # Standard state update
    update_host_state(state, result["is_alive"],
                      result["packet_loss"], result["rtt_avg_ms"])


# ─────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────

# External targets — always monitored regardless of network
EXTERNAL_TARGETS = [
    {"name": "Google DNS", "host": "8.8.8.8"},
    {"name": "Cloudflare", "host": "1.1.1.1"},
]


def _seed_dynamic_targets():
    """
    Seed the DB with the current router IP and external targets.
    Called at startup so probe works even before discovery runs.
    """
    from utils.network import get_network_info
    from db.queries import upsert_target
    info = get_network_info()
    if info["connected"] and info["gateway"]:
        upsert_target(info["gateway"], "Router")
        print(f"  [PROBE] Auto-detected gateway: {info['gateway']}")
    for t in EXTERNAL_TARGETS:
        upsert_target(t["host"], t["name"])


def run():
    from db.database import init_schema
    init_schema()
    _seed_dynamic_targets()

    targets = load_active_targets()
    states: Dict[str, ImprovedHostState] = {
        t["host"]: ImprovedHostState(name=t["name"], host=t["host"])
        for t in targets
    }

    print(f"  Probe engine v2 started — adaptive packet mode.")
    print(f"  {len(targets)} targets | adaptive: "
          f"{PROBE_COUNT_STABLE}/{PROBE_COUNT_DEFAULT}/"
          f"{PROBE_COUNT_UNSTABLE}/{PROBE_COUNT_DEGRADED} pkts "
          f"(stable/default/unstable/degraded) | jitter + median RTT enabled")
    time.sleep(1)

    cycle = 0
    while True:
        # Reload targets every 60s
        if cycle % 6 == 0:
            targets = load_active_targets()
            for t in targets:
                if t["host"] not in states:
                    states[t["host"]] = ImprovedHostState(
                        name=t["name"], host=t["host"])

        results = probe_all(targets, states)

        for r in results:
            if r["host"] not in states:
                states[r["host"]] = ImprovedHostState(
                    name=r["name"], host=r["host"])
            save_improved_result(r)
            update_improved_state(states[r["host"]], r)

        display_status(states, targets)
        cycle += 1

        if cycle % 60 == 0:
            prune_probe_results()

        time.sleep(PROBE_INTERVAL)


if __name__ == "__main__":
    run()
