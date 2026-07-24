"""Pure parsing and frozen-lineage helpers for Synthetic Lab review execution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast
from uuid import UUID

from geo_core.prompts.program_contracts import ProgramKind
from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.evaluation import ClaimAssessment, FactStatus
from geo_core.synthetic_lab.execution_contracts import (
    ReviewCaseRunTask,
    SyntheticExecutionError,
    SyntheticModelResult,
)
from geo_core.synthetic_lab.generation import FrozenCallLineage


def common_review_input(task: ReviewCaseRunTask) -> dict[str, object]:
    untrusted_text = task.case.creative_reference or ""
    primary_subject = str(task.subject_id)
    subject_ids = list(
        dict.fromkeys((primary_subject, *(item.subject_id for item in task.evidence)))
    )
    return {
        "subject_id": primary_subject,
        "allowed_subject_ids": subject_ids,
        "evidence": [
            {
                **item.prompt_value(),
                "evidence_scope": (
                    "primary_subject"
                    if item.subject_id == primary_subject
                    else "competitor_subject"
                ),
            }
            for item in task.evidence
        ],
        "output_locale": "en-AU",
        "untrusted_text": untrusted_text,
        "prompt_injection_present": bool(untrusted_text),
    }


def frozen_call_lineage(
    task: ReviewCaseRunTask,
    result: SyntheticModelResult,
    kind: ProgramKind,
) -> FrozenCallLineage:
    prompt = task.prompts[kind]
    return FrozenCallLineage(
        project_id=task.project_id,
        review_run_id=task.review_run_id,
        review_suite_version_id=task.case.review_suite_version_id,
        review_suite_hash=task.review_suite_hash,
        review_case_id=task.case.id,
        review_case_hash=task.case.content_hash,
        program_kind=kind.value,
        prompt_release_id=prompt.release_id,
        prompt_release_hash=prompt.release_hash,
        profile_version_id=task.runtime_inputs.profile_version_id,
        profile_hash=task.runtime_inputs.profile_hash,
        fact_snapshot_id=task.runtime_inputs.fact_snapshot_id,
        fact_snapshot_hash=task.runtime_inputs.fact_snapshot_hash,
        model_policy_hash=prompt.model_policy_hash,
        model_call_id=result.model_call_id,
        provider=result.provider,
        configured_model=result.configured_model,
        reported_model=result.reported_model,
        model_identity_hash=result.model_identity_hash,
        request_hash=result.request_hash,
        response_hash=result.response_hash,
    )


def claim_assessments(
    task: ReviewCaseRunTask,
    claims: tuple[Mapping[str, object], ...],
    conflict_output: Mapping[str, object],
) -> tuple[ClaimAssessment, ...]:
    claim_ids = [required_string(item.get("claim_id"), "claim ID") for item in claims]
    if len(claim_ids) != len(set(claim_ids)):
        raise SyntheticExecutionError("extracted claim identities are duplicated")
    by_claim = dict(zip(claim_ids, claims, strict=True))
    facts = {item.ref: item for item in task.evidence if item.fact_id is not None}
    try:
        subject_inventory = {UUID(item.subject_id) for item in task.evidence}
    except ValueError as error:
        raise SyntheticExecutionError("frozen evidence subject identity is invalid") from error
    if task.subject_id not in subject_inventory:
        raise SyntheticExecutionError("frozen subject is absent from evidence inventory")
    for claim in claims:
        claim_subject = optional_uuid(claim.get("subject_id"))
        if claim_subject not in subject_inventory:
            raise SyntheticExecutionError("extracted claim invented a subject identity")
    assessment_items = mapping_items(conflict_output.get("assessments"), "claim assessments")
    assessment_ids = [
        required_string(item.get("claim_id"), "assessment claim ID")
        for item in assessment_items
    ]
    if len(assessment_ids) != len(set(assessment_ids)):
        raise SyntheticExecutionError("conflict assessment identities are duplicated")
    if set(assessment_ids) != set(claim_ids):
        raise SyntheticExecutionError("conflict assessments do not cover extracted claims exactly")
    assessments = []
    for item in assessment_items:
        claim_id = required_string(item.get("claim_id"), "assessment claim ID")
        matching_claim = by_claim.get(claim_id)
        if matching_claim is None:
            raise SyntheticExecutionError("conflict assessment references an unknown claim")
        claim = matching_claim
        status = FactStatus(required_string(item.get("status"), "Fact status"))
        fact_ref = str(item.get("fact_ref") or "")
        fact = facts.get(fact_ref)
        if status in {FactStatus.CURRENT_APPROVED, FactStatus.EXPLICIT_CONFLICT} and fact is None:
            raise SyntheticExecutionError("Fact-bound assessment references unknown frozen evidence")
        expected_subject = optional_uuid(item.get("expected_subject_id"))
        observed_subject = optional_uuid(item.get("observed_subject_id"))
        if status is FactStatus.SUBJECT_MIXUP and (
            expected_subject != task.subject_id or observed_subject not in subject_inventory
        ):
            raise SyntheticExecutionError("subject mixup is outside the frozen subject inventory")
        assessments.append(
            ClaimAssessment(
                claim_hash=canonical_hash(required_string(claim.get("text"), "claim text")),
                status=status,
                fact_id=fact.fact_id if fact else None,
                fact_hash=fact.fact_hash if fact else None,
                expected_subject_id=expected_subject,
                observed_subject_id=observed_subject,
                output_annotation=(
                    FactStatus.DERIVED_OR_UNKNOWN.value
                    if status is FactStatus.DERIVED_OR_UNKNOWN
                    else None
                ),
            )
        )
    return tuple(assessments)


def conflict_issue_codes(output: Mapping[str, object]) -> tuple[str, ...]:
    statuses = {
        str(item.get("status"))
        for item in mapping_items(output.get("assessments"), "claim assessments")
    }
    return tuple(sorted(statuses.intersection({"explicit_conflict", "subject_mixup"})))


def evidence_refs(output: Mapping[str, object]) -> list[str]:
    values = string_tuple(output.get("evidence_refs"), "evidence refs")
    if not values:
        raise SyntheticExecutionError("evaluator output has no evidence references")
    return list(values)


def mapping_items(value: object, label: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, (tuple, list)) or any(not isinstance(item, Mapping) for item in value):
        raise SyntheticExecutionError(f"{label} must be an array of objects")
    return tuple(cast(Mapping[str, object], item) for item in value)


def string_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise SyntheticExecutionError(f"{label} must be an array of strings")
    return tuple(cast(str, item).strip() for item in value)


def required_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SyntheticExecutionError(f"{label} is required")
    return value.strip()


def optional_uuid(value: object) -> UUID | None:
    if value in {None, ""}:
        return None
    try:
        return UUID(str(value))
    except ValueError as error:
        raise SyntheticExecutionError("assessment subject identity is invalid") from error


__all__ = [
    "claim_assessments",
    "common_review_input",
    "conflict_issue_codes",
    "evidence_refs",
    "frozen_call_lineage",
    "mapping_items",
    "optional_uuid",
    "required_string",
    "string_tuple",
]
