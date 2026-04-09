"""Health endpoint router."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Basic liveness check endpoint."""
    return {"status": "ok"}
