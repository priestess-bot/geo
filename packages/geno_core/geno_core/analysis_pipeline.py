from __future__ import annotations

from dataclasses import dataclass

from geno_core.models import (
    AnswerAnalysis,
    AuditEvent,
    BrandEntity,
    CompetitorEntity,
    RawEvidenceRecord,
    ScoreContribution,
    VisibilityScoreSnapshot,
)
from geno_core.parser import ComparativeAnswerParser
from geno_core.scoring import score_answer_analyses


@dataclass(frozen=True)
class VisibilityAnalysisResult:
    analyses: tuple[AnswerAnalysis, ...]
    snapshot: VisibilityScoreSnapshot
    contributions: tuple[ScoreContribution, ...]
    audit_event: AuditEvent


def analyze_and_score_records(
    *,
    project_id: str,
    records: tuple[RawEvidenceRecord, ...],
    brand: BrandEntity,
    competitors: tuple[CompetitorEntity, ...],
    platform_weights_snapshot: dict[str, float],
    score_weights: dict[str, float] | None = None,
    entity_aliases: dict[str, tuple[str, ...]] | None = None,
    scope_type: str = "project",
    scope_value: str = "p0a_fixture",
) -> VisibilityAnalysisResult:
    parser = ComparativeAnswerParser()
    analyses = tuple(
        parser.parse_record(
            record=record,
            brand=brand,
            competitors=competitors,
            entity_aliases=entity_aliases,
        )
        for record in records
    )
    score_result = score_answer_analyses(
        project_id=project_id,
        analyses=analyses,
        platform_weights_snapshot=platform_weights_snapshot,
        score_weights=score_weights,
        scope_type=scope_type,
        scope_value=scope_value,
    )
    return VisibilityAnalysisResult(
        analyses=analyses,
        snapshot=score_result.snapshot,
        contributions=tuple(score_result.contributions),
        audit_event=score_result.audit_event,
    )
