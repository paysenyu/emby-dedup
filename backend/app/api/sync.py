"""Sync API router."""

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.schemas.sync import SyncStatusResponse
from app.services.sync_service import run_full_sync_workflow, sync_status_tracker

router = APIRouter(tags=["sync"])


@router.get("/sync/status", response_model=SyncStatusResponse)
def get_sync_status() -> SyncStatusResponse:
    """Return current or last sync status."""
    return sync_status_tracker.get_status()


@router.post("/sync", response_model=SyncStatusResponse)
def trigger_sync(background_tasks: BackgroundTasks) -> SyncStatusResponse:
    """Trigger full sync workflow for Phase 1."""
    started = sync_status_tracker.start()
    if not started:
        raise HTTPException(status_code=409, detail="Sync is already running.")

    background_tasks.add_task(run_full_sync_workflow)
    return sync_status_tracker.get_status()
