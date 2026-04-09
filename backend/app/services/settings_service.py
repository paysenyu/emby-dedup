"""Settings persistence service."""

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import AppSettings
from app.schemas.settings import SettingsPayload, SettingsResponse


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat()


def _default_row() -> AppSettings:
    now = _utc_now_iso()
    return AppSettings(
        emby_base_url="",
        emby_api_key="",
        emby_user_id="",
        selected_libraries_json="[]",
        excluded_paths_json="[]",
        sync_concurrency=1,
        shenyi_base_url="",
        shenyi_api_key="",
        webhook_token="",
        created_at=now,
        updated_at=now,
    )


def _get_or_create_row(db: Session) -> AppSettings:
    row = db.query(AppSettings).order_by(AppSettings.id.asc()).first()
    if row is None:
        row = _default_row()
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _to_response(row: AppSettings) -> SettingsResponse:
    return SettingsResponse(
        emby={
            "base_url": row.emby_base_url,
            "api_key": row.emby_api_key,
            "user_id": row.emby_user_id,
        },
        libraries=json.loads(row.selected_libraries_json or "[]"),
        excluded_paths=json.loads(row.excluded_paths_json or "[]"),
        sync={"concurrency": 1},
        shenyi={
            "base_url": row.shenyi_base_url,
            "api_key": row.shenyi_api_key,
        },
        webhook_token=row.webhook_token,
    )


def load_settings(db: Session) -> SettingsResponse:
    """Load settings from DB, creating defaults on first run."""
    row = _get_or_create_row(db)
    return _to_response(row)


def save_settings(db: Session, payload: SettingsPayload) -> SettingsResponse:
    """Persist settings payload and return the stored values."""
    row = _get_or_create_row(db)
    row.emby_base_url = payload.emby.base_url
    row.emby_api_key = payload.emby.api_key
    row.emby_user_id = payload.emby.user_id
    row.selected_libraries_json = json.dumps(payload.libraries, ensure_ascii=False)
    row.excluded_paths_json = json.dumps(payload.excluded_paths, ensure_ascii=False)
    # Sync concurrency is intentionally fixed to 1.
    row.sync_concurrency = 1
    row.shenyi_base_url = payload.shenyi.base_url
    row.shenyi_api_key = payload.shenyi.api_key
    row.webhook_token = payload.webhook_token
    row.updated_at = _utc_now_iso()

    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_response(row)
