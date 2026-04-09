"""FastAPI entrypoint for Emby Dedup backend."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.analysis import router as analysis_router
from app.api.dashboard import router as dashboard_router
from app.api.delete import router as delete_router
from app.api.health import router as health_router
from app.api.libraries import router as libraries_router
from app.api.metadata import router as metadata_router
from app.api.rules import router as rules_router
from app.api.settings import router as settings_router
from app.api.sync import router as sync_router
from app.api.webhook import router as webhook_router
from app.core.logging_setup import init_logging
from app.core.version import APP_VERSION
from app.db.init_db import init_db

API_PREFIX = "/api"

app = FastAPI(title="Emby Dedup API", version=APP_VERSION)
app.include_router(health_router, prefix=API_PREFIX)
app.include_router(settings_router, prefix=API_PREFIX)
app.include_router(libraries_router, prefix=API_PREFIX)
app.include_router(sync_router, prefix=API_PREFIX)
app.include_router(rules_router, prefix=API_PREFIX)
app.include_router(analysis_router, prefix=API_PREFIX)
app.include_router(metadata_router, prefix=API_PREFIX)
app.include_router(delete_router, prefix=API_PREFIX)
app.include_router(webhook_router, prefix=API_PREFIX)
app.include_router(dashboard_router, prefix=API_PREFIX)


@app.on_event("startup")
def on_startup() -> None:
    """Initialize local persistence before serving requests."""
    init_logging()
    init_db()


_FRONTEND_DIST = Path("/app/frontend_dist")
_INDEX_HTML = _FRONTEND_DIST / "index.html"
_ASSETS_DIR = _FRONTEND_DIST / "assets"
_RESERVED_PREFIXES = (
    "api",
    "docs",
    "redoc",
    "openapi.json",
)

if _ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(_ASSETS_DIR)), name="frontend-assets")


def _is_reserved_path(full_path: str) -> bool:
    clean = full_path.strip("/")
    if not clean:
        return False
    if clean in {"docs", "redoc", "openapi.json"}:
        return True
    return any(clean.startswith(prefix + "/") or clean == prefix for prefix in _RESERVED_PREFIXES)


@app.get("/", include_in_schema=False)
def serve_frontend_root() -> FileResponse:
    if not _INDEX_HTML.exists():
        raise HTTPException(status_code=404, detail="Frontend build not found in container image.")
    return FileResponse(_INDEX_HTML)


@app.get("/{full_path:path}", include_in_schema=False)
def serve_frontend_app(full_path: str) -> FileResponse:
    if _is_reserved_path(full_path):
        raise HTTPException(status_code=404, detail="Not Found")

    if not _INDEX_HTML.exists():
        raise HTTPException(status_code=404, detail="Frontend build not found in container image.")

    candidate = (_FRONTEND_DIST / full_path).resolve()
    if candidate.is_file() and str(candidate).startswith(str(_FRONTEND_DIST.resolve())):
        return FileResponse(candidate)

    return FileResponse(_INDEX_HTML)


