"""Emby webhook receiver API."""

import json
import logging
import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import AnalysisResult, MediaItem
from app.schemas.delete_preview import DeleteWebhookPayload, DeleteWebhookResponse
from app.services.delete_preview_service import process_delete_webhook
from app.services.settings_service import load_settings
from app.services.sync_service import _normalize_media_item_versions
from app.services.webhook_analysis_queue_service import enqueue_webhook_analysis

router = APIRouter(tags=["webhook"])
logger = logging.getLogger("WebhookReceiver")


def _normalize_text(raw_value) -> str:
    return str(raw_value or "").strip()


def _normalize_deleted_files(raw_value) -> list[str]:
    if raw_value is None:
        return []
    if isinstance(raw_value, (list, tuple, set)):
        return [str(x) for x in raw_value if str(x).strip()]
    text = str(raw_value).strip()
    if not text:
        return []
    if text.startswith("[") and text.endswith("]"):
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [str(x) for x in data if str(x).strip()]
        except Exception:
            pass
    if "," in text:
        return [chunk.strip() for chunk in text.split(",") if chunk.strip()]
    return [text]


def _parse_nested_payload(raw_value):
    if isinstance(raw_value, dict):
        return raw_value
    text = str(raw_value or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        return {}
    return {}


def _looks_like_json(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    return (
        (value.startswith("{") and value.endswith("}"))
        or (value.startswith("[") and value.endswith("]"))
        or value in {"null", "true", "false"}
    )


def _try_parse_json_value(raw_value):
    if isinstance(raw_value, (dict, list, tuple, int, float, bool)) or raw_value is None:
        return raw_value
    text = str(raw_value).strip()
    if not _looks_like_json(text):
        return raw_value
    try:
        return json.loads(text)
    except Exception:
        return raw_value


def _form_to_safe_dict(form) -> dict:
    out: dict = {}
    try:
        keys = list(form.keys())
    except Exception:
        return out
    for key in keys:
        try:
            values = list(form.getlist(key)) if hasattr(form, "getlist") else [form.get(key)]
        except Exception:
            continue
        safe_values = [_try_parse_json_value(v) for v in values]
        if len(safe_values) == 1:
            out[key] = safe_values[0]
        else:
            out[key] = safe_values
    return out


def _merge_deleted_files(payload: dict) -> list[str]:
    event_text = _normalize_text(payload.get("Event")).lower()
    is_new_event = any(k in event_text for k in ("library.new", "new", "created"))
    is_delete_event = any(
        k in event_text for k in ("deep.delete", "library.deleted", "delete", "deleted", "remove", "removed")
    )
    deleted_files = _normalize_deleted_files(payload.get("DeletedFiles"))
    if is_new_event:
        return []

    item = payload.get("Item") if isinstance(payload.get("Item"), dict) else {}
    item_path = _normalize_text(item.get("Path"))
    mount_paths = (
        _parse_mount_paths_from_description(_normalize_text(payload.get("Description"))) if is_delete_event else []
    )

    merged: list[str] = []
    include_item_path = bool(item_path) and is_delete_event
    for p in [*deleted_files, *mount_paths, *([item_path] if include_item_path else [])]:
        text = str(p).strip()
        if text:
            merged.append(text)
    # dedupe while preserving order
    return list(dict.fromkeys(merged))


def _extract_form_user_server(form) -> tuple[dict, dict]:
    user = _parse_nested_payload(form.get("User"))
    server = _parse_nested_payload(form.get("Server"))

    if not user:
        user = {
            "Name": _normalize_text(form.get("User.Name") or form.get("User[Name]")),
            "Id": _normalize_text(form.get("User.Id") or form.get("User[Id]")),
        }
    if not server:
        server = {
            "Name": _normalize_text(form.get("Server.Name") or form.get("Server[Name]")),
            "Id": _normalize_text(form.get("Server.Id") or form.get("Server[Id]")),
            "Version": _normalize_text(form.get("Server.Version") or form.get("Server[Version]")),
        }
    return user, server


def _extract_form_item(form) -> dict:
    item = _parse_nested_payload(form.get("Item"))
    if item:
        return item
    item_id = _normalize_text(form.get("Item.Id") or form.get("Item[Id]"))
    item_name = _normalize_text(form.get("Item.Name") or form.get("Item[Name]"))
    item_path = _normalize_text(form.get("Item.Path") or form.get("Item[Path]"))
    provider_ids = _parse_nested_payload(form.get("Item.ProviderIds") or form.get("Item[ProviderIds]"))
    media_sources = _parse_nested_payload(form.get("Item.MediaSources") or form.get("Item[MediaSources]"))
    if not any([item_id, item_name, item_path, provider_ids, media_sources]):
        return {}
    return {
        "Id": item_id,
        "Name": item_name,
        "Path": item_path,
        "ProviderIds": provider_ids if isinstance(provider_ids, dict) else {},
        "MediaSources": media_sources if isinstance(media_sources, list) else [],
    }


def _collect_deleted_paths(payload: DeleteWebhookPayload) -> list[str]:
    paths = [str(x) for x in list(payload.deleted_files or payload.deleted_paths or []) if str(x).strip()]
    if not paths and payload.events:
        for event in payload.events:
            for p in list(event.deleted_files or event.deleted_paths or []):
                p_text = str(p).strip()
                if p_text:
                    paths.append(p_text)
    deduped: list[str] = []
    seen: set[str] = set()
    for p in paths:
        if p in seen:
            continue
        seen.add(p)
        deduped.append(p)
    return deduped


def _is_delete_event(event: str) -> bool:
    text = _normalize_text(event).lower()
    if not text:
        return False
    keywords = ("deep.delete", "library.deleted", "delete", "deleted", "remove", "removed")
    return any(k in text for k in keywords)


def _is_new_event(event: str) -> bool:
    text = _normalize_text(event).lower()
    if not text:
        return False
    keywords = ("library.new", "new", "created")
    return any(k in text for k in keywords)


def _extract_item_paths(item: dict) -> list[str]:
    paths: list[str] = []
    item_path = _normalize_text(item.get("Path"))
    if item_path:
        paths.append(item_path)
    media_sources = item.get("MediaSources")
    if isinstance(media_sources, list):
        for source in media_sources:
            if not isinstance(source, dict):
                continue
            src_path = _normalize_text(source.get("Path"))
            if src_path:
                paths.append(src_path)
    deduped: list[str] = []
    seen: set[str] = set()
    for p in paths:
        key = p.replace("\\", "/").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(p)
    return deduped


def _parse_mount_paths_from_description(description: str) -> list[str]:
    text = str(description or "")
    if not text.strip():
        return []
    lines = [line.rstrip() for line in text.splitlines()]
    marker_index = -1
    for idx, line in enumerate(lines):
        if "mount paths" in line.lower():
            marker_index = idx
            break
    if marker_index < 0:
        return []

    paths: list[str] = []
    marker_line = lines[marker_index]
    if ":" in marker_line:
        _, _, tail = marker_line.partition(":")
        tail = tail.strip()
        if tail:
            paths.extend([chunk.strip() for chunk in tail.split(",") if chunk.strip()])

    for line in lines[marker_index + 1 :]:
        stripped = line.strip(" -\t")
        if not stripped:
            continue
        lower = stripped.lower()
        if "mount paths" in lower:
            continue
        if (":" in stripped and "/" not in stripped and "\\" not in stripped) and not lower.startswith(("/", "\\")):
            # likely next section header
            break
        if "/" in stripped or "\\" in stripped or (len(stripped) > 2 and stripped[1:3] == ":\\"):
            paths.append(stripped)

    deduped: list[str] = []
    seen: set[str] = set()
    for p in paths:
        key = p.replace("\\", "/").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(p)
    return deduped


def _extract_event_item(payload: DeleteWebhookPayload) -> dict:
    if isinstance(payload.item, dict) and payload.item:
        return payload.item
    return {}


def _normalize_event_type(payload: DeleteWebhookPayload) -> str:
    return _normalize_text(payload.event).lower()


def _log_webhook_received(raw_body: dict, payload: DeleteWebhookPayload) -> None:
    logger.info("WebhookReceiver Received Emby webhook")
    logger.info("WebhookBody: %s", json.dumps(raw_body, ensure_ascii=False))
    logger.info("Title: %s", str(payload.title or payload.name or ""))
    logger.info("Event: %s", str(payload.event or ""))
    logger.info("Date: %s", str(payload.date or payload.date_deleted or ""))
    logger.info("User: %s / %s", str(payload.user.name or payload.user_id or ""), str(payload.user.id or ""))
    logger.info(
        "Server: %s / %s",
        str(payload.server.name or ""),
        str(payload.server.id or ""),
    )
    logger.info("DeletedPaths: %s", _collect_deleted_paths(payload))


def _serialize_provider_ids(item: dict) -> str:
    provider_ids = item.get("ProviderIds")
    if isinstance(provider_ids, dict):
        return json.dumps(provider_ids, ensure_ascii=False)
    return "{}"


def _process_new_item_event(db: Session, payload: DeleteWebhookPayload) -> None:
    item = _extract_event_item(payload)
    if not item:
        return
    settings = load_settings(db)
    library_name = _normalize_text(
        item.get("LibraryName")
        or item.get("CollectionType")
        or item.get("ParentName")
        or "Webhook"
    )
    version_rows = _normalize_media_item_versions(
        detail=item,
        library_name=library_name,
        excluded_paths=settings.excluded_paths,
    )
    if not version_rows:
        logger.info(
            "New item webhook ignored (no playable media source): Id=%s Name=%s",
            _normalize_text(item.get("Id")),
            _normalize_text(item.get("Name")),
        )
        return

    emby_item_id = _normalize_text(item.get("Id"))
    try:
        if emby_item_id:
            existing_ids = [int(x.id) for x in db.query(MediaItem.id).filter(MediaItem.emby_item_id == emby_item_id).all()]
            if existing_ids:
                cleaned_media = db.query(MediaItem).filter(MediaItem.id.in_(existing_ids)).delete(synchronize_session=False)
                cleaned_analysis = db.query(AnalysisResult).filter(AnalysisResult.item_id.in_(existing_ids)).delete(
                    synchronize_session=False
                )
                logger.info(
                    "Webhook new-item cleanup existing rows: emby_item_id=%s media_items_deleted=%s analysis_results_deleted=%s",
                    emby_item_id,
                    cleaned_media,
                    cleaned_analysis,
                )
        logger.info(
            "Webhook new-item insert media rows: emby_item_id=%s item_path=%s rows=%s",
            emby_item_id,
            _normalize_text(item.get("Path")),
            len(version_rows),
        )
        db.add_all(version_rows)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Webhook new-item DB operation failed: emby_item_id=%s error=%s", emby_item_id, exc)
        return
    try:
        enqueue_webhook_analysis(trigger="webhook_new_item", item=item)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Webhook new-item analysis enqueue failed: %s", exc)

    item_path = _normalize_text(item.get("Path"))
    logger.info(
        "Item: {Id:%s, Name:%s, Path:%s, ProviderIds:%s}",
        emby_item_id,
        _normalize_text(item.get("Name")),
        item_path,
        _serialize_provider_ids(item),
    )


async def _parse_webhook_payload(request: Request) -> tuple[DeleteWebhookPayload, dict]:
    try:
        content_type = str(request.headers.get("content-type") or "").lower()
        logger.debug("Webhook parse start: content_type=%s", content_type)
        if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
            form = await request.form()
            safe_form = _form_to_safe_dict(form)
            user, server = _extract_form_user_server(form)
            item = _extract_form_item(form)
            fallback_item_id = _normalize_text(item.get("Id"))
            payload_dict = {
                **safe_form,
                "delete_target_item_id": _normalize_text(safe_form.get("delete_target_item_id")) or fallback_item_id,
                "emby_item_id": _normalize_text(safe_form.get("emby_item_id")) or fallback_item_id,
                "ItemId": _normalize_text(safe_form.get("ItemId")),
                "UserId": _normalize_text(safe_form.get("UserId")),
                "Name": _normalize_text(safe_form.get("Name")),
                "DateDeleted": _normalize_text(safe_form.get("DateDeleted")),
                "Title": _normalize_text(safe_form.get("Title")),
                "Description": _normalize_text(safe_form.get("Description")),
                "Date": _normalize_text(safe_form.get("Date")),
                "Event": _normalize_text(safe_form.get("Event")),
                "Severity": _normalize_text(safe_form.get("Severity")),
                "User": user,
                "Server": server,
                "Item": item,
                "Token": _normalize_text(safe_form.get("Token")),
                "DeletedFiles": [],
            }
            # Expand embedded payload in multipart data field (e.g. data='{"Event":"deep.delete",...}').
            if "data" in payload_dict and isinstance(payload_dict.get("data"), dict):
                payload_dict.update(payload_dict.get("data") or {})

            raw_deleted_values = (
                list(form.getlist("DeletedFiles") or [])
                if hasattr(form, "getlist")
                else [safe_form.get("DeletedFiles")]
            )
            if not raw_deleted_values:
                raw_deleted_values = [safe_form.get("DeletedFiles")]
            if not raw_deleted_values:
                raw_deleted_values = [safe_form.get("deleted_paths")]

            deleted_files: list[str] = []
            for raw_value in raw_deleted_values:
                parsed_value = _try_parse_json_value(raw_value)
                deleted_files.extend(_normalize_deleted_files(parsed_value))
            if not deleted_files:
                deleted_files = _normalize_deleted_files(safe_form.get("deleted_paths"))

            # Fill fallback fields from Item.Id when top-level ids are missing.
            form_item = payload_dict.get("Item") if isinstance(payload_dict.get("Item"), dict) else {}
            form_item_id = _normalize_text(payload_dict.get("ItemId")) or _normalize_text(form_item.get("Id"))
            payload_dict["delete_target_item_id"] = _normalize_text(payload_dict.get("delete_target_item_id")) or form_item_id
            payload_dict["emby_item_id"] = _normalize_text(payload_dict.get("emby_item_id")) or form_item_id
            payload_dict["ItemId"] = _normalize_text(payload_dict.get("ItemId")) or form_item_id

            payload_dict["DeletedFiles"] = [str(x) for x in deleted_files if str(x).strip()]
            payload_dict["DeletedFiles"] = _merge_deleted_files(payload_dict)
            logger.info("Webhook parsed payload: %s", json.dumps(payload_dict, ensure_ascii=False))
            return DeleteWebhookPayload.model_validate(payload_dict), payload_dict

        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        safe_body = {k: _try_parse_json_value(v) for k, v in body.items()}
        safe_body["DeletedFiles"] = _normalize_deleted_files(safe_body.get("DeletedFiles"))
        if not safe_body.get("DeletedFiles"):
            safe_body["DeletedFiles"] = _normalize_deleted_files(safe_body.get("deleted_paths"))
        if "User" in safe_body:
            safe_body["User"] = _parse_nested_payload(safe_body.get("User")) or safe_body.get("User")
        if "Server" in safe_body:
            safe_body["Server"] = _parse_nested_payload(safe_body.get("Server")) or safe_body.get("Server")
        if "Item" in safe_body:
            safe_body["Item"] = _parse_nested_payload(safe_body.get("Item")) or safe_body.get("Item")
        if not safe_body.get("Item") and isinstance(safe_body.get("Items"), list) and safe_body.get("Items"):
            first = safe_body.get("Items")[0]
            safe_body["Item"] = first if isinstance(first, dict) else {}
        if "data" in safe_body and isinstance(safe_body.get("data"), dict):
            safe_body.update(safe_body.get("data") or {})
        fallback_item_id = _normalize_text((safe_body.get("Item") or {}).get("Id"))
        safe_body["delete_target_item_id"] = _normalize_text(safe_body.get("delete_target_item_id")) or fallback_item_id
        safe_body["emby_item_id"] = _normalize_text(safe_body.get("emby_item_id")) or fallback_item_id
        safe_body["ItemId"] = _normalize_text(safe_body.get("ItemId")) or fallback_item_id
        safe_body["DeletedFiles"] = _merge_deleted_files(safe_body)
        logger.info("Webhook parsed payload: %s", json.dumps(safe_body, ensure_ascii=False))
        return DeleteWebhookPayload.model_validate(safe_body), safe_body
    except ValidationError as exc:
        logger.exception("Webhook parse validation failed: %s", exc)
        return DeleteWebhookPayload(), {}
    except Exception as exc:
        logger.exception("Webhook parse failed unexpectedly: %s", exc)
        return DeleteWebhookPayload(), {}


@router.post("/webhook/emby", response_model=DeleteWebhookResponse, status_code=status.HTTP_200_OK)
async def post_emby_webhook(
    request: Request,
    token: str = Query(default=""),
    db: Session = Depends(get_db),
) -> DeleteWebhookResponse:
    """Accept Emby webhook callbacks and handle delete/new-item events."""
    try:
        raw_body_bytes = await request.body()
        raw_body_text = raw_body_bytes.decode("utf-8", errors="replace") if raw_body_bytes else ""
        source_ip = str(getattr(request.client, "host", "") or "")
        request_headers = {k: v for k, v in request.headers.items()}
        provided_query_token = str(token or "").strip()
        logger.info("Webhook request received: ip=%s path=%s", source_ip, str(request.url.path))
        logger.debug("Webhook request token(query)=%s", provided_query_token)
        logger.debug("Webhook request headers=%s", json.dumps(request_headers, ensure_ascii=False))
        logger.debug("Webhook request raw_body=%s", raw_body_text)

        payload, raw_body = await _parse_webhook_payload(request)
        settings = load_settings(db)
        expected_token = str(settings.webhook_token or os.getenv("APP_WEBHOOK_TOKEN", "")).strip()
        provided_token = str(token or payload.token or "").strip()
        if not expected_token or provided_token != expected_token:
            logger.info(
                "Webhook token validation failed: ip=%s provided=%s expected_set=%s",
                source_ip,
                provided_token,
                bool(expected_token),
            )
            raise HTTPException(status_code=401, detail="Webhook token is invalid.")

        _log_webhook_received(raw_body, payload)
        event_type = _normalize_event_type(payload)
        deleted_paths = list(_collect_deleted_paths(payload))
        item = _extract_event_item(payload)
        mount_paths = _parse_mount_paths_from_description(payload.description)

        # priority a: DeletedFiles
        if not deleted_paths and item:
            # priority b: Item + event keywords
            if _is_delete_event(event_type):
                deleted_paths = _extract_item_paths(item)
            elif _is_new_event(event_type):
                deleted_paths = []
        if not deleted_paths and mount_paths:
            # priority c: Description Mount Paths
            deleted_paths = mount_paths

        if deleted_paths:
            payload.deleted_files = [str(x) for x in deleted_paths if str(x).strip()]
        if _is_delete_event(event_type) and item and not (payload.item_id or payload.emby_item_id):
            item_id = _normalize_text(item.get("Id"))
            if item_id:
                payload.item_id = item_id
        logger.info(
            "Webhook event parsed: event=%s delete_target_item_id=%s emby_item_id=%s item_id=%s deleted_paths=%s",
            event_type,
            str(payload.delete_target_item_id or ""),
            str(payload.emby_item_id or ""),
            str(payload.item_id or ""),
            len(deleted_paths),
        )
        if deleted_paths:
            logger.debug("Webhook deleted_paths=%s", json.dumps(deleted_paths, ensure_ascii=False))
        if item:
            logger.debug("Webhook item payload=%s", json.dumps(item, ensure_ascii=False))

        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        logger.info(
            "WebhookSummary: timestamp=%s event=%s deleted_paths_count=%s has_item=%s mount_paths_count=%s",
            ts,
            event_type,
            len(deleted_paths),
            bool(item),
            len(mount_paths),
        )
        if mount_paths:
            for p in mount_paths:
                logger.info("MountPath: %s", p)
        if item:
            logger.info(
                "ItemParsed: Id=%s Name=%s Path=%s ProviderIds=%s",
                _normalize_text(item.get("Id")),
                _normalize_text(item.get("Name")),
                _normalize_text(item.get("Path")),
                _serialize_provider_ids(item),
            )

        logger.info("ParsedEvent: event=%s hasItem=%s deletedCount=%s", event_type, bool(item), len(deleted_paths))

        should_process_delete = _is_delete_event(event_type) or (bool(deleted_paths) and not _is_new_event(event_type))
        result = DeleteWebhookResponse(status="ok", matched=0, updated=0)
        if should_process_delete:
            result = process_delete_webhook(db, payload)
        elif item and _is_new_event(event_type):
            logger.info(
                "Webhook new-item event handling: item_id=%s item_name=%s item_path=%s",
                _normalize_text(item.get("Id")),
                _normalize_text(item.get("Name")),
                _normalize_text(item.get("Path")),
            )
            _process_new_item_event(db, payload)
        else:
            logger.info("Webhook non-delete/non-new event ignored: event=%s", event_type)

        if int(result.matched or 0) == 0 or int(result.updated or 0) == 0:
            logger.info(
                "Webhook processed with zero-match or zero-update: event=%s matched=%s updated=%s",
                event_type,
                int(result.matched or 0),
                int(result.updated or 0),
            )
        else:
            logger.info(
                "Webhook processed successfully: event=%s matched=%s updated=%s",
                event_type,
                int(result.matched or 0),
                int(result.updated or 0),
            )

        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Webhook handler failed safely: %s", exc)
        return DeleteWebhookResponse(status="ok", matched=0, updated=0)


@router.post("/webhook/emby/ack", status_code=status.HTTP_204_NO_CONTENT)
async def post_emby_webhook_ack() -> Response:
    """Optional webhook ack endpoint."""
    return Response(status_code=status.HTTP_204_NO_CONTENT)
