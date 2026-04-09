"""Pydantic schemas for analysis APIs."""

from pydantic import BaseModel, Field


class AnalysisRunResponse(BaseModel):
    status: str
    groups: int
    items: int


class ComparisonMetadata(BaseModel):
    tmdb_id: str
    season_number: int | None
    episode_number: int | None


class GroupActionsSummary(BaseModel):
    keep_item_id: int | None
    delete_candidate_item_ids: list[int] = Field(default_factory=list)
    protected_item_ids: list[int] = Field(default_factory=list)


class KeepSummaryMetadata(BaseModel):
    codec_label: str = ""
    resolution_label: str = ""
    effect_label: str = ""
    subtitle_label: str = ""


class AnalysisGroupSummary(BaseModel):
    group_id: str
    media_kind: str
    title: str
    comparison: ComparisonMetadata
    actions: GroupActionsSummary
    item_count: int
    has_manual_override: bool = False
    keep_metadata: KeepSummaryMetadata = Field(default_factory=KeepSummaryMetadata)


class AnalysisGroupsResponse(BaseModel):
    items: list[AnalysisGroupSummary] = Field(default_factory=list)
    total: int
    page: int
    page_size: int


class ComparisonItemMetadata(BaseModel):
    has_chinese_subtitle: bool
    chinese_subtitle_rank: int = 0
    subtitle_category: str = "none"

    runtime_ticks: int | None = None
    runtime_seconds: float | None = None

    effect_label: str = ""
    resolution_label: str = ""
    codec_label: str = ""
    bit_depth: int | None = None
    bitrate: int | None = None
    frame_rate: float | None = None
    file_size: int | None = None

    container: str = ""
    media_source_name: str = ""
    path: str = ""

    video_codec: str = ""
    video_display_title: str = ""
    video_range: str = ""
    video_profile: str = ""
    video_width: int | None = None
    video_height: int | None = None
    average_frame_rate: float | None = None
    real_frame_rate: float | None = None
    pixel_format: str = ""
    color_transfer: str = ""
    color_primaries: str = ""
    color_space: str = ""
    extended_video_type: str = ""
    extended_video_sub_type: str = ""
    extended_video_sub_type_description: str = ""

    audio_codec: str = ""
    audio_display_title: str = ""
    audio_channel_layout: str = ""
    audio_channels: int | None = None
    audio_bitrate: int | None = None
    audio_sample_rate: int | None = None
    audio_profile: str = ""
    audio_is_default: bool = False
    audio_streams: list[dict] = Field(default_factory=list)

    subtitle_streams: list[dict] = Field(default_factory=list)

    date_added: str = ""
    date_created: str = ""


class AnalysisGroupItem(BaseModel):
    item_id: int
    emby_item_id: str
    media_source_id: str
    delete_target_item_id: str
    library_name: str
    item_type: str
    title: str
    series_title: str
    path: str
    is_excluded_path: bool
    action: str
    reason: dict = Field(default_factory=dict)
    metadata: ComparisonItemMetadata


class AnalysisGroupDetailResponse(BaseModel):
    group_id: str
    media_kind: str
    title: str
    comparison: ComparisonMetadata
    keep_item: AnalysisGroupItem | None = None
    delete_candidates: list[AnalysisGroupItem] = Field(default_factory=list)
    protected_items: list[AnalysisGroupItem] = Field(default_factory=list)


class AnalysisOverridePayload(BaseModel):
    keep_item_id: int


class AnalysisOverrideResponse(BaseModel):
    status: str
    group_id: str
    keep_item_id: int
