"""Search aggregation domain, ports, adapters, and application services."""

from __future__ import annotations

from geo_core.search_aggregation.domain import (
    SearchAggregationError,
    SearchAggregationErrorCode,
)
from geo_core.search_aggregation.registry import (
    KNOWN_SEARCH_PROVIDERS,
    SERPAPI_REGISTRATION,
    SEARCH_PROVIDER_REGISTRY,
    SearchProviderRegistration,
    build_search_provider,
    search_provider_registration,
)
from geo_core.search_aggregation.ports import SearchCredentialResolver, SearchProvider
from geo_core.search_aggregation.serpapi_adapter import SerpApiSearchProvider

__all__ = [
    "SERPAPI_REGISTRATION",
    "KNOWN_SEARCH_PROVIDERS",
    "SEARCH_PROVIDER_REGISTRY",
    "SearchAggregationError",
    "SearchAggregationErrorCode",
    "SearchCredentialResolver",
    "SearchProvider",
    "SearchProviderRegistration",
    "SerpApiSearchProvider",
    "build_search_provider",
    "search_provider_registration",
]
