"""Application boundary for non-live manual consumer-surface parsing."""

from __future__ import annotations

from uuid import UUID

from geo_core.sampling import (
    SamplingConflict,
    SurfaceParseSummary,
    parse_governed_manual_surface_artifact,
    release_matches_source,
    surface_parser_release,
)


def parse_manual_surface_summary(
    *,
    release_id: UUID | None,
    source_platform: str,
    source_surface: str,
    evidence_kind: str,
    content_type: str,
    content: bytearray,
    governance_policy_key: str,
    pre_redacted_attestation: bool,
) -> SurfaceParseSummary | None:
    if release_id is None:
        return None
    release = surface_parser_release(release_id)
    if not release_matches_source(
        release,
        platform=source_platform,
        surface=source_surface,
    ):
        raise SamplingConflict(
            "surface parser release differs from the frozen Sampling source stratum"
        )
    result = parse_governed_manual_surface_artifact(
        release,
        evidence_kind=evidence_kind,
        content_type=content_type,
        content=content,
        governance_policy_key=governance_policy_key,
        pre_redacted_attestation=pre_redacted_attestation,
    )
    return SurfaceParseSummary.from_result(result)


__all__ = ["parse_manual_surface_summary"]
