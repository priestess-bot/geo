"""Evidence subject and scope validation for Prompt bootstrap inputs."""

from __future__ import annotations

from collections.abc import Mapping

from geo_core.prompts.bootstrap_validation_errors import (
    PromptOutputRuleViolation,
)


def input_evidence(
    input_value: Mapping[str, object],
) -> list[Mapping[str, object]]:
    evidence = _mapping_items(input_value.get("evidence"))
    refs = [_string(item.get("ref"), code="input_evidence_invalid") for item in evidence]
    if not refs or len(refs) != len(set(refs)):
        raise PromptOutputRuleViolation(
            "input_evidence_invalid",
            "input evidence references must be non-empty and unique",
        )
    primary_subject = _string(
        input_value.get("subject_id"), code="input_subject_invalid"
    )
    allowed_subjects = allowed_subject_ids(input_value)
    for item in evidence:
        evidence_subject = _string(
            item.get("subject_id"), code="input_evidence_invalid"
        )
        scope = item.get("evidence_scope")
        if evidence_subject not in allowed_subjects:
            raise PromptOutputRuleViolation(
                "input_evidence_invalid",
                "input evidence subject is outside the frozen allowlist",
            )
        if scope == "primary_subject" and evidence_subject != primary_subject:
            raise PromptOutputRuleViolation(
                "input_evidence_invalid",
                "primary-subject evidence must match the frozen primary subject",
            )
        if scope == "competitor_subject" and evidence_subject == primary_subject:
            raise PromptOutputRuleViolation(
                "input_evidence_invalid",
                "competitor evidence must name a different allowed subject",
            )
    return evidence


def allowed_subject_ids(input_value: Mapping[str, object]) -> set[str]:
    subject_id = _string(input_value.get("subject_id"), code="input_subject_invalid")
    allowed_items = _string_items(input_value.get("allowed_subject_ids"))
    allowed = set(allowed_items)
    if len(allowed) != len(allowed_items) or subject_id not in allowed:
        raise PromptOutputRuleViolation(
            "input_subject_invalid",
            "subject allowlist must be unique and contain the primary subject",
        )
    return allowed


def evidence_allows_output_subject(
    item: Mapping[str, object],
    *,
    output_subject: str,
    primary_subject: str,
) -> bool:
    evidence_subject = item.get("subject_id")
    scope = item.get("evidence_scope")
    if evidence_subject == output_subject:
        return True
    if scope == "cross_subject_observation":
        return True
    return scope == "competitor_subject" and output_subject == primary_subject


def _mapping_items(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise PromptOutputRuleViolation(
            "input_evidence_invalid", "input evidence must be an array of objects"
        )
    return [item for item in value if isinstance(item, Mapping)]


def _string_items(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PromptOutputRuleViolation(
            "input_subject_invalid", "subject allowlist must be an array of strings"
        )
    return [item for item in value if isinstance(item, str)]


def _string(value: object, *, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PromptOutputRuleViolation(code, "expected a non-empty string")
    return value


__all__ = [
    "allowed_subject_ids",
    "evidence_allows_output_subject",
    "input_evidence",
]
