"""Application entry point:  python -m backend.main   (or start.bat)"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

if __package__ in (None, ""):  # allow "python backend/main.py"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("YOLO_VERBOSE", "False")

import uvicorn  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from backend.config import APP_NAME, APP_VERSION, FRONTEND_DIST, HOST, OPEN_BROWSER, PORT, VIOLATIONS_DIR  # noqa: E402
from backend.logging_setup import setup_logging  # noqa: E402

setup_logging()
log = logging.getLogger("main")

from backend import settings_store  # noqa: E402
from backend.api import cameras, dashboard, system, violations  # noqa: E402
from backend.camera.manager import manager  # noqa: E402
from backend.database.db import init_db  # noqa: E402
from backend.events import bus  # noqa: E402
from backend.notifications.dispatcher import get_dispatcher  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting %s %s", APP_NAME, APP_VERSION)
    init_db()
    settings_store.get_settings()
    bus.bind_loop(asyncio.get_running_loop())
    get_dispatcher()
    manager.load_models_async(then_autostart=True)
    bus.publish("system", {}, activity="System started - loading AI models")
    yield
    log.info("Shutting down...")
    manager.shutdown()


app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(system.router)
app.include_router(cameras.router)
app.include_router(violations.router)
app.include_router(dashboard.router)
app.mount("/evidence", StaticFiles(directory=str(VIOLATIONS_DIR)), name="evidence")

if (FRONTEND_DIST / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith(("api/", "ws", "evidence/")):
            raise HTTPException(404)
        candidate = (FRONTEND_DIST / full_path).resolve()
        if full_path and candidate.is_file() and FRONTEND_DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
else:
    @app.get("/", include_in_schema=False)
    def no_frontend():
        return JSONResponse({"message": "Frontend build not found (frontend/dist). API docs: /docs"})


def run() -> None:
    url = f"http://{'127.0.0.1' if HOST in ('0.0.0.0', '') else HOST}:{PORT}"
    log.info("Dashboard: %s", url)
    if OPEN_BROWSER:
        threading.Timer(2.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning", ws_ping_interval=20)


if __name__ == "__main__":
    run()
