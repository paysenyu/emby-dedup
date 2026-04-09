"""SQLAlchemy models for Phase 1 and Phase 2."""

from datetime import datetime

from sqlalchemy import Integer, REAL, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class AppSettings(Base):
    """Persisted application settings."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    emby_base_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    emby_api_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
    emby_user_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    selected_libraries_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    excluded_paths_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    sync_concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    shenyi_base_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    shenyi_api_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
    webhook_token: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())


class MediaItem(Base):
    """Synced media source rows used by current and future phases."""

    __tablename__ = "media_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    emby_item_id: Mapped[str] = mapped_column(Text, nullable=False)
    media_source_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    delete_target_item_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    media_source_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    library_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    item_type: Mapped[str] = mapped_column(Text, nullable=False, default="")
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    series_title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    production_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tmdb_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    imdb_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tvdb_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    season_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    container: Mapped[str] = mapped_column(Text, nullable=False, default="")
    path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bitrate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    runtime_ticks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    runtime_seconds: Mapped[float | None] = mapped_column(REAL, nullable=True)

    video_codec: Mapped[str] = mapped_column(Text, nullable=False, default="")
    codec_label: Mapped[str] = mapped_column(Text, nullable=False, default="")
    video_display_title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    video_range: Mapped[str] = mapped_column(Text, nullable=False, default="")
    bit_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    average_frame_rate: Mapped[float | None] = mapped_column(REAL, nullable=True)
    real_frame_rate: Mapped[float | None] = mapped_column(REAL, nullable=True)
    frame_rate: Mapped[float | None] = mapped_column(REAL, nullable=True)
    video_profile: Mapped[str] = mapped_column(Text, nullable=False, default="")
    pixel_format: Mapped[str] = mapped_column(Text, nullable=False, default="")
    color_transfer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    color_primaries: Mapped[str] = mapped_column(Text, nullable=False, default="")
    color_space: Mapped[str] = mapped_column(Text, nullable=False, default="")
    extended_video_type: Mapped[str] = mapped_column(Text, nullable=False, default="")
    extended_video_sub_type: Mapped[str] = mapped_column(Text, nullable=False, default="")
    extended_video_sub_type_description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    audio_codec: Mapped[str] = mapped_column(Text, nullable=False, default="")
    audio_display_title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    audio_channel_layout: Mapped[str] = mapped_column(Text, nullable=False, default="")
    audio_channels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_bitrate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_profile: Mapped[str] = mapped_column(Text, nullable=False, default="")
    audio_is_default: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    resolution_label: Mapped[str] = mapped_column(Text, nullable=False, default="")
    effect_label: Mapped[str] = mapped_column(Text, nullable=False, default="")
    subtitle_streams_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    audio_streams_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    has_chinese_subtitle: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chinese_subtitle_rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    eligible_for_dedup: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_excluded_path: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    date_created: Mapped[str] = mapped_column(Text, nullable=False, default="")
    date_added: Mapped[str] = mapped_column(Text, nullable=False, default="")
    raw_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())


class RuleConfig(Base):
    """Persistent comparator rule configuration."""

    __tablename__ = "rule_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rules_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())


class AnalysisResult(Base):
    """Analysis output rows rebuilt for each analysis run."""

    __tablename__ = "analysis_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_key: Mapped[str] = mapped_column(Text, nullable=False)
    media_kind: Mapped[str] = mapped_column(Text, nullable=False)
    tmdb_id: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    season_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    item_id: Mapped[int] = mapped_column(Integer, nullable=False)
    emby_item_id: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    reason_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    is_manual_override: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())


class OperationLog(Base):
    """Minimal operational logging for delete execution."""

    __tablename__ = "operation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    delete_target_item_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    timestamp: Mapped[str] = mapped_column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())

class DeleteQueue(Base):
    """Persistent delete queue rows used for batched delete and webhook confirmation."""

    __tablename__ = "delete_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    item_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delete_target_item_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    emby_item_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    deleted_paths_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    delete_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    status_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())


class WebhookInbox(Base):
    """Persistent inbox for webhook events to mitigate early/late delivery races."""

    __tablename__ = "webhook_inbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False, default="")
    delete_target_item_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    emby_item_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    deleted_paths_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    is_valid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    process_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    matched_queue_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    raw_event_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())
    processed_at: Mapped[str] = mapped_column(Text, nullable=False, default="")
