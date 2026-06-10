from __future__ import annotations

from dataclasses import dataclass
from dataclasses import asdict, is_dataclass
from typing import Any, Mapping

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
    score_input_analyses: tuple[AnswerAnalysis, ...]
    score_input_records: tuple[RawEvidenceRecord, ...]
    score_input_policy: dict[str, Any]
    snapshot: VisibilityScoreSnapshot
    contributions: tuple[ScoreContribution, ...]
    audit_event: AuditEvent


def _gate_to_mapping(google_spike_gate: Mapping[str, object] | object | None) -> Mapping[str, object] | None:
    if google_spike_gate is None:
        return None
    if is_dataclass(google_spike_gate):
        return asdict(google_spike_gate)
    if isinstance(google_spike_gate, Mapping):
        return google_spike_gate
    return None


def _google_main_scoring_allowed(
    *,
    google_spike_gate: Mapping[str, object] | object | None,
    google_spike_readiness_gate: Mapping[str, object] | object | None,
) -> bool:
    gate = _gate_to_mapping(google_spike_gate)
    readiness_gate = _gate_to_mapping(google_spike_readiness_gate)
    if gate is None:
        return False
    if readiness_gate is None:
        return False
    return (
        str(gate.get("gate_status") or "") == "pass"
        and not bool(gate.get("limited_coverage", True))
        and str(readiness_gate.get("gate_status") or "") == "pass"
    )


def build_score_input_policy(
    *,
    records: tuple[RawEvidenceRecord, ...],
    score_input_records: tuple[RawEvidenceRecord, ...],
    google_spike_gate: Mapping[str, object] | object | None,
    google_spike_readiness_gate: Mapping[str, object] | object | None,
) -> dict[str, Any]:
    gate = _gate_to_mapping(google_spike_gate)
    readiness_gate = _gate_to_mapping(google_spike_readiness_gate)
    all_answer_run_ids = [record.answer_run.id for record in records]
    score_input_answer_run_ids = [record.answer_run.id for record in score_input_records]
    score_input_answer_run_id_set = set(score_input_answer_run_ids)
    excluded_answer_run_ids = [
        record.answer_run.id
        for record in records
        if record.answer_run.id not in score_input_answer_run_id_set
    ]
    excluded_answer_run_id_set = set(excluded_answer_run_ids)
    excluded_google_answer_run_ids = [
        record.answer_run.id
        for record in records
        if record.answer_run.platform == "google" and record.answer_run.id in excluded_answer_run_id_set
    ]
    google_allowed = _google_main_scoring_allowed(
        google_spike_gate=google_spike_gate,
        google_spike_readiness_gate=google_spike_readiness_gate,
    )
    return {
        "policy_version": "score_input_scope_v1",
        "google_main_scoring_allowed": google_allowed,
        "google_gate_status": str((gate or {}).get("gate_status") or "not_run"),
        "google_limited_coverage": bool((gate or {}).get("limited_coverage", True)),
        "google_readiness_gate_status": str((readiness_gate or {}).get("gate_status") or "not_run"),
        "google_collection_paths_ready": str((readiness_gate or {}).get("gate_status") or "") == "pass",
        "all_record_count": len(records),
        "score_input_record_count": len(score_input_records),
        "excluded_record_count": len(excluded_answer_run_ids),
        "excluded_google_record_count": len(excluded_google_answer_run_ids),
        "all_answer_run_ids": all_answer_run_ids,
        "score_input_answer_run_ids": score_input_answer_run_ids,
        "excluded_answer_run_ids": excluded_answer_run_ids,
        "excluded_google_answer_run_ids": excluded_google_answer_run_ids,
        "reason": (
            "Google answer runs excluded from the main scoring denominator until both Google spike gates pass"
            if excluded_google_answer_run_ids
            else "All parsed answer runs are eligible for the main scoring denominator"
        ),
    }


def analyze_and_score_records(
    *,
    project_id: str,
    records: tuple[RawEvidenceRecord, ...],
    brand: BrandEntity,
    competitors: tuple[CompetitorEntity, ...],
    platform_weights_snapshot: dict[str, float],
    score_weights: dict[str, float] | None = None,
    formula_version: str = "au_visibility_v1",
    entity_aliases: dict[str, tuple[str, ...]] | None = None,
    scope_type: str = "project",
    scope_value: str = "p0a_fixture",
    google_spike_gate: Mapping[str, object] | object | None = None,
    google_spike_readiness_gate: Mapping[str, object] | object | None = None,
) -> VisibilityAnalysisResult:
    parser = ComparativeAnswerParser()
    record_analysis_pairs = tuple(
        (
            record,
            parser.parse_record(
                record=record,
                brand=brand,
                competitors=competitors,
                entity_aliases=entity_aliases,
            ),
        )
        for record in records
    )
    analyses = tuple(analysis for _, analysis in record_analysis_pairs)
    google_allowed = _google_main_scoring_allowed(
        google_spike_gate=google_spike_gate,
        google_spike_readiness_gate=google_spike_readiness_gate,
    )
    score_input_pairs = tuple(
        (record, analysis)
        for record, analysis in record_analysis_pairs
        if record.answer_run.platform != "google" or google_allowed
    )
    if not score_input_pairs:
        raise ValueError("At least one non-limited-coverage AnswerAnalysis is required for main scoring")
    score_input_records = tuple(record for record, _ in score_input_pairs)
    score_input_analyses = tuple(analysis for _, analysis in score_input_pairs)
    score_input_policy = build_score_input_policy(
        records=records,
        score_input_records=score_input_records,
        google_spike_gate=google_spike_gate,
        google_spike_readiness_gate=google_spike_readiness_gate,
    )
    score_result = score_answer_analyses(
        project_id=project_id,
        analyses=score_input_analyses,
        platform_weights_snapshot=platform_weights_snapshot,
        score_weights=score_weights,
        formula_version=formula_version,
        scope_type=scope_type,
        scope_value=scope_value,
        score_input_policy=score_input_policy,
    )
    return VisibilityAnalysisResult(
        analyses=analyses,
        score_input_analyses=score_input_analyses,
        score_input_records=score_input_records,
        score_input_policy=score_input_policy,
        snapshot=score_result.snapshot,
        contributions=tuple(score_result.contributions),
        audit_event=score_result.audit_event,
    )
