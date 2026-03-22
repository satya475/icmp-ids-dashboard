"""
utils/formatters.py
====================
Formatting helpers for display and API responses.
"""


def fmt_bytes(b: float) -> str:
    """Format bytes as human-readable size string."""
    if b >= 1_000_000_000:
        return f"{b/1_000_000_000:.2f} GB"
    if b >= 1_000_000:
        return f"{b/1_000_000:.1f} MB"
    if b >= 1_000:
        return f"{b/1_000:.1f} KB"
    return f"{int(b)} B"


def fmt_rate(bps: float) -> str:
    """Format bytes-per-second as human-readable rate string."""
    if bps >= 1_000_000:
        return f"{bps/1_000_000:.1f} MB/s"
    if bps >= 1_000:
        return f"{bps/1_000:.1f} KB/s"
    return f"{int(bps)} B/s"


def lookup_vendor(mac: str) -> str:
    """Look up device vendor from MAC address prefix."""
    from config import VENDOR_PREFIXES
    if not mac or mac == "unknown":
        return "Unknown"
    m = mac.lower().replace("-", ":").replace(".", ":")
    return (VENDOR_PREFIXES.get(m[:8]) or
            VENDOR_PREFIXES.get(m[:5]) or
            "Unknown")