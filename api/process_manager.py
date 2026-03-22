"""
api/process_manager.py
=======================
Manages all monitoring subprocesses.
On every Start — automatically cleans stale devices for new network.
"""

import sys, os, subprocess, threading, collections
from datetime import datetime


class ProcessManager:
    def __init__(self):
        self.procs:   dict = {}
        self.log            = collections.deque(maxlen=500)
        self.running: bool  = False
        self.lock           = threading.Lock()

    def _stream(self, name: str, proc):
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                self.log.append({
                    "ts":  datetime.now().strftime("%H:%M:%S"),
                    "src": name,
                    "msg": line
                })

    def _launch(self, name: str, script: str, cwd: str) -> bool:
        python = sys.executable
        # CREATE_NO_WINDOW — no popup terminals on Windows
        flags  = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            proc = subprocess.Popen(
                [python, os.path.join(cwd, script)],
                cwd=cwd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                encoding="utf-8", errors="replace",
                creationflags=flags
            )
            self.procs[name] = proc
            t = threading.Thread(
                target=self._stream, args=(name, proc), daemon=True)
            t.start()
            self._log("system", f"Started {name} (pid {proc.pid})")
            return True
        except Exception as e:
            self._log("error", f"Failed to start {name}: {e}")
            return False

    def _log(self, src: str, msg: str):
        self.log.append({
            "ts":  datetime.now().strftime("%H:%M:%S"),
            "src": src,
            "msg": msg
        })

    def _clean_stale_devices(self, router_ip: str, cwd: str):
        """
        Clean stale devices from old subnet before starting.
        Called on every Start so switching routers always works correctly.
        """
        try:
            import sqlite3
            db_path = os.path.join(cwd, "network_monitor.db")
            if not os.path.exists(db_path):
                return

            base = ".".join(router_ip.strip().split(".")[:3]) + "."
            conn = sqlite3.connect(db_path)

            # Get all active devices
            rows = conn.execute(
                "SELECT ip FROM active_targets WHERE active=1"
            ).fetchall()

            removed = 0
            for r in rows:
                ip = r[0]
                # Keep: current subnet + external targets
                if not ip.startswith(base) and ip not in ("8.8.8.8", "1.1.1.1"):
                    conn.execute(
                        "UPDATE active_targets SET active=0 WHERE ip=?", (ip,))
                    removed += 1

            # Always ensure router IP is active
            conn.execute("""
                INSERT INTO active_targets (ip, name, added_at, active)
                VALUES (?, ?, datetime('now'), 1)
                ON CONFLICT(ip) DO UPDATE SET
                    name = excluded.name,
                    active = 1
            """, (router_ip, f"Router ({router_ip})"))

            # Save current gateway to network_state
            conn.execute("""
                CREATE TABLE IF NOT EXISTS network_state (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TEXT
                )
            """)
            conn.execute("""
                INSERT INTO network_state (key, value, updated_at)
                VALUES ('current_gateway', ?, datetime('now'))
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
            """, (router_ip,))

            conn.commit()
            conn.close()

            if removed > 0:
                self._log("system",
                    f"Cleaned {removed} stale devices from old network")
            self._log("system",
                f"Network set to {base}0/24 — starting fresh")

        except Exception as e:
            self._log("error", f"Cleanup error: {e}")

    def start(self, router_ip: str) -> dict:
        if self.running:
            return {"ok": False, "msg": "Already running"}

        cwd = os.path.dirname(os.path.abspath(__file__))
        cwd = os.path.dirname(cwd)  # go up from api/ to project root

        self._log("system", f"Starting monitor for {router_ip}")

        # Clean stale devices before launching anything
        self._clean_stale_devices(router_ip, cwd)

        with self.lock:
            self._launch("watchdog",   os.path.join("core", "network_watchdog.py"), cwd)
            self._launch("discovery",  os.path.join("core", "discovery.py"),        cwd)
            self._launch("probe",      os.path.join("core", "probe.py"),            cwd)
            self._launch("traceroute", os.path.join("core", "traceroute.py"),       cwd)
            self._launch("health",     os.path.join("core", "health.py"),           cwd)
            self._launch("classifier", os.path.join("core", "classifier.py"),       cwd)
            self._launch("anomaly",    os.path.join("core", "anomaly.py"),          cwd)
            self.running = True

        return {"ok": True, "msg": f"Monitor started for {router_ip}"}

    def start_bandwidth(self) -> dict:
        if "bandwidth" in self.procs and self.procs["bandwidth"].poll() is None:
            return {"ok": False, "msg": "Already running"}
        cwd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._launch("bandwidth", os.path.join("core", "bandwidth.py"), cwd)
        return {"ok": True, "msg": "Bandwidth monitor started"}

    def stop(self) -> dict:
        if not self.running:
            return {"ok": False, "msg": "Not running"}
        with self.lock:
            for name in ["watchdog", "discovery", "probe",
                         "traceroute", "health", "classifier", "anomaly"]:
                proc = self.procs.get(name)
                if proc:
                    try:
                        proc.terminate()
                        self._log("system", f"Stopped {name}")
                    except Exception:
                        pass
            self.procs = {k: v for k, v in self.procs.items()
                          if k not in ("watchdog", "discovery", "probe",
                                       "traceroute", "health",
                                       "classifier", "anomaly")}
            self.running = False
        return {"ok": True, "msg": "Monitor stopped"}

    def stop_bandwidth(self) -> dict:
        proc = self.procs.get("bandwidth")
        if proc:
            proc.terminate()
            del self.procs["bandwidth"]
            self._log("system", "Bandwidth monitor stopped")
            return {"ok": True, "msg": "Stopped"}
        return {"ok": False, "msg": "Not running"}

    def status(self) -> dict:
        return {
            "running":   self.running,
            "processes": {n: p.poll() is None
                          for n, p in self.procs.items()}
        }

    def get_logs(self, since: int = 0) -> dict:
        lines = list(self.log)
        return {"logs": lines[since:], "total": len(lines)}