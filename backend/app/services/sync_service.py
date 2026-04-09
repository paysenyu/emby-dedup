"""Sync service: Emby snapshot -> media source rows + sync status tracking."""

import json
import logging
import os
import re
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, as_completed, wait
from datetime import datetime
from threading import Lock
from time import perf_counter

from app.db.database import SessionLocal
from app.db.models import AnalysisResult, MediaItem
from app.schemas.sync import SyncStatusResponse
from app.services.analysis_orchestrator_service import run_analysis_singleflight as run_analysis
from app.services.emby_client import EmbyClient
from app.services.settings_service import load_settings

logger = logging.getLogger(__name__)

_ZH_LANG_CODES = {"zh", "chi", "zho", "zh-cn", "zh-tw", "zh-hans", "zh-hant"}
_ZH_HINTS = {
    "zh",
    "chinese",
    "chi",
    "zho",
    "\u4e2d\u6587",
    "\u7b80\u4f53",
    "\u7e41\u4f53",
    "\u7e41\u9ad4",
    "\u5b57\u5e55",
}
_SIMPLIFIED_HINTS = {"\u7b80", "\u7b80\u4f53", "chs", "gb", "hans", "simplified"}
_TRADITIONAL_HINTS = {"\u7e41", "\u7e41\u4f53", "\u7e41\u9ad4", "cht", "big5", "hant", "traditional"}
_BILINGUAL_HINTS = {"\u4e2d\u82f1", "\u53cc\u8bed", "\u96d9\u8a9e", "bilingual", "chi&eng", "chs&eng", "cht&eng", "zh+en"}
_MEDIA_SOURCE_DELETE_TARGET_PATTERN = re.compile(r"^mediasource_(\d+)$", re.IGNORECASE)
_TMDB_HINT_PATTERNS = (
    re.compile(r"(?:\{|\(|\[)?\s*tmdb(?:id)?\s*[:=_-]\s*(\d+)", re.IGNORECASE),
    re.compile(r"\b(?:tmdb)[\s_-]*(\d+)\b", re.IGNORECASE),
)
_LIBRARY_PAGE_SIZE = 4000
_FALLBACK_SAMPLE_LIMIT = 50


def _library_page_size() -> int:
    raw = _normalize_str(os.getenv("APP_SYNC_LIBRARY_PAGE_SIZE", str(_LIBRARY_PAGE_SIZE)))
    try:
        return max(1, int(raw))
    except ValueError:
        return _LIBRARY_PAGE_SIZE


def _derive_delete_target_item_id(media_source_id: str, emby_item_id: str) -> str:
    media_source = _normalize_str(media_source_id)
    match = _MEDIA_SOURCE_DELETE_TARGET_PATTERN.match(media_source)
    if match:
        return match.group(1)
    return _normalize_str(emby_item_id)


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat()


def _parse_iso(ts: str | None) -> datetime | None:
    text = str(ts or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _calc_duration_seconds(start_ts: str | None, end_ts: str | None) -> float | None:
    start = _parse_iso(start_ts)
    end = _parse_iso(end_ts)
    if not start or not end:
        return None
    delta = (end - start).total_seconds()
    if delta < 0:
        return None
    return round(delta, 3)


def _normalize_str(value: object) -> str:
    return str(value or "").strip()


def _normalize_lower(value: object) -> str:
    return _normalize_str(value).lower()


def _normalize_path(value: str) -> str:
    return _normalize_str(value).replace("\\", "/").rstrip("/").lower()


def _to_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_fraction(value: object) -> float | None:
    text = _normalize_str(value)
    if not text:
        return None
    if "/" in text:
        left, _, right = text.partition("/")
        try:
            denominator = float(right)
            if denominator == 0:
                return None
            return float(left) / denominator
        except (TypeError, ValueError):
            return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _extract_provider_ids(item: dict) -> dict:
    provider_ids = item.get("ProviderIds")
    return provider_ids if isinstance(provider_ids, dict) else {}


def _extract_media_sources(item: dict) -> list[dict]:
    media_sources = item.get("MediaSources")
    if not isinstance(media_sources, list):
        return []
    return [source for source in media_sources if isinstance(source, dict)]


def _extract_streams_from_source(source: dict) -> list[dict]:
    source_streams = source.get("MediaStreams")
    if not isinstance(source_streams, list):
        return []
    return [stream for stream in source_streams if isinstance(stream, dict)]


def _extract_item_level_streams(item: dict) -> list[dict]:
    raw = item.get("MediaStreams")
    if not isinstance(raw, list):
        return []
    return [stream for stream in raw if isinstance(stream, dict)]


def _is_playable_media_item(item: dict) -> bool:
    item_type = _normalize_lower(item.get("Type"))
    if item_type not in {"movie", "episode"}:
        return False
    if bool(item.get("IsFolder")):
        return False
    return True


def _extract_source_path(item: dict, source: dict) -> str:
    source_path = _normalize_str(source.get("Path"))
    if source_path:
        return source_path

    item_path = _normalize_str(item.get("Path"))
    if item_path:
        return item_path

    for src in _extract_media_sources(item):
        fallback = _normalize_str(src.get("Path"))
        if fallback:
            return fallback
    return ""


def _extract_tmdb_id_hint(*texts: object) -> str:
    for raw in texts:
        text = _normalize_str(raw)
        if not text:
            continue
        for pattern in _TMDB_HINT_PATTERNS:
            match = pattern.search(text)
            if match:
                return _normalize_str(match.group(1))
    return ""


def _is_excluded_path(item_path: str, excluded_paths: list[str]) -> int:
    normalized_item = _normalize_path(item_path)
    if not normalized_item:
        return 0

    for excluded in excluded_paths:
        normalized_excluded = _normalize_path(excluded)
        if not normalized_excluded:
            continue
        if normalized_item == normalized_excluded or normalized_item.startswith(normalized_excluded + "/"):
            return 1
    return 0


def _extract_primary_stream(streams: list[dict], stream_type: str) -> dict:
    wanted = _normalize_lower(stream_type)
    typed = [s for s in streams if _normalize_lower(s.get("Type")) == wanted]
    if not typed:
        return {}

    defaults = [s for s in typed if bool(s.get("IsDefault"))]
    return defaults[0] if defaults else typed[0]


def _normalize_codec_label(codec: str) -> str:
    c = _normalize_lower(codec)
    if c in {"av1", "aomav1"}:
        return "AV1"
    if c in {"hevc", "h265", "h.265", "x265"}:
        return "HEVC"
    if c in {"h264", "h.264", "avc", "x264"}:
        return "H.264"
    if c in {"vp9", "vp09"}:
        return "VP9"
    return _normalize_str(codec).upper()


def _resolution_from_dimensions(width: int | None, height: int | None) -> str:
    if not width or not height:
        return ""
    bigger = max(width, height)
    if bigger >= 3840:
        return "4K"
    if bigger >= 1920:
        return "1080p"
    if bigger >= 1280:
        return "720p"
    return "480p"


def _normalize_effect_label(source: dict, video: dict) -> str:
    texts = [
        _normalize_lower(video.get("ExtendedVideoSubTypeDescription")),
        _normalize_lower(source.get("ExtendedVideoSubTypeDescription")),
        _normalize_lower(video.get("ExtendedVideoSubType")),
        _normalize_lower(source.get("ExtendedVideoSubType")),
        _normalize_lower(video.get("ExtendedVideoType")),
        _normalize_lower(source.get("ExtendedVideoType")),
        _normalize_lower(video.get("VideoRange")),
        _normalize_lower(source.get("VideoRange")),
        _normalize_lower(video.get("DisplayTitle")),
        _normalize_lower(source.get("Name")),
    ]
    merged = " | ".join([t for t in texts if t])

    if "dovi" in merged or "dolby vision" in merged or "dvhe" in merged:
        if "profile 8" in merged or "p8" in merged or "doviprofile8" in merged:
            return "DoVi P8"
        if "profile 7" in merged or "p7" in merged or "doviprofile7" in merged:
            return "DoVi P7"
        if "profile 5" in merged or "p5" in merged or "doviprofile5" in merged:
            return "DoVi P5"
        return "DoVi (Other)"

    if "hdr10+" in merged or "hdr 10+" in merged or "hdr10plus" in merged:
        return "HDR10+"

    if "hdr10" in merged or "hdr" in merged:
        return "HDR"

    return "SDR"


def _normalize_subtitle_stream(stream: dict) -> dict:
    return {
        "codec": _normalize_str(stream.get("Codec")),
        "language": _normalize_str(stream.get("Language")),
        "title": _normalize_str(stream.get("Title")),
        "display_title": _normalize_str(stream.get("DisplayTitle")),
        "display_language": _normalize_str(stream.get("DisplayLanguage")),
        "is_default": bool(stream.get("IsDefault")),
        "is_forced": bool(stream.get("IsForced")),
        "is_external": bool(stream.get("IsExternal")),
        "subtitle_location_type": _normalize_str(stream.get("SubtitleLocationType")),
    }


def _normalize_audio_stream(stream: dict) -> dict:
    return {
        "codec": _normalize_str(stream.get("Codec")),
        "display_title": _normalize_str(stream.get("DisplayTitle")),
        "channel_layout": _normalize_str(stream.get("ChannelLayout")),
        "channels": _to_int(stream.get("Channels")),
        "bitrate": _to_int(stream.get("BitRate")),
        "sample_rate": _to_int(stream.get("SampleRate")),
        "profile": _normalize_str(stream.get("Profile")),
        "is_default": bool(stream.get("IsDefault")),
    }


def _subtitle_category(subtitles: list[dict]) -> str:
    has_chinese = False
    has_simplified = False
    has_traditional = False
    has_bilingual = False

    for stream in subtitles:
        parts = [
            _normalize_lower(stream.get("language")),
            _normalize_lower(stream.get("title")),
            _normalize_lower(stream.get("display_title")),
            _normalize_lower(stream.get("display_language")),
        ]
        text = " ".join([p for p in parts if p])

        if any(code in text for code in _ZH_LANG_CODES) or any(hint in text for hint in _ZH_HINTS):
            has_chinese = True
        if any(hint in text for hint in _SIMPLIFIED_HINTS):
            has_simplified = True
        if any(hint in text for hint in _TRADITIONAL_HINTS):
            has_traditional = True
        if any(hint in text for hint in _BILINGUAL_HINTS) or (("eng" in text or "english" in text) and has_chinese):
            has_bilingual = True

    if has_simplified:
        return "simplified"
    if has_traditional:
        return "traditional"
    if has_bilingual:
        return "bilingual_cn"
    if has_chinese:
        return "generic_chinese"
    return "none"


def _subtitle_rank(category: str) -> int:
    ranks = {
        "none": 0,
        "generic_chinese": 1,
        "bilingual_cn": 2,
        "traditional": 3,
        "simplified": 4,
    }
    return ranks.get(category, 0)


def _has_chinese_subtitle(item: dict) -> int:
    """Backward-compatible helper used by tests and legacy callers."""
    streams = _extract_item_level_streams(item)
    subtitles = [_normalize_subtitle_stream(s) for s in streams if _normalize_lower(s.get("Type")) == "subtitle"]
    category = _subtitle_category(subtitles)
    return 1 if _subtitle_rank(category) > 0 else 0


def _needs_detail_fallback(item: dict) -> bool:
    return bool(_fallback_reasons(item))


def _fallback_reasons(item: dict) -> list[str]:
    reasons: list[str] = []

    provider_ids = _extract_provider_ids(item)
    tmdb_id = _normalize_str(provider_ids.get("Tmdb"))
    tmdb_hint = _extract_tmdb_id_hint(
        item.get("Path"),
        item.get("Name"),
        item.get("SeriesName"),
    )
    if not tmdb_id and not tmdb_hint:
        reasons.append("provider_ids_missing_no_tmdb_hint")

    media_sources = _extract_media_sources(item)
    item_streams = _extract_item_level_streams(item)
    if not media_sources and not item_streams:
        reasons.append("media_sources_and_streams_missing")

    if not _normalize_str(item.get("Name")):
        reasons.append("name_missing")

    if not _normalize_str(item.get("Path")) and not any(_normalize_str(src.get("Path")) for src in media_sources):
        reasons.append("path_missing")

    item_type = _normalize_lower(item.get("Type"))
    if item_type == "episode":
        if not _normalize_str(item.get("SeriesName")):
            reasons.append("episode_series_name_missing")
        if _to_int(item.get("ParentIndexNumber")) is None:
            reasons.append("episode_season_missing")
        if _to_int(item.get("IndexNumber")) is None:
            reasons.append("episode_index_missing")

    return reasons


def _infer_library_subfolder(item_path: str, library_name: str) -> str:
    path = _normalize_str(item_path).replace("\\", "/")
    if not path:
        return ""

    segments = [seg.strip() for seg in path.split("/") if seg and seg.strip()]
    if not segments:
        return ""

    lib = _normalize_lower(library_name)
    if lib:
        for idx, seg in enumerate(segments):
            if _normalize_lower(seg) == lib and idx + 1 < len(segments):
                return segments[idx + 1]

    if len(segments) >= 2:
        return segments[-2]
    return ""


def _media_item_to_mapping(item: MediaItem) -> dict:
    return {column.name: getattr(item, column.name) for column in MediaItem.__table__.columns}


def _fetch_item_detail_for_fallback(base_url: str, api_key: str, user_id: str, item_id: str) -> dict:
    client = EmbyClient(base_url=base_url, api_key=api_key)
    return client.get_item_detail(user_id=user_id, item_id=item_id)


class SyncStatusTracker:
    """In-memory tracker for sync state."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._state = "idle"
        self._last_started_at: str | None = None
        self._last_finished_at: str | None = None
        self._items_synced = 0
        self._current_step: str | None = None
        self._current_library: str | None = None
        self._libraries_total = 0
        self._libraries_completed = 0
        self._items_discovered = 0
        self._detail_requests_total = 0
        self._detail_requests_completed = 0
        self._current_page = 0
        self._current_page_size = 0
        self._current_library_total_items = 0
        self._phase_started_at: str | None = None
        self._timings: dict[str, float] = {}
        self._failed_items = 0
        self._duration_seconds: float | None = None
        self._last_result: str | None = None
        self._last_analysis_at: str | None = None
        self._analysis_groups = 0
        self._analysis_error: str | None = None
        self._error: str | None = None

    def get_status(self) -> SyncStatusResponse:
        with self._lock:
            return SyncStatusResponse(
                state=self._state,
                last_started_at=self._last_started_at,
                last_finished_at=self._last_finished_at,
                items_synced=self._items_synced,
                current_step=self._current_step,
                current_library=self._current_library,
                libraries_total=self._libraries_total,
                libraries_completed=self._libraries_completed,
                items_discovered=self._items_discovered,
                detail_requests_total=self._detail_requests_total,
                detail_requests_completed=self._detail_requests_completed,
                current_page=self._current_page,
                current_page_size=self._current_page_size,
                current_library_total_items=self._current_library_total_items,
                phase_started_at=self._phase_started_at,
                timings=dict(self._timings),
                failed_items=self._failed_items,
                duration_seconds=self._duration_seconds,
                last_result=self._last_result,
                last_analysis_at=self._last_analysis_at,
                analysis_groups=self._analysis_groups,
                analysis_error=self._analysis_error,
                error=self._error,
            )

    def start(self) -> bool:
        with self._lock:
            if self._state == "running":
                return False
            self._state = "running"
            self._last_started_at = _utc_now_iso()
            self._last_finished_at = None
            self._items_synced = 0
            self._current_step = "initializing"
            self._current_library = None
            self._libraries_total = 0
            self._libraries_completed = 0
            self._items_discovered = 0
            self._detail_requests_total = 0
            self._detail_requests_completed = 0
            self._current_page = 0
            self._current_page_size = 0
            self._current_library_total_items = 0
            self._phase_started_at = self._last_started_at
            self._timings = {}
            self._failed_items = 0
            self._duration_seconds = None
            self._last_result = None
            self._analysis_error = None
            self._error = None
            return True

    def set_context(self, *, step: str | None = None, library: str | None = None) -> None:
        with self._lock:
            if step is not None and step != self._current_step:
                self._current_step = step
                self._phase_started_at = _utc_now_iso()
            elif step is not None:
                self._current_step = step
            if library is not None:
                self._current_library = library

    def set_library_totals(self, total: int) -> None:
        with self._lock:
            self._libraries_total = max(0, int(total))

    def set_library_progress(self, completed: int) -> None:
        with self._lock:
            self._libraries_completed = max(0, int(completed))

    def set_page_context(self, *, page: int, page_size: int, total_items: int, library: str | None = None) -> None:
        with self._lock:
            self._current_page = max(0, int(page))
            self._current_page_size = max(0, int(page_size))
            self._current_library_total_items = max(0, int(total_items))
            if library is not None:
                self._current_library = library

    def increment_items_discovered(self, count: int = 1) -> None:
        with self._lock:
            self._items_discovered = max(0, int(self._items_discovered + max(0, count)))

    def increment_detail_requests_total(self, count: int = 1) -> None:
        with self._lock:
            self._detail_requests_total = max(0, int(self._detail_requests_total + max(0, count)))

    def increment_detail_requests_completed(self, count: int = 1) -> None:
        with self._lock:
            self._detail_requests_completed = max(0, int(self._detail_requests_completed + max(0, count)))

    def set_items_synced(self, count: int) -> None:
        with self._lock:
            self._items_synced = max(0, int(count))

    def increment_failed_items(self, count: int = 1) -> None:
        with self._lock:
            self._failed_items = max(0, int(self._failed_items + max(0, count)))

    def record_timing(self, name: str, seconds: float) -> None:
        with self._lock:
            rounded = round(max(0.0, float(seconds)), 3)
            self._timings[name] = round(self._timings.get(name, 0.0) + rounded, 3)

    def set_analysis_result(self, *, groups: int = 0, error: str | None = None, duration_seconds: float | None = None) -> None:
        with self._lock:
            self._last_analysis_at = _utc_now_iso()
            self._analysis_groups = max(0, int(groups))
            self._analysis_error = error
            if duration_seconds is not None:
                self._timings["analysis"] = round(max(0.0, float(duration_seconds)), 3)

    def finish_success(self, items_synced: int = 0) -> None:
        with self._lock:
            self._state = "idle"
            self._last_finished_at = _utc_now_iso()
            self._items_synced = items_synced
            self._current_step = "completed"
            self._current_library = None
            self._current_page = 0
            self._current_page_size = 0
            self._current_library_total_items = 0
            self._phase_started_at = self._last_finished_at
            self._duration_seconds = _calc_duration_seconds(self._last_started_at, self._last_finished_at)
            self._last_result = "success"
            self._error = None

    def finish_failure(self, message: str) -> None:
        with self._lock:
            self._state = "idle"
            self._last_finished_at = _utc_now_iso()
            self._current_step = "failed"
            self._current_library = None
            self._current_page = 0
            self._current_page_size = 0
            self._current_library_total_items = 0
            self._phase_started_at = self._last_finished_at
            self._duration_seconds = _calc_duration_seconds(self._last_started_at, self._last_finished_at)
            self._last_result = "failed"
            self._error = message


sync_status_tracker = SyncStatusTracker()


def _normalize_media_item_versions(detail: dict, library_name: str, excluded_paths: list[str]) -> list[MediaItem]:
    now = _utc_now_iso()
    provider_ids = _extract_provider_ids(detail)
    tmdb_id = _normalize_str(provider_ids.get("Tmdb"))
    if not tmdb_id:
        tmdb_id = _extract_tmdb_id_hint(
            detail.get("Path"),
            detail.get("Name"),
            detail.get("SeriesName"),
        )
    imdb_id = _normalize_str(provider_ids.get("Imdb"))
    tvdb_id = _normalize_str(provider_ids.get("Tvdb"))
    emby_item_id = _normalize_str(detail.get("Id"))

    source_items = _extract_media_sources(detail)
    if not source_items:
        source_items = [{}]

    runtime_ticks_detail = _to_int(detail.get("RunTimeTicks"))
    rows: list[MediaItem] = []

    for index, source in enumerate(source_items):
        streams = _extract_streams_from_source(source)
        if not streams:
            streams = _extract_item_level_streams(detail)

        video = _extract_primary_stream(streams, "video")
        audio_streams = [_normalize_audio_stream(s) for s in streams if _normalize_lower(s.get("Type")) == "audio"]
        subtitle_streams = [_normalize_subtitle_stream(s) for s in streams if _normalize_lower(s.get("Type")) == "subtitle"]
        primary_audio = next((a for a in audio_streams if a.get("is_default")), audio_streams[0] if audio_streams else {})

        source_path = _extract_source_path(detail, source)
        if not tmdb_id:
            tmdb_id = _extract_tmdb_id_hint(source_path)
        width = _to_int(video.get("Width"))
        height = _to_int(video.get("Height"))
        average_fps = _parse_fraction(video.get("AverageFrameRate"))
        real_fps = _parse_fraction(video.get("RealFrameRate"))
        frame_rate = real_fps if real_fps is not None else average_fps

        runtime_ticks = _to_int(source.get("RunTimeTicks"))
        if runtime_ticks is None:
            runtime_ticks = runtime_ticks_detail
        runtime_seconds = (runtime_ticks / 10_000_000) if runtime_ticks else None

        media_source_id = _normalize_str(source.get("Id")) or f"{emby_item_id}:source:{index}"
        delete_target_item_id = _derive_delete_target_item_id(media_source_id, emby_item_id)
        subtitle_category = _subtitle_category(subtitle_streams)
        subtitle_rank = _subtitle_rank(subtitle_category)
        media_source_name = _normalize_str(source.get("Name")) or _normalize_str(detail.get("Name"))
        video_codec = _normalize_str(video.get("Codec")).lower()

        rows.append(
            MediaItem(
                emby_item_id=emby_item_id,
                media_source_id=media_source_id,
                delete_target_item_id=delete_target_item_id,
                media_source_name=media_source_name,
                library_name=library_name,
                item_type=_normalize_str(detail.get("Type")),
                title=_normalize_str(detail.get("Name")),
                series_title=_normalize_str(detail.get("SeriesName")),
                production_year=_to_int(detail.get("ProductionYear")),
                tmdb_id=tmdb_id,
                imdb_id=imdb_id,
                tvdb_id=tvdb_id,
                season_number=_to_int(detail.get("ParentIndexNumber")),
                episode_number=_to_int(detail.get("IndexNumber")),
                container=_normalize_str(source.get("Container")).lower(),
                path=source_path,
                file_size=_to_int(source.get("Size")),
                bitrate=_to_int(source.get("Bitrate") or detail.get("Bitrate")),
                runtime_ticks=runtime_ticks,
                runtime_seconds=runtime_seconds,
                video_codec=video_codec,
                codec_label=_normalize_codec_label(video_codec),
                video_display_title=_normalize_str(video.get("DisplayTitle")),
                video_range=_normalize_str(video.get("VideoRange") or source.get("VideoRange")),
                bit_depth=_to_int(video.get("BitDepth")),
                video_width=width,
                video_height=height,
                average_frame_rate=average_fps,
                real_frame_rate=real_fps,
                frame_rate=frame_rate,
                video_profile=_normalize_str(video.get("Profile")),
                pixel_format=_normalize_str(video.get("PixelFormat")),
                color_transfer=_normalize_str(video.get("ColorTransfer")),
                color_primaries=_normalize_str(video.get("ColorPrimaries")),
                color_space=_normalize_str(video.get("ColorSpace")),
                extended_video_type=_normalize_str(video.get("ExtendedVideoType") or source.get("ExtendedVideoType")),
                extended_video_sub_type=_normalize_str(video.get("ExtendedVideoSubType") or source.get("ExtendedVideoSubType")),
                extended_video_sub_type_description=_normalize_str(
                    video.get("ExtendedVideoSubTypeDescription") or source.get("ExtendedVideoSubTypeDescription")
                ),
                audio_codec=_normalize_str(primary_audio.get("codec")),
                audio_display_title=_normalize_str(primary_audio.get("display_title")),
                audio_channel_layout=_normalize_str(primary_audio.get("channel_layout")),
                audio_channels=_to_int(primary_audio.get("channels")),
                audio_bitrate=_to_int(primary_audio.get("bitrate")),
                audio_sample_rate=_to_int(primary_audio.get("sample_rate")),
                audio_profile=_normalize_str(primary_audio.get("profile")),
                audio_is_default=1 if bool(primary_audio.get("is_default")) else 0,
                resolution_label=_resolution_from_dimensions(width, height),
                effect_label=_normalize_effect_label(source, video),
                subtitle_streams_json=json.dumps(subtitle_streams, ensure_ascii=False),
                audio_streams_json=json.dumps(audio_streams, ensure_ascii=False),
                has_chinese_subtitle=1 if subtitle_rank > 0 else 0,
                chinese_subtitle_rank=subtitle_rank,
                eligible_for_dedup=1 if tmdb_id else 0,
                is_excluded_path=_is_excluded_path(source_path, excluded_paths),
                date_created=_normalize_str(detail.get("DateCreated")),
                date_added=_normalize_str(detail.get("DateLastMediaAdded") or detail.get("DateCreated")),
                raw_json=json.dumps(detail, ensure_ascii=False),
                created_at=now,
                updated_at=now,
            )
        )

    return rows


def _consume_detail_future(
    future: Future,
    future_meta: dict[Future, tuple[str, str, float]],
    normalized_rows: list[MediaItem],
    excluded_paths: list[str],
) -> tuple[float, float, bool]:
    library_name, item_id, started_at = future_meta.pop(future)
    sync_status_tracker.increment_detail_requests_completed()
    detail_duration = perf_counter() - started_at

    try:
        detail = future.result()
    except Exception:
        sync_status_tracker.increment_failed_items()
        logger.exception(
            "Sync detail fallback failed at step=normalize_items library=%s item_id=%s",
            library_name,
            item_id,
        )
        return detail_duration, 0.0, False

    if not _is_playable_media_item(detail):
        logger.debug("Skipping non-playable detail fallback item library=%s item_id=%s", library_name, item_id)
        return detail_duration, 0.0, False

    normalize_started = perf_counter()
    version_rows = _normalize_media_item_versions(
        detail=detail,
        library_name=library_name,
        excluded_paths=excluded_paths,
    )
    normalize_duration = perf_counter() - normalize_started
    normalized_rows.extend(version_rows)
    sync_status_tracker.set_items_synced(len(normalized_rows))
    logger.debug(
        "Fallback normalized emby item library=%s item_id=%s media_sources=%s version_rows=%s",
        library_name,
        item_id,
        len(_extract_media_sources(detail)),
        len(version_rows),
    )
    return detail_duration, normalize_duration, True


def _drain_ready_fallbacks(
    pending_futures: set[Future],
    future_meta: dict[Future, tuple[str, str, float]],
    normalized_rows: list[MediaItem],
    excluded_paths: list[str],
) -> tuple[float, float, list[tuple[str, bool]]]:
    detail_total = 0.0
    normalize_total = 0.0
    outcomes: list[tuple[str, bool]] = []
    while pending_futures:
        done, _ = wait(pending_futures, timeout=0, return_when=FIRST_COMPLETED)
        if not done:
            break
        for future in done:
            library_name, _, _ = future_meta.get(future, ("", "", 0.0))
            pending_futures.remove(future)
            detail_duration, normalize_duration, ok = _consume_detail_future(
                future=future,
                future_meta=future_meta,
                normalized_rows=normalized_rows,
                excluded_paths=excluded_paths,
            )
            detail_total += detail_duration
            normalize_total += normalize_duration
            if library_name:
                outcomes.append((library_name, ok))
    return detail_total, normalize_total, outcomes


def run_full_sync_workflow() -> None:
    """Run full sync using paged list results first, then detail fallback only when needed."""
    db = SessionLocal()
    try:
        sync_status_tracker.set_context(step="loading_settings", library=None)
        settings = load_settings(db)
        user_id = _normalize_str(settings.emby.user_id)
        if not user_id:
            raise ValueError("No Emby user selected. Please set settings.emby.user_id first.")

        selected_libraries = [name.strip() for name in settings.libraries if isinstance(name, str) and name.strip()]
        if not selected_libraries:
            raise ValueError("No libraries selected. Please configure settings.libraries first.")

        client = EmbyClient(settings.emby.base_url, settings.emby.api_key)

        sync_status_tracker.set_context(step="discover_libraries", library=None)
        list_views_started = perf_counter()
        try:
            available_libraries = client.list_user_views(user_id)
        except Exception:
            logger.exception("Sync failed at step=discover_libraries user_id=%s", user_id)
            raise ValueError(f"Failed to list user-accessible libraries for user '{user_id}'.")
        list_views_duration = perf_counter() - list_views_started
        sync_status_tracker.record_timing("list_user_views", list_views_duration)
        logger.info("Sync discover libraries finished: user_id=%s duration=%.3fs", user_id, list_views_duration)

        by_name = {lib.get("name", "").lower(): lib for lib in available_libraries if lib.get("name")}
        selected_infos: list[dict[str, str]] = []
        for name in selected_libraries:
            lib = by_name.get(name.lower())
            if lib and lib.get("id"):
                selected_infos.append({"id": lib["id"], "name": lib["name"]})

        if not selected_infos:
            raise ValueError("Selected libraries are not accessible by the selected Emby user.")

        sync_status_tracker.set_library_totals(len(selected_infos))
        sync_status_tracker.set_items_synced(0)

        concurrency = 1
        normalized_rows: list[MediaItem] = []
        detail_total_duration = 0.0
        normalize_total_duration = 0.0
        pending_futures: set[Future] = set()
        future_meta: dict[Future, tuple[str, str, float]] = {}
        library_stats: dict[str, dict[str, int]] = {}
        fallback_reason_global: dict[str, int] = {}
        fallback_samples: list[dict[str, object]] = []

        def _ensure_library_stats(name: str) -> dict[str, int]:
            stats = library_stats.get(name)
            if stats is None:
                stats = {
                    "pages": 0,
                    "discovered": 0,
                    "playable": 0,
                    "fallback_queued": 0,
                    "fallback_completed": 0,
                    "fallback_failed": 0,
                }
                library_stats[name] = stats
            return stats

        def _inc_reason_counts(target: dict[str, int], reasons: list[str]) -> None:
            if not reasons:
                reasons = ["unknown"]
            for reason in reasons:
                key = _normalize_str(reason) or "unknown"
                target[key] = int(target.get(key, 0)) + 1

        sync_status_tracker.set_context(step="list_library_items", library=None)
        page_size = _library_page_size()
        logger.info("Sync page size configured: %s", page_size)
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            for library_index, lib in enumerate(selected_infos, start=1):
                library_started = perf_counter()
                page_index = 0
                start_index = 0
                discovered_for_library = 0
                playable_for_library = 0
                sync_status_tracker.set_context(step="list_library_items", library=lib["name"])
                current_library_stats = _ensure_library_stats(lib["name"])

                while True:
                    page_fetch_started = perf_counter()
                    try:
                        items, total_count = client.list_library_items_page(
                            user_id=user_id,
                            library_id=lib["id"],
                            start_index=start_index,
                            limit=page_size,
                        )
                    except Exception:
                        logger.exception("Sync failed at step=list_library_items library=%s", lib["name"])
                        raise ValueError(f"Failed to list items for library '{lib['name']}'.")

                    page_fetch_duration = perf_counter() - page_fetch_started
                    if not items:
                        logger.info(
                            "Library scan finished with empty page: library=%s page=%s fetched=0 duration=%.3fs",
                            lib["name"],
                            page_index + 1,
                            page_fetch_duration,
                        )
                        break

                    page_index += 1
                    current_library_stats["pages"] = page_index
                    sync_status_tracker.set_page_context(
                        page=page_index,
                        page_size=len(items),
                        total_items=total_count,
                        library=lib["name"],
                    )
                    logger.info(
                        "Library page scanned: library=%s page=%s page_size=%s total_items=%s fetch_duration=%.3fs",
                        lib["name"],
                        page_index,
                        len(items),
                        total_count,
                        page_fetch_duration,
                    )

                    playable_items: list[dict] = []
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        discovered_for_library += 1
                        if not _is_playable_media_item(item):
                            continue
                        playable_items.append(item)

                    playable_count = len(playable_items)
                    playable_for_library += playable_count
                    current_library_stats["discovered"] = discovered_for_library
                    current_library_stats["playable"] = playable_for_library
                    sync_status_tracker.increment_items_discovered(playable_count)
                    sync_status_tracker.set_context(step="normalize_items", library=lib["name"])

                    for item in playable_items:
                        item_id = _normalize_str(item.get("Id"))
                        if not item_id:
                            sync_status_tracker.increment_failed_items()
                            logger.warning("Skipping playable item without id: library=%s page=%s", lib["name"], page_index)
                            continue

                        if _needs_detail_fallback(item):
                            sync_status_tracker.increment_detail_requests_total()
                            current_library_stats["fallback_queued"] += 1
                            reasons = _fallback_reasons(item)
                            _inc_reason_counts(fallback_reason_global, reasons)
                            for reason in reasons or ["unknown"]:
                                per_lib_key = f"reason_{reason}"
                                current_library_stats[per_lib_key] = int(current_library_stats.get(per_lib_key, 0)) + 1

                            sample_path = _extract_source_path(item, {})
                            sample_subfolder = _infer_library_subfolder(sample_path, lib["name"])
                            if sample_subfolder:
                                subfolder_key = f"subfolder_{sample_subfolder}"
                                current_library_stats[subfolder_key] = int(current_library_stats.get(subfolder_key, 0)) + 1
                            if len(fallback_samples) < _FALLBACK_SAMPLE_LIMIT:
                                fallback_samples.append(
                                    {
                                        "library": lib["name"],
                                        "item_id": item_id,
                                        "item_type": _normalize_str(item.get("Type")),
                                        "name": _normalize_str(item.get("Name")),
                                        "series_name": _normalize_str(item.get("SeriesName")),
                                        "season_number": _to_int(item.get("ParentIndexNumber")),
                                        "episode_number": _to_int(item.get("IndexNumber")),
                                        "path": sample_path,
                                        "subfolder": sample_subfolder,
                                        "reasons": reasons or ["unknown"],
                                    }
                                )
                            started_at = perf_counter()
                            future = executor.submit(
                                _fetch_item_detail_for_fallback,
                                settings.emby.base_url,
                                settings.emby.api_key,
                                user_id,
                                item_id,
                            )
                            pending_futures.add(future)
                            future_meta[future] = (lib["name"], item_id, started_at)
                            continue

                        normalize_started = perf_counter()
                        version_rows = _normalize_media_item_versions(
                            detail=item,
                            library_name=lib["name"],
                            excluded_paths=settings.excluded_paths,
                        )
                        normalize_duration = perf_counter() - normalize_started
                        normalize_total_duration += normalize_duration
                        normalized_rows.extend(version_rows)
                        sync_status_tracker.set_items_synced(len(normalized_rows))
                        logger.debug(
                            "Direct normalized emby item library=%s item_id=%s media_sources=%s version_rows=%s",
                            lib["name"],
                            item_id,
                            len(_extract_media_sources(item)),
                            len(version_rows),
                        )

                    drained_detail, drained_normalize, drained_outcomes = _drain_ready_fallbacks(
                        pending_futures=pending_futures,
                        future_meta=future_meta,
                        normalized_rows=normalized_rows,
                        excluded_paths=settings.excluded_paths,
                    )
                    for drained_library_name, ok in drained_outcomes:
                        drained_stats = _ensure_library_stats(drained_library_name)
                        if ok:
                            drained_stats["fallback_completed"] += 1
                        else:
                            drained_stats["fallback_failed"] += 1
                    detail_total_duration += drained_detail
                    normalize_total_duration += drained_normalize

                    sync_status_tracker.set_context(step="list_library_items", library=lib["name"])
                    start_index += len(items)
                    if len(items) < page_size:
                        break
                    if total_count and start_index >= total_count:
                        break

                sync_status_tracker.set_library_progress(library_index)
                library_duration = perf_counter() - library_started
                sync_status_tracker.record_timing("list_library_items", library_duration)
                logger.info(
                    "Library scan finished: library=%s pages=%s discovered_items=%s playable_items=%s duration=%.3fs",
                    lib["name"],
                    page_index,
                    discovered_for_library,
                    playable_for_library,
                    library_duration,
                )

            if pending_futures:
                sync_status_tracker.set_context(step="normalize_items", library=None)
                for future in as_completed(list(pending_futures)):
                    library_name, _, _ = future_meta.get(future, ("", "", 0.0))
                    pending_futures.remove(future)
                    detail_duration, normalize_duration, ok = _consume_detail_future(
                        future=future,
                        future_meta=future_meta,
                        normalized_rows=normalized_rows,
                        excluded_paths=settings.excluded_paths,
                    )
                    if library_name:
                        completed_stats = _ensure_library_stats(library_name)
                        if ok:
                            completed_stats["fallback_completed"] += 1
                        else:
                            completed_stats["fallback_failed"] += 1
                    detail_total_duration += detail_duration
                    normalize_total_duration += normalize_duration

        completed_details = sync_status_tracker.get_status().detail_requests_completed
        sync_status_tracker.record_timing("detail_requests", detail_total_duration)
        sync_status_tracker.record_timing("normalize_items", normalize_total_duration)
        average_detail = (detail_total_duration / completed_details) if completed_details else 0.0
        logger.info(
            "Sync normalization finished: direct_and_fallback_rows=%s detail_requests_completed=%s detail_duration=%.3fs detail_avg=%.3fs normalize_duration=%.3fs",
            len(normalized_rows),
            completed_details,
            detail_total_duration,
            average_detail,
            normalize_total_duration,
        )
        if fallback_reason_global:
            logger.info(
                "Fallback reason summary (global): %s",
                json.dumps(dict(sorted(fallback_reason_global.items(), key=lambda kv: (-kv[1], kv[0]))), ensure_ascii=False),
            )
        if fallback_samples:
            logger.info("Fallback sample items (limited=%s): %s", _FALLBACK_SAMPLE_LIMIT, json.dumps(fallback_samples, ensure_ascii=False))
        if library_stats:
            for lib_name in sorted(library_stats.keys()):
                stats = library_stats[lib_name]
                reason_counts = {
                    k[len("reason_") :]: int(v)
                    for k, v in stats.items()
                    if k.startswith("reason_")
                }
                subfolder_counts = {
                    k[len("subfolder_") :]: int(v)
                    for k, v in stats.items()
                    if k.startswith("subfolder_")
                }
                logger.info(
                    "Library fallback summary: library=%s pages=%s discovered=%s playable=%s fallback_queued=%s fallback_completed=%s fallback_failed=%s reason_counts=%s subfolder_counts=%s",
                    lib_name,
                    int(stats.get("pages", 0)),
                    int(stats.get("discovered", 0)),
                    int(stats.get("playable", 0)),
                    int(stats.get("fallback_queued", 0)),
                    int(stats.get("fallback_completed", 0)),
                    int(stats.get("fallback_failed", 0)),
                    json.dumps(dict(sorted(reason_counts.items(), key=lambda kv: (-kv[1], kv[0]))), ensure_ascii=False),
                    json.dumps(dict(sorted(subfolder_counts.items(), key=lambda kv: (-kv[1], kv[0]))), ensure_ascii=False),
                )

        selected_library_names = [str(lib.get("name") or "") for lib in selected_infos if str(lib.get("name") or "").strip()]
        sync_status_tracker.set_context(step="rebuilding_media_items", library=None)
        db_delete_started = perf_counter()
        deleted_media_rows = 0
        if selected_library_names:
            deleted_media_rows = (
                db.query(MediaItem)
                .filter(MediaItem.library_name.in_(selected_library_names))
                .delete(synchronize_session=False)
            )
        db.query(AnalysisResult).delete(synchronize_session=False)
        db_delete_duration = perf_counter() - db_delete_started
        sync_status_tracker.record_timing("db_delete", db_delete_duration)

        db_insert_started = perf_counter()
        if normalized_rows:
            mappings = [_media_item_to_mapping(row) for row in normalized_rows]
            db.bulk_insert_mappings(MediaItem, mappings)
        db.commit()
        db_insert_duration = perf_counter() - db_insert_started
        sync_status_tracker.record_timing("db_insert", db_insert_duration)
        logger.info(
            "Sync database rebuild finished: selected_libraries=%s deleted_media_rows=%s delete_duration=%.3fs insert_duration=%.3fs inserted_rows=%s",
            selected_library_names,
            int(deleted_media_rows),
            db_delete_duration,
            db_insert_duration,
            len(normalized_rows),
        )

        analysis_groups = 0
        analysis_error: str | None = None
        sync_status_tracker.set_context(step="running_analysis", library=None)
        analysis_started = perf_counter()
        try:
            analysis_result = run_analysis(db)
            analysis_groups = int(analysis_result.groups)
        except Exception as exc:
            analysis_error = f"Auto analysis failed: {exc}"
            logger.exception("Sync auto-analysis failed")
        analysis_duration = perf_counter() - analysis_started
        sync_status_tracker.set_analysis_result(
            groups=analysis_groups,
            error=analysis_error,
            duration_seconds=analysis_duration,
        )

        sync_status_tracker.finish_success(items_synced=len(normalized_rows))
        logger.info(
            "Sync completed. user_id=%s items_synced=%s items_discovered=%s detail_requests_total=%s failed_items=%s analysis_groups=%s analysis_error=%s",
            user_id,
            len(normalized_rows),
            sync_status_tracker.get_status().items_discovered,
            sync_status_tracker.get_status().detail_requests_total,
            sync_status_tracker.get_status().failed_items,
            analysis_groups,
            analysis_error,
        )
    except Exception as exc:
        db.rollback()
        logger.exception("Sync workflow failed with exception")
        sync_status_tracker.finish_failure(f"Sync failed: {exc}")
    finally:
        db.close()
