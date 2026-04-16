"""
db/database.py
===============
Database connection and schema initialization.
"""

import sqlite3
from config import DB_FILE


def get_connection(db_file: str = DB_FILE) -> sqlite3.Connection:
    """Open a database connection with row factory enabled."""
    conn = sqlite3.connect(db_file, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")    # allows multiple processes to read/write
    conn.execute("PRAGMA synchronous=NORMAL")  # faster writes, still safe
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
    rtt_med_ms  REAL,       -- ADD THIS
    jitter_ms   REAL,       -- ADD THIS
    quality     TEXT,       -- ADD THIS
    packet_loss REAL        NOT NULL
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
    # Agent registry — one row per building
    conn.execute("""CREATE TABLE IF NOT EXISTS agents (
        agent_id      TEXT PRIMARY KEY,
        location      TEXT NOT NULL,
        building      TEXT NOT NULL,
        subnet        TEXT,
        router_ip     TEXT,
        last_seen     TEXT,
        first_seen    TEXT,
        is_online     INTEGER DEFAULT 0,
        version       TEXT DEFAULT '1.0'
    )""")

    # Agent probe results — device data from each building
    conn.execute("""CREATE TABLE IF NOT EXISTS agent_results (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id      TEXT NOT NULL,
        location      TEXT NOT NULL,
        ip            TEXT NOT NULL,
        name          TEXT,
        is_alive      INTEGER NOT NULL,
        rtt_avg_ms    REAL,
        packet_loss   REAL,
        quality       TEXT,
        is_router     INTEGER DEFAULT 0,
        timestamp     TEXT NOT NULL
    )""")

    # Agent bandwidth samples
    conn.execute("""CREATE TABLE IF NOT EXISTS agent_bandwidth (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id      TEXT NOT NULL,
        location      TEXT NOT NULL,
        ip            TEXT NOT NULL,
        bytes_in      INTEGER DEFAULT 0,
        bytes_out     INTEGER DEFAULT 0,
        timestamp     TEXT NOT NULL
    )""")

    # Building health snapshots — one per agent report
    conn.execute("""CREATE TABLE IF NOT EXISTS building_health (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id      TEXT NOT NULL,
        location      TEXT NOT NULL,
        timestamp     TEXT NOT NULL,
        health_score  REAL,
        router_status TEXT,
        router_rtt    REAL,
        devices_total INTEGER DEFAULT 0,
        devices_up    INTEGER DEFAULT 0,
        devices_down  INTEGER DEFAULT 0,
        avg_rtt       REAL,
        packet_loss   REAL,
        bandwidth_in  INTEGER DEFAULT 0,
        bandwidth_out INTEGER DEFAULT 0
    )""")

    # Indexes for performance
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_agent_results_agent
        ON agent_results(agent_id, timestamp)""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_building_health_agent
        ON building_health(agent_id, timestamp)""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_agent_bw
        ON agent_bandwidth(agent_id, timestamp)""")

    conn.commit()
    conn.close()
    return True
