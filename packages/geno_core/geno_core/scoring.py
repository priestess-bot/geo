from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import pstdev
from uuid import uuid4

from geno_core.audit import build_audit_event
from geno_core.models import AnswerAnalysis, AuditEvent, ScoreContribution, VisibilityScoreSnapshot


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


def _component_scores(analysis: AnswerAnalysis) -> dict[str, float]:
    return {
        "MentionScore": 100.0 if analysis.brand_mentioned else 0.0,
        "RecommendationScore": 100.0 if analysis.brand_recommended else 0.0,
        "PositionScore": _position_score(analysis.brand_position),
        "CitationScore": _citation_score(analysis.citation_count),
        "LocalRelevanceScore": analysis.local_relevance_score,
        "SentimentScore": analysis.sentiment_score,
        "FreshnessScore": analysis.freshness_score,
        "CompetitorShareScore": analysis.competitor_share_score,
    }


def _final_score_from_components(component_scores: dict[str, float]) -> float:
    return round(sum(component_scores[name] * weight for name, weight in AU_VISIBILITY_V1.items()), 4)


def _avg_parser_agreement(analyses: tuple[AnswerAnalysis, ...]) -> float | None:
    rates = [
        float(analysis.parser_comparison["agreement_rate"])
        for analysis in analyses
        if analysis.parser_comparison and analysis.parser_comparison.get("agreement_rate") is not None
    ]
    if not rates:
        return None
    return round(sum(rates) / len(rates), 4)


@dataclass(frozen=True)
class AggregateScoreResult:
    snapshot: VisibilityScoreSnapshot
    contributions: list[ScoreContribution]
    audit_event: AuditEvent


def score_answer_analyses(
    *,
    project_id: str,
    analyses: tuple[AnswerAnalysis, ...],
    platform_weights_snapshot: dict[str, float],
    scope_type: str,
    scope_value: str,
) -> AggregateScoreResult:
    if not analyses:
        raise ValueError("At least one AnswerAnalysis is required")
    per_answer_components = [_component_scores(analysis) for analysis in analyses]
    component_scores = {
        name: round(
            sum(answer_components[name] for answer_components in per_answer_components)
            / len(per_answer_components),
            4,
        )
        for name in AU_VISIBILITY_V1
    }
    per_answer_scores = [_final_score_from_components(components) for components in per_answer_components]
    final_score = _final_score_from_components(component_scores)
    now = datetime.now(UTC)
    snapshot_id = str(uuid4())
    triggered_count = len(analyses)
    mentioned_count = sum(1 for analysis in analyses if analysis.brand_mentioned)
    recommended_count = sum(1 for analysis in analyses if analysis.brand_recommended)
    answer_run_ids = [analysis.answer_run_id for analysis in analyses]
    avg_parser_confidence = round(sum(analysis.confidence for analysis in analyses) / len(analyses), 4)
    avg_parser_agreement = _avg_parser_agreement(analyses)
    confidence_note = f"avg_parser_confidence={avg_parser_confidence}"
    if avg_parser_agreement is not None:
        confidence_note = f"{confidence_note}; parser_ab_agreement={avg_parser_agreement}"
    snapshot = VisibilityScoreSnapshot(
        id=snapshot_id,
        project_id=project_id,
        scope_type=scope_type,
        scope_value=scope_value,
        formula_version="au_visibility_v1",
        platform_weights_snapshot=platform_weights_snapshot,
        final_score=final_score,
        trigger_rate=1.0,
        mention_rate=round(mentioned_count / triggered_count, 4),
        recommendation_rate=round(recommended_count / triggered_count, 4),
        answer_run_ids=answer_run_ids,
        created_at=now,
        dispersion=round(pstdev(per_answer_scores), 4) if len(per_answer_scores) > 1 else 0.0,
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
            evidence_answer_run_ids=answer_run_ids,
            positive_evidence_summary=f"{name} average={component_scores[name]} across {len(analyses)} answers",
            negative_evidence_summary=""
            if component_scores[name] > 0
            else f"No supporting evidence for {name}",
            confidence_note=confidence_note,
            created_at=now,
        )
        for name, weight in AU_VISIBILITY_V1.items()
    ]
    audit_event = build_audit_event(
        event_type="visibility_score_snapshot_created",
        project_id=project_id,
        actor_type="system",
        actor_id="geno-core.scoring",
        target_type="visibility_score_snapshot",
        target_id=snapshot_id,
        before=None,
        after={
            "snapshot_id": snapshot_id,
            "formula_version": snapshot.formula_version,
            "final_score": snapshot.final_score,
            "trigger_rate": snapshot.trigger_rate,
            "mention_rate": snapshot.mention_rate,
            "recommendation_rate": snapshot.recommendation_rate,
            "dispersion": snapshot.dispersion,
        },
        input_refs={"answer_run_ids": answer_run_ids},
        output_refs={
            "score_snapshot_ids": [snapshot_id],
            "score_contribution_ids": [contribution.id for contribution in contributions],
        },
        method_version="au_visibility_v1",
        reason="M3 aggregate visibility score snapshot",
    )
    return AggregateScoreResult(
        snapshot=snapshot,
        contributions=contributions,
        audit_event=audit_event,
    )
