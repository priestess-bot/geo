"""Unit tests for the OpenRouter Web Search adapter."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from geo_core.search_aggregation.domain import (
    AiOverviewQuery,
    AiOverviewResult,
    SearchAggregationError,
)
from geo_core.search_aggregation.openrouter_adapter import (
    OpenRouterWebSearchProvider,
    _extract_answer_text,
    _extract_citations,
)


def _response(
    status_code: int = 200, json_data: Any | None = None, text: str = ""
) -> httpx.Response:
    """Build an ``httpx.Response`` with a valid request so ``raise_for_status`` works."""
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    if json_data is not None:
        return httpx.Response(status_code, json=json_data, request=request)
    return httpx.Response(status_code, text=text, request=request)


class TestOpenRouterWebSearchProvider:
    def test_rejects_empty_key(self) -> None:
        with pytest.raises(SearchAggregationError, match="OpenRouter API key is required"):
            OpenRouterWebSearchProvider(api_key="")

    def test_rejects_none_key(self) -> None:
        with pytest.raises(SearchAggregationError, match="OpenRouter API key is required"):
            OpenRouterWebSearchProvider(api_key=None)  # type: ignore[arg-type]

    def test_builds_request_body_with_web_search_tool(self) -> None:
        provider = OpenRouterWebSearchProvider(api_key="test-key", model="openai/gpt-5.5")
        captured: dict[str, Any] = {}

        async def _fake_post(
            self: httpx.AsyncClient, url: str, *, headers: dict[str, str], json: dict[str, Any]
        ) -> httpx.Response:
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return _response(
                200,
                json_data={
                    "choices": [
                        {
                            "message": {
                                "content": "Answer",
                                "annotations": [],
                            }
                        }
                    ]
                },
            )

        with patch.object(httpx.AsyncClient, "post", _fake_post):
            result = asyncio.run(
                provider.fetch_ai_overview(AiOverviewQuery(text="best robot vacuum"))
            )

        assert captured["json"]["model"] == "openai/gpt-5.5"
        assert captured["json"]["messages"] == [{"role": "user", "content": "best robot vacuum"}]
        assert captured["json"]["tools"] == [{"type": "openrouter:web_search"}]
        assert captured["headers"]["Authorization"] == "Bearer test-key"
        assert captured["headers"]["HTTP-Referer"] == "https://geo.local"
        assert captured["headers"]["X-Title"] == "GEO Search Demo"
        assert isinstance(result, AiOverviewResult)

    def test_extracts_answer_from_content(self) -> None:
        provider = OpenRouterWebSearchProvider(api_key="test-key")

        async def _fake_post(*args: Any, **kwargs: Any) -> httpx.Response:
            return _response(
                200,
                json_data={
                    "choices": [
                        {
                            "message": {
                                "content": "  OpenRouter found the answer.  ",
                                "annotations": [],
                            }
                        }
                    ]
                },
            )

        with patch.object(httpx.AsyncClient, "post", _fake_post):
            result = asyncio.run(provider.fetch_ai_overview(AiOverviewQuery(text="q")))

        assert len(result.blocks) == 1
        assert result.blocks[0].type == "paragraph"
        assert result.blocks[0].text == "OpenRouter found the answer."

    def test_extracts_references_from_url_citations(self) -> None:
        provider = OpenRouterWebSearchProvider(api_key="test-key")

        async def _fake_post(*args: Any, **kwargs: Any) -> httpx.Response:
            return _response(
                200,
                json_data={
                    "choices": [
                        {
                            "message": {
                                "content": "Answer with citations.",
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "url_citation": {
                                            "url": "https://www.example.com/review",
                                            "title": "Example Review",
                                            "content": "Snippet",
                                            "start_index": 10,
                                            "end_index": 20,
                                        },
                                    },
                                    {
                                        "type": "url_citation",
                                        "url_citation": {
                                            "url": "https://openai.com/news",
                                            "title": "OpenAI News",
                                        },
                                    },
                                ],
                            }
                        }
                    ]
                },
            )

        with patch.object(httpx.AsyncClient, "post", _fake_post):
            result = asyncio.run(provider.fetch_ai_overview(AiOverviewQuery(text="q")))

        assert len(result.references) == 2
        assert result.references[0].title == "Example Review"
        assert result.references[0].url == "https://www.example.com/review"
        assert result.references[0].source == "example.com"
        assert result.references[1].title == "OpenAI News"
        assert result.references[1].url == "https://openai.com/news"
        assert result.references[1].source == "openai.com"

    def test_deduplicates_citation_urls(self) -> None:
        provider = OpenRouterWebSearchProvider(api_key="test-key")

        async def _fake_post(*args: Any, **kwargs: Any) -> httpx.Response:
            return _response(
                200,
                json_data={
                    "choices": [
                        {
                            "message": {
                                "content": "Answer.",
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "url_citation": {
                                            "url": "https://example.com/page",
                                            "title": "First",
                                        },
                                    },
                                    {
                                        "type": "url_citation",
                                        "url_citation": {
                                            "url": "https://example.com/page",
                                            "title": "Duplicate",
                                        },
                                    },
                                ],
                            }
                        }
                    ]
                },
            )

        with patch.object(httpx.AsyncClient, "post", _fake_post):
            result = asyncio.run(provider.fetch_ai_overview(AiOverviewQuery(text="q")))

        assert len(result.references) == 1
        assert result.references[0].title == "First"

    def test_preserves_raw_response(self) -> None:
        provider = OpenRouterWebSearchProvider(api_key="test-key")
        raw = {
            "id": "resp-123",
            "choices": [
                {
                    "message": {
                        "content": "Answer.",
                        "annotations": [],
                    }
                }
            ],
        }

        async def _fake_post(*args: Any, **kwargs: Any) -> httpx.Response:
            return _response(200, json_data=raw)

        with patch.object(httpx.AsyncClient, "post", _fake_post):
            result = asyncio.run(provider.fetch_ai_overview(AiOverviewQuery(text="q")))

        assert result.raw_response == raw

    def test_allows_empty_references_when_no_annotations(self) -> None:
        provider = OpenRouterWebSearchProvider(api_key="test-key")

        async def _fake_post(*args: Any, **kwargs: Any) -> httpx.Response:
            return _response(
                200,
                json_data={"choices": [{"message": {"content": "No citations here."}}]},
            )

        with patch.object(httpx.AsyncClient, "post", _fake_post):
            result = asyncio.run(provider.fetch_ai_overview(AiOverviewQuery(text="q")))

        assert len(result.blocks) == 1
        assert result.references == []

    def test_returns_empty_blocks_when_content_missing(self) -> None:
        provider = OpenRouterWebSearchProvider(api_key="test-key")

        async def _fake_post(*args: Any, **kwargs: Any) -> httpx.Response:
            return _response(200, json_data={"choices": [{"message": {}}]})

        with patch.object(httpx.AsyncClient, "post", _fake_post):
            result = asyncio.run(provider.fetch_ai_overview(AiOverviewQuery(text="q")))

        assert result.blocks == []
        assert result.references == []
        assert result.raw_response is not None

    def test_network_error_becomes_search_aggregation_error(self) -> None:
        provider = OpenRouterWebSearchProvider(api_key="test-key")

        async def _fake_post(*args: Any, **kwargs: Any) -> httpx.Response:
            raise httpx.NetworkError("connection failed")

        with patch.object(httpx.AsyncClient, "post", _fake_post):
            with pytest.raises(SearchAggregationError, match="Network error contacting OpenRouter"):
                asyncio.run(provider.fetch_ai_overview(AiOverviewQuery(text="q")))

    def test_http_error_becomes_search_aggregation_error(self) -> None:
        provider = OpenRouterWebSearchProvider(api_key="test-key")

        async def _fake_post(*args: Any, **kwargs: Any) -> httpx.Response:
            return _response(401, text="Unauthorized")

        with patch.object(httpx.AsyncClient, "post", _fake_post):
            with pytest.raises(SearchAggregationError, match="OpenRouter returned HTTP 401"):
                asyncio.run(provider.fetch_ai_overview(AiOverviewQuery(text="q")))

    def test_invalid_json_becomes_search_aggregation_error(self) -> None:
        provider = OpenRouterWebSearchProvider(api_key="test-key")

        async def _fake_post(*args: Any, **kwargs: Any) -> httpx.Response:
            return _response(200, text="not json")

        with patch.object(httpx.AsyncClient, "post", _fake_post):
            with pytest.raises(SearchAggregationError, match="OpenRouter returned invalid JSON"):
                asyncio.run(provider.fetch_ai_overview(AiOverviewQuery(text="q")))

    def test_fetch_raw_search_returns_raw_json(self) -> None:
        provider = OpenRouterWebSearchProvider(api_key="test-key")
        raw = {"choices": [{"message": {"content": "Raw"}}]}

        async def _fake_post(*args: Any, **kwargs: Any) -> httpx.Response:
            return _response(200, json_data=raw)

        with patch.object(httpx.AsyncClient, "post", _fake_post):
            result = asyncio.run(provider.fetch_raw_search(AiOverviewQuery(text="q")))

        assert result == raw


class TestExtractAnswerText:
    def test_returns_content(self) -> None:
        payload: dict[str, Any] = {"choices": [{"message": {"content": "answer"}}]}
        assert _extract_answer_text(payload) == "answer"

    def test_returns_none_when_choices_missing(self) -> None:
        assert _extract_answer_text({}) is None

    def test_returns_none_when_content_missing(self) -> None:
        payload: dict[str, Any] = {"choices": [{"message": {}}]}
        assert _extract_answer_text(payload) is None


class TestExtractCitations:
    def test_extracts_url_citations(self) -> None:
        payload = {
            "choices": [
                {
                    "message": {
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url_citation": {
                                    "url": "https://example.com",
                                    "title": "Example",
                                },
                            }
                        ]
                    }
                }
            ]
        }
        citations = _extract_citations(payload)
        assert len(citations) == 1
        assert citations[0].url == "https://example.com"
        assert citations[0].title == "Example"

    def test_ignores_non_url_citation_annotations(self) -> None:
        payload = {
            "choices": [
                {
                    "message": {
                        "annotations": [
                            {"type": "other", "url_citation": {"url": "https://example.com"}}
                        ]
                    }
                }
            ]
        }
        assert _extract_citations(payload) == []

    def test_returns_empty_when_annotations_missing(self) -> None:
        assert _extract_citations({"choices": [{"message": {}}]}) == []
