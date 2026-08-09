from __future__ import annotations

import json

import httpx
import pytest

from geo_core.model_gateway.provider_adapters.base import (
    JsonResponseInvalid,
    JsonResponseTooLarge,
)
from geo_core.model_gateway.provider_adapters.http_transport import (
    SecureHttpxJsonTransport,
)


def _factory(handler):
    return lambda: httpx.MockTransport(handler)


def test_https_transport_disables_redirects_env_proxy_and_filters_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert request.headers["Authorization"] == "Bearer fixture-secret"
        return httpx.Response(
            302,
            headers={
                "Location": "https://redirect.example.test/secret",
                "X-Request-ID": "safe-request-id",
                "Set-Cookie": "must-not-escape=secret",
            },
            json={"redirect": True},
        )

    transport = SecureHttpxJsonTransport(transport_factory=_factory(handler))
    response = transport.post(
        url="https://provider.example.test/v1/responses",
        headers={"Authorization": "Bearer fixture-secret"},
        payload={"input": "fixture"},
        timeout_seconds=3,
    )

    assert calls == ["https://provider.example.test/v1/responses"]
    assert response.status_code == 302
    assert response.headers == {"x-request-id": "safe-request-id"}
    assert "fixture-secret" not in repr((transport, response))
    assert "must-not-escape" not in repr(response)


def test_transport_bounds_streamed_body_before_json_parsing() -> None:
    content = json.dumps({"answer": "x" * 2048}).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, content=content)

    transport = SecureHttpxJsonTransport(
        max_response_bytes=1024,
        transport_factory=_factory(handler),
    )

    with pytest.raises(JsonResponseTooLarge, match="too large"):
        transport.post(
            url="https://provider.example.test/v1/responses",
            headers={},
            payload={},
            timeout_seconds=3,
        )


def test_success_requires_json_but_non_success_preserves_http_classification() -> None:
    responses = iter(
        (
            httpx.Response(200, content=b"not-json"),
            httpx.Response(503, content=b"upstream unavailable"),
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return next(responses)

    transport = SecureHttpxJsonTransport(transport_factory=_factory(handler))
    values = {
        "url": "https://provider.example.test/v1/responses",
        "headers": {},
        "payload": {},
        "timeout_seconds": 3,
    }
    with pytest.raises(JsonResponseInvalid, match="not valid JSON"):
        transport.post(**values)

    response = transport.post(**values)
    assert response.status_code == 503
    assert response.body == {"error": {"type": "unparseable_provider_error"}}


def test_transport_exception_is_sanitized_without_request_headers_or_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Bearer fixture-secret in upstream error", request=request)

    transport = SecureHttpxJsonTransport(transport_factory=_factory(handler))

    with pytest.raises(TimeoutError) as captured:
        transport.post(
            url="https://provider.example.test/v1/responses",
            headers={"Authorization": "Bearer fixture-secret"},
            payload={"secret": "fixture-body-secret"},
            timeout_seconds=3,
        )

    rendered = repr(captured.value)
    assert "fixture-secret" not in rendered
    assert "fixture-body-secret" not in rendered
    assert str(captured.value) == "provider request timed out"


def test_get_transport_rejects_non_scalar_query_parameters_before_io() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"ok": True})

    transport = SecureHttpxJsonTransport(transport_factory=_factory(handler))

    with pytest.raises(ValueError, match="must be a scalar"):
        transport.get(
            url="https://provider.example.test/search",
            headers={},
            params={"nested": {"not": "allowed"}},
            timeout_seconds=3,
        )

    assert calls == 0
