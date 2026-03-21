"""
main.py
========
Single entry point for the entire Network Monitor project.

Usage:
    python main.py              # starts dashboard (open http://localhost:5000)
    python main.py --probe      # runs probe engine only
    python main.py --discovery  # runs discovery only
    python main.py --bandwidth  # runs bandwidth monitor only
"""

import sys
import os

# Make sure project root is in Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.database import init_schema


def _run_health_in_background():
    """Run health engine directly in dashboard process — no subprocess."""
    import threading, time
    from utils.network import get_current_gateway
    from db.database import get_connection
    from config import DB_FILE

    def health_loop():
        from core.health import (init_health_tables, start_session,
                                  get_current_session, take_snapshot,
                                  training_loop)
        import threading
        init_health_tables()
        # Start training loop
        t = threading.Thread(target=training_loop, daemon=True)
        t.start()

        current_gw = None
        session_id = None

        while True:
            try:
                gw = get_current_gateway()
                if gw and gw != "0.0.0.0":
                    if gw != current_gw:
                        session_id = start_session(gw, 
                            ".".join(gw.split(".")[:3]) + ".0/24")
                        current_gw = gw
                        print(f"  [HEALTH] Session started for {gw}")
                    if session_id:
                        scores = take_snapshot(session_id)
                        print(f"  [HEALTH] Score: {scores['health_score']:.0f}/100")
            except Exception as e:
                print(f"  [HEALTH ERROR] {e}")
            time.sleep(60)

    t = threading.Thread(target=health_loop, daemon=True)
    t.name = "health-engine"
    t.start()
    print("  [HEALTH] Health engine running in background")


def run_dashboard():
    """Start the Flask dashboard (default mode)."""
    from flask import Flask
    from config import DASHBOARD_HOST, DASHBOARD_PORT, SECRET_KEY
    from api.routes import api
    from api.process_manager import ProcessManager
    from flask import render_template

    # Init DB schema before anything else
    init_schema()

    # Run health engine directly in this process
    _run_health_in_background()

    app = Flask(
        __name__,
        template_folder=os.path.join("web", "templates"),
        static_folder=os.path.join("web", "static")
    )
    app.secret_key = SECRET_KEY
    app.config["PROCESS_MANAGER"] = ProcessManager()
    app.register_blueprint(api)

    @app.route("/")
    def dashboard():
        return render_template("dashboard.html")

    @app.route("/bandwidth")
    def bandwidth():
        return render_template("bandwidth.html")

    @app.route("/reports")
    def reports():
        return render_template("reports.html")

    @app.route("/health")
    def health_page():
        return render_template("health.html")

    @app.route("/insights")
    def insights():
        return render_template("insights.html")

    print(f"\n  Network Monitor")
    print(f"  ---------------")
    print(f"  Dashboard : http://localhost:{DASHBOARD_PORT}")
    print(f"  Bandwidth : http://localhost:{DASHBOARD_PORT}/bandwidth")
    print(f"  Database  : {os.path.abspath('network_monitor.db')}")
    print(f"\n  Enter your router IP in the dashboard and click Start.\n")

    app.run(
        host=DASHBOARD_HOST,
        port=DASHBOARD_PORT,
        debug=False,
        threaded=True
    )


def run_probe():
    """Run probe engine standalone."""
    init_schema()
    from core.probe import run
    run()


def run_discovery():
    """Run discovery engine standalone."""
    init_schema()
    from core.discovery import run
    run()


def run_bandwidth():
    """Run bandwidth monitor standalone."""
    init_schema()
    from core.bandwidth import run
    run()


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--probe" in args:
        run_probe()
    elif "--discovery" in args:
        run_discovery()
    elif "--bandwidth" in args:
        run_bandwidth()
    else:
        run_dashboard()
