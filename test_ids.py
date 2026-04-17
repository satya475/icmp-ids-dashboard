from ids.capture  import start_capture
from ids.engine.decision import process_packet
from ids.alerts   import handle_alert

def on_packet(features):
    process_packet(features, on_alert=handle_alert)

print("=" * 50)
print("  Hybrid IDS Running!")
print("  Capturing live traffic...")
print("  Press Ctrl+C to stop")
print("=" * 50)

start_capture(callback=on_packet, count=0)