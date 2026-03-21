"""
core/bandwidth.py
==================
Per-device bandwidth monitoring via packet capture (scapy + npcap).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


import sys, os, time, threading, collections
sys.stdout.reconfigure(encoding='utf-8')

from datetime import datetime
from config import DB_FILE, BW_SAMPLE_INTERVAL
from db.queries import save_bandwidth_sample, prune_bandwidth
from utils.network import detect_network, subnet_base
from utils.formatters import fmt_rate

# Per-device counters updated by sniffer thread
_counters: dict = {}
_lock = threading.Lock()


def _packet_callback(pkt):
    """Called for every captured packet."""
    try:
        from scapy.all import IP
        if IP not in pkt:
            return
        src, dst, size = pkt[IP].src, pkt[IP].dst, len(pkt)
        with _lock:
            for ip, direction in [(src, "out"), (dst, "in")]:
                if ip not in _counters:
                    _counters[ip] = {"bytes_in": 0, "bytes_out": 0,
                                     "pkts_in":  0, "pkts_out":  0}
                if direction == "out":
                    _counters[ip]["bytes_out"] += size
                    _counters[ip]["pkts_out"]  += 1
                else:
                    _counters[ip]["bytes_in"]  += size
                    _counters[ip]["pkts_in"]   += 1
    except Exception:
        pass


def _sniffer(subnet: str):
    from scapy.all import sniff, conf
    conf.verb = 0
    base   = subnet_base(subnet)
    filter = f"net {base}.0/24"
    print(f"  Packet capture started on {base}.0/24")
    sniff(filter=filter, prn=_packet_callback, store=False)


def _sampling_loop():
    """Snapshot counters every BW_SAMPLE_INTERVAL seconds and save to DB."""
    prune_ctr = 0
    while True:
        time.sleep(BW_SAMPLE_INTERVAL)
        with _lock:
            snapshot = {ip: dict(c) for ip, c in _counters.items()}
            for c in _counters.values():
                c["bytes_in"] = c["bytes_out"] = c["pkts_in"] = c["pkts_out"] = 0

        for ip, c in snapshot.items():
            if c["bytes_in"] > 0 or c["bytes_out"] > 0:
                save_bandwidth_sample(ip, c["bytes_in"], c["bytes_out"],
                                      c["pkts_in"], c["pkts_out"])
        prune_ctr += 1
        if prune_ctr % 720 == 0:
            prune_bandwidth()


def _display_loop(subnet: str):
    import sqlite3
    base = subnet_base(subnet)

    def get_names():
        try:
            import sqlite3
            conn = sqlite3.connect(DB_FILE)
            rows = conn.execute("SELECT ip, name FROM active_targets").fetchall()
            conn.close()
            return {r[0]: r[1] for r in rows}
        except Exception:
            return {}

    while True:
        time.sleep(2)
        os.system("cls" if os.name == "nt" else "clear")
        names = get_names()
        with _lock:
            local = sorted(
                [(ip, dict(c)) for ip, c in _counters.items() if ip.startswith(base)],
                key=lambda x: x[1]["bytes_in"] + x[1]["bytes_out"], reverse=True)

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"  Bandwidth Monitor  -  {ts}")
        print(f"  Subnet: {base}.0/24 | Dashboard: http://localhost:5000/bandwidth\n")
        print(f"  {'DEVICE':<22} {'IP':<18} {'DOWN':>12} {'UP':>12}")
        print(f"  {'-'*22} {'-'*18} {'-'*12} {'-'*12}")
        if not local:
            print(f"  Waiting for traffic...")
        else:
            for ip, c in local[:20]:
                name = names.get(ip, ip)[:20]
                print(f"  {name:<22} {ip:<18} "
                      f"{fmt_rate(c['bytes_in']/2):>12} "
                      f"{fmt_rate(c['bytes_out']/2):>12}")
        print(f"\n  Ctrl+C to stop.")


def run():
    """Start bandwidth monitoring."""
    from db.database import init_schema
    init_schema()

    subnet, _ = detect_network()

    try:
        t_sniff   = threading.Thread(target=_sniffer,       args=(subnet,), daemon=True)
        t_sample  = threading.Thread(target=_sampling_loop, daemon=True)
        t_sniff.start()
        t_sample.start()
        _display_loop(subnet)
    except KeyboardInterrupt:
        print("\n  Bandwidth monitor stopped.")


if __name__ == "__main__":
    run()
