"""Libraries API router."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.libraries import LibrariesResponse
from app.services.emby_client import (
    EmbyApiError,
    EmbyAuthError,
    EmbyClient,
    EmbyServerUnreachableError,
    EmbySettingsMissingError,
)
from app.services.settings_service import load_settings

router = APIRouter(tags=["libraries"])


@router.get("/libraries", response_model=LibrariesResponse)
def get_libraries(db: Session = Depends(get_db)) -> LibrariesResponse:
    """Return user-accessible libraries from Emby."""
    settings = load_settings(db)
    user_id = (settings.emby.user_id or "").strip()

    if not user_id:
        raise HTTPException(status_code=400, detail="Emby user id is required. Please save settings.emby.user_id.")

    try:
        client = EmbyClient(
            base_url=settings.emby.base_url,
            api_key=settings.emby.api_key,
        )
        items = client.list_user_views(user_id=user_id)
    except EmbySettingsMissingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EmbyAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except EmbyServerUnreachableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EmbyApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return LibrariesResponse(items=items)
