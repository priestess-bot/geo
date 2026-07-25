"""Frozen release registry for governed consumer-surface parsers."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from uuid import UUID, uuid5

from geo_core.sampling.contracts import SamplingRuleViolation
from geo_core.sampling.surface_parser_contracts import (
    SURFACE_PARSER_NAMESPACE,
    ConsumerSurface,
    SurfaceParserRelease,
)


def _release(
    key: str,
    *,
    platform: str,
    surface: ConsumerSurface,
    marker: str,
    allowed_hosts: tuple[str, ...],
) -> SurfaceParserRelease:
    return SurfaceParserRelease(
        id=uuid5(SURFACE_PARSER_NAMESPACE, key),
        release_key=key,
        release_version="2026-07-24.1",
        platform=platform,
        surface=surface,
        surface_marker=marker,
        allowed_hosts=allowed_hosts,
    )


SURFACE_PARSER_RELEASES = (
    _release(
        "google-ai-overviews-parser-v1",
        platform="google",
        surface=ConsumerSurface.GOOGLE_AI_OVERVIEWS,
        marker="google_ai_overview_answer",
        allowed_hosts=("google.com", "www.google.com"),
    ),
    _release(
        "google-ai-mode-parser-v1",
        platform="google",
        surface=ConsumerSurface.GOOGLE_AI_MODE,
        marker="google_ai_mode_answer",
        allowed_hosts=("google.com", "www.google.com"),
    ),
    _release(
        "bing-copilot-parser-v1",
        platform="bing",
        surface=ConsumerSurface.BING_COPILOT,
        marker="bing_copilot_answer",
        allowed_hosts=("bing.com", "www.bing.com"),
    ),
)
_RELEASE_BY_ID = MappingProxyType({item.id: item for item in SURFACE_PARSER_RELEASES})


def surface_parser_release(release_id: UUID) -> SurfaceParserRelease:
    try:
        return _RELEASE_BY_ID[release_id]
    except KeyError:
        raise SamplingRuleViolation("surface parser release does not exist") from None


def release_matches_source(release: SurfaceParserRelease, *, platform: str, surface: str) -> bool:
    platform_key = platform.strip().casefold().replace("-", "_")
    surface_key = surface.strip().casefold().replace("-", "_")
    if surface_key == release.surface.value or platform_key == release.surface.value:
        return True
    aliases: Mapping[ConsumerSurface, frozenset[tuple[str, str]]] = {
        ConsumerSurface.GOOGLE_AI_OVERVIEWS: frozenset(
            {("google", "ai_overviews"), ("google_search", "ai_overviews")}
        ),
        ConsumerSurface.GOOGLE_AI_MODE: frozenset(
            {("google", "ai_mode"), ("google_search", "ai_mode")}
        ),
        ConsumerSurface.BING_COPILOT: frozenset({("bing", "copilot"), ("bing_search", "copilot")}),
    }
    return (platform_key, surface_key) in aliases[release.surface]
