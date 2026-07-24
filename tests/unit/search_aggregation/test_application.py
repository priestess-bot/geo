"""Unit tests for the search aggregation application service."""

from __future__ import annotations

import asyncio

from geo_core.search_aggregation.application import SearchAggregationService
from geo_core.search_aggregation.domain import (
    AiOverviewBlock,
    AiOverviewQuery,
    AiOverviewReference,
    AiOverviewResult,
)
from geo_core.search_aggregation.mock_adapter import MockSearchProvider


def test_service_delegates_to_provider() -> None:
    provider = MockSearchProvider()
    service = SearchAggregationService(provider)
    result = asyncio.run(service.get_google_ai_overview(AiOverviewQuery(text="test query")))

    assert isinstance(result, AiOverviewResult)
    assert result.query == "test query"
    assert any(isinstance(block, AiOverviewBlock) for block in result.blocks)
    assert any(isinstance(reference, AiOverviewReference) for reference in result.references)
    assert result.raw_response is not None
