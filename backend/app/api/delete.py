"""Delete preview API router (preview + execute + queue)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.delete_preview import (
    DeleteExecutePayload,
    DeleteExecuteResponse,
    DeletePreviewPayload,
    DeletePreviewResponse,
    DeleteQueueStatusResponse,
)
from app.services.delete_preview_service import (
    build_delete_preview,
    execute_deletes,
    list_delete_queue_status,
)
from app.services.shenyi_client import ShenyiSettingsMissingError

router = APIRouter(tags=["delete"])


@router.post("/delete/preview", response_model=DeletePreviewResponse)
def post_delete_preview(payload: DeletePreviewPayload, db: Session = Depends(get_db)) -> DeletePreviewResponse:
    """Return read-only preview of what would be deleted."""
    try:
        return build_delete_preview(db, payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to build delete preview: {exc}") from exc


@router.post("/delete/execute", response_model=DeleteExecuteResponse)
def post_delete_execute(payload: DeleteExecutePayload, db: Session = Depends(get_db)) -> DeleteExecuteResponse:
    """Queue and execute batched DeleteVersion requests for selected items or current delete candidates."""
    try:
        return execute_deletes(db, payload)
    except ShenyiSettingsMissingError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Delete execution requires Shenyi settings. Update /settings shenyi.base_url and shenyi.api_key. ({exc})",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Delete execution failed unexpectedly: {exc}") from exc


@router.get("/delete/queue/status", response_model=DeleteQueueStatusResponse)
def get_delete_queue_status(
    ids: list[int] = Query(default=[]),
    limit: int = Query(default=20, ge=1, le=500),
    latest_only: bool = Query(default=True),
    db: Session = Depends(get_db),
) -> DeleteQueueStatusResponse:
    """Return queue status rows for selected queue ids or recent queue rows."""
    try:
        normalized_ids = [int(x) for x in ids if int(x) > 0]
        return list_delete_queue_status(db, ids=normalized_ids, limit=limit, latest_only=latest_only)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch delete queue status: {exc}") from exc
