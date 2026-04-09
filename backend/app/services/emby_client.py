"""Minimal Emby API client for library discovery and sync."""

import json
import socket
import time
from urllib.parse import urlencode

import requests
from requests import Response, Session


class EmbySettingsMissingError(Exception):
    """Raised when required Emby settings are missing."""


class EmbyAuthError(Exception):
    """Raised when Emby returns unauthorized/forbidden."""


class EmbyServerUnreachableError(Exception):
    """Raised when Emby server cannot be reached."""


class EmbyApiError(Exception):
    """Raised for non-auth Emby API failures."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _normalize_base_url(base_url: str) -> str:
    return (base_url or "").strip().rstrip("/")


class EmbyClient:
    """Simple client for key Emby API reads."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 10.0,
        retries: int = 3,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        self.base_url = _normalize_base_url(base_url)
        self.api_key = (api_key or "").strip()
        self.timeout = timeout
        self.retries = max(1, int(retries))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))
        self.session = Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "X-Emby-Token": self.api_key,
            }
        )

        if not self.base_url or not self.api_key:
            raise EmbySettingsMissingError("Emby base URL and API key are required.")

    @staticmethod
    def _decode_response_text(response: Response) -> str:
        encoding = response.encoding or "utf-8"
        try:
            return response.content.decode(encoding)
        except UnicodeDecodeError:
            return response.content.decode("utf-8", errors="replace")

    def _request_json(self, path: str, query_params: dict[str, str] | None = None) -> dict | list:
        params = dict(query_params or {})
        params["api_key"] = self.api_key
        query = urlencode(params)
        url = f"{self.base_url}{path}?{query}"

        last_error: Exception | None = None

        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.get(url, timeout=self.timeout)
                payload = self._decode_response_text(response)
                status_code = int(response.status_code)

                if status_code in (401, 403):
                    raise EmbyAuthError("Invalid Emby API key.")
                if status_code >= 500 or status_code == 429:
                    last_error = EmbyApiError(
                        f"Emby API request failed with HTTP {status_code} for {path}.",
                        status_code=status_code,
                    )
                    if attempt < self.retries:
                        time.sleep(self.retry_backoff_seconds * attempt)
                        continue
                    raise last_error
                if status_code >= 400:
                    raise EmbyApiError(
                        f"Emby API request failed with HTTP {status_code} for {path}.",
                        status_code=status_code,
                    )

                try:
                    return json.loads(payload)
                except json.JSONDecodeError as exc:
                    raise EmbyApiError(f"Emby returned invalid JSON for {path}.") from exc

            except (requests.Timeout, socket.timeout, TimeoutError) as exc:
                last_error = EmbyServerUnreachableError(
                    f"Timed out after {self.timeout:.0f}s while calling Emby endpoint {path}."
                )
                if attempt < self.retries:
                    time.sleep(self.retry_backoff_seconds * attempt)
                    continue
                raise last_error from exc
            except requests.ConnectionError as exc:
                detail = str(exc)
                last_error = EmbyServerUnreachableError(f"Unable to reach Emby server for {path}: {detail}")
                if attempt < self.retries:
                    time.sleep(self.retry_backoff_seconds * attempt)
                    continue
                raise last_error from exc
            except requests.RequestException as exc:
                detail = str(exc)
                last_error = EmbyApiError(f"Emby API request failed for {path}: {detail}")
                if attempt < self.retries:
                    time.sleep(self.retry_backoff_seconds * attempt)
                    continue
                raise last_error from exc

        if last_error:
            raise last_error
        raise EmbyApiError(f"Unknown Emby request error for {path}.")

    def list_libraries(self) -> list[dict[str, str]]:
        raw_items = self._request_json("/Library/VirtualFolders")
        if not isinstance(raw_items, list):
            raise EmbyApiError("Unexpected Emby response format for libraries.")

        items: list[dict[str, str]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            items.append(
                {
                    "id": str(item.get("ItemId") or item.get("Id") or ""),
                    "name": str(item.get("Name") or ""),
                    "collection_type": str(item.get("CollectionType") or ""),
                }
            )
        return items

    def list_user_views(self, user_id: str) -> list[dict[str, str]]:
        payload = self._request_json(f"/Users/{user_id}/Views")
        if not isinstance(payload, dict):
            raise EmbyApiError("Unexpected Emby response format for user views.")

        raw_items = payload.get("Items")
        if not isinstance(raw_items, list):
            raise EmbyApiError("Emby user views response missing Items array.")

        items: list[dict[str, str]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            items.append(
                {
                    "id": str(item.get("Id") or ""),
                    "name": str(item.get("Name") or ""),
                    "collection_type": str(item.get("CollectionType") or ""),
                }
            )
        return items

    def get_primary_user_id(self) -> str:
        payload = self._request_json("/Users/Query")
        if not isinstance(payload, dict):
            raise EmbyApiError("Unexpected Emby response format for users query.")

        users = payload.get("Items")
        if not isinstance(users, list) or not users:
            raise EmbyApiError("No Emby users found for media queries.")

        first = users[0] if isinstance(users[0], dict) else {}
        user_id = str(first.get("Id") or "")
        if not user_id:
            raise EmbyApiError("Emby users query did not return a valid user id.")
        return user_id

    def list_library_items_page(self, user_id: str, library_id: str, start_index: int, limit: int = 4000) -> tuple[list[dict], int]:
        payload = self._request_json(
            f"/Users/{user_id}/Items",
            {
                "ParentId": library_id,
                "Recursive": "true",
                "IncludeItemTypes": "Movie,Episode",
                # Keep duplicate logical items separated during sync so dedup can
                # compare versions even when Emby UI has merged presentations.
                "GroupByPresentationUniqueKey": "false",
                "StartIndex": str(max(0, int(start_index))),
                "Limit": str(max(1, int(limit))),
                "EnableTotalRecordCount": "false",
                "Fields": (
                    "ProviderIds,Path,MediaSources,ParentIndexNumber,IndexNumber,"
                    "SeriesName,ProductionYear,DateCreated,DateLastMediaAdded"
                ),
            },
        )
        if not isinstance(payload, dict):
            raise EmbyApiError("Unexpected Emby response format for library items.")

        items = payload.get("Items")
        if not isinstance(items, list):
            raise EmbyApiError("Emby library items response missing Items array.")

        total = payload.get("TotalRecordCount")
        try:
            total_count = int(total)
        except (TypeError, ValueError):
            total_count = len(items)

        return items, max(0, total_count)

    def list_library_items_paginated(self, user_id: str, library_id: str, limit: int = 4000) -> list[dict]:
        page_size = max(1, int(limit))
        start_index = 0
        results: list[dict] = []

        while True:
            items, total_count = self.list_library_items_page(
                user_id=user_id,
                library_id=library_id,
                start_index=start_index,
                limit=page_size,
            )
            if not items:
                break

            results.extend(items)
            start_index += len(items)

            if len(items) < page_size:
                break
            if total_count and start_index >= total_count:
                break

        return results

    def list_library_items(self, user_id: str, library_id: str) -> list[dict]:
        return self.list_library_items_paginated(user_id=user_id, library_id=library_id, limit=4000)

    def get_item_detail(self, user_id: str, item_id: str) -> dict:
        payload = self._request_json(
            f"/Users/{user_id}/Items/{item_id}",
            {
                "Fields": (
                    "ProviderIds,Path,MediaSources,MediaStreams,ParentIndexNumber,IndexNumber,"
                    "SeriesName,ProductionYear,DateCreated,DateLastMediaAdded"
                ),
            },
        )
        if not isinstance(payload, dict):
            raise EmbyApiError("Unexpected Emby response format for item detail.")
        return payload

    def get_user_item_count(self, user_id: str, include_item_types: str) -> int:
        payload = self._request_json(
            f"/Users/{user_id}/Items",
            {
                "Recursive": "true",
                "IncludeItemTypes": include_item_types,
                "StartIndex": "0",
                "Limit": "1",
            },
        )
        if not isinstance(payload, dict):
            raise EmbyApiError("Unexpected Emby response format for user item count.")
        total = payload.get("TotalRecordCount")
        try:
            return max(0, int(total))
        except (TypeError, ValueError):
            items = payload.get("Items")
            return len(items) if isinstance(items, list) else 0

    def get_server_item_counts(self) -> dict:
        payload = self._request_json("/Items/Counts")
        if not isinstance(payload, dict):
            return {}
        return payload

    def item_exists(self, item_id: str) -> bool:
        target = str(item_id or "").strip()
        if not target:
            return False
        try:
            payload = self._request_json(f"/Items/{target}")
            return isinstance(payload, dict) and bool(str(payload.get("Id") or "").strip())
        except EmbyApiError as exc:
            if int(exc.status_code or 0) == 404:
                return False
            raise

    def user_item_exists(self, user_id: str, item_id: str) -> bool:
        uid = str(user_id or "").strip()
        target = str(item_id or "").strip()
        if not uid or not target:
            return False
        try:
            payload = self._request_json(f"/Users/{uid}/Items/{target}")
            return isinstance(payload, dict) and bool(str(payload.get("Id") or "").strip())
        except EmbyApiError as exc:
            if int(exc.status_code or 0) == 404:
                return False
            raise
