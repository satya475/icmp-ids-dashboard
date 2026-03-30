"""
Run once to download the IEEE OUI database:
  python utils/download_oui.py
"""
import urllib.request, os

URL      = "https://standards-oui.ieee.org/oui/oui.csv"
OUT_DIR  = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
OUT_FILE = os.path.join(OUT_DIR, "oui.csv")

os.makedirs(OUT_DIR, exist_ok=True)
print("Downloading IEEE OUI database (~10MB)...")
urllib.request.urlretrieve(URL, OUT_FILE)
print(f"Saved to {OUT_FILE}")
print("Done — vendor lookup will now work for 35,000+ MAC prefixes.")
