from scapy.all import sniff, IP, ICMP

print("[TEST] Starting capture... ping 8.8.8.8 in another terminal!")

def on_packet(packet):
    if packet.haslayer(IP):
        print(f"Packet: {packet[IP].src} -> {packet[IP].dst} | size: {len(packet)}")

sniff(filter="icmp", prn=on_packet, count=10, store=False)