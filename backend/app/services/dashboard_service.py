"""Dashboard stats service."""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import MediaItem
from app.schemas.dashboard import DashboardStatsResponse
from app.services.emby_client import EmbyClient
from app.services.settings_service import load_settings


def load_dashboard_stats(db: Session) -> DashboardStatsResponse:
    settings = load_settings(db)
    user_id = str(settings.emby.user_id or "").strip()

    client = EmbyClient(settings.emby.base_url, settings.emby.api_key)
    if not user_id:
        user_id = client.get_primary_user_id()

    movie_count = client.get_user_item_count(user_id, "Movie")
    series_count = client.get_user_item_count(user_id, "Series")
    episode_count = client.get_user_item_count(user_id, "Episode")

    counts = client.get_server_item_counts()
    storage_total = counts.get("TotalFileSize") if isinstance(counts, dict) else None
    try:
        storage_size_total = int(storage_total) if storage_total is not None else None
    except (TypeError, ValueError):
        storage_size_total = None
    if storage_size_total is None or storage_size_total <= 0:
        fallback_total = db.query(func.coalesce(func.sum(MediaItem.file_size), 0)).scalar()
        try:
            fallback_value = int(fallback_total or 0)
        except (TypeError, ValueError):
            fallback_value = 0
        storage_size_total = fallback_value if fallback_value > 0 else None

    return DashboardStatsResponse(
        movie_count=movie_count,
        series_count=series_count,
        episode_count=episode_count,
        storage_size_total=storage_size_total,
        source="emby",
    )
