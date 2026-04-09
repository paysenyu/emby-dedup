"""Schemas for dashboard stats."""

from pydantic import BaseModel


class DashboardStatsResponse(BaseModel):
    movie_count: int
    series_count: int
    episode_count: int
    storage_size_total: int | None = None
    source: str = "emby"
