"""
utils/formatters.py
====================
Formatting helpers for display and API responses.
"""
import os
import csv


_vendor_cache = {}
_oui_loaded = False


def _load_oui_database():
    """Load IEEE OUI database from local file."""
    global _oui_loaded
    if _oui_loaded:
        return

    oui_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "oui.csv"
    )

    if not os.path.exists(oui_path):
        _oui_loaded = True
        return  # file not downloaded yet — fall back to local table

    try:
        with open(oui_path, encoding="utf-8", errors="ignore") as f:
            reader = csv.reader(f)
            next(reader)  # skip header
            for row in reader:
                if len(row) >= 3:
                    prefix = row[1].strip().lower()          # e.g. "A8:86:DD"
                    vendor = row[2].strip()                   # e.g. "Apple, Inc."
                    _vendor_cache[prefix.replace("-", ":")] = vendor
        print(f"  [VENDOR] Loaded {len(_vendor_cache)} OUI entries")
    except Exception as e:
        print(f"  [VENDOR] OUI load error: {e}")

    _oui_loaded = True

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

    # Priority 1 — your custom table (fastest, most accurate for your devices)
    local = VENDOR_PREFIXES.get(m[:8])
    if local:
        return local

    # Priority 2 — full IEEE OUI database
    _load_oui_database()
    vendor = _vendor_cache.get(m[:8])
    if vendor:
        return vendor

    return "Unknown"