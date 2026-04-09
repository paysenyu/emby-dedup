"""Settings API router."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.settings import SettingsPayload, SettingsResponse
from app.services.settings_service import load_settings, save_settings

router = APIRouter(tags=["settings"])


@router.get("/settings", response_model=SettingsResponse)
def get_settings(db: Session = Depends(get_db)) -> SettingsResponse:
    """Return persisted application settings."""
    return load_settings(db)


@router.put("/settings", response_model=SettingsResponse)
def put_settings(payload: SettingsPayload, db: Session = Depends(get_db)) -> SettingsResponse:
    """Update and persist application settings."""
    return save_settings(db, payload)
