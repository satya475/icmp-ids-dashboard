"""
core/state.py
==============
Host state machine with hysteresis.
Calls alerts.py when devices go DOWN or RTT is high.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from config import DOWN_THRESHOLD, UP_THRESHOLD
from db.queries import save_state_change


@dataclass
class HostState:
    name:             str
    host:             str
    status:           str = "UNKNOWN"
    consecutive_fail: int = 0
    consecutive_ok:   int = 0
    last_seen:        Optional[datetime] = None
    last_rtt:         Optional[float]   = None


def update_host_state(state: HostState, is_alive: bool,
                      packet_loss: float, rtt: Optional[float]) -> bool:
    """
    Update state machine. Saves DB change and fires alerts on transition.
    Returns True if status changed.
    """
    old_status = state.status

    if is_alive and packet_loss < 0.5:
        state.consecutive_fail = 0
        state.consecutive_ok  += 1
        state.last_seen = datetime.now()
        state.last_rtt  = rtt
        if state.consecutive_ok >= UP_THRESHOLD:
            state.status = "UP"
    else:
        state.consecutive_ok   = 0
        state.consecutive_fail += 1
        if state.consecutive_fail >= DOWN_THRESHOLD:
            state.status = "DOWN"
        elif state.consecutive_fail >= 1:
            state.status = "DEGRADED"

    if state.status != old_status:
        save_state_change(state.host, state.name, old_status, state.status)
        _dispatch(state, old_status)
        return True

    # Check RTT alert even if status didn't change
    if state.status == "UP" and rtt is not None:
        try:
            from core.alerts import check_rtt_alert
            check_rtt_alert(state.name, state.host, rtt)
        except Exception:
            pass

    return False


def _dispatch(state: HostState, old_status: str):
    """Print console alert and fire email alerts."""
    ts = datetime.now().strftime("%H:%M:%S")

    if state.status == "DOWN":
        print(f"[ALERT] {state.name} ({state.host}) is DOWN [{ts}]")
        try:
            from core.alerts import alert_device_down
            alert_device_down(state.name, state.host)
        except Exception as e:
            print(f"[ALERT ERROR] {e}")

    elif state.status == "DEGRADED":
        print(f"[WARN]  {state.name} ({state.host}) is DEGRADED [{ts}]")

    elif state.status == "UP" and old_status in ("DOWN", "DEGRADED"):
        print(f"[OK]    {state.name} ({state.host}) is back UP [{ts}]")
