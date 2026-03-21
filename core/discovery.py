"""
core/discovery.py
==================
Multi-method network discovery:
  1. ARP broadcast (scapy) — bypasses firewalls
  2. TCP port scan          — catches ICMP-blocking devices
  3. Ping sweep + ARP cache — fallback
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


import sys, os, time, subprocess, re, socket, threading
sys.stdout.reconfigure(encoding='utf-8')

from datetime import datetime
from colorama import init, Fore, Style

from config import (DB_FILE, SCAN_INTERVAL, ARP_TIMEOUT,
                    TCP_PORTS, TCP_TIMEOUT, PING_TIMEOUT_MS, PING_BATCH_SIZE)
from db.database import get_connection
from db.queries import (get_known_ips, upsert_device, upsert_target,
                        deactivate_subnet_targets)
from utils.network import detect_network, resolve_hostname, subnet_base
from utils.formatters import lookup_vendor

init(autoreset=True)


# ─────────────────────────────────────────
# Method 1: ARP broadcast
# ─────────────────────────────────────────

def arp_broadcast(subnet: str) -> dict:
    results = {}
    try:
        from scapy.all import ARP, Ether, srp, conf
        conf.verb = 0
        base = subnet_base(subnet)
        print(f"  {Fore.CYAN}[Method 1] ARP broadcast...{Style.RESET_ALL}")
        pkt = Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=f"{base}.1/24")
        answered, _ = srp(pkt, timeout=ARP_TIMEOUT)
        for _, r in answered:
            results[r.psrc] = r.hwsrc.lower()
        print(f"  {Fore.GREEN}  -> {len(results)} via ARP broadcast{Style.RESET_ALL}")
    except ImportError:
        print(f"  {Fore.YELLOW}  -> scapy not installed{Style.RESET_ALL}")
    except Exception as e:
        print(f"  {Fore.YELLOW}  -> ARP broadcast failed: {e}{Style.RESET_ALL}")
    return results


# ─────────────────────────────────────────
# Method 2: TCP port scan
# ─────────────────────────────────────────

def _tcp_scan_ip(ip: str, results: dict, lock: threading.Lock):
    for port in TCP_PORTS:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(TCP_TIMEOUT)
            if s.connect_ex((ip, port)) == 0:
                with lock:
                    if ip not in results:
                        results[ip] = f"tcp:{port}"
                s.close()
                return
            s.close()
        except Exception:
            pass


def tcp_scan(subnet: str, skip: set) -> dict:
    base, results, lock, threads = subnet_base(subnet), {}, threading.Lock(), []
    print(f"  {Fore.CYAN}[Method 2] TCP port scan...{Style.RESET_ALL}")
    for i in range(1, 255):
        ip = f"{base}.{i}"
        if ip in skip:
            continue
        t = threading.Thread(target=_tcp_scan_ip, args=(ip, results, lock), daemon=True)
        threads.append(t)
        t.start()
        if sum(1 for x in threads if x.is_alive()) >= 50:
            time.sleep(0.1)
    for t in threads:
        t.join(timeout=TCP_TIMEOUT + 1)
    print(f"  {Fore.GREEN}  -> {len(results)} via TCP scan{Style.RESET_ALL}")
    return results


# ─────────────────────────────────────────
# Method 3: Ping sweep + ARP cache
# ─────────────────────────────────────────

def ping_arp_cache(subnet: str, skip: set) -> dict:
    base, results = subnet_base(subnet), {}
    print(f"  {Fore.CYAN}[Method 3] Ping sweep + ARP cache...{Style.RESET_ALL}")
    procs = []
    for i in range(1, 255):
        ip = f"{base}.{i}"
        if ip in skip:
            continue
        p = subprocess.Popen(
            ["ping", "-n", "1", "-w", str(PING_TIMEOUT_MS), ip],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs.append(p)
        if len(procs) >= PING_BATCH_SIZE:
            for proc in procs: proc.wait()
            procs = []
    for proc in procs: proc.wait()
    try:
        output  = subprocess.check_output(["arp", "-a"], text=True)
        pattern = re.compile(
            r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+"
            r"([0-9a-fA-F]{2}[-:][0-9a-fA-F]{2}[-:][0-9a-fA-F]{2}"
            r"[-:][0-9a-fA-F]{2}[-:][0-9a-fA-F]{2}[-:][0-9a-fA-F]{2})")
        for line in output.splitlines():
            m = pattern.search(line)
            if m:
                ip  = m.group(1)
                mac = m.group(2).replace("-", ":").lower()
                if ip.startswith(base) and not ip.endswith(".255") and ip not in skip:
                    results[ip] = mac
    except Exception as e:
        print(f"  {Fore.YELLOW}  -> ARP cache failed: {e}{Style.RESET_ALL}")
    print(f"  {Fore.GREEN}  -> {len(results)} via ping/ARP cache{Style.RESET_ALL}")
    return results


# ─────────────────────────────────────────
# Main discovery scan
# ─────────────────────────────────────────

def scan(subnet: str) -> list:
    """Run full discovery scan. Returns list of found device dicts."""
    known     = get_known_ips()
    all_found = {}
    base      = subnet_base(subnet)

    for ip, mac in arp_broadcast(subnet).items():
        all_found[ip] = {"mac": mac, "method": "arp-broadcast"}
    for ip, method in tcp_scan(subnet, set(all_found)).items():
        if ip not in all_found:
            all_found[ip] = {"mac": "unknown", "method": method}
    for ip, mac in ping_arp_cache(subnet, set(all_found)).items():
        if ip not in all_found:
            all_found[ip] = {"mac": mac, "method": "arp-cache"}

    print(f"\n  {Fore.CYAN}Found {len(all_found)} devices. Resolving...{Style.RESET_ALL}\n")

    devices = []
    for ip, info in sorted(all_found.items(),
                           key=lambda x: list(map(int, x[0].split(".")))):
        vendor   = lookup_vendor(info["mac"])
        hostname = resolve_hostname(ip)
        is_new   = ip not in known
        name     = vendor if vendor != "Unknown" else (hostname or ip)

        upsert_device(ip, info["mac"], vendor, hostname, info["method"])
        upsert_target(ip, name)

        if is_new:
            print(f"  {Fore.GREEN}[NEW]{Style.RESET_ALL} {ip:<18} {info['mac']:<20} {vendor}")

        devices.append({"ip": ip, "mac": info["mac"], "vendor": vendor,
                        "hostname": hostname, "method": info["method"], "is_new": is_new})

    deactivate_subnet_targets(base + ".", set(all_found.keys()))
    return devices


def _check_rescan_flag(db_file=None) -> bool:
    """Check if watchdog has requested an immediate rescan."""
    try:
        from config import DB_FILE as default_db
        from db.database import get_connection
        db = db_file or default_db
        conn = get_connection(db)
        row  = conn.execute(
            "SELECT value FROM network_state WHERE key='rescan_needed'"
        ).fetchone()
        if row and row["value"] == "1":
            # Clear the flag
            conn.execute("""UPDATE network_state SET value='0'
                WHERE key='rescan_needed'""")
            conn.commit()
            conn.close()
            return True
        conn.close()
        return False
    except Exception:
        return False


def run():
    """Main discovery loop — respects network watchdog rescan requests."""
    from db.database import init_schema
    init_schema()
    print(f"  Discovery engine started.")

    last_gateway = None

    while True:
        from utils.network import detect_network
        subnet, gateway = detect_network()

        # Check if watchdog requested immediate rescan
        rescan = _check_rescan_flag()
        if rescan:
            print(f"\n  [DISCOVERY] Router change detected — scanning {subnet} immediately")

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n  -- Scan  {ts}  [{subnet}] --\n")
        devices = scan(subnet)
        print(f"\n  {len(devices)} devices found on {subnet}.")
        last_gateway = gateway

        if rescan:
            print(f"  Next scan in {SCAN_INTERVAL}s\n")
            time.sleep(SCAN_INTERVAL)
        else:
            print(f"  Next scan in {SCAN_INTERVAL}s\n")
            # Check rescan flag every 5s while waiting
            for _ in range(SCAN_INTERVAL // 5):
                time.sleep(5)
                if _check_rescan_flag():
                    print("  [DISCOVERY] Rescan requested — scanning now")
                    break


if __name__ == "__main__":
    run()
