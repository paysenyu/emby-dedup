"""Rule configuration persistence and defaults."""

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import RuleConfig
from app.schemas.rules import RulesPayload, RulesResponse


_CATEGORICAL_CHOICES: dict[str, list[str]] = {
    "codec": ["AV1", "HEVC", "H.264", "VP9"],
    "resolution": ["4K", "1080p", "720p", "480p"],
    "effect": ["DoVi P8", "DoVi P7", "DoVi P5", "DoVi (Other)", "HDR10+", "HDR", "SDR"],
    "subtitle": ["Chinese", "None"],
}

_DEFAULT_RULE_ROWS: list[dict] = [
    {"id": "subtitle", "enabled": True, "order": 1, "priority": _CATEGORICAL_CHOICES["subtitle"]},
    {"id": "runtime", "enabled": True, "order": 2, "priority": "desc"},
    {"id": "effect", "enabled": True, "order": 3, "priority": _CATEGORICAL_CHOICES["effect"]},
    {"id": "resolution", "enabled": True, "order": 4, "priority": _CATEGORICAL_CHOICES["resolution"]},
    {"id": "bit_depth", "enabled": True, "order": 5, "priority": "desc"},
    {"id": "bitrate", "enabled": True, "order": 6, "priority": "desc"},
    {"id": "codec", "enabled": True, "order": 7, "priority": _CATEGORICAL_CHOICES["codec"]},
    {"id": "filesize", "enabled": True, "order": 8, "priority": "desc"},
    {"id": "date_added", "enabled": True, "order": 9, "priority": "asc"},
    {"id": "frame_rate", "enabled": False, "order": 10, "priority": "desc"},
]


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat()


def _default_rules() -> list[dict]:
    return [dict(row) for row in _DEFAULT_RULE_ROWS]


def _safe_int(value: object, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _normalize_categorical_priority(rule_id: str, incoming: object) -> object:
    choices = _CATEGORICAL_CHOICES.get(rule_id)
    if not choices:
        return incoming

    ordered: list[str] = []
    if isinstance(incoming, list):
        for value in incoming:
            text = str(value or "").strip()
            if text in choices and text not in ordered:
                ordered.append(text)

    for choice in choices:
        if choice not in ordered:
            ordered.append(choice)

    return ordered


def _normalize_rule_rows(rules: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for index, rule in enumerate(rules, start=1):
        if not isinstance(rule, dict):
            continue
        rid = str(rule.get("id") or "").strip()
        if not rid:
            continue
        normalized.append(
            {
                "id": rid,
                "enabled": bool(rule.get("enabled", True)),
                "order": _safe_int(rule.get("order"), index),
                "priority": _normalize_categorical_priority(rid, rule.get("priority")),
            }
        )
    normalized.sort(key=lambda x: (x["order"], x["id"]))
    return normalized


def _get_or_create_row(db: Session) -> RuleConfig:
    row = db.query(RuleConfig).order_by(RuleConfig.id.asc()).first()
    if row is None:
        now = _utc_now_iso()
        row = RuleConfig(
            rules_json=json.dumps(_default_rules(), ensure_ascii=False),
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _persist_rules(db: Session, row: RuleConfig, rules: list[dict]) -> None:
    row.rules_json = json.dumps(rules, ensure_ascii=False)
    row.updated_at = _utc_now_iso()
    db.add(row)
    db.commit()
    db.refresh(row)


def load_rules(db: Session) -> RulesResponse:
    row = _get_or_create_row(db)
    try:
        raw_rules = json.loads(row.rules_json or "[]")
    except json.JSONDecodeError:
        raw_rules = []

    normalized = _normalize_rule_rows(raw_rules if isinstance(raw_rules, list) else [])
    if not normalized:
        normalized = _default_rules()
        _persist_rules(db, row, normalized)

    return RulesResponse(rules=normalized)


def save_rules(db: Session, payload: RulesPayload) -> RulesResponse:
    row = _get_or_create_row(db)
    normalized = _normalize_rule_rows([r.model_dump() for r in payload.rules])
    if not normalized:
        normalized = _default_rules()
    _persist_rules(db, row, normalized)
    return RulesResponse(rules=normalized)
