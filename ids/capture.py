"""
ids/capture.py
===============
Captures ALL live network packets using Scapy.
Extracts basic info from each packet and passes
it to the detection engine.
"""

from scapy.all import sniff, IP, TCP, UDP, ICMP
from datetime import datetime


def extract_features(packet):
    """
    Pull useful information out of a single packet.
    Returns a dictionary of features.
    """
    if not packet.haslayer(IP):
        return None

    features = {
        "timestamp"   : datetime.now().isoformat(),
        "src_ip"      : packet[IP].src,
        "dst_ip"      : packet[IP].dst,
        "protocol"    : packet[IP].proto,
        "packet_size" : len(packet),
        "ttl"         : packet[IP].ttl,
        "src_port"    : None,
        "dst_port"    : None,
        "flags"       : None,
    }

    # TCP packet
    if packet.haslayer(TCP):
        features["src_port"] = packet[TCP].sport
        features["dst_port"] = packet[TCP].dport
        features["flags"]    = str(packet[TCP].flags)

    # UDP packet
    elif packet.haslayer(UDP):
        features["src_port"] = packet[UDP].sport
        features["dst_port"] = packet[UDP].dport

    # ICMP packet
    elif packet.haslayer(ICMP):
        features["icmp_type"] = packet[ICMP].type
        features["icmp_code"] = packet[ICMP].code

    return features


def start_capture(callback, filter="ip", count=0):
    """
    Start capturing live packets.
    Every packet gets sent to callback function.
    count = 0 means capture forever
    """
    print("[IDS] Packet capture started...")
    print("[IDS] Watching all network traffic...\n")

    sniff(
        filter=filter,
        prn=lambda pkt: _process(pkt, callback),
        store=False,
        count=count
    )


def _process(packet, callback):
    """Extract features and send to callback."""
    features = extract_features(packet)
    if features:
        callback(features)