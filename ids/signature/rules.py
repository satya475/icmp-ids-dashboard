"""
ids/signature/rules.py
=======================
Attack rules for Signature IDS.
Each rule checks one specific attack pattern.
"""

from datetime import datetime, timedelta
from collections import defaultdict

# Cooldown tracker for signature rules
from datetime import datetime, timedelta
sig_last_alert  = {}
SIG_COOLDOWN_SEC = 30


def _signature_cooldown(src_ip, rule_name):
    """Return True if we should SKIP this alert (cooldown active)."""
    key  = f"{src_ip}:{rule_name}"
    now  = datetime.now()
    last = sig_last_alert.get(key)
    if last and now - last < timedelta(seconds=SIG_COOLDOWN_SEC):
        return True
    sig_last_alert[key] = now
    return False

# ─────────────────────────────────────────
# Traffic tracking (memory)
# ─────────────────────────────────────────

# Tracks how many times each IP sent a packet
# Format: { "192.168.1.1": [timestamp1, timestamp2, ...] }
icmp_tracker  = defaultdict(list)
port_tracker  = defaultdict(list)
syn_tracker   = defaultdict(list)

# ─────────────────────────────────────────
# Thresholds
# ─────────────────────────────────────────

ICMP_FLOOD_LIMIT   = 20   # pings per second = flood
PORT_SCAN_LIMIT    = 20   # different ports in 1 second = scan
SYN_FLOOD_LIMIT    = 20   # SYN packets per second = SYN flood
LARGE_PACKET_SIZE  = 1500 # bytes, above this = suspicious
WINDOW_SECONDS     = 1    # time window for counting

# ─────────────────────────────────────────
# Whitelist — never alert these IPs
# ─────────────────────────────────────────

WHITELISTED_IPS = {
    "192.168.201.1",    # your router
    "192.168.201.163",  # your PC
    "8.8.8.8",          # Google DNS
    "8.8.4.4",          # Google DNS 2
    "1.1.1.1",          # Cloudflare DNS
    "192.168.201.108",  # known device on WiFi
}

# Dangerous ports to watch
DANGEROUS_PORTS = [
    4444,   # Metasploit default
    1337,   # Common hacker port
    31337,  # Elite backdoor
    9001,   # Tor
    6667,   # IRC (used by botnets)
]


# ─────────────────────────────────────────
# Helper
# ─────────────────────────────────────────

def _clean_old(tracker, ip, window=WINDOW_SECONDS):
    """Remove timestamps older than the time window."""
    cutoff = datetime.now() - timedelta(seconds=window)
    tracker[ip] = [t for t in tracker[ip] if t > cutoff]


def _make_alert(rule_name, severity, src_ip, dst_ip, message, features):
    """Create a standard alert dictionary."""
    return {
        "timestamp" : datetime.now().isoformat(),
        "rule"      : rule_name,
        "severity"  : severity,
        "src_ip"    : src_ip,
        "dst_ip"    : dst_ip,
        "message"   : message,
        "features"  : features,
        "type"      : "signature",
    }


# ─────────────────────────────────────────
# Rule 1: ICMP Flood Detection
# ─────────────────────────────────────────

def rule_icmp_flood(features):
    """
    Detects ICMP flood attack.
    Too many pings from same IP in 1 second = flood.
    """
    # Only check ICMP packets (protocol 1)
    if features.get("protocol") != 1:
        return None

    src_ip = features["src_ip"]

    if src_ip in WHITELISTED_IPS:
        return None

    # Track this packet
    icmp_tracker[src_ip].append(datetime.now())
    _clean_old(icmp_tracker, src_ip)

    count = len(icmp_tracker[src_ip])

    if count >= ICMP_FLOOD_LIMIT:
        if _signature_cooldown(src_ip, "ICMP_FLOOD"):
            return None
        return _make_alert(
            rule_name = "ICMP_FLOOD",
            severity  = "high",
            src_ip    = src_ip,
            dst_ip    = features["dst_ip"],
            message   = (f"ICMP Flood detected from {src_ip}! "
                        f"{count} pings/sec (limit: {ICMP_FLOOD_LIMIT})"),
            features  = features,
        )
    return None


# ─────────────────────────────────────────
# Rule 2: Port Scan Detection
# ─────────────────────────────────────────

def rule_port_scan(features):
    """
    Detects port scanning.
    One IP hitting many different ports quickly = scan.
    """
    # Only check TCP/UDP
    if features.get("protocol") not in [6, 17]:
        return None

    src_ip   = features["src_ip"]
    dst_port = features.get("dst_port")

    if src_ip in WHITELISTED_IPS:
        return None

    if not dst_port:
        return None

    # Track unique ports this IP has hit
    key = f"{src_ip}_ports"
    port_tracker[key].append((datetime.now(), dst_port))

    # Clean old entries
    cutoff = datetime.now() - timedelta(seconds=WINDOW_SECONDS)
    port_tracker[key] = [
        (t, p) for t, p in port_tracker[key] if t > cutoff
    ]

    # Count unique ports
    unique_ports = set(p for t, p in port_tracker[key])

    if len(unique_ports) >= PORT_SCAN_LIMIT:
        if _signature_cooldown(src_ip, "PORT_SCAN"):
            return None
        return _make_alert(
            rule_name = "PORT_SCAN",
            severity  = "high",
            src_ip    = src_ip,
            dst_ip    = features["dst_ip"],
            message   = (f"Port scan detected from {src_ip}! "
                        f"Hitting {len(unique_ports)} ports/sec "
                        f"(limit: {PORT_SCAN_LIMIT})"),
            features  = features,
        )
    return None


# ─────────────────────────────────────────
# Rule 3: SYN Flood Detection
# ─────────────────────────────────────────

def rule_syn_flood(features):
    """
    Detects SYN flood attack.
    Too many SYN packets from same IP = flood.
    SYN packets are used to start TCP connections.
    """
    # Only TCP
    if features.get("protocol") != 6:
        return None

    # Only SYN flag (S flag)
    if features.get("flags") != "S":
        return None

    src_ip = features["src_ip"]

    syn_tracker[src_ip].append(datetime.now())
    _clean_old(syn_tracker, src_ip)

    count = len(syn_tracker[src_ip])

    # Skip whitelisted IPs
    if src_ip in WHITELISTED_IPS:
        return None

    if count >= SYN_FLOOD_LIMIT:
        if _signature_cooldown(src_ip, "SYN_FLOOD"):
            return None
        return _make_alert(
            rule_name = "SYN_FLOOD",
            severity  = "critical",
            src_ip    = src_ip,
            dst_ip    = features["dst_ip"],
            message   = (f"SYN Flood detected from {src_ip}! "
                        f"{count} SYN packets/sec "
                        f"(limit: {SYN_FLOOD_LIMIT})"),
            features  = features,
        )
    return None


# ─────────────────────────────────────────
# Rule 4: Large Packet Detection
# ─────────────────────────────────────────

def rule_large_packet(features):
    """
    Detects abnormally large packets.
    Could indicate data exfiltration or buffer overflow attempt.
    """
    size = features.get("packet_size", 0)

    if size > LARGE_PACKET_SIZE:
        if _signature_cooldown(features["src_ip"], "LARGE_PACKET"):
            return None  # skip alert, cooldown active
        return _make_alert(
            rule_name = "LARGE_PACKET",
            severity  = "medium",
            src_ip    = features["src_ip"],
            dst_ip    = features["dst_ip"],
            message   = (f"Large packet detected from {features['src_ip']}! "
                        f"Size: {size} bytes "
                        f"(limit: {LARGE_PACKET_SIZE})"),
            features  = features,
        )
    return None


# ─────────────────────────────────────────
# Rule 5: Dangerous Port Detection
# ─────────────────────────────────────────

def rule_dangerous_port(features):
    """
    Detects connections to known dangerous ports.
    These ports are commonly used by malware and hackers.
    """
    dst_port = features.get("dst_port")
    src_port = features.get("src_port")

    suspicious_port = None

    if dst_port in DANGEROUS_PORTS:
        suspicious_port = dst_port
    elif src_port in DANGEROUS_PORTS:
        suspicious_port = src_port

    if suspicious_port:
        if _signature_cooldown(src_ip, "DANGEROUS_PORT"):
            return None
        return _make_alert(
            rule_name = "DANGEROUS_PORT",
            severity  = "critical",
            src_ip    = features["src_ip"],
            dst_ip    = features["dst_ip"],
            message   = (f"Dangerous port detected! "
                        f"{features['src_ip']} → port {suspicious_port} "
                        f"(known malicious port)"),
            features  = features,
        )
    return None


# ─────────────────────────────────────────
# All rules in one list
# ─────────────────────────────────────────

ALL_RULES = [
    rule_icmp_flood,
    rule_port_scan,
    rule_syn_flood,
    rule_large_packet,
    rule_dangerous_port,
]