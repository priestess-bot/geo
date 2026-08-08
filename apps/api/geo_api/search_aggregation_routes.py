"""Internal routes for Google AI Overview aggregation.

This module is read-only: it calls an external search provider and returns a
structured projection without touching the database.
"""

from __future__ import annotations

import logging
import os
from typing import Annotated, Any

from fastapi import APIRouter, Header, Request, status

from geo_api.problems import ApiProblem
from geo_api.search_aggregation_contracts import (
    AiOverviewBlockContract,
    AiOverviewListItemContract,
    AiOverviewReferenceContract,
    GoogleAiOverviewRequest,
    GoogleAiOverviewResponse,
)
from geo_api.stable_routes import PROBLEM_RESPONSES, authentication_input, services_for_request
from geo_core.search_aggregation.application import SearchAggregationService
from geo_core.search_aggregation.domain import AiOverviewQuery, SearchAggregationError
from geo_core.search_aggregation.openrouter_adapter import OpenRouterWebSearchProvider
from geo_core.search_aggregation.perplexity_adapter import PerplexityOpenRouterProvider


_LOGGER = logging.getLogger("geo_api.search_aggregation")
AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]


def search_aggregation_router() -> APIRouter:
    """Build the search aggregation router for the internal API surface."""
    router = APIRouter(
        prefix="/v1/search",
        tags=["search"],
        responses=PROBLEM_RESPONSES,
    )

    @router.post(
        "/openrouter-openai-web",
        response_model=GoogleAiOverviewResponse,
        status_code=status.HTTP_200_OK,
        operation_id="getOpenRouterOpenAIWebOverview",
    )
    async def get_openrouter_openai_web_overview(
        payload: GoogleAiOverviewRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> Any:
        """Return a structured OpenRouter OpenAI Web Search answer."""
        _ = _current_identity(request, authorization)

        provider = _resolve_provider(engine="openrouter_openai_web_search")
        service = SearchAggregationService(provider)
        try:
            result = await service.get_google_ai_overview(_build_query(payload))
        except SearchAggregationError as exc:
            raise ApiProblem(
                status=502,
                title="Search Provider Error",
                detail=str(exc),
                type_uri="urn:geo:problem:search-provider-error",
            ) from exc

        if not result.blocks:
            raise ApiProblem(
                status=404,
                title="OpenRouter Answer Not Available",
                detail=f"OpenRouter did not return an answer for '{payload.query}'.",
                type_uri="urn:geo:problem:openrouter-answer-not-available",
            )

        return _result_to_contract(result)

    @router.post(
        "/openrouter-openai-web-raw",
        status_code=status.HTTP_200_OK,
        operation_id="getOpenRouterOpenAIWebRawSearch",
    )
    async def get_openrouter_openai_web_raw_search(
        payload: GoogleAiOverviewRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> Any:
        """Return the raw OpenRouter response for debugging."""
        _ = _current_identity(request, authorization)

        provider = _resolve_provider(engine="openrouter_openai_web_search")
        service = SearchAggregationService(provider)
        try:
            return await service.get_google_raw_search(_build_query(payload))
        except SearchAggregationError as exc:
            raise ApiProblem(
                status=502,
                title="Search Provider Error",
                detail=str(exc),
                type_uri="urn:geo:problem:search-provider-error",
            ) from exc

    @router.post(
        "/perplexity",
        response_model=GoogleAiOverviewResponse,
        status_code=status.HTTP_200_OK,
        operation_id="getPerplexityOverview",
    )
    async def get_perplexity_overview(
        payload: GoogleAiOverviewRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> Any:
        """Return a structured Perplexity answer for a search query."""
        _ = _current_identity(request, authorization)

        provider = _resolve_provider(engine="perplexity")
        service = SearchAggregationService(provider)
        try:
            result = await service.get_google_ai_overview(_build_query(payload))
        except SearchAggregationError as exc:
            raise ApiProblem(
                status=502,
                title="Search Provider Error",
                detail=str(exc),
                type_uri="urn:geo:problem:search-provider-error",
            ) from exc

        if not result.blocks:
            raise ApiProblem(
                status=404,
                title="Perplexity Answer Not Available",
                detail=f"Perplexity did not return an answer for '{payload.query}'.",
                type_uri="urn:geo:problem:perplexity-answer-not-available",
            )

        return _result_to_contract(result)

    @router.post(
        "/perplexity-raw",
        status_code=status.HTTP_200_OK,
        operation_id="getPerplexityRawSearch",
    )
    async def get_perplexity_raw_search(
        payload: GoogleAiOverviewRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> Any:
        """Return the raw OpenRouter/Perplexity response for debugging."""
        _ = _current_identity(request, authorization)

        provider = _resolve_provider(engine="perplexity")
        service = SearchAggregationService(provider)
        try:
            return await service.get_google_raw_search(_build_query(payload))
        except SearchAggregationError as exc:
            raise ApiProblem(
                status=502,
                title="Search Provider Error",
                detail=str(exc),
                type_uri="urn:geo:problem:search-provider-error",
            ) from exc

    return router


def _result_to_contract(result: Any) -> GoogleAiOverviewResponse:
    """Convert a domain ``AiOverviewResult`` to the transport contract."""
    return GoogleAiOverviewResponse(
        query=result.query,
        blocks=[
            AiOverviewBlockContract(
                type=block.type,
                text=block.text,
                items=[
                    AiOverviewListItemContract(
                        text=item.text,
                        inline_references=[
                            AiOverviewReferenceContract(
                                title=inline.reference.title,
                                url=inline.reference.url,
                                source=inline.reference.source,
                                highlighted_text=inline.highlighted_text,
                            )
                            for inline in item.inline_references
                        ],
                    )
                    for item in (block.items or [])
                ],
                inline_references=[
                    AiOverviewReferenceContract(
                        title=inline.reference.title,
                        url=inline.reference.url,
                        source=inline.reference.source,
                        highlighted_text=inline.highlighted_text,
                    )
                    for inline in block.inline_references
                ],
            )
            for block in result.blocks
        ],
        references=[
            AiOverviewReferenceContract(
                title=ref.title,
                url=ref.url,
                source=ref.source,
            )
            for ref in result.references
        ],
        has_overview=bool(result.blocks),
    )


def _build_query(payload: GoogleAiOverviewRequest) -> AiOverviewQuery:
    """Map the transport contract to the domain query."""
    return AiOverviewQuery(
        text=payload.query,
        locale=payload.hl or "en-US",
        region=(payload.gl or "us").upper(),
        location=payload.location,
        google_domain=payload.google_domain,
    )


def _resolve_provider(
    engine: str,
) -> OpenRouterWebSearchProvider | PerplexityOpenRouterProvider:
    """Choose one explicit API provider; consumer surfaces use Browser Capture."""
    if engine == "openrouter_openai_web_search":
        openrouter_key = _load_openrouter_key()
        if openrouter_key:
            return OpenRouterWebSearchProvider(
                api_key=openrouter_key,
                model=os.getenv("GEO_OPENROUTER_MODEL", "openai/gpt-5.5"),
                http_referer=os.getenv("GEO_OPENROUTER_HTTP_REFERER", "https://geo.local"),
                app_title=os.getenv("GEO_OPENROUTER_APP_TITLE", "GEO Search Demo"),
            )
        raise SearchAggregationError("OpenRouter API key is required.")

    if engine == "perplexity":
        openrouter_key = _load_openrouter_key()
        if openrouter_key:
            return PerplexityOpenRouterProvider(
                api_key=openrouter_key,
                model=os.getenv("GEO_PERPLEXITY_MODEL", "perplexity/sonar"),
                http_referer=os.getenv("GEO_OPENROUTER_HTTP_REFERER", "https://geo.local"),
                app_title=os.getenv("GEO_OPENROUTER_APP_TITLE", "GEO Search Demo"),
            )
        raise SearchAggregationError("OpenRouter API key is required for Perplexity.")

    raise SearchAggregationError(f"Unsupported search API provider: {engine}")


def _load_openrouter_key() -> str | None:
    """Load the OpenRouter API key from a file or environment variable."""
    key_file = os.getenv("GEO_OPENROUTER_API_KEY_FILE", "./openrouter_key.txt")
    try:
        if os.path.isfile(key_file):
            with open(key_file, encoding="utf-8") as handle:
                content = handle.read().strip()
                if content:
                    return content
    except OSError as exc:
        _LOGGER.warning("Could not read OpenRouter key file %s: %s", key_file, exc)

    env_key = os.getenv("GEO_OPENROUTER_API_KEY", "").strip()
    return env_key or None


def _current_identity(request: Request, authorization: str | None) -> Any:
    """Return the current actor identity, raising on authentication failure."""
    return services_for_request(request).current_identity(
        authentication_input(request, authorization)
    )
