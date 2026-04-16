"""
agent.py — PingGuard Building Agent
=====================================
Run this on ONE PC per building/location.
It monitors the local network and reports to central server.

Usage:
  python agent.py --server https://xyz.trycloudflare.com
                  --location "Building B"
                  --building "Head Office"

Requirements:
  pip install icmplib requests colorama
  Run as Administrator (for ICMP)
"""

import sys, os, time, argparse, socket
import threading, subprocess, re, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import requests
except ImportError:
    print("Installing requests...")
    os.system("pip install requests")
    import requests

try:
    from icmplib import ping
except ImportError:
    print("Installing icmplib...")
    os.system("pip install icmplib")
    from icmplib import ping

from datetime import datetime

# ─────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────
REPORT_INTERVAL  = 30    # send data to server every 30s
PROBE_INTERVAL   = 10    # probe devices every 10s
PROBE_COUNT      = 5     # ICMP packets per device
AGENT_VERSION    = "1.0"

# ─────────────────────────────────────────
# Shared state
# ─────────────────────────────────────────
_probe_results  = {}   # {ip: result_dict}
_bw_counters    = {}   # {ip: {bytes_in, bytes_out}}
_lock           = threading.Lock()


# ─────────────────────────────────────────
# Network detection
# ─────────────────────────────────────────

def detect_local_network():
    """Auto-detect subnet, gateway, my IP."""
    try:
        output = subprocess.check_output(
            "ipconfig", text=True,
            stderr=subprocess.DEVNULL)
        blocks = re.split(r'\r?\n\r?\n', output)

        candidates = []
        for block in blocks:
            if "Media disconnected" in block: continue
            if "Tunnel" in block: continue
            gw  = re.search(
                r"Default Gateway[^:]*:\s*([\d.]+)", block)
            ip  = re.search(
                r"IPv4 Address[^:]*:\s*([\d.]+)", block)
            if gw and ip:
                gateway = gw.group(1).strip()
                my_ip   = ip.group(1).strip()
                if not gateway.startswith("169.") \
                   and gateway != "0.0.0.0":
                    candidates.append((gateway, my_ip))

        if candidates:
            gateway, my_ip = candidates[0]
            base   = ".".join(gateway.split(".")[:3])
            subnet = f"{base}.0/24"
            return gateway, my_ip, subnet, base

    except Exception:
        pass
    return None, None, None, None


# ─────────────────────────────────────────
# Device discovery
# ─────────────────────────────────────────

def discover_devices(subnet_base: str) -> set:
    """Find all devices on local subnet via ARP."""
    devices = set()
    try:
        # Ping sweep to populate ARP cache
        procs = []
        for i in range(1, 255):
            ip = f"{subnet_base}.{i}"
            p  = subprocess.Popen(
                ["ping", "-n", "1", "-w", "200", ip],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
            procs.append(p)
            if len(procs) >= 30:
                for proc in procs: proc.wait()
                procs = []
        for proc in procs: proc.wait()

        # Read ARP cache
        output  = subprocess.check_output(
            ["arp", "-a"], text=True,
            stderr=subprocess.DEVNULL)
        pattern = re.compile(
            r"(\d+\.\d+\.\d+\.\d+)\s+"
            r"([0-9a-fA-F]{2}[-:][0-9a-fA-F]{2})")
        for line in output.splitlines():
            m = pattern.search(line)
            if m:
                ip = m.group(1)
                if ip.startswith(subnet_base) \
                   and not ip.endswith(".255"):
                    devices.add(ip)
    except Exception as e:
        print(f"  [AGENT] Discovery error: {e}")

    return devices


# ─────────────────────────────────────────
# ICMP probing
# ─────────────────────────────────────────

def probe_device(ip: str, name: str,
                 is_router: bool = False) -> dict:
    """Probe a single device with ICMP."""
    try:
        count  = 10 if is_router else PROBE_COUNT
        result = ping(ip, count=count,
                     timeout=2, privileged=True)

        if result.is_alive:
            rtts = result.rtts
            # Trim outliers for accuracy
            if len(rtts) >= 5:
                s    = sorted(rtts)
                trim = max(1, len(s) // 10)
                rtts = s[trim:-trim]

            avg = sum(rtts)/len(rtts)
            med = sorted(rtts)[len(rtts)//2]

            # Quality classification
            if   med < 10:  quality = "excellent"
            elif med < 50:  quality = "good"
            elif med < 100: quality = "fair"
            elif med < 200: quality = "poor"
            else:           quality = "bad"

            return {
                "ip":         ip,
                "name":       name,
                "is_alive":   True,
                "rtt_avg_ms": round(avg, 2),
                "rtt_med_ms": round(med, 2),
                "packet_loss":round(result.packet_loss, 3),
                "quality":    quality,
                "is_router":  is_router,
                "timestamp":  datetime.now().isoformat(),
            }
    except Exception:
        pass

    return {
        "ip":         ip,
        "name":       name,
        "is_alive":   False,
        "rtt_avg_ms": None,
        "rtt_med_ms": None,
        "packet_loss":1.0,
        "quality":    "no-reply",
        "is_router":  is_router,
        "timestamp":  datetime.now().isoformat(),
    }


def probe_all_devices(devices: set,
                      gateway: str):
    """Probe all devices in parallel."""
    results = {}
    lock    = threading.Lock()

    def worker(ip):
        is_router = (ip == gateway)
        name = f"Router ({ip})" if is_router else ip
        r    = probe_device(ip, name, is_router)
        with lock:
            results[ip] = r

    threads = [
        threading.Thread(
            target=worker, args=(ip,), daemon=True)
        for ip in devices
    ]
    for t in threads: t.start()
    for t in threads: t.join(timeout=15)
    return results


# ─────────────────────────────────────────
# Bandwidth monitoring (basic)
# ─────────────────────────────────────────

def start_bandwidth_capture(subnet_base: str):
    """
    Capture bandwidth using scapy if available.
    Gracefully skips if scapy not installed.
    """
    try:
        from scapy.all import sniff, IP, conf
        conf.verb = 0
        bw_lock = threading.Lock()

        def packet_callback(pkt):
            try:
                if IP not in pkt:
                    return
                src  = pkt[IP].src
                dst  = pkt[IP].dst
                size = len(pkt)
                with bw_lock:
                    for ip, direction in [
                            (src,"out"),(dst,"in")]:
                        if ip.startswith(subnet_base):
                            if ip not in _bw_counters:
                                _bw_counters[ip] = {
                                    "bytes_in": 0,
                                    "bytes_out": 0}
                            if direction == "out":
                                _bw_counters[ip]["bytes_out"] += size
                            else:
                                _bw_counters[ip]["bytes_in"]  += size
            except Exception:
                pass

        filter_str = f"net {subnet_base}.0/24"
        t = threading.Thread(
            target=sniff,
            kwargs={"filter": filter_str,
                    "prn": packet_callback,
                    "store": False},
            daemon=True)
        t.start()
        print("  [AGENT] Bandwidth capture: active")
    except ImportError:
        print("  [AGENT] Bandwidth capture: skipped "
              "(scapy not installed)")
    except Exception as e:
        print(f"  [AGENT] Bandwidth capture: skipped ({e})")


# ─────────────────────────────────────────
# Report to central server
# ─────────────────────────────────────────

def report_to_server(server_url: str,
                     agent_id: str,
                     location: str,
                     building: str,
                     gateway: str,
                     subnet: str,
                     results: dict):
    """Send all collected data to central PingGuard server."""

    # Collect bandwidth snapshot and reset counters
    with _lock:
        bw_snapshot = dict(_bw_counters)
        _bw_counters.clear()

    bw_data = [
        {"ip": ip,
         "bytes_in":  v["bytes_in"],
         "bytes_out": v["bytes_out"]}
        for ip, v in bw_snapshot.items()
        if v["bytes_in"] > 0 or v["bytes_out"] > 0
    ]

    payload = {
        "agent_id":  agent_id,
        "location":  location,
        "building":  building,
        "subnet":    subnet,
        "router_ip": gateway,
        "version":   AGENT_VERSION,
        "timestamp": datetime.now().isoformat(),
        "results":   list(results.values()),
        "bandwidth": bw_data,
    }

    try:
        resp = requests.post(
            f"{server_url}/api/agent/report",
            json=payload, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("ok"):
                up   = sum(1 for r in results.values()
                          if r.get("is_alive"))
                down = len(results) - up
                router = next(
                    (r for r in results.values()
                     if r.get("is_router")), None)
                r_rtt = (f"{router['rtt_avg_ms']:.1f}ms"
                         if router and router.get("rtt_avg_ms")
                         else "DOWN")
                print(
                    f"  [{datetime.now().strftime('%H:%M:%S')}] "
                    f"Reported {len(results)} devices — "
                    f"UP:{up} DOWN:{down} "
                    f"Router:{r_rtt}")
            else:
                print(f"  [AGENT] Server error: "
                      f"{data.get('error')}")
        else:
            print(f"  [AGENT] HTTP {resp.status_code}")
    except requests.exceptions.ConnectionError:
        print(f"  [AGENT] Cannot reach server — "
              f"will retry in {REPORT_INTERVAL}s")
    except Exception as e:
        print(f"  [AGENT] Report error: {e}")


# ─────────────────────────────────────────
# Main
# ─────────────────────────────────────────

def run():
    parser = argparse.ArgumentParser(
        description="PingGuard Building Agent")
    parser.add_argument(
        "--server", required=True,
        help="Central server URL e.g. "
             "https://xyz.trycloudflare.com")
    parser.add_argument(
        "--location", required=True,
        help="Location name e.g. 'Building B - Floor 2'")
    parser.add_argument(
        "--building", default=None,
        help="Building name (optional) e.g. 'Head Office'")
    args = parser.parse_args()

    building = args.building or args.location
    agent_id = f"{socket.gethostname()}-{args.location.replace(' ','_')}"

    # Detect network
    gateway, my_ip, subnet, base = detect_local_network()
    if not gateway:
        print("  [AGENT] ERROR: Cannot detect network.")
        print("  Connect to your building's WiFi/LAN first.")
        sys.exit(1)

    print(f"\n  PingGuard Agent v{AGENT_VERSION}")
    print(f"  {'─'*40}")
    print(f"  Agent ID  : {agent_id}")
    print(f"  Location  : {args.location}")
    print(f"  Building  : {building}")
    print(f"  My IP     : {my_ip}")
    print(f"  Gateway   : {gateway}")
    print(f"  Subnet    : {subnet}")
    print(f"  Server    : {args.server}")
    print(f"  Reporting : every {REPORT_INTERVAL}s")
    print(f"  {'─'*40}\n")

    # Start bandwidth capture
    start_bandwidth_capture(base)

    # Initial discovery
    print("  Discovering devices on local network...")
    known_devices = discover_devices(base)
    known_devices.add(gateway)   # always include router
    print(f"  Found {len(known_devices)} devices\n")

    # Rediscover every 5 minutes
    last_discovery = time.time()

    probe_results = {}
    last_report   = 0

    while True:
        try:
            # Rediscover every 5 minutes
            if time.time() - last_discovery > 300:
                new = discover_devices(base)
                new.add(gateway)
                added = new - known_devices
                if added:
                    print(f"  [AGENT] {len(added)} "
                          f"new devices found")
                known_devices = new
                last_discovery = time.time()

            # Probe all devices
            probe_results = probe_all_devices(
                known_devices, gateway)

            # Report to server every REPORT_INTERVAL
            if time.time() - last_report >= REPORT_INTERVAL:
                report_to_server(
                    args.server, agent_id,
                    args.location, building,
                    gateway, subnet, probe_results)
                last_report = time.time()

        except KeyboardInterrupt:
            print("\n  Agent stopped.")
            break
        except Exception as e:
            print(f"  [AGENT ERROR] {e}")

        time.sleep(PROBE_INTERVAL)


if __name__ == "__main__":
    run()