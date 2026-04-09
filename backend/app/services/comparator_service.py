"""Ordered comparator engine for Phase 2 analysis."""

from datetime import datetime

from app.db.models import MediaItem


def _normalize_str(value: object) -> str:
    return str(value or "").strip().lower()


def _compare_numeric(a: float | int | None, b: float | int | None, direction: str) -> int:
    if a is None and b is None:
        return 0
    if a is None:
        return -1
    if b is None:
        return 1
    if a == b:
        return 0
    if _normalize_str(direction) == "asc":
        return 1 if a < b else -1
    return 1 if a > b else -1


def _compare_categorical(a: str, b: str, priority: object) -> int:
    av = _normalize_str(a)
    bv = _normalize_str(b)
    if av == bv:
        return 0
    if not isinstance(priority, list):
        return 0

    order = [_normalize_str(x) for x in priority]
    a_in = av in order
    b_in = bv in order

    if a_in and b_in:
        return 1 if order.index(av) < order.index(bv) else -1
    if a_in:
        return 1
    if b_in:
        return -1
    return 0


def _parse_iso(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _compare_date(a: str, b: str, direction: str) -> int:
    ad = _parse_iso(a)
    bd = _parse_iso(b)
    if ad is None and bd is None:
        return 0
    if ad is None:
        return -1
    if bd is None:
        return 1
    if ad == bd:
        return 0
    if _normalize_str(direction) == "asc":
        return 1 if ad < bd else -1
    return 1 if ad > bd else -1


def compare_items(item_a: MediaItem, item_b: MediaItem, ordered_rules: list[dict]) -> tuple[int, str | None]:
    """Return comparison result and winning rule id: 1 means item_a wins, -1 means item_b wins."""
    for rule in ordered_rules:
        rule_id = _normalize_str(rule.get("id"))
        if not bool(rule.get("enabled", False)):
            continue

        direction = _normalize_str(rule.get("priority"))
        result = 0

        if rule_id == "subtitle":
            # Business rule: Chinese > none, simplified > traditional.
            result = _compare_numeric(item_a.chinese_subtitle_rank, item_b.chinese_subtitle_rank, "desc")
        elif rule_id == "runtime":
            result = _compare_numeric(item_a.runtime_seconds, item_b.runtime_seconds, direction or "desc")
        elif rule_id == "effect":
            result = _compare_categorical(item_a.effect_label, item_b.effect_label, rule.get("priority"))
        elif rule_id == "resolution":
            result = _compare_categorical(item_a.resolution_label, item_b.resolution_label, rule.get("priority"))
        elif rule_id == "bit_depth":
            result = _compare_numeric(item_a.bit_depth, item_b.bit_depth, direction or "desc")
        elif rule_id == "bitrate":
            result = _compare_numeric(item_a.bitrate, item_b.bitrate, direction or "desc")
        elif rule_id == "codec":
            result = _compare_categorical(item_a.codec_label, item_b.codec_label, rule.get("priority"))
        elif rule_id == "filesize":
            result = _compare_numeric(item_a.file_size, item_b.file_size, direction or "desc")
        elif rule_id == "date_added":
            result = _compare_date(item_a.date_added, item_b.date_added, direction or "asc")
        elif rule_id == "frame_rate":
            result = _compare_numeric(item_a.frame_rate, item_b.frame_rate, direction or "desc")

        if result != 0:
            return result, rule_id

    return 0, None
