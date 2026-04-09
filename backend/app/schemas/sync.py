"""Schemas for sync status endpoints."""

from pydantic import BaseModel, Field


class SyncStatusResponse(BaseModel):
    state: str
    last_started_at: str | None
    last_finished_at: str | None
    items_synced: int
    current_step: str | None = None
    current_library: str | None = None
    libraries_total: int = 0
    libraries_completed: int = 0
    items_discovered: int = 0
    detail_requests_total: int = 0
    detail_requests_completed: int = 0
    current_page: int = 0
    current_page_size: int = 0
    current_library_total_items: int = 0
    phase_started_at: str | None = None
    timings: dict[str, float] = Field(default_factory=dict)
    failed_items: int = 0
    duration_seconds: float | None = None
    last_result: str | None = None
    last_analysis_at: str | None = None
    analysis_groups: int = 0
    analysis_error: str | None = None
    error: str | None
