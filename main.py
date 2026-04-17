"""
main.py
========
PingGuard — Entry point.
Now using FastAPI + Uvicorn instead of Flask.

Usage:
  python main.py              # start dashboard
  python main.py --probe      # probe engine only
  python main.py --discovery  # discovery only
  python main.py --bandwidth  # bandwidth only
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def init_schema():
    from db.database import init_schema as _init
    _init()


# ─────────────────────────────────────────
# Background engines
# ─────────────────────────────────────────

def _run_health_in_background():
    import threading, time
    from utils.network import get_current_gateway

    def health_loop():
        from core.health import (init_health_tables, start_session,
                                  get_current_session, take_snapshot,
                                  training_loop)
        import threading as _t
        init_health_tables()
        _t.Thread(target=training_loop, daemon=True).start()
        current_gw = None
        session_id = None
        while True:
            try:
                gw = get_current_gateway()
                if gw and gw != "0.0.0.0":
                    if gw != current_gw:
                        session_id = start_session(
                            gw, ".".join(gw.split(".")[:3]) + ".0/24")
                        current_gw = gw
                        print(f"  [HEALTH] Session started for {gw}")
                    if session_id:
                        scores = take_snapshot(session_id)
                        print(f"  [HEALTH] Score: "
                              f"{scores['health_score']:.0f}/100")
            except Exception as e:
                print(f"  [HEALTH ERROR] {e}")
            time.sleep(60)

    t = threading.Thread(target=health_loop, daemon=True)
    t.name = "health-engine"
    t.start()

def _run_ids_in_background():
    """Start IDS packet capture in background thread."""
    import threading

    def ids_loop():
        import time
        # Small delay to let dashboard start first
        time.sleep(5)
        try:
            from ids.capture import start_capture
            from ids.engine.decision import process_packet
            from ids.alerts import handle_alert

            def on_packet(features):
                process_packet(features, on_alert=handle_alert)

            print("  [IDS] Hybrid IDS started — monitoring all traffic...")
            print("  [IDS] Signature IDS + ML IDS active")

            start_capture(callback=on_packet, count=0)

        except Exception as e:
            print(f"  [IDS ERROR] {e}")

    t = threading.Thread(target=ids_loop, daemon=True)
    t.name = "hybrid-ids"
    t.start()

def _run_device_health_in_background():
    import threading, time

    def device_health_loop():
        from core.device_health import (
            init_device_health_tables, aggregate_daily,
            update_baselines, calculate_degradation, prune_old_data
        )
        init_device_health_tables()
        print("  [DEVICE HEALTH] Tracker running in background")
        while True:
            try:
                aggregate_daily()
                update_baselines()
                calculate_degradation()
                prune_old_data()
            except Exception as e:
                print(f"  [DEVICE HEALTH ERROR] {e}")
            time.sleep(3600)

    t = threading.Thread(target=device_health_loop, daemon=True)
    t.name = "device-health"
    t.start()


# ─────────────────────────────────────────
# FastAPI app
# ─────────────────────────────────────────

def run_dashboard():
    import uvicorn
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
    from fastapi.requests import Request
    from fastapi.responses import HTMLResponse
    from api.routes import router
    from api.process_manager import ProcessManager
    from config import DASHBOARD_HOST, DASHBOARD_PORT

    init_schema()

    # Start background engines
    _run_health_in_background()
    _run_device_health_in_background()

    # ML training engine
    import threading, time
    def _train_synthetic():
        time.sleep(5)
        try:
            from core.synthetic_data import train_on_synthetic
            train_on_synthetic()
        except Exception as e:
            print(f"  [SYNTHETIC ERROR] {e}")
        while True:
            time.sleep(86400)
            try:
                from core.synthetic_data import train_on_synthetic
                train_on_synthetic()
            except Exception as e:
                print(f"  [SYNTHETIC ERROR] {e}")

    threading.Thread(target=_train_synthetic, daemon=True,
                     name="synthetic-trainer").start()

    from core.ml_engine import start_ml_engine
    start_ml_engine()
    _run_ids_in_background()

    # Create FastAPI app
    app = FastAPI(
        title="PingGuard",
        description="Enterprise Network Intelligence Platform",
        version="2.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Attach process manager to app state
    app.state.process_manager = ProcessManager()

    # Mount static files
    app.mount(
        "/static",
        StaticFiles(directory=os.path.join("web", "static")),
        name="static"
    )

    # Templates
    templates = Jinja2Templates(
        directory=os.path.join("web", "templates"))

    # Include API router
    app.include_router(router)

    # ── Page routes ───────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        return templates.TemplateResponse(
            "dashboard.html", {"request": request})

    @app.get("/bandwidth", response_class=HTMLResponse)
    async def bandwidth(request: Request):
        return templates.TemplateResponse(
            "bandwidth.html", {"request": request})

    @app.get("/reports", response_class=HTMLResponse)
    async def reports(request: Request):
        return templates.TemplateResponse(
            "reports.html", {"request": request})

    @app.get("/health", response_class=HTMLResponse)
    async def health_page(request: Request):
        return templates.TemplateResponse(
            "health.html", {"request": request})

    @app.get("/insights", response_class=HTMLResponse)
    async def insights(request: Request):
        return templates.TemplateResponse(
            "insights.html", {"request": request})

    @app.get("/degradation", response_class=HTMLResponse)
    async def degradation(request: Request):
        return templates.TemplateResponse(
            "degradation.html", {"request": request})

    print(f"\n  PingGuard v2.0 — FastAPI")
    print(f"  -------------------------")
    print(f"  Dashboard : http://localhost:{DASHBOARD_PORT}")
    print(f"  API Docs  : http://localhost:{DASHBOARD_PORT}/docs")
    print(f"  Database  : {os.path.abspath('network_monitor.db')}")
    print(f"\n  Enter your router IP in the dashboard and click Start.\n")

    uvicorn.run(
        app,
        host=DASHBOARD_HOST,
        port=int(DASHBOARD_PORT),
        log_level="warning"
    )


# ─────────────────────────────────────────
# Other modes
# ─────────────────────────────────────────

def run_probe():
    init_schema()
    from core.probe import run
    run()


def run_discovery():
    init_schema()
    from core.discovery import run
    run()


def run_bandwidth():
    init_schema()
    from core.bandwidth import run
    run()


# ─────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PingGuard")
    parser.add_argument("--probe",     action="store_true")
    parser.add_argument("--discovery", action="store_true")
    parser.add_argument("--bandwidth", action="store_true")
    args = parser.parse_args()

    if args.probe:
        run_probe()
    elif args.discovery:
        run_discovery()
    elif args.bandwidth:
        run_bandwidth()
    else:
        run_dashboard()