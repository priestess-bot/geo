"""Contracts for the Secret-backed formal SerpAPI Provider path."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any
from unittest.mock import patch
from uuid import UUID

import httpx
import pytest

from geo_core.search_aggregation import (
    SERPAPI_REGISTRATION,
    build_search_provider,
    search_provider_registration,
)
from geo_core.search_aggregation.domain import (
    AiOverviewQuery,
    SearchAggregationError,
    SearchAggregationErrorCode,
)
from geo_core.search_aggregation.serpapi_adapter import SerpApiSearchProvider
from geo_core.secrets.models import SecretValue, SecretVersionHandle


PROJECT_ID = UUID("11111111-1111-4111-8111-111111111111")
REFERENCE_ID = UUID("22222222-2222-4222-8222-222222222222")
HANDLE = SecretVersionHandle(
    project_id=PROJECT_ID,
    reference_id=REFERENCE_ID,
    purpose="search.serpapi",
    version=4,
)


class FakeCredentialResolver:
    def __init__(self, value: str = "fixture-serpapi-credential") -> None:
        self.value = value
        self.handles: list[SecretVersionHandle] = []

    def resolve(self, handle: SecretVersionHandle) -> SecretValue:
        self.handles.append(handle)
        return SecretValue(self.value)


def _response(
    status_code: int,
    *,
    payload: Mapping[str, Any] | list[Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> httpx.Response:
    request = httpx.Request("GET", "https://serpapi.com/search.json")
    return httpx.Response(status_code, json=payload, headers=headers, request=request)


def _provider(
    resolver: FakeCredentialResolver | None = None,
    **kwargs: Any,
) -> tuple[SerpApiSearchProvider, FakeCredentialResolver]:
    actual = resolver or FakeCredentialResolver()
    return (
        SerpApiSearchProvider(
            secret_handle=HANDLE,
            credential_resolver=actual,
            **kwargs,
        ),
        actual,
    )


def test_registry_requires_secret_reference_and_registers_serpapi() -> None:
    assert search_provider_registration("serpapi") == SERPAPI_REGISTRATION
    resolver = FakeCredentialResolver()
    provider = build_search_provider(
        "serpapi",
        secret_handle=HANDLE,
        credential_resolver=resolver,
    )
    assert isinstance(provider, SerpApiSearchProvider)
    assert provider._api_key is None

    with pytest.raises(SearchAggregationError) as error:
        build_search_provider(
            "serpapi",
            secret_handle=SecretVersionHandle(
                project_id=PROJECT_ID,
                reference_id=REFERENCE_ID,
                purpose="model_provider.serpapi",
                version=4,
            ),
            credential_resolver=resolver,
        )
    assert error.value.code is SearchAggregationErrorCode.CONFIGURATION


def test_secret_backed_provider_resolves_exact_handle_and_normalizes_payload() -> None:
    provider, resolver = _provider()
    captured: dict[str, Any] = {}

    async def fake_get(
        self: httpx.AsyncClient,
        url: str,
        *,
        params: Mapping[str, Any],
    ) -> httpx.Response:
        captured["url"] = url
        captured["params"] = dict(params)
        return _response(
            200,
            payload={
                "ai_overview": {
                    "text_blocks": [{"type": "paragraph", "text": "Answer"}],
                    "references": [{"title": "Source", "link": "https://example.test"}],
                }
            },
        )

    with patch.object(httpx.AsyncClient, "get", fake_get):
        result = asyncio.run(
            provider.fetch_ai_overview(
                AiOverviewQuery(text="best Australian coffee", locale="en-AU", region="AU")
            )
        )

    assert result.blocks[0].text == "Answer"
    assert result.references[0].url == "https://example.test"
    assert captured["url"] == "https://serpapi.com/search.json"
    assert captured["params"]["engine"] == "google"
    assert captured["params"]["gl"] == "au"
    assert captured["params"]["hl"] == "en"
    assert captured["params"]["api_key"] == "fixture-serpapi-credential"
    assert resolver.handles == [HANDLE]
    assert provider._api_key is None
    assert "fixture-serpapi-credential" not in repr(provider)


def test_transient_http_failure_retries_with_backoff() -> None:
    sleeps: list[float] = []
    responses = [
        _response(503, payload={"error": "temporary"}),
        _response(200, payload={"ai_overview": {"answer": "Recovered"}}),
    ]
    provider, _ = _provider(
        max_attempts=3,
        retry_base_seconds=0.5,
        sleep=lambda delay: _record_sleep(sleeps, delay),
    )

    async def fake_get(*args: Any, **kwargs: Any) -> httpx.Response:
        del args, kwargs
        return responses.pop(0)

    with patch.object(httpx.AsyncClient, "get", fake_get):
        result = asyncio.run(provider.fetch_ai_overview(AiOverviewQuery(text="q")))

    assert result.blocks[0].text == "Recovered"
    assert sleeps == [0.5]


def test_page_token_result_preserves_initial_and_resolved_raw_evidence() -> None:
    responses = [
        _response(200, payload={"ai_overview": {"page_token": "token-1"}}),
        _response(200, payload={"ai_overview": {"answer": "Resolved answer"}}),
    ]
    provider, _ = _provider()

    async def fake_get(*args: Any, **kwargs: Any) -> httpx.Response:
        del args, kwargs
        return responses.pop(0)

    with patch.object(httpx.AsyncClient, "get", fake_get):
        result = asyncio.run(provider.fetch_ai_overview(AiOverviewQuery(text="q")))

    assert result.blocks[0].text == "Resolved answer"
    assert result.raw_response == {
        "search_response": {"ai_overview": {"page_token": "token-1"}},
        "ai_overview_response": {"ai_overview": {"answer": "Resolved answer"}},
    }


def test_rate_limit_uses_retry_after_and_remains_classified_when_exhausted() -> None:
    sleeps: list[float] = []
    provider, _ = _provider(
        max_attempts=2,
        retry_base_seconds=0.1,
        sleep=lambda delay: _record_sleep(sleeps, delay),
    )

    async def fake_get(*args: Any, **kwargs: Any) -> httpx.Response:
        del args, kwargs
        return _response(429, payload={"error": "rate limited"}, headers={"Retry-After": "2"})

    with patch.object(httpx.AsyncClient, "get", fake_get):
        with pytest.raises(SearchAggregationError) as error:
            asyncio.run(provider.fetch_ai_overview(AiOverviewQuery(text="q")))

    assert error.value.code is SearchAggregationErrorCode.RATE_LIMIT
    assert error.value.retryable is True
    assert error.value.status_code == 429
    assert sleeps == [2.0]


def test_authentication_failure_is_not_retried() -> None:
    calls = 0
    provider, _ = _provider(max_attempts=3)

    async def fake_get(*args: Any, **kwargs: Any) -> httpx.Response:
        nonlocal calls
        del args, kwargs
        calls += 1
        return _response(401, payload={"error": "invalid"})

    with patch.object(httpx.AsyncClient, "get", fake_get):
        with pytest.raises(SearchAggregationError) as error:
            asyncio.run(provider.fetch_ai_overview(AiOverviewQuery(text="q")))

    assert calls == 1
    assert error.value.code is SearchAggregationErrorCode.AUTHENTICATION
    assert error.value.retryable is False


def test_secret_resolution_failure_is_configuration_error_without_provider_body() -> None:
    class BrokenResolver:
        def resolve(self, handle: SecretVersionHandle) -> SecretValue:
            del handle
            raise RuntimeError("credential backend unavailable")

    provider = SerpApiSearchProvider(
        secret_handle=HANDLE,
        credential_resolver=BrokenResolver(),
    )
    with pytest.raises(SearchAggregationError) as error:
        asyncio.run(provider.fetch_ai_overview(AiOverviewQuery(text="q")))

    assert error.value.code is SearchAggregationErrorCode.CONFIGURATION
    assert "credential backend unavailable" not in str(error.value)


async def _record_sleep(target: list[float], delay: float) -> None:
    target.append(delay)
