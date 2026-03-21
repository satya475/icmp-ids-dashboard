"""
db/database.py
===============
Database connection and schema initialization.
"""

import sqlite3
from config import DB_FILE


def get_connection(db_file: str = DB_FILE) -> sqlite3.Connection:
    """Open a database connection with row factory enabled."""
    conn = sqlite3.connect(db_file, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(db_file: str = DB_FILE):
    """Create all tables and indexes if they don't exist."""
    conn = get_connection(db_file)

    conn.execute("""CREATE TABLE IF NOT EXISTS probe_results (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        host        TEXT    NOT NULL,
        name        TEXT    NOT NULL,
        timestamp   TEXT    NOT NULL,
        is_alive    INTEGER NOT NULL,
        rtt_avg_ms  REAL,
        rtt_min_ms  REAL,
        rtt_max_ms  REAL,
        packet_loss REAL    NOT NULL
    )""")

    conn.execute("""CREATE TABLE IF NOT EXISTS state_changes (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        host       TEXT NOT NULL,
        name       TEXT NOT NULL,
        timestamp  TEXT NOT NULL,
        old_status TEXT,
        new_status TEXT NOT NULL
    )""")

    conn.execute("""CREATE TABLE IF NOT EXISTS active_targets (
        ip       TEXT PRIMARY KEY,
        name     TEXT NOT NULL,
        added_at TEXT NOT NULL,
        active   INTEGER DEFAULT 1
    )""")

    conn.execute("""CREATE TABLE IF NOT EXISTS discovered_devices (
        ip         TEXT PRIMARY KEY,
        mac        TEXT,
        vendor     TEXT,
        hostname   TEXT,
        method     TEXT,
        first_seen TEXT NOT NULL,
        last_seen  TEXT NOT NULL
    )""")

    conn.execute("""CREATE TABLE IF NOT EXISTS bandwidth_samples (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        ip        TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        bytes_in  INTEGER DEFAULT 0,
        bytes_out INTEGER DEFAULT 0,
        pkts_in   INTEGER DEFAULT 0,
        pkts_out  INTEGER DEFAULT 0
    )""")

    # Indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_probe_host_time   ON probe_results(host, timestamp)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_device_ip         ON discovered_devices(ip)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bw_ip_time        ON bandwidth_samples(ip, timestamp)")

    conn.commit()
    conn.close()
    return True
