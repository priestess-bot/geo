"""Validation for imported Playwright storage state used by Browser Capture."""

from __future__ import annotations

import json
from collections.abc import Mapping
from urllib.parse import urlsplit

from geo_core.browser_capture.domain import BrowserCaptureError


MAX_STORAGE_STATE_BYTES = 2_000_000
_ALLOWED_HOST_SUFFIXES = ("google.com", "bing.com", "microsoft.com")


def validate_browser_storage_state(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise BrowserCaptureError("Browser session storage state must be a JSON object")
    serialized = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > MAX_STORAGE_STATE_BYTES:
        raise BrowserCaptureError("Browser session storage state exceeds 2 MB")
    cookies = value.get("cookies")
    origins = value.get("origins")
    if not isinstance(cookies, list) or not isinstance(origins, list):
        raise BrowserCaptureError(
            "Browser session storage state needs cookies and origins arrays"
        )
    for cookie in cookies:
        if not isinstance(cookie, Mapping):
            raise BrowserCaptureError("Browser session cookie is invalid")
        domain = str(cookie.get("domain", "")).lstrip(".").casefold()
        if not _supported_host(domain):
            raise BrowserCaptureError(
                "Browser session cookie domain is outside supported surfaces"
            )
    for origin in origins:
        if not isinstance(origin, Mapping):
            raise BrowserCaptureError("Browser session origin is invalid")
        parsed = urlsplit(str(origin.get("origin", "")))
        if parsed.scheme != "https" or not _supported_host((parsed.hostname or "").casefold()):
            raise BrowserCaptureError(
                "Browser session origin is outside supported surfaces"
            )
    return {"cookies": cookies, "origins": origins}


def _supported_host(host: str) -> bool:
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in _ALLOWED_HOST_SUFFIXES)


__all__ = ["MAX_STORAGE_STATE_BYTES", "validate_browser_storage_state"]
