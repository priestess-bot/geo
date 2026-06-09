from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from geno_core.models import AnswerAnalysis, ScoreContribution, VisibilityScoreSnapshot


AU_VISIBILITY_V1: dict[str, float] = {
    "MentionScore": 0.18,
    "RecommendationScore": 0.22,
    "PositionScore": 0.12,
    "CitationScore": 0.16,
    "LocalRelevanceScore": 0.14,
    "SentimentScore": 0.08,
    "FreshnessScore": 0.05,
    "CompetitorShareScore": 0.05,
}


@dataclass(frozen=True)
class ScoreResult:
    snapshot: VisibilityScoreSnapshot
    contributions: list[ScoreContribution]


def _position_score(position: int | None) -> float:
    if position is None:
        return 0.0
    if position <= 1:
        return 100.0
    if position == 2:
        return 80.0
    if position == 3:
        return 60.0
    return 30.0


def _citation_score(citation_count: int) -> float:
    if citation_count <= 0:
        return 0.0
    if citation_count == 1:
        return 60.0
    if citation_count == 2:
        return 80.0
    return 100.0


def score_answer_analysis(
    *,
    project_id: str,
    analysis: AnswerAnalysis,
    platform_weights_snapshot: dict[str, float],
    scope_type: str = "answer",
    scope_value: str = "single",
) -> ScoreResult:
    component_scores = {
        "MentionScore": 100.0 if analysis.brand_mentioned else 0.0,
        "RecommendationScore": 100.0 if analysis.brand_recommended else 0.0,
        "PositionScore": _position_score(analysis.brand_position),
        "CitationScore": _citation_score(analysis.citation_count),
        "LocalRelevanceScore": analysis.local_relevance_score,
        "SentimentScore": analysis.sentiment_score,
        "FreshnessScore": analysis.freshness_score,
        "CompetitorShareScore": analysis.competitor_share_score,
    }
    final_score = round(
        sum(component_scores[name] * weight for name, weight in AU_VISIBILITY_V1.items()),
        4,
    )
    now = datetime.now(UTC)
    snapshot_id = str(uuid4())
    snapshot = VisibilityScoreSnapshot(
        id=snapshot_id,
        project_id=project_id,
        scope_type=scope_type,
        scope_value=scope_value,
        formula_version="au_visibility_v1",
        platform_weights_snapshot=platform_weights_snapshot,
        final_score=final_score,
        trigger_rate=1.0,
        mention_rate=1.0 if analysis.brand_mentioned else 0.0,
        recommendation_rate=1.0 if analysis.brand_recommended else 0.0,
        answer_run_ids=[analysis.answer_run_id],
        created_at=now,
    )
    contributions = [
        ScoreContribution(
            id=str(uuid4()),
            score_snapshot_id=snapshot_id,
            component_name=name,
            component_score=component_scores[name],
            weight=weight,
            weighted_contribution=round(component_scores[name] * weight, 4),
            denominator="surface_triggered" if name in {"MentionScore", "RecommendationScore"} else "answer",
            evidence_answer_run_ids=[analysis.answer_run_id],
            positive_evidence_summary="component contributes positively"
            if component_scores[name] > 0
            else "",
            negative_evidence_summary="component has no supporting evidence"
            if component_scores[name] == 0
            else "",
            confidence_note=f"parser_confidence={analysis.confidence}",
            created_at=now,
        )
        for name, weight in AU_VISIBILITY_V1.items()
    ]
    return ScoreResult(snapshot=snapshot, contributions=contributions)
