"""
setup.py
=========
Run this once after cloning the project:
  python setup.py

This will:
  1. Create the database with correct schema
  2. Download the OUI vendor database
  3. Create a .env file from the example
  4. Train ML models on synthetic data
"""

import os
import sys

print("\n  PingGuard — First Time Setup")
print("  ================================\n")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Step 1 — Create database
print("  [1/4] Creating database...")
try:
    from db.database import init_schema
    init_schema()
    print("        database created OK\n")
except Exception as e:
    print(f"        ERROR: {e}\n")

# Step 2 — Download OUI vendor database
print("  [2/4] Downloading OUI vendor database (~10MB)...")
try:
    import urllib.request
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    os.makedirs(data_dir, exist_ok=True)
    oui_path = os.path.join(data_dir, "oui.csv")
    if os.path.exists(oui_path):
        print("        already downloaded, skipping\n")
    else:
        urllib.request.urlretrieve(
            "https://standards-oui.ieee.org/oui/oui.csv", oui_path)
        print("        downloaded OK\n")
except Exception as e:
    print(f"        WARNING: Could not download OUI db: {e}")
    print("        Vendor lookup will use built-in table only\n")

# Step 3 — Create .env from example
print("  [3/4] Setting up .env file...")
env_path     = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
example_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env.example")
if os.path.exists(env_path):
    print("        .env already exists, skipping\n")
elif os.path.exists(example_path):
    import shutil
    shutil.copy(example_path, env_path)
    print("        .env created from .env.example\n")
else:
    # Create minimal .env
    with open(env_path, "w") as f:
        f.write("# PingGuard Configuration\n")
        f.write("DASHBOARD_PORT=5000\n")
        f.write("PROBE_INTERVAL=10\n")
    print("        .env created with defaults\n")

# Step 4 — Train ML models
print("  [4/4] Training ML models on synthetic data...")
try:
    from core.synthetic_data import train_on_synthetic
    train_on_synthetic()
    print("        models trained OK\n")
except Exception as e:
    print(f"        WARNING: Model training failed: {e}")
    print("        Models will train automatically when monitoring starts\n")

print("  ================================")
print("  Setup complete!")
print("  Run:  python main.py")
print("  Open: http://localhost:5000\n")