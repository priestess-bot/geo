from __future__ import annotations

import pytest

from geo_core.sampling import CaptureMethod
from geo_core.sampling.provider_sources import (
    ProviderSourceIdentityError,
    gateway_provider_for_source,
    require_canonical_provider_source,
)


@pytest.mark.parametrize(
    ("provider", "platform", "surface", "capture_method"),
    (
        ("openai", "openai", "openai_api", CaptureMethod.PROVIDER_API),
        ("gemini", "google", "google_gemini_api", CaptureMethod.PROVIDER_API),
        ("perplexity", "perplexity", "perplexity_api", CaptureMethod.PROVIDER_API),
        (
            "microsoft",
            "microsoft",
            "microsoft_foundry_bing_grounding",
            CaptureMethod.PROXY_GROUNDED_API,
        ),
        ("kimi", "kimi", "kimi_api", CaptureMethod.PROVIDER_API),
    ),
)
def test_five_provider_sources_keep_gateway_routing_out_of_metric_identity(
    provider: str,
    platform: str,
    surface: str,
    capture_method: CaptureMethod,
) -> None:
    identity = require_canonical_provider_source(
        gateway_provider=provider,
        platform=platform,
        surface=surface,
        capture_method=capture_method,
    )

    assert identity.gateway_provider == provider
    assert gateway_provider_for_source(
        platform=platform,
        surface=surface,
        capture_method=capture_method,
    ) == provider


def test_gemini_cannot_put_its_gateway_key_into_the_google_source_stratum() -> None:
    with pytest.raises(ProviderSourceIdentityError, match="canonical"):
        require_canonical_provider_source(
            gateway_provider="gemini",
            platform="gemini",
            surface="google_gemini_api",
            capture_method=CaptureMethod.PROVIDER_API,
        )


@pytest.mark.parametrize(
    ("platform", "surface", "capture_method"),
    (
        ("google", "google_gemini_api", CaptureMethod.PROXY_GROUNDED_API),
        ("google", "openai_api", CaptureMethod.PROVIDER_API),
        ("microsoft", "microsoft_foundry_bing_grounding", CaptureMethod.PROVIDER_API),
    ),
)
def test_known_surfaces_reject_relabelling(
    platform: str, surface: str, capture_method: CaptureMethod
) -> None:
    with pytest.raises(ProviderSourceIdentityError, match="inconsistent"):
        gateway_provider_for_source(
            platform=platform,
            surface=surface,
            capture_method=capture_method,
        )


def test_historical_noncanonical_source_remains_readable() -> None:
    assert gateway_provider_for_source(
        platform="openai",
        surface="web_search",
        capture_method=CaptureMethod.PROVIDER_API,
    ) == "openai"
