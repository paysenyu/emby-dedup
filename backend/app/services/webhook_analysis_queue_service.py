"""Webhook-triggered analysis debounce queue with optional external dispatch."""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime

import requests

from app.db.database import SessionLocal
from app.services.analysis_orchestrator_service import run_analysis_singleflight

logger = logging.getLogger(__name__)

_DEBOUNCE_LOCK = threading.Lock()
_PENDING_TIMER: threading.Timer | None = None
_LAST_ENQUEUED_AT: str | None = None


def _normalize_seconds(value: str, default: float) -> float:
    try:
        return max(1.0, float(str(value).strip()))
    except Exception:
        return default


def _debounce_seconds() -> float:
    return _normalize_seconds(os.getenv("APP_WEBHOOK_ANALYSIS_DEBOUNCE_SECONDS", "45"), 45.0)


def _queue_mode() -> str:
    mode = str(os.getenv("APP_WEBHOOK_ANALYSIS_QUEUE_MODE", "http") or "").strip().lower()
    return mode if mode in {"inprocess", "http"} else "inprocess"


def _dispatch_http_queue(payload: dict) -> bool:
    queue_url = str(os.getenv("APP_WEBHOOK_ANALYSIS_QUEUE_URL", "") or "").strip()
    if not queue_url:
        return False
    headers = {"Content-Type": "application/json"}
    token = str(os.getenv("APP_WEBHOOK_ANALYSIS_QUEUE_TOKEN", "") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = requests.post(queue_url, json=payload, headers=headers, timeout=5.0)
        if 200 <= int(response.status_code) < 300:
            logger.info("Webhook analysis task dispatched to external queue: status=%s", response.status_code)
            return True
        logger.warning(
            "External queue dispatch failed: status=%s body=%s",
            response.status_code,
            str(response.text or "")[:300],
        )
        return False
    except Exception as exc:
        logger.warning("External queue dispatch failed unexpectedly: %s", exc)
        return False


def _run_analysis_task(trigger: str) -> None:
    db = SessionLocal()
    try:
        result = run_analysis_singleflight(db)
        logger.info(
            "Webhook debounce analysis executed: trigger=%s status=%s groups=%s items=%s",
            trigger,
            result.status,
            result.groups,
            result.items,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Webhook debounce analysis failed: trigger=%s error=%s", trigger, exc)
    finally:
        db.close()


def _fire_inprocess(trigger: str) -> None:
    global _PENDING_TIMER
    with _DEBOUNCE_LOCK:
        _PENDING_TIMER = None
    _run_analysis_task(trigger=trigger)


def _enqueue_inprocess(trigger: str) -> None:
    global _PENDING_TIMER, _LAST_ENQUEUED_AT
    with _DEBOUNCE_LOCK:
        delay = _debounce_seconds()
        if _PENDING_TIMER is not None:
            _PENDING_TIMER.cancel()
        _LAST_ENQUEUED_AT = datetime.utcnow().isoformat()
        timer = threading.Timer(delay, _fire_inprocess, args=(trigger,))
        timer.daemon = True
        _PENDING_TIMER = timer
        timer.start()
        logger.info(
            "Webhook analysis task debounced in-process: trigger=%s delay_seconds=%.1f enqueued_at=%s",
            trigger,
            delay,
            _LAST_ENQUEUED_AT,
        )


def enqueue_webhook_analysis(trigger: str, item: dict | None = None) -> None:
    payload = {
        "task": "analysis.debounce.run",
        "trigger": str(trigger or "webhook_new_item"),
        "enqueued_at": datetime.utcnow().isoformat(),
        "debounce_seconds": _debounce_seconds(),
        "item_id": str((item or {}).get("Id") or ""),
        "item_name": str((item or {}).get("Name") or ""),
    }
    mode = _queue_mode()
    if mode == "http":
        ok = _dispatch_http_queue(payload)
        if ok:
            return
        logger.warning("External webhook analysis queue unavailable; task not enqueued locally.")
        return
    _enqueue_inprocess(trigger=payload["trigger"])


def handle_external_webhook_analysis_task(payload: dict) -> dict:
    """Optional endpoint handler for external queue consumers."""
    trigger = str((payload or {}).get("trigger") or "external_queue")
    _enqueue_inprocess(trigger=trigger)
    return {"status": "ok", "queued": True, "mode": _queue_mode(), "payload": json.dumps(payload or {}, ensure_ascii=False)}
