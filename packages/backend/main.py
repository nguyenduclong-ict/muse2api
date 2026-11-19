"""FastAPI entrypoint for muse2apiv2."""
from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from config import Config
from db import Database
from routers import accounts, admin_core, proxies, v1_openai
from services.cleanup import CleanupService
from services.keepalive import KeepAliveService
from services.voice_preview import VoicePreviewService
from services.wss_pool import WSSPool


def _configure_logging(level_name: str) -> None:
    """Configure root logger so application and service logs appear in stdout."""
    level = getattr(logging, level_name.upper(), logging.INFO)
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        root.addHandler(handler)
    root.setLevel(level)


_configure_logging(Config().log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = Config()
    db = Database(cfg)
    orphaned = db.fail_orphaned_tasks()
    if orphaned:
        logging.getLogger(__name__).warning("Marked %d orphaned running/queued task(s) as failed on startup", orphaned)
    wss_pool = WSSPool(cfg, db)
    keepalive = KeepAliveService(cfg, db)
    cleanup = CleanupService(cfg, db)
    voice_preview = VoicePreviewService(cfg, db, wss_pool)

    app.state.cfg = cfg
    app.state.db = db
    app.state.wss_pool = wss_pool
    app.state.keepalive = keepalive
    app.state.cleanup = cleanup
    app.state.voice_preview = voice_preview

    keepalive.start()
    cleanup.start()
    wss_pool.start_background()
    try:
        yield
    finally:
        keepalive.stop()
        cleanup.stop()
        wss_pool.stop_background()
        wss_pool.close_all()


app = FastAPI(title="muse2apiv2", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(accounts.router)
app.include_router(proxies.router)
app.include_router(admin_core.router)
app.include_router(v1_openai.router)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    return {"status": "ready"}


# Single-port React SPA serving when frontend/dist exists
_dist = Config().frontend_dist_dir
if os.path.isdir(_dist):
    _assets = os.path.join(_dist, "assets")
    if os.path.isdir(_assets):
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        if full_path.startswith(("v1/", "admin/", "healthz", "readyz")):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        index_html = os.path.join(_dist, "index.html")
        if os.path.isfile(index_html):
            return FileResponse(index_html)
        return JSONResponse({"detail": "Frontend not built"}, status_code=404)


if __name__ == "__main__":
    import uvicorn

    c = Config()
    uvicorn.run("main:app", host=c.host, port=c.port, reload=False, log_level=c.log_level.lower())
