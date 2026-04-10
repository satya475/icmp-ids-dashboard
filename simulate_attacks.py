"""
simulate_attacks.py
====================
Simulates all 5 attack types to test our Hybrid IDS.
Run this while test_ids.py is running in another terminal!
"""

from scapy.all import send, IP, TCP, ICMP, Raw
import time


def banner(title):
    print("\n" + "=" * 50)
    print(f"  SIMULATING: {title}")
    print("=" * 50)
    time.sleep(1)


# ─────────────────────────────────────────
# Attack 1 — ICMP Flood
# ─────────────────────────────────────────

def simulate_icmp_flood():
    banner("ICMP FLOOD ATTACK")
    print("Sending 50 ICMP packets rapidly to 8.8.8.8...")
    print("Expected: 🔴 [HIGH] ICMP_FLOOD\n")

    send(
        IP(dst="8.8.8.8") / ICMP(),
        count   = 50,
        inter   = 0.01,
        verbose = False
    )
    print("✅ ICMP flood sent!")
    time.sleep(5)


# ─────────────────────────────────────────
# Attack 2 — Port Scan
# ─────────────────────────────────────────

def simulate_port_scan():
    banner("PORT SCAN ATTACK")
    print("Scanning 20 different ports on 8.8.8.8...")
    print("Expected: 🔴 [HIGH] PORT_SCAN\n")

    ports = [
        21, 22, 23, 25, 80, 443, 445,
        3306, 3389, 8080, 8443, 9200,
        27017, 1433, 5432, 6667, 1337,
        4444, 31337, 9001
    ]

    for p in ports:
        send(
            IP(dst="8.8.8.8") / TCP(dport=p, flags="S"),
            verbose = False
        )
        print(f"  Scanned port {p}")
        time.sleep(0.05)

    print("✅ Port scan done!")
    time.sleep(5)


# ─────────────────────────────────────────
# Attack 3 — SYN Flood
# ─────────────────────────────────────────

def simulate_syn_flood():
    banner("SYN FLOOD ATTACK")
    print("Sending 30 SYN packets to 8.8.8.8:80...")
    print("Expected: 🚨 [CRITICAL] SYN_FLOOD\n")

    send(
        IP(dst="8.8.8.8") / TCP(dport=80, flags="S"),
        count   = 30,
        inter   = 0.01,
        verbose = False
    )
    print("✅ SYN flood sent!")
    time.sleep(5)


# ─────────────────────────────────────────
# Attack 4 — Large Packet
# ─────────────────────────────────────────

def simulate_large_packet():
    banner("LARGE PACKET ATTACK")
    print("Sending oversized packets to 8.8.8.8...")
    print("Expected: 🟡 [MEDIUM] LARGE_PACKET\n")
    send(
        IP(dst="8.8.8.8") / TCP(dport=80) / Raw(b"X" * 2000),
        count   = 5,
        inter   = 0.5,
        verbose = False
    )
    print("✅ Large packets sent!")
    time.sleep(5)


# ─────────────────────────────────────────
# Attack 5 — Dangerous Port
# ─────────────────────────────────────────

def simulate_dangerous_port():
    banner("DANGEROUS PORT ATTACK")
    print("Connecting to known malicious ports...")
    print("Ports: 4444 (Metasploit), 1337, 6667 (Botnet), 31337")
    print("Expected: 🚨 [CRITICAL] DANGEROUS_PORT\n")

    dangerous_ports = [4444, 1337, 6667, 31337, 9001]

    for port in dangerous_ports:
        send(
            IP(dst="8.8.8.8") / TCP(dport=port, flags="S"),
            verbose = False
        )
        print(f"  Sent to port {port}")
        time.sleep(0.5)

    print("✅ Dangerous port test done!")
    time.sleep(5)


# ─────────────────────────────────────────
# Menu
# ─────────────────────────────────────────

def menu():
    print("\n" + "=" * 50)
    print("  Hybrid IDS Attack Simulator")
    print("  Make sure test_ids.py is running!")
    print("=" * 50)
    print("\n  1 → ICMP Flood")
    print("  2 → Port Scan")
    print("  3 → SYN Flood")
    print("  4 → Large Packet")
    print("  5 → Dangerous Port")
    print("  6 → Run ALL attacks")
    print("  0 → Exit")

    choice = input("\nSelect attack to simulate: ").strip()

    if choice == "1":
        simulate_icmp_flood()
    elif choice == "2":
        simulate_port_scan()
    elif choice == "3":
        simulate_syn_flood()
    elif choice == "4":
        simulate_large_packet()
    elif choice == "5":
        simulate_dangerous_port()
    elif choice == "6":
        simulate_icmp_flood()
        simulate_port_scan()
        simulate_syn_flood()
        simulate_large_packet()
        simulate_dangerous_port()
        print("\n🎉 All attacks simulated!")
    elif choice == "0":
        print("Exiting...")
        return
    else:
        print("Invalid choice!")

    menu()  # show menu again


# ─────────────────────────────────────────
# Run
# ─────────────────────────────────────────

if __name__ == "__main__":
    menu()