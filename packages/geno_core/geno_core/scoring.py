from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_FLOOR, InvalidOperation
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

VISIBILITY_V1_0: dict[str, float] = {
    "MentionScore": 0.30,
    "RecommendationScore": 0.30,
    "PositionScore": 0.10,
    "CitationScore": 0.10,
    "LocalRelevanceScore": 0.20,
    "SentimentScore": 0.00,
    "FreshnessScore": 0.00,
    "CompetitorShareScore": 0.00,
}


@dataclass(frozen=True)
class ScoreFormulaDefinition:
    formula_version: str
    weights: dict[str, float]
    description: str
    status: str
    supersedes: str | None = None


@dataclass(frozen=True)
class ScoreWeightProfileDefinition:
    profile_key: str
    name: str
    description: str
    base_formula_version: str
    weights: dict[str, float]
    is_system: bool = True
    status: str = "active"


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
    "visibility_v1.0": ScoreFormulaDefinition(
        formula_version="visibility_v1.0",
        weights=VISIBILITY_V1_0,
        description=(
            "Production v1 GEO formula: Trigger is reported as denominator context; Brand Mention 30%, "
            "Recommendation 30%, Citation Strength 10%, Competitor Relative Position 10%, and "
            "Local/market relevance 20% using existing component signals."
        ),
        status="active",
    ),
}

SCORE_WEIGHT_PROFILE_REGISTRY: dict[str, ScoreWeightProfileDefinition] = {
    "au_visibility_v1": ScoreWeightProfileDefinition(
        profile_key="au_visibility_v1",
        name="AU GEO 可见度均衡方案",
        description="适合澳大利亚 DTC 项目的默认方案，平衡品牌提及、推荐强度、引用可信度、本地相关性和竞品份额。",
        base_formula_version="au_visibility_v1",
        weights=AU_VISIBILITY_V1,
    ),
    "au_visibility_v1_1_local_boost": ScoreWeightProfileDefinition(
        profile_key="au_visibility_v1_1_local_boost",
        name="AU 本地相关性强化方案",
        description="更重视城市、本地配送、退换政策和澳大利亚市场语境，适合本地服务差异明显的品牌。",
        base_formula_version="au_visibility_v1",
        weights=AU_VISIBILITY_V1_1_LOCAL_BOOST,
    ),
    "visibility_v1_0_purchase_decision": ScoreWeightProfileDefinition(
        profile_key="visibility_v1_0_purchase_decision",
        name="购买决策推荐方案",
        description="更重视 AI 是否把目标品牌作为购买建议推荐，并关注品牌在答案顺序中的位置。",
        base_formula_version="au_visibility_v1",
        weights=VISIBILITY_V1_0,
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


def list_score_weight_profiles() -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "id": None,
            "profile_key": profile.profile_key,
            "name": profile.name,
            "description": profile.description,
            "base_formula_version": profile.base_formula_version,
            "formula_version": profile.base_formula_version,
            "weights": dict(profile.weights),
            "scope": "global",
            "is_system": profile.is_system,
            "status": profile.status,
            "updated_by": "system-default",
        }
        for profile in SCORE_WEIGHT_PROFILE_REGISTRY.values()
    )


def get_score_formula(formula_version: str = "au_visibility_v1") -> ScoreFormulaDefinition:
    version = formula_version.strip() or "au_visibility_v1"
    try:
        return SCORE_FORMULA_REGISTRY[version]
    except KeyError as exc:
        known_versions = ", ".join(sorted(SCORE_FORMULA_REGISTRY))
        raise ValueError(f"Unknown score formula version: {version}. Known versions: {known_versions}") from exc


def normalize_score_weights_to_cents(score_weights: dict[str, float] | None = None) -> dict[str, float]:
    if score_weights is None:
        return dict(AU_VISIBILITY_V1)
    expected = set(SCORE_COMPONENTS)
    provided = set(score_weights)
    missing = sorted(expected - provided)
    unknown = sorted(provided - expected)
    if missing:
        raise ValueError(f"Missing score weight components: {', '.join(missing)}")
    if unknown:
        raise ValueError(f"Unknown score weight components: {', '.join(unknown)}")
    decimals: dict[str, Decimal] = {}
    for name in SCORE_COMPONENTS:
        try:
            value = Decimal(str(score_weights[name]))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"Invalid score weight for {name}") from exc
        if value < 0:
            raise ValueError("Score weights must be non-negative")
        decimals[name] = value
    total = sum(decimals.values(), Decimal("0"))
    if total <= 0:
        raise ValueError("Score weights must have a positive total")
    scaled: list[tuple[str, Decimal, int, Decimal]] = []
    allocated = 0
    for name in SCORE_COMPONENTS:
        exact = decimals[name] / total * Decimal("100")
        floor_units = int(exact.to_integral_value(rounding=ROUND_FLOOR))
        scaled.append((name, exact, floor_units, exact - Decimal(floor_units)))
        allocated += floor_units
    remainder = 100 - allocated
    order = sorted(range(len(scaled)), key=lambda index: (-scaled[index][3], scaled[index][0]))
    units = {name: floor_units for name, _, floor_units, _ in scaled}
    for index in order[:remainder]:
        units[scaled[index][0]] += 1
    return {name: round(units[name] / 100, 2) for name in SCORE_COMPONENTS}


def normalize_score_weights(
    score_weights: dict[str, float] | None = None,
    *,
    formula_version: str = "au_visibility_v1",
) -> dict[str, float]:
    formula = get_score_formula(formula_version)
    if score_weights is None:
        return dict(formula.weights)
    return normalize_score_weights_to_cents(score_weights)


class RegistryScoringFormula:
    def __init__(self, formula_version: str = "au_visibility_v1") -> None:
        formula = get_score_formula(formula_version)
        self.formula_version = formula.formula_version

    def score_analysis(
        self,
        *,
        project_id: str,
        analysis: AnswerAnalysis,
        platform_weights_snapshot: dict[str, float],
        score_weights: dict[str, float] | None = None,
        scope_type: str = "answer",
        scope_value: str = "single",
    ) -> "ScoreResult":
        return score_answer_analysis(
            project_id=project_id,
            analysis=analysis,
            platform_weights_snapshot=platform_weights_snapshot,
            score_weights=score_weights,
            formula_version=self.formula_version,
            scope_type=scope_type,
            scope_value=scope_value,
        )

    def score_analyses(
        self,
        *,
        project_id: str,
        analyses: tuple[AnswerAnalysis, ...],
        platform_weights_snapshot: dict[str, float],
        score_weights: dict[str, float] | None = None,
        scope_type: str,
        scope_value: str,
    ) -> "AggregateScoreResult":
        return score_answer_analyses(
            project_id=project_id,
            analyses=analyses,
            platform_weights_snapshot=platform_weights_snapshot,
            score_weights=score_weights,
            formula_version=self.formula_version,
            scope_type=scope_type,
            scope_value=scope_value,
        )


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
    score_input_policy: dict[str, Any] | None = None,
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
    if score_input_policy:
        excluded_count = len(score_input_policy.get("excluded_answer_run_ids", []))
        confidence_note = (
            f"{confidence_note}; score_input_policy={score_input_policy.get('policy_version', 'unknown')}; "
            f"excluded_answer_runs={excluded_count}"
        )
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
            "score_input_policy": score_input_policy or {},
        },
        input_refs={
            "answer_run_ids": answer_run_ids,
            **{
                key: [str(value) for value in values]
                for key, values in (score_input_policy or {}).items()
                if key.endswith("_answer_run_ids") and isinstance(values, list)
            },
        },
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
