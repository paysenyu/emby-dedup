"""Delete preview and execute services."""

from datetime import datetime, timedelta
import json
import logging
import os
import random
import time

from sqlalchemy.orm import Session

from app.db.models import AnalysisResult, DeleteQueue, MediaItem, OperationLog, WebhookInbox
from app.schemas.delete_preview import (
    DeleteExecuteItemResult,
    DeleteExecutePayload,
    DeleteExecuteResponse,
    DeletePreviewGroup,
    DeletePreviewPayload,
    DeletePreviewResponse,
    DeleteQueueEntry,
    DeleteQueueStatusResponse,
    DeleteWebhookPayload,
    DeleteWebhookResponse,
)
from app.services.analysis_service import get_group_detail
from app.services.emby_client import EmbyClient
from app.services.settings_service import load_settings
from app.services.shenyi_client import ShenyiClient, ShenyiServerError

logger = logging.getLogger(__name__)


IGNORED_ACTIONS = {"ignored"}
NON_DELETABLE_ACTIONS = {"protected", *IGNORED_ACTIONS}
DELETE_BATCH_SIZE = 25
DELETE_MAX_RETRIES = 3
DEFAULT_BATCH_DELAY_MIN_SECONDS = 1.0
DEFAULT_BATCH_DELAY_MAX_SECONDS = 2.0
DEFAULT_IN_PROGRESS_RETRY_INTERVAL_SECONDS = 60
STATUS_REASON_ACCEPTED = "accepted"
STATUS_REASON_WEBHOOK_CONFIRMED = "webhook_confirmed"
STATUS_REASON_PROBE_CONFIRMED = "probe_confirmed"
STATUS_REASON_TIMEOUT_EXISTS = "timeout_exists"
STATUS_REASON_INVALID_PAYLOAD = "invalid_payload"
STATUS_REASON_MANUAL_REQUIRED = "manual_cleanup_required"


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat()


def _parse_paths(raw: str) -> list[str]:
    try:
        data = json.loads(raw or "[]")
        if isinstance(data, list):
            return [str(x) for x in data if str(x).strip()]
    except Exception:
        return []
    return []


def _delete_batch_size() -> int:
    raw = os.getenv("APP_DELETE_BATCH_SIZE", str(DELETE_BATCH_SIZE)).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return DELETE_BATCH_SIZE


def _in_progress_retry_interval_seconds() -> int:
    raw = os.getenv(
        "APP_DELETE_INPROGRESS_RETRY_INTERVAL_SECONDS",
        str(DEFAULT_IN_PROGRESS_RETRY_INTERVAL_SECONDS),
    ).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_IN_PROGRESS_RETRY_INTERVAL_SECONDS


def _batch_delay_seconds() -> float:
    raw = os.getenv("APP_DELETE_BATCH_DELAY_SECONDS", "").strip()
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            return 0.0
    return random.uniform(DEFAULT_BATCH_DELAY_MIN_SECONDS, DEFAULT_BATCH_DELAY_MAX_SECONDS)


def _delete_preflight_enabled() -> bool:
    raw = str(os.getenv("APP_DELETE_PREFLIGHT_MULTI_VERSION", "1") or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _parse_iso(ts: str) -> datetime | None:
    raw = str(ts or "").strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is not None:
            return parsed.astimezone(tz=None).replace(tzinfo=None)
        return parsed
    except ValueError:
        return None


def _attempt_delete_once(
    db: Session,
    client: ShenyiClient,
    row: DeleteQueue,
    *,
    failure_status: str = "pending",
) -> bool:
    row.retry_count = int(row.retry_count or 0) + 1
    logger.info(
        "DeleteVersion request: id=%s item_id=%s target=%s retry_count=%s from_status=%s",
        int(row.id or 0),
        int(row.item_id or 0),
        str(row.delete_target_item_id or ""),
        int(row.retry_count or 0),
        str(row.delete_status or ""),
    )
    try:
        status_code, msg = client.delete_version(str(row.delete_target_item_id or ""))
        row.delete_status = "in_progress"
        row.status_reason = STATUS_REASON_ACCEPTED
        row.status_code = status_code
        row.message = msg or "DeleteVersion accepted. Waiting webhook confirmation."
        row.updated_at = _utc_now_iso()
        logger.info(
            "DeleteVersion response: id=%s target=%s status_code=%s new_status=%s",
            int(row.id or 0),
            str(row.delete_target_item_id or ""),
            status_code,
            row.delete_status,
        )
        _log_delete(
            db,
            item_id=str(row.item_id),
            delete_target_item_id=str(row.delete_target_item_id or ""),
            status="in_progress",
            status_reason=STATUS_REASON_ACCEPTED,
            status_code=status_code,
            message=row.message,
        )
        return True
    except ShenyiServerError as exc:
        row.status_code = exc.status_code
        row.updated_at = _utc_now_iso()
        if int(row.retry_count or 0) >= DELETE_MAX_RETRIES:
            row.delete_status = "failed"
            row.message = f"{str(exc)} (retried {DELETE_MAX_RETRIES} times)"
            logger.info(
                "DeleteVersion failed permanently: id=%s target=%s retry_count=%s status_code=%s message=%s",
                int(row.id or 0),
                str(row.delete_target_item_id or ""),
                int(row.retry_count or 0),
                exc.status_code,
                row.message,
            )
            _log_delete(
                db,
                item_id=str(row.item_id),
                delete_target_item_id=str(row.delete_target_item_id or ""),
                status="failed",
                status_reason=STATUS_REASON_TIMEOUT_EXISTS,
                status_code=exc.status_code,
                message=row.message,
            )
        else:
            row.delete_status = failure_status
            row.message = str(exc)
            logger.debug(
                "DeleteVersion failed, will retry: id=%s target=%s retry_count=%s next_status=%s message=%s",
                int(row.id or 0),
                str(row.delete_target_item_id or ""),
                int(row.retry_count or 0),
                row.delete_status,
                row.message,
            )
        return False
    except Exception as exc:  # pragma: no cover - defensive fallback
        row.status_code = None
        row.updated_at = _utc_now_iso()
        if int(row.retry_count or 0) >= DELETE_MAX_RETRIES:
            row.delete_status = "failed"
            row.message = f"{str(exc)} (retried {DELETE_MAX_RETRIES} times)"
            logger.exception(
                "DeleteVersion unexpected failure permanently: id=%s target=%s retry_count=%s message=%s",
                int(row.id or 0),
                str(row.delete_target_item_id or ""),
                int(row.retry_count or 0),
                row.message,
            )
            _log_delete(
                db,
                item_id=str(row.item_id),
                delete_target_item_id=str(row.delete_target_item_id or ""),
                status="failed",
                status_reason=STATUS_REASON_TIMEOUT_EXISTS,
                status_code=None,
                message=row.message,
            )
        else:
            row.delete_status = failure_status
            row.message = str(exc)
            logger.exception(
                "DeleteVersion unexpected failure, will retry: id=%s target=%s retry_count=%s next_status=%s",
                int(row.id or 0),
                str(row.delete_target_item_id or ""),
                int(row.retry_count or 0),
                row.delete_status,
            )
        return False


def _probe_delete_target_exists(
    emby_client: EmbyClient | None,
    *,
    user_id: str,
    delete_target_item_id: str,
) -> bool | None:
    target = str(delete_target_item_id or "").strip()
    if not target or emby_client is None:
        return None
    uid = str(user_id or "").strip()
    if uid:
        return bool(emby_client.user_item_exists(uid, target))
    return bool(emby_client.item_exists(target))


def _retry_in_progress_rows(
    db: Session,
    client: ShenyiClient,
    *,
    emby_client: EmbyClient | None = None,
    emby_user_id: str = "",
) -> None:
    now = datetime.utcnow()
    threshold = now - timedelta(seconds=_in_progress_retry_interval_seconds())
    rows = (
        db.query(DeleteQueue)
        .filter(DeleteQueue.delete_status == "in_progress")
        .order_by(DeleteQueue.id.asc())
        .all()
    )
    changed = False
    logger.debug("Retry in-progress queue scan: total=%s", len(rows))
    for row in rows:
        updated_at = _parse_iso(str(row.updated_at or ""))
        if int(row.retry_count or 0) >= DELETE_MAX_RETRIES:
            # Keep a final waiting window after the last retry so late webhook
            # callbacks can still arrive and flip the row to done.
            if updated_at is not None and updated_at > threshold:
                continue
            probe_result: bool | None = None
            try:
                probe_result = _probe_delete_target_exists(
                    emby_client,
                    user_id=emby_user_id,
                    delete_target_item_id=str(row.delete_target_item_id or ""),
                )
            except Exception as exc:
                row.delete_status = "failed"
                row.status_reason = STATUS_REASON_TIMEOUT_EXISTS
                row.message = f"Webhook timeout and Emby probe failed ({exc})."
                row.updated_at = _utc_now_iso()
                logger.warning(
                    "Queue probe failed: id=%s item_id=%s target=%s error=%s",
                    int(row.id or 0),
                    int(row.item_id or 0),
                    str(row.delete_target_item_id or ""),
                    exc,
                )
                _log_delete(
                    db,
                    item_id=str(row.item_id),
                    delete_target_item_id=str(row.delete_target_item_id or ""),
                    status="failed",
                    status_reason=STATUS_REASON_TIMEOUT_EXISTS,
                    status_code=row.status_code,
                    message=row.message,
                )
                changed = True
                continue

            if probe_result is False:
                row.delete_status = "done"
                row.status_reason = STATUS_REASON_PROBE_CONFIRMED
                row.message = f"Confirmed by Emby probe (target={str(row.delete_target_item_id or '')})."
                logger.info(
                    "Queue status transition: id=%s item_id=%s in_progress->done reason=probe_confirmed",
                    int(row.id or 0),
                    int(row.item_id or 0),
                )
                media_deleted = db.query(MediaItem).filter(MediaItem.id == int(row.item_id or 0)).delete(synchronize_session=False)
                analysis_deleted = db.query(AnalysisResult).filter(AnalysisResult.item_id == int(row.item_id or 0)).delete(
                    synchronize_session=False
                )
                logger.info(
                    "Local cleanup by probe: item_id=%s media_items_deleted=%s analysis_results_deleted=%s",
                    int(row.item_id or 0),
                    media_deleted,
                    analysis_deleted,
                )
                queue_group_id = str(row.group_id or "")
                remaining = db.query(AnalysisResult).filter(AnalysisResult.group_key == queue_group_id).count()
                if remaining <= 1:
                    group_cleared = db.query(AnalysisResult).filter(AnalysisResult.group_key == queue_group_id).delete(
                        synchronize_session=False
                    )
                    logger.info(
                        "Group cleanup by probe: group_id=%s cleared_analysis_rows=%s remaining_before_clear=%s",
                        queue_group_id,
                        group_cleared,
                        remaining,
                    )
            else:
                row.delete_status = "failed"
                row.status_reason = STATUS_REASON_TIMEOUT_EXISTS
                if probe_result is True:
                    row.message = f"Webhook timeout and Emby item still exists (target={str(row.delete_target_item_id or '')})."
                else:
                    row.message = f"Webhook timeout and Emby probe unavailable (target={str(row.delete_target_item_id or '')})."
            row.updated_at = _utc_now_iso()
            logger.info(
                "Queue status transition: id=%s item_id=%s in_progress->%s reason=%s retry_count=%s",
                int(row.id or 0),
                int(row.item_id or 0),
                str(row.delete_status or ""),
                str(row.status_reason or ""),
                int(row.retry_count or 0),
            )
            _log_delete(
                db,
                item_id=str(row.item_id),
                delete_target_item_id=str(row.delete_target_item_id or ""),
                status=str(row.delete_status or ""),
                status_reason=str(row.status_reason or ""),
                status_code=row.status_code,
                message=row.message,
            )
            changed = True
            continue

        if updated_at is not None and updated_at > threshold:
            continue

        logger.debug(
            "Retrying in-progress queue row: id=%s item_id=%s retry_count=%s updated_at=%s threshold=%s",
            int(row.id or 0),
            int(row.item_id or 0),
            int(row.retry_count or 0),
            str(row.updated_at or ""),
            threshold.isoformat(),
        )
        _attempt_delete_once(db, client, row, failure_status="in_progress")
        changed = True

    if changed:
        db.commit()


def _log_delete(
    db: Session,
    *,
    item_id: str,
    delete_target_item_id: str,
    status: str,
    status_reason: str,
    status_code: int | None,
    message: str,
) -> None:
    db.add(
        OperationLog(
            item_id=item_id,
            delete_target_item_id=delete_target_item_id,
            status=status,
            status_reason=status_reason,
            status_code=status_code,
            message=message,
            timestamp=_utc_now_iso(),
        )
    )


def build_delete_preview(db: Session, payload: DeletePreviewPayload) -> DeletePreviewResponse:
    requested_ids = [gid for gid in payload.group_ids if gid]

    if requested_ids:
        group_ids = requested_ids
    else:
        group_ids = [
            str(group_key)
            for group_key, in db.query(AnalysisResult.group_key)
            .distinct()
            .order_by(AnalysisResult.group_key.asc())
            .all()
            if group_key
        ]

    groups: list[DeletePreviewGroup] = []
    delete_count = 0
    protected_count = 0

    for group_id in group_ids:
        detail = get_group_detail(db, group_id)
        if detail is None:
            continue

        groups.append(
            DeletePreviewGroup(
                group_id=detail.group_id,
                title=detail.title,
                media_kind=detail.media_kind,
                comparison=detail.comparison,
                keep_item=detail.keep_item,
                delete_candidates=detail.delete_candidates,
                protected_items=detail.protected_items,
            )
        )
        delete_count += len(detail.delete_candidates)
        protected_count += len(detail.protected_items)

    return DeletePreviewResponse(groups=groups, delete_count=delete_count, protected_count=protected_count)


def _candidate_query(db: Session, payload: DeleteExecutePayload):
    group_ids = [g for g in payload.group_ids if g]
    item_ids = [int(x) for x in payload.item_ids if int(x) > 0]

    query = db.query(AnalysisResult)
    if group_ids:
        query = query.filter(AnalysisResult.group_key.in_(group_ids))

    if item_ids:
        query = query.filter(AnalysisResult.item_id.in_(item_ids))
        query = query.filter(~AnalysisResult.action.in_(NON_DELETABLE_ACTIONS))
    else:
        query = query.filter(AnalysisResult.action == "delete_candidate")

    return query.order_by(AnalysisResult.group_key.asc(), AnalysisResult.item_id.asc())


def _chunked(values: list, size: int) -> list[list]:
    return [values[i : i + size] for i in range(0, len(values), size)]


def _queue_to_entry(row: DeleteQueue) -> DeleteQueueEntry:
    return DeleteQueueEntry(
        id=int(row.id),
        group_id=str(row.group_id or ""),
        item_id=int(row.item_id or 0),
        emby_item_id=str(row.emby_item_id or ""),
        delete_target_item_id=str(row.delete_target_item_id or ""),
        delete_status=str(row.delete_status or "pending"),
        status_reason=str(row.status_reason or ""),
        retry_count=int(row.retry_count or 0),
        status_code=row.status_code,
        message=str(row.message or ""),
        deleted_paths=_parse_paths(row.deleted_paths_json),
        created_at=str(row.created_at or ""),
        updated_at=str(row.updated_at or ""),
    )


def _create_webhook_inbox_rows(db: Session, *, event_type: str, normalized_events: list[dict], raw_payload: dict) -> list[WebhookInbox]:
    created: list[WebhookInbox] = []
    now = _utc_now_iso()
    raw_payload_json = json.dumps(raw_payload or {}, ensure_ascii=False)
    for event in normalized_events:
        row = WebhookInbox(
            event_type=str(event_type or ""),
            delete_target_item_id=str(event.get("delete_target_item_id", "") or ""),
            emby_item_id=str(event.get("emby_item_id", "") or ""),
            deleted_paths_json=json.dumps(list(event.get("deleted_paths", []) or []), ensure_ascii=False),
            is_valid=1 if bool(event.get("valid", False)) else 0,
            process_status="pending",
            matched_queue_ids_json="[]",
            message="",
            raw_event_json=raw_payload_json,
            created_at=now,
            processed_at="",
        )
        db.add(row)
        created.append(row)
    if created:
        db.flush()
    return created


def _is_target_deletable_multiversion(
    *,
    emby_client: EmbyClient | None,
    user_id: str,
    delete_target_item_id: str,
) -> tuple[bool, str]:
    if not _delete_preflight_enabled():
        return True, ""
    if emby_client is None:
        return True, ""
    uid = str(user_id or "").strip()
    target = str(delete_target_item_id or "").strip()
    if not uid or not target:
        return True, ""
    try:
        detail = emby_client.get_item_detail(user_id=uid, item_id=target)
    except Exception as exc:
        logger.warning("Delete preflight skipped (detail unavailable): target=%s error=%s", target, exc)
        return True, ""

    media_sources = detail.get("MediaSources")
    if not isinstance(media_sources, list):
        media_sources = []
    if len(media_sources) <= 1:
        return False, "Target is not merged multi-version in Emby. Please clean up manually in Emby."
    return True, ""


def _latest_key_for_row(row: DeleteQueue) -> str:
    target = str(row.delete_target_item_id or "").strip()
    if target:
        return f"target:{target}"
    return f"item:{int(row.item_id or 0)}"


def _dedupe_latest_rows(rows: list[DeleteQueue]) -> list[DeleteQueue]:
    latest_by_key: dict[str, DeleteQueue] = {}
    for row in rows:
        latest_by_key[_latest_key_for_row(row)] = row
    deduped = list(latest_by_key.values())
    deduped.sort(key=lambda x: int(x.id or 0))
    return deduped


def list_delete_queue_status(db: Session, ids: list[int], limit: int = 20, latest_only: bool = True) -> DeleteQueueStatusResponse:
    try:
        settings = load_settings(db)
        client = ShenyiClient(settings.shenyi.base_url, settings.shenyi.api_key)
        emby_client = None
        try:
            emby_client = EmbyClient(settings.emby.base_url, settings.emby.api_key)
        except Exception:
            emby_client = None
        _retry_in_progress_rows(
            db,
            client,
            emby_client=emby_client,
            emby_user_id=str(settings.emby.user_id or ""),
        )
        _replay_pending_webhook_inbox(db)
    except Exception:
        # Queue status should still be readable even if retry loop is unavailable.
        pass

    valid_ids = [int(x) for x in ids if int(x) > 0]
    query = db.query(DeleteQueue)
    if valid_ids:
        query = query.filter(DeleteQueue.id.in_(valid_ids))
        rows = query.order_by(DeleteQueue.id.asc()).all()
    else:
        rows = query.order_by(DeleteQueue.id.desc()).limit(max(1, min(int(limit), 500))).all()
        rows.reverse()

    if latest_only:
        rows = _dedupe_latest_rows(rows)
        if not valid_ids:
            rows = rows[-max(1, min(int(limit), 500)) :]

    logger.debug("Queue status fetched: count=%s ids=%s limit=%s", len(rows), valid_ids, int(limit))
    return DeleteQueueStatusResponse(items=[_queue_to_entry(row) for row in rows])


def _process_webhook_event(
    db: Session,
    *,
    event: dict,
    inbox_row: WebhookInbox | None = None,
) -> tuple[int, int]:
    target = str(event.get("delete_target_item_id", "") or "").strip()
    emby_item_id = str(event.get("emby_item_id", "") or "").strip()
    deleted_paths = [str(x) for x in list(event.get("deleted_paths", []) or []) if str(x).strip()]
    is_valid = bool(event.get("valid", False))
    has_paths = bool(deleted_paths)
    logger.debug(
        "Process delete webhook event: target=%s emby_item_id=%s deleted_paths=%s valid=%s",
        target,
        emby_item_id,
        len(deleted_paths),
        is_valid,
    )

    if not is_valid and not has_paths:
        logger.info(
            "Invalid webhook payload ignored safely: missing item identifier target=%s emby_item_id=%s",
            target,
            emby_item_id,
        )
        if inbox_row is not None:
            inbox_row.process_status = "ignored"
            inbox_row.message = "invalid_payload"
            inbox_row.processed_at = _utc_now_iso()
        return 0, 0

    base_query = db.query(DeleteQueue).filter(DeleteQueue.delete_status.in_(["pending", "in_progress", "failed"]))
    queue_rows: list[DeleteQueue] = []
    if target:
        queue_rows = (
            base_query.filter(DeleteQueue.delete_target_item_id == target)
            .order_by(DeleteQueue.id.asc())
            .all()
        )
        logger.debug("Queue match by delete_target_item_id=%s rows=%s", target, len(queue_rows))
    if not queue_rows and emby_item_id:
        queue_rows = (
            base_query.filter(DeleteQueue.emby_item_id == emby_item_id)
            .order_by(DeleteQueue.id.asc())
            .all()
        )
        logger.debug("Queue fallback match by emby_item_id=%s rows=%s", emby_item_id, len(queue_rows))
    if not queue_rows and deleted_paths:
        pending_rows = base_query.order_by(DeleteQueue.id.asc()).all()
        path_set = {p.replace("\\", "/").strip().lower() for p in deleted_paths if str(p).strip()}
        for pending in pending_rows:
            media = db.query(MediaItem).filter(MediaItem.id == int(pending.item_id)).first()
            media_path = str(getattr(media, "path", "") or "").replace("\\", "/").strip().lower()
            queued_paths = {
                p.replace("\\", "/").strip().lower()
                for p in _parse_paths(str(pending.deleted_paths_json or "[]"))
                if str(p).strip()
            }
            if media_path and media_path in path_set:
                queue_rows.append(pending)
                continue
            if queued_paths.intersection(path_set):
                queue_rows.append(pending)
        logger.debug("Queue fallback match by deleted_paths rows=%s", len(queue_rows))
    if not queue_rows:
        if inbox_row is not None:
            inbox_row.process_status = "pending"
            inbox_row.message = "unmatched"
            inbox_row.processed_at = _utc_now_iso()
        logger.info(
            "Webhook event unmatched: target=%s emby_item_id=%s deleted_paths=%s",
            target,
            emby_item_id,
            len(deleted_paths),
        )
        return 0, 0

    logger.info(
        "Webhook event matched queue rows: ids=%s deleted_paths=%s",
        [int(x.id) for x in queue_rows],
        deleted_paths,
    )
    matched = len(queue_rows)
    updated = 0
    matched_ids: list[int] = []
    for queue_row in queue_rows:
        matched_ids.append(int(queue_row.id or 0))
        queue_item_id = int(queue_row.item_id)
        queue_group_id = str(queue_row.group_id or "")
        queue_target = str(queue_row.delete_target_item_id or "")

        if deleted_paths:
            queue_row.deleted_paths_json = json.dumps(deleted_paths, ensure_ascii=False)
        queue_row.delete_status = "done"
        queue_row.status_reason = STATUS_REASON_WEBHOOK_CONFIRMED
        queue_row.message = f"Webhook confirmed delete (target={queue_target})."
        queue_row.updated_at = _utc_now_iso()
        logger.info(
            "Queue status transition: id=%s item_id=%s ->done deleted_paths=%s",
            int(queue_row.id or 0),
            queue_item_id,
            len(deleted_paths),
        )

        media_deleted = db.query(MediaItem).filter(MediaItem.id == queue_item_id).delete(synchronize_session=False)
        analysis_deleted = db.query(AnalysisResult).filter(AnalysisResult.item_id == queue_item_id).delete(
            synchronize_session=False
        )
        logger.info(
            "Local cleanup: item_id=%s media_items_deleted=%s analysis_results_deleted=%s",
            queue_item_id,
            media_deleted,
            analysis_deleted,
        )

        remaining = db.query(AnalysisResult).filter(AnalysisResult.group_key == queue_group_id).count()
        if remaining <= 1:
            group_cleared = db.query(AnalysisResult).filter(AnalysisResult.group_key == queue_group_id).delete(
                synchronize_session=False
            )
            logger.info(
                "Group cleanup: group_id=%s cleared_analysis_rows=%s remaining_before_clear=%s",
                queue_group_id,
                group_cleared,
                remaining,
            )

        _log_delete(
            db,
            item_id=str(queue_item_id),
            delete_target_item_id=queue_target,
            status="done",
            status_reason=STATUS_REASON_WEBHOOK_CONFIRMED,
            status_code=queue_row.status_code,
            message=queue_row.message,
        )
        updated += 1

    if inbox_row is not None:
        inbox_row.process_status = "matched"
        inbox_row.message = "matched"
        inbox_row.matched_queue_ids_json = json.dumps(matched_ids, ensure_ascii=False)
        inbox_row.processed_at = _utc_now_iso()
    return matched, updated


def _replay_pending_webhook_inbox(db: Session, limit: int = 200) -> tuple[int, int]:
    rows = (
        db.query(WebhookInbox)
        .filter(WebhookInbox.process_status == "pending")
        .order_by(WebhookInbox.id.asc())
        .limit(max(1, int(limit)))
        .all()
    )
    matched_total = 0
    updated_total = 0
    for row in rows:
        event = {
            "delete_target_item_id": str(row.delete_target_item_id or ""),
            "emby_item_id": str(row.emby_item_id or ""),
            "deleted_paths": _parse_paths(str(row.deleted_paths_json or "[]")),
            "valid": bool(int(row.is_valid or 0)),
        }
        matched, updated = _process_webhook_event(db, event=event, inbox_row=row)
        matched_total += matched
        updated_total += updated
    if rows:
        db.commit()
    return matched_total, updated_total


def execute_deletes(db: Session, payload: DeleteExecutePayload) -> DeleteExecuteResponse:
    candidate_rows = _candidate_query(db, payload).all()
    # Snapshot scalar fields early. Webhook callbacks can delete analysis rows
    # while this function is still running, which would make ORM instances
    # raise "Instance ... has been deleted" on attribute access after commits.
    candidates = [
        {
            "group_key": str(c.group_key or ""),
            "item_id": int(c.item_id),
            "emby_item_id": str(c.emby_item_id or ""),
            "action": str(c.action or ""),
        }
        for c in candidate_rows
    ]
    logger.info(
        "Delete execution start: candidates=%s group_ids=%s item_ids=%s",
        len(candidates),
        [str(x) for x in payload.group_ids],
        [int(x) for x in payload.item_ids],
    )

    if not candidates:
        logger.info("Delete execution finished with no candidates.")
        return DeleteExecuteResponse(success_count=0, failed_count=0, results=[])

    settings = load_settings(db)
    client = ShenyiClient(settings.shenyi.base_url, settings.shenyi.api_key)
    emby_client = None
    try:
        emby_client = EmbyClient(settings.emby.base_url, settings.emby.api_key)
    except Exception:
        emby_client = None
    _retry_in_progress_rows(
        db,
        client,
        emby_client=emby_client,
        emby_user_id=str(settings.emby.user_id or ""),
    )
    _replay_pending_webhook_inbox(db)

    candidate_item_ids = [int(c["item_id"]) for c in candidates]
    media_rows = db.query(MediaItem).filter(MediaItem.id.in_(candidate_item_ids)).all() if candidate_item_ids else []
    media_by_id: dict[int, dict] = {}
    for m in media_rows:
        media_by_id[int(m.id)] = {
            "id": int(m.id),
            "title": str(m.title or ""),
            "path": str(m.path or ""),
            "media_source_id": str(m.media_source_id or ""),
            "is_excluded_path": bool(m.is_excluded_path),
            "delete_target_item_id": str(m.delete_target_item_id or ""),
        }
    existing_open_rows = (
        db.query(DeleteQueue)
        .filter(
            DeleteQueue.delete_status.in_(["pending", "in_progress"]),
            DeleteQueue.item_id.in_(candidate_item_ids),
        )
        .order_by(DeleteQueue.id.asc())
        .all()
        if candidate_item_ids
        else []
    )
    existing_open_by_item_id: dict[int, DeleteQueue] = {}
    for row in existing_open_rows:
        existing_open_by_item_id.setdefault(int(row.item_id), row)

    queue_rows: list[DeleteQueue] = []
    queue_by_item_id: dict[int, DeleteQueue] = {}
    results: list[DeleteExecuteItemResult] = []
    success_count = 0
    failed_count = 0

    for candidate in candidates:
        candidate_group_key = str(candidate["group_key"] or "")
        candidate_item_id = int(candidate["item_id"])
        candidate_emby_item_id = str(candidate["emby_item_id"] or "")
        candidate_action = str(candidate["action"] or "")

        media = media_by_id.get(candidate_item_id)
        if media is None:
            message = "Item no longer exists in local media snapshot."
            logger.info(
                "Delete execution failed: missing media snapshot row item_id=%s emby_item_id=%s",
                candidate_item_id,
                candidate_emby_item_id,
            )
            results.append(
                DeleteExecuteItemResult(
                    group_id=candidate_group_key,
                    item_id=candidate_item_id,
                    emby_item_id=candidate_emby_item_id,
                    media_source_id="",
                    delete_target_item_id=candidate_emby_item_id,
                    action=candidate_action,
                    delete_status="pending",
                    status_reason=STATUS_REASON_TIMEOUT_EXISTS,
                    deleted_paths=[],
                    status="failed",
                    status_code=None,
                    message=message,
                )
            )
            _log_delete(
                db,
                item_id=str(candidate_item_id),
                delete_target_item_id=str(candidate_emby_item_id or ""),
                status="failed",
                status_reason=STATUS_REASON_TIMEOUT_EXISTS,
                status_code=None,
                message=message,
            )
            failed_count += 1
            continue

        media_source_id = str(media.get("media_source_id", "") or "")
        media_path = str(media.get("path", "") or "")
        is_excluded_path = bool(media.get("is_excluded_path", False))
        delete_target = str(media.get("delete_target_item_id", "") or candidate_emby_item_id)
        deleted_paths = [media_path] if media_path else []
        existing_row = existing_open_by_item_id.get(candidate_item_id)
        if existing_row is not None:
            logger.info(
                "Delete execution reused existing queue row: id=%s item_id=%s delete_target_item_id=%s status=%s retry_count=%s",
                int(existing_row.id or 0),
                candidate_item_id,
                str(existing_row.delete_target_item_id or ""),
                str(existing_row.delete_status or ""),
                int(existing_row.retry_count or 0),
            )
            queue_by_item_id[candidate_item_id] = existing_row
            continue

        if is_excluded_path or candidate_action in NON_DELETABLE_ACTIONS:
            message = "Skipped: item is protected or ignored and cannot be deleted."
            logger.info(
                "Delete execution skipped: item_id=%s action=%s excluded=%s",
                candidate_item_id,
                candidate_action,
                is_excluded_path,
            )
            results.append(
                DeleteExecuteItemResult(
                    group_id=candidate_group_key,
                    item_id=candidate_item_id,
                    emby_item_id=candidate_emby_item_id,
                    media_source_id=media_source_id,
                    delete_target_item_id=delete_target,
                    action=candidate_action,
                    delete_status="pending",
                    status_reason="skipped",
                    deleted_paths=deleted_paths,
                    status="skipped",
                    status_code=None,
                    message=message,
                )
            )
            _log_delete(
                db,
                item_id=str(candidate_item_id),
                delete_target_item_id=delete_target,
                status="skipped",
                status_reason="skipped",
                status_code=None,
                message=message,
            )
            failed_count += 1
            continue

        is_deletable, preflight_message = _is_target_deletable_multiversion(
            emby_client=emby_client,
            user_id=str(settings.emby.user_id or ""),
            delete_target_item_id=delete_target,
        )
        if not is_deletable:
            message = preflight_message or "Delete preflight rejected. Manual cleanup required."
            logger.info(
                "Delete execution preflight rejected: item_id=%s target=%s message=%s",
                candidate_item_id,
                delete_target,
                message,
            )
            results.append(
                DeleteExecuteItemResult(
                    group_id=candidate_group_key,
                    item_id=candidate_item_id,
                    emby_item_id=candidate_emby_item_id,
                    media_source_id=media_source_id,
                    delete_target_item_id=delete_target,
                    action=candidate_action,
                    delete_status="failed",
                    status_reason=STATUS_REASON_MANUAL_REQUIRED,
                    deleted_paths=deleted_paths,
                    status="failed",
                    status_code=None,
                    message=message,
                )
            )
            _log_delete(
                db,
                item_id=str(candidate_item_id),
                delete_target_item_id=delete_target,
                status="failed",
                status_reason=STATUS_REASON_MANUAL_REQUIRED,
                status_code=None,
                message=message,
            )
            failed_count += 1
            continue

        queue_rows.append(
            DeleteQueue(
                group_id=candidate_group_key,
                item_id=candidate_item_id,
                delete_target_item_id=delete_target,
                emby_item_id=candidate_emby_item_id,
                deleted_paths_json=json.dumps(deleted_paths, ensure_ascii=False),
                delete_status="pending",
                status_reason="",
                retry_count=0,
                status_code=None,
                message="Queued for DeleteVersion.",
                created_at=_utc_now_iso(),
                updated_at=_utc_now_iso(),
            )
        )

    if queue_rows:
        db.add_all(queue_rows)
        db.flush()
        # Persist queue rows before sending DeleteVersion so early webhook callbacks
        # can always match by queue identifiers.
        db.commit()
        _replay_pending_webhook_inbox(db)
        logger.info("Delete queue rows inserted: count=%s", len(queue_rows))

    for row in queue_rows:
        queue_by_item_id[int(row.item_id)] = row

    batches = _chunked(queue_rows, _delete_batch_size())
    logger.info("Delete queue batching: batches=%s batch_size=%s", len(batches), _delete_batch_size())
    for batch_index, batch in enumerate(batches):
        logger.info(
            "Processing delete batch: index=%s size=%s",
            batch_index + 1,
            len(batch),
        )
        for row in batch:
            if str(row.delete_status or "") in {"done", "failed"}:
                logger.info(
                    "Delete batch skip row already terminal: id=%s item_id=%s status=%s reason=%s",
                    int(row.id or 0),
                    int(row.item_id or 0),
                    str(row.delete_status or ""),
                    str(row.status_reason or ""),
                )
                continue
            media = media_by_id.get(int(row.item_id))
            logger.debug(
                "Delete attempt queued: title=%s path=%s emby_item_id=%s media_source_id=%s delete_target_item_id=%s",
                str(media.get("title", "") or ""),
                str(media.get("path", "") or ""),
                str(row.emby_item_id or ""),
                str(media.get("media_source_id", "") or ""),
                str(row.delete_target_item_id or ""),
            )
            while int(row.retry_count or 0) < DELETE_MAX_RETRIES and row.delete_status != "in_progress":
                if _attempt_delete_once(db, client, row):
                    break
            if row.delete_status != "in_progress" and int(row.retry_count or 0) >= DELETE_MAX_RETRIES:
                row.delete_status = "failed"
                row.status_reason = STATUS_REASON_TIMEOUT_EXISTS
                row.updated_at = _utc_now_iso()
                if not str(row.message or "").strip():
                    row.message = f"DeleteVersion failed after {DELETE_MAX_RETRIES} retries."
                logger.info(
                    "Queue status transition: id=%s item_id=%s pending->failed retry_count=%s",
                    int(row.id or 0),
                    int(row.item_id or 0),
                    int(row.retry_count or 0),
                )
            elif row.delete_status == "in_progress":
                logger.info(
                    "Queue status transition: id=%s item_id=%s pending->in_progress retry_count=%s",
                    int(row.id or 0),
                    int(row.item_id or 0),
                    int(row.retry_count or 0),
                )
            # Commit each row immediately so fast webhook callbacks can see
            # the latest queue status in a different DB session.
            db.commit()
        if batch_index < len(batches) - 1:
            delay = _batch_delay_seconds()
            logger.debug("Delete batch delay: index=%s delay_seconds=%.3f", batch_index + 1, delay)
            time.sleep(delay)

    for candidate in candidates:
        candidate_group_key = str(candidate["group_key"] or "")
        candidate_item_id = int(candidate["item_id"])
        candidate_emby_item_id = str(candidate["emby_item_id"] or "")
        candidate_action = str(candidate["action"] or "")
        media = media_by_id.get(candidate_item_id)

        if media is None:
            continue

        row = queue_by_item_id.get(candidate_item_id)
        media_source_id = str(media.get("media_source_id", "") or "")
        delete_target = str(media.get("delete_target_item_id", "") or candidate_emby_item_id)
        deleted_paths = [str(media.get("path", ""))] if str(media.get("path", "") or "").strip() else []

        if row is None:
            continue

        if row.delete_status == "in_progress":
            status = "running"
            status_reason = str(row.status_reason or STATUS_REASON_ACCEPTED)
            message = f"DeleteVersion succeeded (target={delete_target}). Waiting webhook confirmation."
        elif row.delete_status == "done":
            success_count += 1
            status = "success"
            status_reason = str(row.status_reason or STATUS_REASON_WEBHOOK_CONFIRMED)
            message = str(row.message or f"Webhook confirmed delete (target={delete_target}).")
        elif row.delete_status == "pending":
            status = "running"
            status_reason = str(row.status_reason or "")
            message = f"Delete request already queued (target={delete_target})."
        else:
            failed_count += 1
            status = "failed"
            status_reason = str(row.status_reason or STATUS_REASON_TIMEOUT_EXISTS)
            message = str(row.message or "DeleteVersion failed.")
        logger.debug(
            "Delete execution result row: item_id=%s id=%s delete_status=%s status=%s status_code=%s",
            candidate_item_id,
            int(row.id or 0),
            str(row.delete_status or ""),
            status,
            row.status_code,
        )

        results.append(
            DeleteExecuteItemResult(
                group_id=candidate_group_key,
                item_id=candidate_item_id,
                emby_item_id=candidate_emby_item_id,
                media_source_id=media_source_id,
                delete_target_item_id=delete_target,
                action=candidate_action,
                id=int(row.id),
                delete_status=str(row.delete_status or "pending"),
                status_reason=status_reason,
                deleted_paths=_parse_paths(row.deleted_paths_json) or deleted_paths,
                status=status,
                status_code=row.status_code,
                message=message,
            )
        )

    logger.info(
        "Delete execution finished: success_count=%s failed_count=%s results=%s",
        success_count,
        failed_count,
        len(results),
    )
    return DeleteExecuteResponse(success_count=success_count, failed_count=failed_count, results=results)


def process_delete_webhook(db: Session, payload: DeleteWebhookPayload) -> DeleteWebhookResponse:
    logger.info(
        "Process delete webhook start: delete_target_item_id=%s emby_item_id=%s item_id=%s",
        str(payload.delete_target_item_id or ""),
        str(payload.emby_item_id or ""),
        str(payload.item_id or ""),
    )
    try:
        normalized_events: list[dict] = []
        for event in list(payload.events or []):
            target = str(event.delete_target_item_id or event.item_id or "")
            emby_item_id = str(event.emby_item_id or event.item_id or "")
            deleted_paths = [str(x) for x in list(event.deleted_paths or event.deleted_files or []) if str(x).strip()]
            normalized_events.append(
                {
                    "delete_target_item_id": target,
                    "emby_item_id": emby_item_id,
                    "deleted_paths": deleted_paths,
                    "valid": bool(target or emby_item_id),
                }
            )

        item_obj = payload.item if isinstance(payload.item, dict) else {}
        item_obj_id = str(item_obj.get("Id") or "").strip()
        item_obj_path = str(item_obj.get("Path") or "").strip()
        payload_deleted_paths = [
            str(x)
            for x in list(payload.deleted_paths or payload.deleted_files or [])
            if str(x).strip()
        ]
        if not normalized_events and (
            payload.delete_target_item_id
            or payload.emby_item_id
            or payload.item_id
            or item_obj_id
            or payload_deleted_paths
        ):
            normalized_events = [
                {
                    "delete_target_item_id": str(payload.delete_target_item_id or payload.item_id or item_obj_id or ""),
                    "emby_item_id": str(payload.emby_item_id or payload.item_id or item_obj_id or ""),
                    "deleted_paths": payload_deleted_paths,
                    "valid": bool(
                        payload.delete_target_item_id
                        or payload.emby_item_id
                        or payload.item_id
                        or item_obj_id
                        or payload_deleted_paths
                    ),
                }
            ]
            if item_obj_path:
                normalized_events[0]["deleted_paths"].append(item_obj_path)

        if not normalized_events:
            logger.info("Process delete webhook skipped: no normalized events found.")
            return DeleteWebhookResponse(status="ok", matched=0, updated=0)

        inbox_rows = _create_webhook_inbox_rows(
            db,
            event_type=str(payload.event or ""),
            normalized_events=normalized_events,
            raw_payload=payload.model_dump(by_alias=True),
        )
        matched = 0
        updated = 0
        for idx, event in enumerate(normalized_events):
            inbox_row = inbox_rows[idx] if idx < len(inbox_rows) else None
            m, u = _process_webhook_event(db, event=event, inbox_row=inbox_row)
            matched += m
            updated += u

        db.commit()
        if matched == 0 or updated == 0:
            logger.info("Process delete webhook end with zero-match/update: matched=%s updated=%s", matched, updated)
        else:
            logger.info("Process delete webhook end: matched=%s updated=%s", matched, updated)
        return DeleteWebhookResponse(status="ok", matched=matched, updated=updated)
    except Exception as exc:
        db.rollback()
        logger.exception("Process delete webhook DB handling failed safely: %s", exc)
        return DeleteWebhookResponse(status="ok", matched=0, updated=0)

