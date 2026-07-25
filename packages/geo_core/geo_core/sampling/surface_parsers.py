"""Versioned parsers for governed fixture and manual consumer-surface evidence.

This compatibility facade keeps the original public import path stable while
the contracts, frozen release registry, and parsing operations remain reviewable
as separate modules. These parsers never drive a browser or establish live or
Australian-egress eligibility.
"""

from geo_core.sampling.surface_parser_contracts import (
    ARTIFACT_SCHEMA_VERSION,
    PARSER_ENGINE_VERSION,
    REQUIRED_FIXTURE_BLOCK_REASONS,
    ConsumerSurface,
    SurfaceArtifactCaptureKind,
    SurfaceBlockReason,
    SurfaceCitation,
    SurfaceParseOutcome,
    SurfaceParseResult,
    SurfaceParseSummary,
    SurfaceParserFidelityScore,
    SurfaceParserGoldCase,
    SurfaceParserRelease,
    SurfaceParserReleaseStatus,
)
from geo_core.sampling.surface_parser_operations import (
    parse_governed_manual_surface_artifact,
    parse_surface_artifact,
    score_surface_parser_release,
    surface_parse_summary_from_mapping,
)
from geo_core.sampling.surface_parser_releases import (
    SURFACE_PARSER_RELEASES,
    release_matches_source,
    surface_parser_release,
)

__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "ConsumerSurface",
    "PARSER_ENGINE_VERSION",
    "REQUIRED_FIXTURE_BLOCK_REASONS",
    "SURFACE_PARSER_RELEASES",
    "SurfaceArtifactCaptureKind",
    "SurfaceBlockReason",
    "SurfaceCitation",
    "SurfaceParseOutcome",
    "SurfaceParseResult",
    "SurfaceParseSummary",
    "SurfaceParserFidelityScore",
    "SurfaceParserGoldCase",
    "SurfaceParserRelease",
    "SurfaceParserReleaseStatus",
    "parse_governed_manual_surface_artifact",
    "parse_surface_artifact",
    "release_matches_source",
    "score_surface_parser_release",
    "surface_parse_summary_from_mapping",
    "surface_parser_release",
]
