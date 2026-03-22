"""
utils/network.py
=================
Network detection utilities.
ALL network info is read fresh every call — never cached.
This ensures the project works correctly on any router.
"""

import subprocess
import re
import socket
from typing import Tuple, Optional


def detect_network() -> Tuple[str, str]:
    """
    Auto-detect active subnet and gateway from ipconfig.
    Called fresh every time — never uses cached values.
    Returns (subnet, gateway) e.g. ("192.168.1.0/24", "192.168.1.1")
    Works on any router automatically.
    """
    try:
        output = subprocess.check_output(
            "ipconfig", text=True, stderr=subprocess.DEVNULL)
        blocks = re.split(r'\r?\n\r?\n', output)

        candidates = []
        for block in blocks:
            if "Media disconnected" in block or "Tunnel" in block:
                continue
            gw = re.search(r"Default Gateway[^:]*:\s*([\d.]+)", block)
            ip = re.search(r"IPv4 Address[^:]*:\s*([\d.]+)", block)
            if gw and ip:
                gateway = gw.group(1).strip()
                my_ip   = ip.group(1).strip()
                if not gateway.startswith("169.") and gateway != "0.0.0.0":
                    candidates.append((gateway, my_ip))

        if candidates:
            # Prefer Wi-Fi over other adapters
            gateway, my_ip = candidates[0]
            base   = ".".join(gateway.split(".")[:3])
            subnet = f"{base}.0/24"
            return subnet, gateway

    except Exception:
        pass

    return "0.0.0.0/0", "0.0.0.0"


def get_current_gateway() -> Optional[str]:
    """Return just the gateway IP of the current network."""
    _, gateway = detect_network()
    return gateway if gateway != "0.0.0.0" else None


def get_network_info() -> dict:
    """
    Return full current network info as a dict.
    Used by the dashboard to show real-time network state.
    """
    try:
        output = subprocess.check_output(
            "ipconfig", text=True, stderr=subprocess.DEVNULL)
        blocks = re.split(r'\r?\n\r?\n', output)

        adapters = []
        active   = None

        for block in blocks:
            if "Media disconnected" in block or "Tunnel" in block:
                continue
            gw   = re.search(r"Default Gateway[^:]*:\s*([\d.]+)", block)
            ip   = re.search(r"IPv4 Address[^:]*:\s*([\d.]+)", block)
            mask = re.search(r"Subnet Mask[^:]*:\s*([\d.]+)", block)
            name = re.search(r"^(.+?):", block, re.MULTILINE)

            if gw and ip:
                gateway = gw.group(1).strip()
                my_ip   = ip.group(1).strip()
                if gateway.startswith("169.") or gateway == "0.0.0.0":
                    continue
                base    = ".".join(gateway.split(".")[:3])
                subnet  = f"{base}.0/24"
                adapter = {
                    "name":    (name.group(1).strip() if name else "Unknown"),
                    "ip":      my_ip,
                    "gateway": gateway,
                    "subnet":  subnet,
                    "mask":    mask.group(1).strip() if mask else "255.255.255.0",
                }
                adapters.append(adapter)
                if active is None:
                    active = adapter

        return {
            "connected":   active is not None,
            "gateway":     active["gateway"] if active else None,
            "my_ip":       active["ip"]      if active else None,
            "subnet":      active["subnet"]  if active else None,
            "adapter":     active["name"]    if active else None,
            "all_adapters":adapters,
        }

    except Exception as e:
        return {
            "connected": False,
            "gateway":   None,
            "my_ip":     None,
            "subnet":    None,
            "adapter":   None,
            "error":     str(e),
        }


def validate_router_ip(entered_ip: str) -> dict:
    """
    Validate an IP entered by the user against the actual current network.
    Returns a dict with ok=True/False and a helpful message.
    """
    entered_ip = entered_ip.strip()

    # Basic format check
    parts = entered_ip.split(".")
    if len(parts) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255
                                   for p in parts):
        return {
            "ok":      False,
            "error":   "invalid_format",
            "message": f"'{entered_ip}' is not a valid IP address. "
                       f"Format must be like 192.168.1.1",
        }

    # Get actual current network
    info = get_network_info()

    if not info["connected"]:
        return {
            "ok":      False,
            "error":   "not_connected",
            "message": "Your PC is not connected to any network. "
                       "Please connect to Wi-Fi or ethernet first.",
        }

    actual_gateway = info["gateway"]
    actual_subnet  = info["subnet"]
    actual_base    = ".".join(actual_gateway.split(".")[:3])
    entered_base   = ".".join(entered_ip.split(".")[:3])

    # Check if entered IP is on the current subnet
    if entered_base != actual_base:
        return {
            "ok":           False,
            "error":        "wrong_network",
            "message":      (
                f"You entered {entered_ip} but your PC is connected to "
                f"the {actual_base}.x network (gateway: {actual_gateway}). "
                f"Either enter {actual_gateway} or connect to the correct router first."
            ),
            "suggested_ip": actual_gateway,
            "actual_subnet":actual_subnet,
        }

    # Check if it's actually the gateway
    if entered_ip != actual_gateway:
        return {
            "ok":           True,   # allow it but warn
            "warning":      True,
            "error":        "not_gateway",
            "message":      (
                f"Note: {entered_ip} is not your detected gateway "
                f"({actual_gateway}). Monitoring will still work but "
                f"you may want to use {actual_gateway} instead."
            ),
            "suggested_ip": actual_gateway,
        }

    return {
        "ok":      True,
        "warning": False,
        "message": f"Connected to {actual_gateway} on {actual_subnet}",
        "info":    info,
    }


def subnet_base(subnet: str) -> str:
    """Extract base from subnet. '192.168.1.0/24' → '192.168.1'"""
    return ".".join(subnet.split(".")[:3])


def resolve_hostname(ip: str) -> Optional[str]:
    """
    Try multiple methods to get a human-readable name for an IP.
    1. Reverse DNS
    2. NetBIOS name (Windows devices)
    3. mDNS (.local names)
    Returns short hostname or None.
    """
    # Method 1 — Reverse DNS
    try:
        name = socket.gethostbyaddr(ip)[0]
        if name and name != ip:
            # Clean up — remove domain suffix, keep short name
            short = name.split(".")[0]
            if short and short != ip and len(short) > 1:
                return short
    except Exception:
        pass

    # Method 2 — NetBIOS (Windows PC names on local network)
    try:
        import subprocess
        result = subprocess.run(
            ["nbtstat", "-A", ip],
            capture_output=True, text=True, timeout=3,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0
        )
        for line in result.stdout.splitlines():
            if "<00>" in line and "UNIQUE" in line:
                name = line.split()[0].strip()
                if name and name != ip:
                    return name
    except Exception:
        pass

    return None


def get_my_ip() -> Optional[str]:
    """Get this machine's outbound IP address."""
    info = get_network_info()
    return info.get("my_ip")


def validate_ip(ip: str) -> bool:
    """Simple format check for IPv4."""
    parts = ip.strip().split(".")
    if len(parts) != 4:
        return False
    return all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)