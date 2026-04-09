"""Health endpoint router."""

from fastapi import APIRouter
from app.core.version import APP_VERSION

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Basic liveness check endpoint."""
    return {"status": "ok", "version": APP_VERSION}
