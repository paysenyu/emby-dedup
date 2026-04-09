"""Analysis API router."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.analysis import (
    AnalysisGroupDetailResponse,
    AnalysisGroupsResponse,
    AnalysisOverridePayload,
    AnalysisOverrideResponse,
    AnalysisRunResponse,
)
from app.services.analysis_orchestrator_service import run_analysis_singleflight
from app.services.analysis_service import apply_manual_override, get_group_detail, list_groups

router = APIRouter(tags=["analysis"])


@router.post("/analysis/run", response_model=AnalysisRunResponse)
def post_analysis_run(db: Session = Depends(get_db)) -> AnalysisRunResponse:
    """Rebuild analysis results using latest synced media snapshot."""
    return run_analysis_singleflight(db)


@router.get("/analysis/groups", response_model=AnalysisGroupsResponse)
def get_analysis_groups(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    library: str | None = None,
    protected_only: bool = False,
    has_manual_override: bool | None = None,
    db: Session = Depends(get_db),
) -> AnalysisGroupsResponse:
    """List duplicate groups from latest analysis results."""
    return list_groups(
        db,
        page=page,
        page_size=page_size,
        library=library,
        protected_only=protected_only,
        has_manual_override=has_manual_override,
    )


@router.get("/analysis/groups/{group_id}", response_model=AnalysisGroupDetailResponse)
def get_analysis_group(group_id: str, db: Session = Depends(get_db)) -> AnalysisGroupDetailResponse:
    """Return details for a duplicate group."""
    detail = get_group_detail(db, group_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Group not found.")
    return detail


@router.put("/analysis/groups/{group_id}/override", response_model=AnalysisOverrideResponse)
def put_analysis_group_override(
    group_id: str,
    payload: AnalysisOverridePayload,
    db: Session = Depends(get_db),
) -> AnalysisOverrideResponse:
    """Apply manual keep-item override for a group."""
    try:
        return apply_manual_override(db, group_id=group_id, keep_item_id=payload.keep_item_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
