"""Analysis grouping and result generation for Phase 2."""

import json
import logging
from collections import defaultdict
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import AnalysisResult, MediaItem
from app.schemas.analysis import (
    AnalysisGroupDetailResponse,
    AnalysisGroupItem,
    AnalysisGroupsResponse,
    AnalysisGroupSummary,
    AnalysisOverrideResponse,
    AnalysisRunResponse,
    ComparisonItemMetadata,
    ComparisonMetadata,
    GroupActionsSummary,
    KeepSummaryMetadata,
)
from app.services.comparator_service import compare_items
from app.services.rules_service import load_rules

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat()


def _normalize_str(value: object) -> str:
    return str(value or "").strip()


def _is_keep_action(action: str) -> bool:
    return action in {"keep_recommended", "keep_manual"}


def _is_valid_tmdb_id(value: object) -> bool:
    tmdb = _normalize_str(value)
    return bool(tmdb) and tmdb != "0"


def _media_kind(item: MediaItem) -> str | None:
    item_type = _normalize_str(item.item_type).lower()
    if item_type == "movie":
        return "movie"
    if item_type == "episode":
        return "episode"
    return None


def _group_key_for_item(item: MediaItem) -> str | None:
    if not _is_valid_tmdb_id(item.tmdb_id):
        return None

    kind = _media_kind(item)
    if kind == "movie":
        return f"movie:{item.tmdb_id}"
    if kind == "episode":
        if item.season_number is None or item.episode_number is None:
            return None
        return f"episode:{item.tmdb_id}:{item.season_number}:{item.episode_number}"
    return None


def _pick_keep_item(items: list[MediaItem], ordered_rules: list[dict]) -> tuple[MediaItem, str | None]:
    winner = sorted(items, key=lambda x: x.id)[0]
    winner_rule: str | None = None
    for candidate in sorted(items, key=lambda x: x.id)[1:]:
        result, rule_id = compare_items(candidate, winner, ordered_rules)
        if result > 0:
            winner = candidate
            winner_rule = rule_id
    return winner, winner_rule


def _load_json_list(text: str) -> list[dict]:
    try:
        raw = json.loads(text or "[]")
        if isinstance(raw, list):
            return [x for x in raw if isinstance(x, dict)]
    except json.JSONDecodeError:
        return []
    return []


def _subtitle_category(rank: int) -> str:
    mapping = {
        0: "none",
        1: "generic_chinese",
        2: "bilingual_cn",
        3: "traditional",
        4: "simplified",
    }
    return mapping.get(int(rank or 0), "none")


def _subtitle_label(rank: int) -> str:
    return "Chinese" if int(rank or 0) > 0 else "None"


def _item_metadata(media: MediaItem) -> ComparisonItemMetadata:
    subtitle_streams = _load_json_list(media.subtitle_streams_json)
    audio_streams = _load_json_list(media.audio_streams_json)
    subtitle_rank = int(media.chinese_subtitle_rank or 0)

    return ComparisonItemMetadata(
        has_chinese_subtitle=bool(media.has_chinese_subtitle),
        chinese_subtitle_rank=subtitle_rank,
        subtitle_category=_subtitle_category(subtitle_rank),
        runtime_ticks=media.runtime_ticks,
        runtime_seconds=media.runtime_seconds,
        effect_label=media.effect_label or "",
        resolution_label=media.resolution_label or "",
        codec_label=media.codec_label or "",
        bit_depth=media.bit_depth,
        bitrate=media.bitrate,
        frame_rate=media.frame_rate,
        file_size=media.file_size,
        container=media.container or "",
        media_source_name=media.media_source_name or "",
        path=media.path or "",
        video_codec=media.video_codec or "",
        video_display_title=media.video_display_title or "",
        video_range=media.video_range or "",
        video_profile=media.video_profile or "",
        video_width=media.video_width,
        video_height=media.video_height,
        average_frame_rate=media.average_frame_rate,
        real_frame_rate=media.real_frame_rate,
        pixel_format=media.pixel_format or "",
        color_transfer=media.color_transfer or "",
        color_primaries=media.color_primaries or "",
        color_space=media.color_space or "",
        extended_video_type=media.extended_video_type or "",
        extended_video_sub_type=media.extended_video_sub_type or "",
        extended_video_sub_type_description=media.extended_video_sub_type_description or "",
        audio_codec=media.audio_codec or "",
        audio_display_title=media.audio_display_title or "",
        audio_channel_layout=media.audio_channel_layout or "",
        audio_channels=media.audio_channels,
        audio_bitrate=media.audio_bitrate,
        audio_sample_rate=media.audio_sample_rate,
        audio_profile=media.audio_profile or "",
        audio_is_default=bool(media.audio_is_default),
        audio_streams=audio_streams,
        subtitle_streams=subtitle_streams,
        date_added=media.date_added or "",
        date_created=media.date_created or "",
    )


def run_analysis(db: Session) -> AnalysisRunResponse:
    rules = load_rules(db).rules
    ordered_rules = sorted([r.model_dump() for r in rules if r.enabled], key=lambda x: (x["order"], x["id"]))
    logger.info("Analysis run start: enabled_rules=%s", len(ordered_rules))

    media_items = (
        db.query(MediaItem)
        .filter(MediaItem.eligible_for_dedup == 1)
        .filter(MediaItem.tmdb_id != "")
        .filter(MediaItem.tmdb_id != "0")
        .all()
    )
    logger.info("Analysis source media rows: count=%s", len(media_items))

    grouped: dict[str, list[MediaItem]] = defaultdict(list)
    for item in media_items:
        key = _group_key_for_item(item)
        if key:
            grouped[key].append(item)

    group_entries = {k: v for k, v in grouped.items() if len(v) >= 2}
    logger.info("Analysis grouped candidates: groups=%s", len(group_entries))

    deleted_old_rows = db.query(AnalysisResult).delete(synchronize_session=False)
    logger.info("Analysis cleanup old rows: deleted=%s", deleted_old_rows)

    now = _utc_now_iso()
    rows: list[AnalysisResult] = []

    for group_key, items in group_entries.items():
        sorted_items = sorted(items, key=lambda x: x.id)
        keep_item, winner_rule = _pick_keep_item(sorted_items, ordered_rules)

        media_kind = _media_kind(keep_item) or "movie"
        title = keep_item.series_title if media_kind == "episode" and keep_item.series_title else keep_item.title

        for item in sorted_items:
            if item.id == keep_item.id:
                action = "keep_recommended"
                reason = {"by": winner_rule or "stable_tie_breaker"}
            elif bool(item.is_excluded_path):
                action = "protected"
                reason = {"by": "excluded_path"}
            else:
                action = "delete_candidate"
                reason = {"by": "comparator_loser"}

            rows.append(
                AnalysisResult(
                    group_key=group_key,
                    media_kind=media_kind,
                    tmdb_id=item.tmdb_id,
                    title=title,
                    season_number=item.season_number,
                    episode_number=item.episode_number,
                    item_id=item.id,
                    emby_item_id=item.emby_item_id,
                    action=action,
                    reason_json=json.dumps(reason, ensure_ascii=False),
                    is_manual_override=0,
                    created_at=now,
                    updated_at=now,
                )
            )

    if rows:
        db.add_all(rows)
    db.commit()
    logger.info("Analysis run end: inserted_rows=%s groups=%s", len(rows), len(group_entries))

    return AnalysisRunResponse(status="ok", groups=len(group_entries), items=len(rows))


def list_groups(
    db: Session,
    page: int = 1,
    page_size: int = 50,
    library: str | None = None,
    protected_only: bool = False,
    has_manual_override: bool | None = None,
) -> AnalysisGroupsResponse:
    rows = db.query(AnalysisResult).order_by(AnalysisResult.group_key.asc(), AnalysisResult.id.asc()).all()

    by_group: dict[str, list[AnalysisResult]] = defaultdict(list)
    for row in rows:
        by_group[row.group_key].append(row)

    summaries: list[AnalysisGroupSummary] = []
    for group_key, group_rows in by_group.items():
        keep_row = next((r for r in group_rows if _is_keep_action(r.action)), None)
        delete_ids = [r.item_id for r in group_rows if r.action == "delete_candidate"]
        protected_ids = [r.item_id for r in group_rows if r.action == "protected"]
        override_flag = any(bool(r.is_manual_override) for r in group_rows)

        if protected_only and len(protected_ids) == 0:
            continue
        if has_manual_override is not None and override_flag != has_manual_override:
            continue

        item_ids = [r.item_id for r in group_rows]
        media_rows = db.query(MediaItem).filter(MediaItem.id.in_(item_ids)).all()
        media_by_id = {m.id: m for m in media_rows}

        if library and not any(m.library_name == library for m in media_rows):
            continue

        first = group_rows[0]
        keep_media = media_by_id.get(keep_row.item_id) if keep_row else None
        keep_meta = KeepSummaryMetadata(
            codec_label=(keep_media.codec_label if keep_media else "") or "",
            resolution_label=(keep_media.resolution_label if keep_media else "") or "",
            effect_label=(keep_media.effect_label if keep_media else "") or "",
            subtitle_label=_subtitle_label((keep_media.chinese_subtitle_rank if keep_media else 0) or 0),
        )

        summaries.append(
            AnalysisGroupSummary(
                group_id=group_key,
                media_kind=first.media_kind,
                title=first.title,
                comparison=ComparisonMetadata(
                    tmdb_id=first.tmdb_id,
                    season_number=first.season_number,
                    episode_number=first.episode_number,
                ),
                actions=GroupActionsSummary(
                    keep_item_id=keep_row.item_id if keep_row else None,
                    delete_candidate_item_ids=delete_ids,
                    protected_item_ids=protected_ids,
                ),
                item_count=len(group_rows),
                has_manual_override=override_flag,
                keep_metadata=keep_meta,
            )
        )

    summaries.sort(key=lambda x: x.group_id)
    total = len(summaries)

    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    start = (page - 1) * page_size
    end = start + page_size

    return AnalysisGroupsResponse(items=summaries[start:end], total=total, page=page, page_size=page_size)


def get_group_detail(db: Session, group_id: str) -> AnalysisGroupDetailResponse | None:
    rows = (
        db.query(AnalysisResult)
        .filter(AnalysisResult.group_key == group_id)
        .order_by(AnalysisResult.id.asc())
        .all()
    )
    if not rows:
        return None

    item_ids = [row.item_id for row in rows]
    media_rows = db.query(MediaItem).filter(MediaItem.id.in_(item_ids)).all()
    media_by_id = {item.id: item for item in media_rows}

    keep_item: AnalysisGroupItem | None = None
    delete_candidates: list[AnalysisGroupItem] = []
    protected_items: list[AnalysisGroupItem] = []

    for row in rows:
        media = media_by_id.get(row.item_id)
        if media is None:
            continue
        try:
            reason = json.loads(row.reason_json or "{}")
        except json.JSONDecodeError:
            reason = {}

        item = AnalysisGroupItem(
            item_id=media.id,
            emby_item_id=media.emby_item_id,
            media_source_id=media.media_source_id,
            delete_target_item_id=media.delete_target_item_id or media.emby_item_id,
            library_name=media.library_name,
            item_type=media.item_type,
            title=media.title,
            series_title=media.series_title,
            path=media.path,
            is_excluded_path=bool(media.is_excluded_path),
            action=row.action,
            reason=reason,
            metadata=_item_metadata(media),
        )

        if _is_keep_action(row.action):
            keep_item = item
        elif row.action == "delete_candidate":
            delete_candidates.append(item)
        elif row.action == "protected":
            protected_items.append(item)

    first = rows[0]
    return AnalysisGroupDetailResponse(
        group_id=first.group_key,
        media_kind=first.media_kind,
        title=first.title,
        comparison=ComparisonMetadata(
            tmdb_id=first.tmdb_id,
            season_number=first.season_number,
            episode_number=first.episode_number,
        ),
        keep_item=keep_item,
        delete_candidates=delete_candidates,
        protected_items=protected_items,
    )


def apply_manual_override(db: Session, group_id: str, keep_item_id: int) -> AnalysisOverrideResponse:
    rows = db.query(AnalysisResult).filter(AnalysisResult.group_key == group_id).all()
    if not rows:
        raise ValueError("Group not found.")

    target_row = next((r for r in rows if r.item_id == keep_item_id), None)
    if target_row is None:
        raise ValueError("keep_item_id does not belong to this group.")

    item_ids = [r.item_id for r in rows]
    media_rows = db.query(MediaItem).filter(MediaItem.id.in_(item_ids)).all()
    media_by_id = {m.id: m for m in media_rows}

    now = _utc_now_iso()
    for row in rows:
        media = media_by_id.get(row.item_id)
        if media is None:
            continue

        if row.item_id == keep_item_id:
            row.action = "keep_manual"
            reason = {"by": "manual_override"}
        elif bool(media.is_excluded_path):
            row.action = "protected"
            reason = {"by": "excluded_path"}
        else:
            row.action = "delete_candidate"
            reason = {"by": "manual_override_loser"}

        row.reason_json = json.dumps(reason, ensure_ascii=False)
        row.is_manual_override = 1
        row.updated_at = now
        db.add(row)

    db.commit()
    return AnalysisOverrideResponse(status="ok", group_id=group_id, keep_item_id=keep_item_id)
