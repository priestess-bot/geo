"""Canonical business-source identities for governed Provider Sampling."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from geo_core.sampling.contracts import CaptureMethod, SamplingRuleViolation


class ProviderSourceIdentityError(SamplingRuleViolation):
    """A Gateway provider was presented as the wrong measurement source."""


@dataclass(frozen=True)
class ProviderSourceIdentity:
    """Keep Gateway routing separate from the source users compare in metrics."""

    gateway_provider: str
    platform: str
    surface: str
    capture_method: CaptureMethod


_IDENTITIES = (
    ProviderSourceIdentity(
        gateway_provider="openai",
        platform="openai",
        surface="openai_api",
        capture_method=CaptureMethod.PROVIDER_API,
    ),
    ProviderSourceIdentity(
        gateway_provider="gemini",
        platform="google",
        surface="google_gemini_api",
        capture_method=CaptureMethod.PROVIDER_API,
    ),
    ProviderSourceIdentity(
        gateway_provider="perplexity",
        platform="perplexity",
        surface="perplexity_api",
        capture_method=CaptureMethod.PROVIDER_API,
    ),
    ProviderSourceIdentity(
        gateway_provider="microsoft",
        platform="microsoft",
        surface="microsoft_foundry_bing_grounding",
        capture_method=CaptureMethod.PROXY_GROUNDED_API,
    ),
    ProviderSourceIdentity(
        gateway_provider="kimi",
        platform="kimi",
        surface="kimi_api",
        capture_method=CaptureMethod.PROVIDER_API,
    ),
    ProviderSourceIdentity(
        gateway_provider="serpapi",
        platform="serpapi",
        surface="google_search",
        capture_method=CaptureMethod.PROVIDER_API,
    ),
)

PROVIDER_SOURCES_BY_GATEWAY: Mapping[str, ProviderSourceIdentity] = MappingProxyType(
    {item.gateway_provider: item for item in _IDENTITIES}
)
PROVIDER_SOURCES_BY_SURFACE: Mapping[str, ProviderSourceIdentity] = MappingProxyType(
    {item.surface: item for item in _IDENTITIES}
)


def canonical_provider_source(gateway_provider: str) -> ProviderSourceIdentity:
    """Return the exact first-release identity for one supported Provider adapter."""

    try:
        return PROVIDER_SOURCES_BY_GATEWAY[gateway_provider]
    except KeyError as exc:
        raise ProviderSourceIdentityError(
            f"Provider Sampling source is not registered: {gateway_provider}"
        ) from exc


def gateway_provider_for_source(
    *,
    platform: str,
    surface: str,
    capture_method: CaptureMethod | str,
) -> str:
    """Resolve the Gateway route without putting that key into metric strata.

    Historical Sampling fixtures used implementation-facing surface labels. They
    remain readable when their platform and Gateway key are the same. A known
    canonical surface, however, is always checked strictly and can never be
    relabelled as a consumer UI or another provider.
    """

    method = CaptureMethod(capture_method)
    identity = PROVIDER_SOURCES_BY_SURFACE.get(surface)
    if identity is None:
        return platform
    if identity.platform != platform or identity.capture_method is not method:
        raise ProviderSourceIdentityError(
            "Provider Sampling platform/surface/capture identity is inconsistent"
        )
    return identity.gateway_provider


def require_canonical_provider_source(
    *,
    gateway_provider: str,
    platform: str,
    surface: str,
    capture_method: CaptureMethod | str,
) -> ProviderSourceIdentity:
    """Require the exact source contract used by release and live-canary gates."""

    identity = canonical_provider_source(gateway_provider)
    method = CaptureMethod(capture_method)
    if (
        identity.platform != platform
        or identity.surface != surface
        or identity.capture_method is not method
    ):
        raise ProviderSourceIdentityError(
            "Provider canary must use its canonical platform/surface/capture identity"
        )
    return identity


__all__ = [
    "PROVIDER_SOURCES_BY_GATEWAY",
    "PROVIDER_SOURCES_BY_SURFACE",
    "ProviderSourceIdentity",
    "ProviderSourceIdentityError",
    "canonical_provider_source",
    "gateway_provider_for_source",
    "require_canonical_provider_source",
]
