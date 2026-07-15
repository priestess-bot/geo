from __future__ import annotations

from copy import deepcopy
from typing import Any

from geo_core.models import MarketProfile, PlatformConfig


BROADER_PLATFORM_REGISTRY_VERSION = "au_broader_platform_registry_v1"

AU_BROADER_PLATFORM_CANDIDATES: tuple[dict[str, Any], ...] = (
    {
        "id": "gemini_ai_search",
        "platform": "gemini",
        "surface": "gemini_search",
        "build_stage": "P1",
        "platform_role": "ai_answer_platform",
        "default_weight": 0.0,
        "enabled": False,
        "priority": 1,
        "access_methods": ["official_api", "browser"],
        "adapter_status": "planned_not_implemented",
        "required_environment": ["GEMINI_API_KEY"],
        "evidence_requirements": ["answer_present", "surface_triggered", "citations", "raw_payload_hash"],
        "scoring_policy": "excluded_until_adapter_health_and_method_disclosure_pass",
        "source_signal_types": ["official_site", "local_media", "comparison_site"],
        "next_work_item": "gemini_collector_spike",
    },
    {
        "id": "bing_copilot_search",
        "platform": "bing_copilot",
        "surface": "copilot_search",
        "build_stage": "P1",
        "platform_role": "ai_answer_platform",
        "default_weight": 0.0,
        "enabled": False,
        "priority": 2,
        "access_methods": ["browser", "third_party_api", "manual"],
        "adapter_status": "planned_not_implemented",
        "required_environment": ["BING_COPILOT_BROWSER_ENABLED"],
        "evidence_requirements": ["answer_present", "surface_triggered", "citations", "screenshot_or_html_hash"],
        "scoring_policy": "excluded_until_adapter_health_and_method_disclosure_pass",
        "source_signal_types": ["official_site", "industry_site", "local_media"],
        "next_work_item": "copilot_browser_or_serp_spike",
    },
    {
        "id": "claude_web_search",
        "platform": "claude",
        "surface": "claude_search",
        "build_stage": "P1",
        "platform_role": "ai_answer_platform",
        "default_weight": 0.0,
        "enabled": False,
        "priority": 3,
        "access_methods": ["official_api", "browser"],
        "adapter_status": "planned_not_implemented",
        "required_environment": ["ANTHROPIC_API_KEY"],
        "evidence_requirements": ["answer_present", "citations_or_source_refs", "raw_payload_hash"],
        "scoring_policy": "excluded_until_adapter_health_and_method_disclosure_pass",
        "source_signal_types": ["official_site", "comparison_site", "industry_site"],
        "next_work_item": "claude_search_adapter_spike",
    },
    {
        "id": "youtube_search_reviews",
        "platform": "youtube",
        "surface": "youtube_search",
        "build_stage": "P2",
        "platform_role": "source_platform",
        "default_weight": 0.0,
        "enabled": False,
        "priority": 4,
        "access_methods": ["official_api", "browser"],
        "adapter_status": "planned_not_implemented",
        "required_environment": ["YOUTUBE_API_KEY"],
        "evidence_requirements": ["source_url", "title", "channel", "published_at", "raw_payload_hash"],
        "scoring_policy": "source_graph_only_until_answer_runner_defined",
        "source_signal_types": ["youtube", "review_site"],
        "next_work_item": "youtube_source_adapter",
    },
    {
        "id": "reddit_au_threads",
        "platform": "reddit",
        "surface": "reddit_search",
        "build_stage": "P2",
        "platform_role": "source_platform",
        "default_weight": 0.0,
        "enabled": False,
        "priority": 5,
        "access_methods": ["official_api", "third_party_api", "browser"],
        "adapter_status": "planned_not_implemented",
        "required_environment": ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"],
        "evidence_requirements": ["thread_url", "subreddit", "title", "created_at", "raw_payload_hash"],
        "scoring_policy": "source_graph_only_until_answer_runner_defined",
        "source_signal_types": ["reddit", "review_site", "local_media"],
        "next_work_item": "reddit_source_adapter",
    },
    {
        "id": "productreview_au_reviews",
        "platform": "productreview",
        "surface": "productreview_reviews",
        "build_stage": "P2",
        "platform_role": "source_platform",
        "default_weight": 0.0,
        "enabled": False,
        "priority": 6,
        "access_methods": ["browser", "manual"],
        "adapter_status": "planned_not_implemented",
        "required_environment": ["PRODUCTREVIEW_BROWSER_ENABLED"],
        "evidence_requirements": ["review_url", "rating", "review_text_hash", "review_date"],
        "scoring_policy": "source_graph_only_until_answer_runner_defined",
        "source_signal_types": ["review_site", "comparison_site"],
        "next_work_item": "productreview_source_adapter",
    },
)


def _broader_platform_configs() -> list[PlatformConfig]:
    return [
        PlatformConfig(
            platform=str(candidate["platform"]),
            surface=str(candidate["surface"]),
            build_stage=str(candidate["build_stage"]),
            weight=float(candidate["default_weight"]),
            enabled=bool(candidate["enabled"]),
        )
        for candidate in AU_BROADER_PLATFORM_CANDIDATES
    ]


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
            *_broader_platform_configs(),
        ],
    )


def build_au_broader_platform_registry() -> dict[str, Any]:
    profile = build_au_market_profile()
    profile_surfaces = {
        f"{item.platform}:{item.surface}": {
            "platform": item.platform,
            "surface": item.surface,
            "build_stage": item.build_stage,
            "weight": item.weight,
            "enabled": item.enabled,
        }
        for item in profile.platforms
    }
    candidates = []
    for candidate in AU_BROADER_PLATFORM_CANDIDATES:
        item = deepcopy(candidate)
        key = f"{item['platform']}:{item['surface']}"
        item["market_profile_registered"] = key in profile_surfaces
        item["market_profile_config"] = profile_surfaces.get(key, {})
        candidates.append(item)

    stage_counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    for candidate in candidates:
        stage = str(candidate["build_stage"])
        role = str(candidate["platform_role"])
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
        role_counts[role] = role_counts.get(role, 0) + 1

    p0a_enabled = [
        f"{item.platform}:{item.surface}" for item in profile.platforms if item.build_stage == "P0a" and item.enabled
    ]
    p0b_surfaces = [f"{item.platform}:{item.surface}" for item in profile.platforms if item.build_stage == "P0b"]
    candidate_surfaces = [f"{item['platform']}:{item['surface']}" for item in candidates]
    disabled_candidates = [item["id"] for item in candidates if item.get("enabled") is False]

    return {
        "registry_version": BROADER_PLATFORM_REGISTRY_VERSION,
        "market_profile": {
            "market": profile.market,
            "market_code": profile.market_code,
            "locale": profile.locale,
            "timezone": profile.timezone,
            "currency": profile.currency,
            "primary_language": profile.primary_language,
            "source_types": list(profile.source_types),
            "p0a_enabled_platform_surfaces": p0a_enabled,
            "p0b_platform_surfaces": p0b_surfaces,
            "all_platform_surfaces": list(profile_surfaces),
        },
        "summary": {
            "candidate_count": len(candidates),
            "registered_candidate_count": sum(1 for item in candidates if item["market_profile_registered"]),
            "enabled_candidate_count": len(candidates) - len(disabled_candidates),
            "disabled_candidate_count": len(disabled_candidates),
            "stage_counts": stage_counts,
            "role_counts": role_counts,
            "p0a_enabled_platform_surfaces": p0a_enabled,
            "p0b_platform_surfaces": p0b_surfaces,
            "candidate_platform_surfaces": candidate_surfaces,
            "adapter_status_counts": {
                status: sum(1 for item in candidates if item["adapter_status"] == status)
                for status in sorted({str(item["adapter_status"]) for item in candidates})
            },
        },
        "candidate_platforms": candidates,
        "stage_policy": [
            "P0a remains the stable evidence chain and only enables ChatGPT Search plus Perplexity Sonar.",
            "P0b Google AIO and AI Mode remain isolated behind Google spike gates.",
            "P1 AI-answer candidates are registered but disabled until adapter health, evidence fields and method disclosure pass.",
            "P2 source-platform candidates feed citation graph, source gap and content evidence before they can affect scoring.",
        ],
        "recommended_sequence": [
            "gemini_ai_search",
            "bing_copilot_search",
            "claude_web_search",
            "youtube_search_reviews",
            "reddit_au_threads",
            "productreview_au_reviews",
        ],
        "current_boundary": [
            "This registry proves AU broader platform expansion is explicit and auditable.",
            "It does not mean Gemini, Copilot, Claude, YouTube, Reddit or ProductReview collectors are implemented.",
            "All broader candidates stay disabled and weight=0.0 until a dedicated adapter, evidence package and gate are added.",
        ],
    }
