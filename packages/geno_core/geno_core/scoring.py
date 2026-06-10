from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import pstdev
from typing import Any
from uuid import uuid4

from geno_core.audit import build_audit_event
from geno_core.models import AnswerAnalysis, AuditEvent, ScoreContribution, VisibilityScoreSnapshot


SCORE_COMPONENTS: tuple[str, ...] = (
    "MentionScore",
    "RecommendationScore",
    "PositionScore",
    "CitationScore",
    "LocalRelevanceScore",
    "SentimentScore",
    "FreshnessScore",
    "CompetitorShareScore",
)

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

AU_VISIBILITY_V1_1_LOCAL_BOOST: dict[str, float] = {
    "MentionScore": 0.17,
    "RecommendationScore": 0.21,
    "PositionScore": 0.11,
    "CitationScore": 0.15,
    "LocalRelevanceScore": 0.18,
    "SentimentScore": 0.07,
    "FreshnessScore": 0.06,
    "CompetitorShareScore": 0.05,
}


@dataclass(frozen=True)
class ScoreFormulaDefinition:
    formula_version: str
    weights: dict[str, float]
    description: str
    status: str
    supersedes: str | None = None


SCORE_FORMULA_REGISTRY: dict[str, ScoreFormulaDefinition] = {
    "au_visibility_v1": ScoreFormulaDefinition(
        formula_version="au_visibility_v1",
        weights=AU_VISIBILITY_V1,
        description="Default AU visibility score formula used for P0a customer evidence reports.",
        status="active",
    ),
    "au_visibility_v1_1_local_boost": ScoreFormulaDefinition(
        formula_version="au_visibility_v1_1_local_boost",
        weights=AU_VISIBILITY_V1_1_LOCAL_BOOST,
        description="AU visibility score variant that increases local relevance and freshness emphasis.",
        status="candidate",
        supersedes="au_visibility_v1",
    ),
}


def list_score_formulas() -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "formula_version": formula.formula_version,
            "weights": dict(formula.weights),
            "description": formula.description,
            "status": formula.status,
            "supersedes": formula.supersedes,
        }
        for formula in SCORE_FORMULA_REGISTRY.values()
    )


def get_score_formula(formula_version: str = "au_visibility_v1") -> ScoreFormulaDefinition:
    version = formula_version.strip() or "au_visibility_v1"
    try:
        return SCORE_FORMULA_REGISTRY[version]
    except KeyError as exc:
        known_versions = ", ".join(sorted(SCORE_FORMULA_REGISTRY))
        raise ValueError(f"Unknown score formula version: {version}. Known versions: {known_versions}") from exc


def normalize_score_weights(
    score_weights: dict[str, float] | None = None,
    *,
    formula_version: str = "au_visibility_v1",
) -> dict[str, float]:
    formula = get_score_formula(formula_version)
    if score_weights is None:
        return dict(formula.weights)
    expected = set(SCORE_COMPONENTS)
    provided = set(score_weights)
    missing = sorted(expected - provided)
    unknown = sorted(provided - expected)
    if missing:
        raise ValueError(f"Missing score weight components: {', '.join(missing)}")
    if unknown:
        raise ValueError(f"Unknown score weight components: {', '.join(unknown)}")
    normalized = {name: round(float(score_weights[name]), 6) for name in SCORE_COMPONENTS}
    if any(weight < 0 for weight in normalized.values()):
        raise ValueError("Score weights must be non-negative")
    total_weight = round(sum(normalized.values()), 6)
    if abs(total_weight - 1.0) > 0.0001:
        raise ValueError("Score weights must sum to 1.0")
    return normalized


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
    score_weights: dict[str, float] | None = None,
    formula_version: str = "au_visibility_v1",
    scope_type: str = "answer",
    scope_value: str = "single",
) -> ScoreResult:
    formula = get_score_formula(formula_version)
    component_weights = normalize_score_weights(score_weights, formula_version=formula.formula_version)
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
        sum(component_scores[name] * weight for name, weight in component_weights.items()),
        4,
    )
    now = datetime.now(UTC)
    snapshot_id = str(uuid4())
    snapshot = VisibilityScoreSnapshot(
        id=snapshot_id,
        project_id=project_id,
        scope_type=scope_type,
        scope_value=scope_value,
        formula_version=formula.formula_version,
        platform_weights_snapshot=platform_weights_snapshot,
        final_score=final_score,
        trigger_rate=1.0,
        mention_rate=1.0 if analysis.brand_mentioned else 0.0,
        recommendation_rate=1.0 if analysis.brand_recommended else 0.0,
        answer_run_ids=[analysis.answer_run_id],
        created_at=now,
        component_weights_snapshot=component_weights,
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
        for name, weight in component_weights.items()
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


def _final_score_from_components(component_scores: dict[str, float], score_weights: dict[str, float]) -> float:
    return round(sum(component_scores[name] * weight for name, weight in score_weights.items()), 4)


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
    score_weights: dict[str, float] | None = None,
    formula_version: str = "au_visibility_v1",
    scope_type: str,
    scope_value: str,
) -> AggregateScoreResult:
    if not analyses:
        raise ValueError("At least one AnswerAnalysis is required")
    formula = get_score_formula(formula_version)
    component_weights = normalize_score_weights(score_weights, formula_version=formula.formula_version)
    per_answer_components = [_component_scores(analysis) for analysis in analyses]
    component_scores = {
        name: round(
            sum(answer_components[name] for answer_components in per_answer_components)
            / len(per_answer_components),
            4,
        )
        for name in component_weights
    }
    per_answer_scores = [_final_score_from_components(components, component_weights) for components in per_answer_components]
    final_score = _final_score_from_components(component_scores, component_weights)
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
        formula_version=formula.formula_version,
        platform_weights_snapshot=platform_weights_snapshot,
        final_score=final_score,
        trigger_rate=1.0,
        mention_rate=round(mentioned_count / triggered_count, 4),
        recommendation_rate=round(recommended_count / triggered_count, 4),
        answer_run_ids=answer_run_ids,
        created_at=now,
        dispersion=round(pstdev(per_answer_scores), 4) if len(per_answer_scores) > 1 else 0.0,
        component_weights_snapshot=component_weights,
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
        for name, weight in component_weights.items()
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
            "formula_status": formula.status,
            "final_score": snapshot.final_score,
            "trigger_rate": snapshot.trigger_rate,
            "mention_rate": snapshot.mention_rate,
            "recommendation_rate": snapshot.recommendation_rate,
            "dispersion": snapshot.dispersion,
            "component_weights_snapshot": component_weights,
        },
        input_refs={"answer_run_ids": answer_run_ids},
        output_refs={
            "score_snapshot_ids": [snapshot_id],
            "score_contribution_ids": [contribution.id for contribution in contributions],
        },
        method_version=formula.formula_version,
        reason="M3 aggregate visibility score snapshot",
    )
    return AggregateScoreResult(
        snapshot=snapshot,
        contributions=contributions,
        audit_event=audit_event,
    )


def rescore_snapshot_with_formula(
    *,
    project_id: str,
    analyses: tuple[AnswerAnalysis, ...],
    platform_weights_snapshot: dict[str, float],
    target_formula_version: str,
    score_weights: dict[str, float] | None = None,
    scope_type: str = "formula_replay",
    scope_value: str = "runtime_replay",
) -> AggregateScoreResult:
    result = score_answer_analyses(
        project_id=project_id,
        analyses=analyses,
        platform_weights_snapshot=platform_weights_snapshot,
        score_weights=score_weights,
        formula_version=target_formula_version,
        scope_type=scope_type,
        scope_value=scope_value,
    )
    replay_audit = build_audit_event(
        event_type="visibility_score_snapshot_rescored",
        project_id=project_id,
        actor_type="system",
        actor_id="geno-core.scoring",
        target_type="visibility_score_snapshot",
        target_id=result.snapshot.id,
        before=None,
        after={
            "snapshot_id": result.snapshot.id,
            "formula_version": result.snapshot.formula_version,
            "final_score": result.snapshot.final_score,
            "component_weights_snapshot": result.snapshot.component_weights_snapshot,
        },
        input_refs={"answer_run_ids": result.snapshot.answer_run_ids},
        output_refs={
            "score_snapshot_ids": [result.snapshot.id],
            "score_contribution_ids": [contribution.id for contribution in result.contributions],
        },
        method_version=result.snapshot.formula_version,
        reason="Replay historical answer analyses with a selected score formula version",
    )
    return AggregateScoreResult(
        snapshot=result.snapshot,
        contributions=result.contributions,
        audit_event=replay_audit,
    )
