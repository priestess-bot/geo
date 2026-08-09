"""Explicit registration for supported search aggregation providers.

The registry is intentionally small. A provider becomes runnable only when its
immutable Secret Store handle and resolver are supplied by the worker
composition; there is no environment/API-key fallback in this path.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from geo_core.search_aggregation.domain import SearchAggregationError, SearchAggregationErrorCode
from geo_core.search_aggregation.ports import SearchCredentialResolver, SearchProvider
from geo_core.search_aggregation.serpapi_adapter import SerpApiSearchProvider
from geo_core.secrets.models import SecretVersionHandle
from geo_core.model_gateway.releases import KNOWN_SEARCH_PROVIDERS


@dataclass(frozen=True)
class SearchProviderRegistration:
    """Stable provider metadata used by runtime admission and evidence."""

    provider_id: str
    display_name: str
    endpoint: str
    secret_purpose: str
    surface: str


SERPAPI_REGISTRATION = SearchProviderRegistration(
    provider_id="serpapi",
    display_name="SerpAPI Google Search",
    endpoint="https://serpapi.com/search.json",
    secret_purpose="search.serpapi",
    surface="google_search",
)

SEARCH_PROVIDER_REGISTRY: Mapping[str, SearchProviderRegistration] = MappingProxyType(
    {SERPAPI_REGISTRATION.provider_id: SERPAPI_REGISTRATION}
)

if set(SEARCH_PROVIDER_REGISTRY) != set(KNOWN_SEARCH_PROVIDERS):
    raise RuntimeError("search provider registry and KNOWN_SEARCH_PROVIDERS differ")


def search_provider_registration(provider_id: str) -> SearchProviderRegistration:
    """Return a registered provider or fail closed with a safe message."""
    try:
        return SEARCH_PROVIDER_REGISTRY[provider_id]
    except KeyError as exc:
        raise SearchAggregationError(
            f"Search provider is not registered: {provider_id}.",
            code=SearchAggregationErrorCode.CONFIGURATION,
        ) from exc


def build_search_provider(
    provider_id: str,
    *,
    secret_handle: SecretVersionHandle,
    credential_resolver: SearchCredentialResolver,
    timeout_seconds: float = 30.0,
    max_attempts: int = 3,
    retry_base_seconds: float = 0.25,
) -> SearchProvider:
    """Build one registered provider from an immutable Secret Store handle."""
    registration = search_provider_registration(provider_id)
    if secret_handle.purpose != registration.secret_purpose:
        raise SearchAggregationError(
            "Search provider Secret Store purpose does not match its registration.",
            code=SearchAggregationErrorCode.CONFIGURATION,
        )
    if provider_id == SERPAPI_REGISTRATION.provider_id:
        return SerpApiSearchProvider(
            timeout_seconds=timeout_seconds,
            secret_handle=secret_handle,
            credential_resolver=credential_resolver,
            max_attempts=max_attempts,
            retry_base_seconds=retry_base_seconds,
        )
    raise SearchAggregationError(
        f"Search provider is not implemented: {provider_id}.",
        code=SearchAggregationErrorCode.CONFIGURATION,
    )


__all__ = [
    "SERPAPI_REGISTRATION",
    "SEARCH_PROVIDER_REGISTRY",
    "SearchProviderRegistration",
    "build_search_provider",
    "search_provider_registration",
]
