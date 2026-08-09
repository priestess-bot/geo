"""Production HTTPS JSON transport with bounded, non-inheriting network behavior."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from urllib.parse import urlsplit

import httpx

from geo_core.model_gateway.contracts import ProviderPolicyViolation
from geo_core.model_gateway.provider_adapters.base import (
    JsonGetTransport,
    JsonResponse,
    JsonResponseInvalid,
    JsonResponseTooLarge,
)


_SAFE_RESPONSE_HEADERS = frozenset(
    {
        "retry-after",
        "request-id",
        "x-correlation-id",
        "x-ms-request-id",
        "x-request-id",
    }
)


class SecureHttpxJsonTransport(JsonGetTransport):
    """One-shot TLS transport; it never follows redirects or trusts host proxy env."""

    def __init__(
        self,
        *,
        max_response_bytes: int = 4 * 1024 * 1024,
        transport_factory: Callable[[], httpx.BaseTransport] | None = None,
    ) -> None:
        if max_response_bytes < 1024:
            raise ValueError("provider response limit must be at least 1024 bytes")
        self.max_response_bytes = max_response_bytes
        self._transport_factory = transport_factory

    def __repr__(self) -> str:
        return f"SecureHttpxJsonTransport(max_response_bytes={self.max_response_bytes})"

    def post(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout_seconds: float,
    ) -> JsonResponse:
        _validate_url(url)
        if timeout_seconds <= 0:
            raise ValueError("provider timeout must be positive")
        transport = self._transport_factory() if self._transport_factory is not None else None
        try:
            with httpx.Client(
                transport=transport,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(timeout_seconds),
            ) as client:
                with client.stream("POST", url, headers=dict(headers), json=payload) as response:
                    content = _bounded_content(response, maximum=self.max_response_bytes)
                    body = _json_body(content, successful=200 <= response.status_code < 300)
                    safe_headers = {
                        name.lower(): value
                        for name, value in response.headers.items()
                        if name.lower() in _SAFE_RESPONSE_HEADERS
                    }
                    return JsonResponse(response.status_code, body, safe_headers)
        except (JsonResponseInvalid, JsonResponseTooLarge):
            raise
        except httpx.TimeoutException:
            raise TimeoutError("provider request timed out") from None
        except httpx.TransportError:
            raise ConnectionError("provider request failed") from None

    def get(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        params: Mapping[str, object],
        timeout_seconds: float,
    ) -> JsonResponse:
        """Perform one bounded GET without redirects or inherited proxy state."""
        _validate_url(url)
        if timeout_seconds <= 0:
            raise ValueError("provider timeout must be positive")
        transport = self._transport_factory() if self._transport_factory is not None else None
        try:
            with httpx.Client(
                transport=transport,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(timeout_seconds),
            ) as client:
                query_params = _httpx_query_params(params)
                with client.stream(
                    "GET", url, headers=dict(headers), params=query_params
                ) as response:
                    content = _bounded_content(response, maximum=self.max_response_bytes)
                    body = _json_body(content, successful=200 <= response.status_code < 300)
                    safe_headers = {
                        name.lower(): value
                        for name, value in response.headers.items()
                        if name.lower() in _SAFE_RESPONSE_HEADERS
                    }
                    return JsonResponse(response.status_code, body, safe_headers)
        except (JsonResponseInvalid, JsonResponseTooLarge):
            raise
        except httpx.TimeoutException:
            raise TimeoutError("provider request timed out") from None
        except httpx.TransportError:
            raise ConnectionError("provider request failed") from None


def _httpx_query_params(
    params: Mapping[str, object],
) -> dict[str, str | int | float | bool | None]:
    normalized: dict[str, str | int | float | bool | None] = {}
    for name, value in params.items():
        if value is not None and not isinstance(value, (str, int, float, bool)):
            raise ValueError(f"provider query parameter {name!r} must be a scalar")
        normalized[name] = value
    return normalized


def _validate_url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ProviderPolicyViolation(
            "provider transport requires an HTTPS URL without credentials or fragments"
        )


def _bounded_content(response: httpx.Response, *, maximum: int) -> bytes:
    declared = response.headers.get("content-length")
    if declared is not None:
        try:
            declared_size = int(declared)
        except ValueError:
            declared_size = 0
        if declared_size > maximum:
            raise JsonResponseTooLarge("provider response is too large")
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > maximum:
            raise JsonResponseTooLarge("provider response is too large")
        chunks.append(chunk)
    return b"".join(chunks)


def _json_body(content: bytes, *, successful: bool) -> object:
    try:
        return json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError):
        if successful:
            raise JsonResponseInvalid("provider response is not valid JSON") from None
        return {"error": {"type": "unparseable_provider_error"}}


__all__ = ["SecureHttpxJsonTransport"]
