from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from geno_core.audit import build_audit_event
from geno_core.models import AnswerAnalysis, AuditEvent, RawEvidenceRecord


ANALYSIS_OUTPUT_CONTRACT_VERSION = "answer_analysis_output_contract_v1"
HUMAN_REVIEW_OVERRIDE_VERSION = "answer_analysis_human_review_override_v1"


def _stable_id(kind: str, *parts: object) -> str:
    return str(uuid5(NAMESPACE_URL, ":".join(("geno", kind, *(str(part) for part in parts)))))


def _recommendation_state(analysis: AnswerAnalysis) -> str:
    if analysis.brand_recommended:
        return "brand_recommended"
    if analysis.brand_mentioned:
        return "brand_mentioned_not_recommended"
    if analysis.competitors_mentioned:
        return "competitor_recommended_or_mentioned"
    return "no_recommendation_detected"


def _sentiment_label(score: float) -> str:
    if score >= 70:
        return "positive"
    if score <= 40:
        return "negative"
    return "neutral"


def build_answer_analysis_output_contract(
    *,
    analysis: AnswerAnalysis,
    record: RawEvidenceRecord,
) -> dict[str, Any]:
    citation_domains = tuple(dict.fromkeys(citation.domain for citation in record.citations if citation.domain))
    limitations: list[str] = []
    if "no_citations" in analysis.uncertainty_flags or not record.citations:
        limitations.append("citation_strength_limited_by_missing_sources")
    if analysis.brand_position is None:
        limitations.append("brand_position_not_observed")
    if analysis.parser_comparison and analysis.parser_comparison.get("mismatched_fields"):
        limitations.append("parser_judge_disagreement_requires_review")
    if not record.answer_run.answer_present:
        limitations.append("answer_not_present")

    entity_positions: list[dict[str, Any]] = []
    if analysis.brand_position is not None:
        entity_positions.append(
            {
                "entity_type": "brand",
                "entity_name": "brand",
                "position": analysis.brand_position,
                "basis": "first textual occurrence among brand and competitor aliases",
            }
        )
    for index, competitor in enumerate(analysis.competitors_mentioned, start=1):
        entity_positions.append(
            {
                "entity_type": "competitor",
                "entity_name": competitor,
                "position": index,
                "basis": "competitor textual occurrence detected; exact relative rank is not claimed",
            }
        )

    recommended_entities = ["brand"] if analysis.brand_recommended else []
    if not recommended_entities and analysis.competitors_mentioned:
        recommended_entities.extend(analysis.competitors_mentioned)

    citation_strength = "strong" if analysis.citation_count >= 3 else "limited" if analysis.citation_count else "none"
    return {
        "contract_version": ANALYSIS_OUTPUT_CONTRACT_VERSION,
        "analysis_id": analysis.id,
        "answer_run_id": analysis.answer_run_id,
        "parser_engine_id": analysis.parser_engine_id,
        "parser_version": analysis.analysis_version,
        "brand_mentions": ["brand"] if analysis.brand_mentioned else [],
        "competitor_mentions": sorted(analysis.competitors_mentioned),
        "entity_positions": entity_positions,
        "recommendation_state": _recommendation_state(analysis),
        "recommended_entities_ordered": tuple(recommended_entities),
        "citation_domains": citation_domains,
        "citation_strength": citation_strength,
        "unsupported_claims": (),
        "sentiment_label": _sentiment_label(analysis.sentiment_score),
        "fact_risk_label": None,
        "local_relevance_label": "local" if analysis.local_relevance_score >= 60 else "generic",
        "limitations": tuple(limitations),
        "raw_metrics": {
            "citation_count": analysis.citation_count,
            "local_relevance_score": analysis.local_relevance_score,
            "sentiment_score": analysis.sentiment_score,
            "freshness_score": analysis.freshness_score,
            "competitor_share_score": analysis.competitor_share_score,
            "confidence": analysis.confidence,
        },
        "not_claimed_metrics": (
            "average_position",
            "share_of_voice",
            "wrong_fact_flag",
            "negative_sentiment_as_validated_fact",
        ),
    }


def apply_human_review_override(
    *,
    project_id: str,
    analysis: AnswerAnalysis,
    reviewer_id: str,
    overrides: Mapping[str, Any],
    reason: str,
    reviewed_at: datetime | None = None,
) -> tuple[AnswerAnalysis, AuditEvent]:
    allowed_fields = {
        "brand_mentioned",
        "brand_recommended",
        "brand_position",
        "competitors_mentioned",
        "citation_count",
        "local_relevance_score",
        "sentiment_score",
        "freshness_score",
        "competitor_share_score",
        "confidence",
        "uncertainty_flags",
    }
    unknown_fields = tuple(sorted(set(overrides) - allowed_fields))
    if unknown_fields:
        raise ValueError(f"unsupported analysis override fields: {', '.join(unknown_fields)}")
    before = {field: getattr(analysis, field) for field in allowed_fields if field in overrides}
    override_values = dict(overrides)
    if "competitors_mentioned" in override_values:
        override_values["competitors_mentioned"] = list(override_values["competitors_mentioned"] or [])
    if "uncertainty_flags" in override_values:
        override_values["uncertainty_flags"] = list(override_values["uncertainty_flags"] or [])
    current_metadata = dict(analysis.parser_comparison or {})
    review_history = list(current_metadata.get("human_review_history") or [])
    reviewed_at = reviewed_at or datetime.now(UTC)
    review_id = _stable_id("analysis-human-review", analysis.id, reviewer_id, reviewed_at.isoformat())
    review_history.append(
        {
            "review_id": review_id,
            "reviewer_id": reviewer_id,
            "reason": reason,
            "overrides": override_values,
            "reviewed_at": reviewed_at.isoformat(),
            "override_version": HUMAN_REVIEW_OVERRIDE_VERSION,
        }
    )
    overridden = replace(
        analysis,
        **override_values,
        analysis_version=f"{analysis.analysis_version}+human_review",
        parser_comparison={
            **current_metadata,
            "human_review_history": review_history,
            "original_parser_output": {field: getattr(analysis, field) for field in allowed_fields},
        },
    )
    audit_event = build_audit_event(
        event_type="analysis.reviewed",
        project_id=project_id,
        actor_type="user",
        actor_id=reviewer_id,
        target_type="answer_analysis",
        target_id=analysis.id,
        before=before,
        after=override_values,
        input_refs={"answer_analysis_ids": [analysis.id]},
        output_refs={"answer_analysis_ids": [overridden.id], "human_review_ids": [review_id]},
        method_version=HUMAN_REVIEW_OVERRIDE_VERSION,
        reason=reason,
    )
    return overridden, audit_event
