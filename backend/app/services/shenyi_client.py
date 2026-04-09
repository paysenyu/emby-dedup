"""Shenyi client for delete execution."""

from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ShenyiSettingsMissingError(Exception):
    pass


class ShenyiServerError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _normalize_base_url(base_url: str) -> str:
    return (base_url or "").strip().rstrip("/")


class ShenyiClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 15.0) -> None:
        self.base_url = _normalize_base_url(base_url)
        self.api_key = (api_key or "").strip()
        self.timeout = timeout
        if not self.base_url or not self.api_key:
            raise ShenyiSettingsMissingError("Shenyi base URL and API key are required for delete execution.")

    def delete_version(self, emby_item_id: str) -> tuple[int, str]:
        params = urlencode({"DeleteParent": "false", "api_key": self.api_key})
        url = f"{self.base_url}/Items/{emby_item_id}/DeleteVersion?{params}"
        req = Request(url, method="POST")
        req.add_header("Accept", "application/json")
        req.add_header("X-Emby-Token", self.api_key)

        try:
            with urlopen(req, timeout=self.timeout) as resp:
                code = int(getattr(resp, "status", 200))
                if code in {200, 204}:
                    return code, "success"
                raise ShenyiServerError(f"DeleteVersion failed with status {code}.", status_code=code)
        except HTTPError as exc:
            if int(exc.code) in {200, 204}:
                return int(exc.code), "success"
            raise ShenyiServerError(f"DeleteVersion failed with HTTP {exc.code}.", status_code=int(exc.code)) from exc
        except URLError as exc:
            raise ShenyiServerError(f"Unable to reach Shenyi server: {exc.reason}", status_code=None) from exc
