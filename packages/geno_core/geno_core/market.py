from __future__ import annotations

from geno_core.models import MarketProfile, PlatformConfig


def build_au_market_profile() -> MarketProfile:
    return MarketProfile(
        market="Australia",
        market_code="AU",
        locale="en-AU",
        timezone="Australia/Sydney",
        currency="AUD",
        primary_language="Australian English",
        cities=["Australia", "Sydney", "Melbourne", "Brisbane", "Perth", "Adelaide"],
        source_types=[
            "official_site",
            "google_business",
            "review_site",
            "reddit",
            "youtube",
            "local_media",
            "industry_site",
            "comparison_site",
            "marketplace",
            "government_or_regulator",
            "association",
        ],
        platforms=[
            PlatformConfig(
                platform="chatgpt",
                surface="chatgpt_search",
                build_stage="P0a",
                weight=0.30,
                enabled=True,
            ),
            PlatformConfig(
                platform="perplexity",
                surface="sonar",
                build_stage="P0a",
                weight=0.25,
                enabled=True,
            ),
            PlatformConfig(
                platform="google",
                surface="google_aio",
                build_stage="P0b",
                weight=0.45,
                enabled=False,
            ),
            PlatformConfig(
                platform="google",
                surface="google_ai_mode",
                build_stage="P0b",
                weight=0.45,
                enabled=False,
            ),
        ],
    )
