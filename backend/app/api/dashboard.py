"""Dashboard API router."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.dashboard import DashboardStatsResponse
from app.services.emby_client import EmbyApiError, EmbyAuthError, EmbyServerUnreachableError, EmbySettingsMissingError
from app.services.dashboard_service import load_dashboard_stats

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/stats", response_model=DashboardStatsResponse)
def get_dashboard_stats(db: Session = Depends(get_db)) -> DashboardStatsResponse:
    try:
        return load_dashboard_stats(db)
    except EmbySettingsMissingError as exc:
        raise HTTPException(status_code=400, detail=f"Emby settings missing: {exc}") from exc
    except EmbyAuthError as exc:
        raise HTTPException(status_code=401, detail=f"Emby auth failed: {exc}") from exc
    except EmbyServerUnreachableError as exc:
        raise HTTPException(status_code=502, detail=f"Emby unreachable: {exc}") from exc
    except EmbyApiError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch dashboard stats: {exc}") from exc
