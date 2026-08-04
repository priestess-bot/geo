"""Allowlist-only presenters for direct Synthetic Lab generation."""

from __future__ import annotations

from typing import cast

from geo_api.synthetic_lab_contracts import Channel
from geo_api.synthetic_lab_direct_contracts import (
    ChannelStylePageResponse,
    ChannelStyleResponse,
    DirectGenerationOptionsResponse,
    DirectGenerationSubjectResponse,
    DirectKnowledgeItemResponse,
    SyntheticCandidateEvaluationResponse,
    SyntheticCandidateRevisionResponse,
    SyntheticClaimAssessmentResponse,
    SyntheticGenerationBatchResponse,
    SyntheticReviewResultResponse,
)
from geo_api.synthetic_lab_presenters import _enum_value, _field, _page, _unwrap


def channel_style_response(item: object) -> ChannelStyleResponse:
    value, replayed = _unwrap(item)
    return ChannelStyleResponse(
        id=_field(value, "id"),
        project_id=_field(value, "project_id"),
        style_id=_field(value, "style_id"),
        version_number=_field(value, "version_number"),
        previous_version_id=_field(value, "previous_version_id", None),
        channel=cast(Channel, _field(value, "channel")),
        locale=_field(value, "locale"),
        directive=_field(value, "directive"),
        provenance=_enum_value(_field(value, "provenance")),
        calibration_status=_enum_value(_field(value, "calibration_status")),
        style_hash=_field(value, "style_hash"),
        replayed=replayed,
    )


def direct_generation_options_response(
    item: object, *, project_id: object
) -> DirectGenerationOptionsResponse:
    return DirectGenerationOptionsResponse(
        subjects=[
            DirectGenerationSubjectResponse(
                id=_field(subject, "id"),
                name=_field(subject, "name"),
                canonical_url=_field(subject, "canonical_url", None),
                knowledge_snapshot_hash=_field(subject, "knowledge_snapshot_hash", None),
                knowledge_items=[
                    _knowledge_item_response(
                        knowledge,
                        project_id=project_id,
                        matched=False,
                        conflicting=False,
                    )
                    for knowledge in _field(subject, "knowledge_items")
                ],
                competitor_knowledge_snapshot_hash=_field(
                    subject, "competitor_knowledge_snapshot_hash", None
                ),
                competitor_knowledge_items=[
                    _knowledge_item_response(
                        knowledge,
                        project_id=project_id,
                        matched=False,
                        conflicting=False,
                    )
                    for knowledge in _field(subject, "competitor_knowledge_items", ())
                ],
            )
            for subject in _field(item, "subjects")
        ],
        channel_styles=[channel_style_response(style) for style in _field(item, "channel_styles")],
        has_competitor_knowledge=bool(_field(item, "has_competitor_knowledge")),
    )


def review_result_response(item: object) -> SyntheticReviewResultResponse:
    task = _field(item, "task")
    result = _field(item, "result")
    case = _field(task, "case")
    resolution = _field(result, "resolution")
    prompts = _field(task, "prompts")
    generation_prompt = next(
        (prompt for kind, prompt in prompts.items() if _enum_value(kind) == "generation"),
        None,
    )
    if generation_prompt is None:
        raise ValueError("Synthetic Review result is missing its generation runtime")
    knowledge_snapshot = _field(task, "knowledge_snapshot", None)
    channel_style = _field(task, "channel_style", None)
    direct = knowledge_snapshot is not None and channel_style is not None

    def lineage_fields(lineage: object) -> dict[str, str]:
        return {
            "provider": _field(lineage, "provider"),
            "configured_model": _field(lineage, "configured_model"),
        }

    evaluations = [
        SyntheticCandidateEvaluationResponse(
            id=_field(evaluation, "id"),
            candidate_id=_field(evaluation, "candidate_id"),
            candidate_output_hash=_field(evaluation, "candidate_output_hash"),
            style_score=_field(evaluation, "style_score"),
            style_passed=_field(evaluation, "style_passed"),
            disposition=_enum_value(_field(evaluation, "disposition")),
            correctable_issue_codes=list(_field(evaluation, "correctable_issue_codes")),
            soft_issue_codes=list(_field(evaluation, "soft_issue_codes")),
            warning_codes=list(_field(evaluation, "warning_codes")),
            claim_assessments=[
                SyntheticClaimAssessmentResponse(
                    claim_hash=_field(assessment, "claim_hash"),
                    status=_enum_value(_field(assessment, "status")),
                    fact_id=_field(assessment, "fact_id", None),
                    fact_hash=_field(assessment, "fact_hash", None),
                    expected_subject_id=_field(assessment, "expected_subject_id", None),
                    observed_subject_id=_field(assessment, "observed_subject_id", None),
                    output_annotation=_field(assessment, "output_annotation", None),
                    evidence_refs=list(_field(assessment, "evidence_refs", ())),
                )
                for assessment in _field(evaluation, "claim_assessments")
            ],
            **lineage_fields(_field(evaluation, "call_lineage")),
            evidence_artifact_hash=_field(evaluation, "evidence_artifact_hash"),
        )
        for evaluation in _field(result, "evaluations")
    ]
    revisions = [
        SyntheticCandidateRevisionResponse(
            id=_field(revision, "id"),
            round_number=_field(revision, "round_number"),
            parent_candidate_id=_field(revision, "parent_candidate_id"),
            parent_output_hash=_field(revision, "parent_output_hash"),
            revised_candidate_id=_field(_field(revision, "revised_candidate"), "id"),
            revised_output_hash=_field(_field(revision, "revised_candidate"), "output_hash"),
            issue_codes=list(_field(revision, "issue_codes")),
            **lineage_fields(_field(revision, "call_lineage")),
        )
        for revision in _field(result, "revisions")
    ]
    batches = [
        SyntheticGenerationBatchResponse(
            id=_field(batch, "id"),
            batch_number=_field(batch, "batch_number"),
            kind=_enum_value(_field(batch, "kind")),
            scenario_mode=_enum_value(_field(batch, "scenario_mode")),
            candidate_count=len(_field(batch, "candidates")),
            **lineage_fields(_field(batch, "call_lineage")),
        )
        for batch in _field(result, "batches")
    ]
    matched_refs = {
        evidence_ref
        for evaluation in _field(result, "evaluations")
        for assessment in _field(evaluation, "claim_assessments")
        for evidence_ref in _field(assessment, "evidence_refs", ())
    }
    conflict_refs = {
        evidence_ref
        for evaluation in _field(result, "evaluations")
        for assessment in _field(evaluation, "claim_assessments")
        if _enum_value(_field(assessment, "status")) in {"explicit_conflict", "subject_mixup"}
        for evidence_ref in _field(assessment, "evidence_refs", ())
    }
    knowledge_items = (
        [
            _knowledge_item_response(
                knowledge,
                project_id=_field(result, "project_id"),
                matched=_field(knowledge, "ref") in matched_refs,
                conflicting=_field(knowledge, "ref") in conflict_refs,
            )
            for knowledge in _field(knowledge_snapshot, "items")
        ]
        if direct
        else []
    )
    runtime_inputs = _field(task, "runtime_inputs", None)
    profile_version_id = (
        _field(runtime_inputs, "profile_version_id")
        if runtime_inputs is not None
        else _field(case, "profile_version_id")
    )
    fact_snapshot_id = (
        _field(runtime_inputs, "fact_snapshot_id")
        if runtime_inputs is not None
        else _field(case, "fact_snapshot_id")
    )
    return SyntheticReviewResultResponse(
        job_id=_field(item, "job_id"),
        project_id=_field(result, "project_id"),
        review_run_id=_field(result, "review_run_id"),
        run_origin="direct" if direct else "regression",
        input_snapshot_id=_field(knowledge_snapshot, "id", None) if direct else None,
        review_suite_version_id=(None if direct else _field(case, "review_suite_version_id")),
        review_case_id=None if direct else _field(result, "review_case_id"),
        scenario_id=_field(result, "review_case_id"),
        case_key=_field(case, "case_key"),
        channel=cast(Channel, _field(case, "channel")),
        scenario_mode=_enum_value(_field(case, "mode")),
        competitor_scenario=_field(case, "competitor_scenario"),
        style_pass_threshold=_field(task, "style_pass_threshold"),
        runtime_selection_id=_field(generation_prompt, "runtime_option_id"),
        profile_version_id=profile_version_id,
        fact_snapshot_id=fact_snapshot_id,
        generation_goal=_field(case, "generation_goal", None),
        channel_style_version_id=_field(channel_style, "id", None) if direct else None,
        channel_style_version_number=(
            _field(channel_style, "version_number", None) if direct else None
        ),
        channel_style_hash=_field(channel_style, "style_hash", None) if direct else None,
        knowledge_snapshot_hash=(
            _field(knowledge_snapshot, "snapshot_hash", None) if direct else None
        ),
        knowledge_context_items=knowledge_items,
        final_text=_field(result, "resolved_candidate_text", None),
        status=_enum_value(_field(resolution, "status")),
        warning_codes=list(_field(resolution, "warning_codes")),
        failure_code=_field(resolution, "failure_code", None),
        resolution_candidate_id=_field(resolution, "candidate_id"),
        result_hash=_field(result, "result_hash"),
        batches=batches,
        evaluations=evaluations,
        revisions=revisions,
        model_call_ids=list(_field(result, "model_call_ids")),
        workflow_attempt_ids=list(_field(result, "workflow_attempt_ids")),
    )


def channel_style_page(page: object) -> ChannelStylePageResponse:
    return _page(page, channel_style_response, ChannelStylePageResponse)


def _knowledge_item_response(
    item: object,
    *,
    project_id: object,
    matched: bool,
    conflicting: bool,
) -> DirectKnowledgeItemResponse:
    kind = _field(item, "kind")
    evidence_id = _field(item, "evidence_id")
    source_url = _field(item, "source_url", None)
    trace_href = (
        f"/projects/{project_id}?tab=knowledge&knowledge_tab=trace&knowledge_fact_id={evidence_id}"
        if kind == "approved_fact"
        else source_url or f"/projects/{project_id}?tab=knowledge&knowledge_tab=sources"
    )
    return DirectKnowledgeItemResponse(
        evidence_id=evidence_id,
        kind=kind,
        subject_entity_id=_field(item, "subject_entity_id"),
        subject_name=_field(item, "subject_name"),
        summary=_field(item, "summary"),
        snapshot_hash=_field(item, "snapshot_hash"),
        source_title=_field(item, "source_title", None),
        source_url=source_url,
        trace_href=trace_href,
        matched=matched,
        conflicting=conflicting,
    )


__all__ = [
    "channel_style_page",
    "channel_style_response",
    "direct_generation_options_response",
    "review_result_response",
]
