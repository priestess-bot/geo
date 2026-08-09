"""Unit tests for the SerpAPI search aggregation adapter."""

from __future__ import annotations

import pytest

from geo_core.search_aggregation.serpapi_adapter import (
    SerpApiSearchProvider,
    _extract_blocks_and_references,
    _find_overview_payload,
)


class TestFindOverviewPayload:
    def test_prefers_ai_overview(self) -> None:
        payload = {"ai_overview": {"text_blocks": []}, "answer_box": {"answer": "x"}}
        assert _find_overview_payload(payload) == {"text_blocks": []}

    def test_rejects_answer_box_as_a_different_surface(self) -> None:
        payload = {"answer_box": {"answer": "42"}}
        assert _find_overview_payload(payload) is None

    def test_returns_none_when_missing(self) -> None:
        assert _find_overview_payload({}) is None


class TestExtractBlocksAndReferences:
    def test_extracts_text_blocks(self) -> None:
        overview = {
            "text_blocks": [
                {"type": "paragraph", "text": "Hello world"},
                {"type": "list", "items": ["a", "b"]},
            ],
            "references": [
                {"title": "Example", "link": "https://example.com", "source": "example.com"}
            ],
        }
        blocks, references = _extract_blocks_and_references(overview)
        assert len(blocks) == 2
        assert blocks[0].type == "paragraph"
        assert blocks[0].text == "Hello world"
        assert blocks[1].type == "list"
        assert blocks[1].items is not None
        assert [item.text for item in blocks[1].items] == ["a", "b"]
        assert len(references) == 1
        assert references[0].title == "Example"
        assert references[0].url == "https://example.com"
        assert references[0].source == "example.com"

    def test_answer_box_fallback(self) -> None:
        overview = {"answer": "Answer text", "list": ["one", "two"]}
        blocks, references = _extract_blocks_and_references(overview)
        assert len(blocks) == 2
        assert blocks[0].text == "Answer text"
        assert blocks[1].items is not None
        assert [item.text for item in blocks[1].items] == ["one", "two"]

    def test_empty_overview(self) -> None:
        blocks, references = _extract_blocks_and_references(None)
        assert blocks == []
        assert references == []


class TestSerpApiSearchProvider:
    def test_rejects_empty_key(self) -> None:
        with pytest.raises(Exception):
            SerpApiSearchProvider(api_key="")

    def test_builds_query_params(self) -> None:
        provider = SerpApiSearchProvider(api_key="secret")
        assert provider._api_key == "secret"
