"""Deterministic Prompt Program rendering and fixed-input Release diffs."""

from __future__ import annotations

from collections.abc import Mapping
import json

from geo_core.prompts.program_contracts import (
    ProgramReleaseStatus,
    PromptProgramRuleViolation,
    _VARIABLE,
    _canonical_hash,
    _canonical_value,
    _freeze_json_object,
    _schema_string_sequence,
    _text_hash,
)
from geo_core.prompts.program_models import (
    CompiledProgramPrompt,
    ProgramReleaseDiff,
    ProgramReleaseState,
    PromptProgramRelease,
    _assert_state_matches_release,
)


def render_program_release(
    *, release: PromptProgramRelease, variables: Mapping[str, object]
) -> CompiledProgramPrompt:
    frozen_variables = _freeze_json_object(variables, field_name="Prompt Program variables")
    required = set(_schema_string_sequence(release.schemas.variable_schema, "required"))
    missing = sorted(required - set(frozen_variables))
    if missing:
        raise PromptProgramRuleViolation(f"missing Prompt Program variables: {', '.join(missing)}")
    properties = release.schemas.variable_schema.get("properties", {})
    if not isinstance(properties, Mapping):
        raise PromptProgramRuleViolation("variable_schema.properties must be an object")
    if release.schemas.variable_schema.get("additionalProperties") is False:
        unknown = sorted(set(frozen_variables) - set(properties))
        if unknown:
            raise PromptProgramRuleViolation(
                f"unknown Prompt Program variables: {', '.join(unknown)}"
            )

    compiled_system = _render_template(release.system_template, frozen_variables)
    compiled_user = _render_template(release.user_template, frozen_variables)
    return CompiledProgramPrompt(
        release_id=release.id,
        release_hash=release.release_hash,
        variable_input_hash=_canonical_hash(_canonical_value(frozen_variables)),
        compiled_system=compiled_system,
        compiled_system_hash=_text_hash(compiled_system),
        compiled_user=compiled_user,
        compiled_user_hash=_text_hash(compiled_user),
        output_schema_version=release.schemas.output_schema_version,
        model_policy_version=release.model_policy.version,
        model_policy_hash=release.model_policy.policy_hash,
    )


def compare_candidate_to_approved(
    *,
    approved_release: PromptProgramRelease,
    approved_state: ProgramReleaseState,
    candidate_release: PromptProgramRelease,
    candidate_state: ProgramReleaseState,
    fixed_variables: Mapping[str, object],
) -> ProgramReleaseDiff:
    """Diff a candidate against the current approved/frozen Release on fixed input."""

    _assert_state_matches_release(state=approved_state, release=approved_release)
    _assert_state_matches_release(state=candidate_state, release=candidate_release)
    if approved_state.status not in {
        ProgramReleaseStatus.APPROVED,
        ProgramReleaseStatus.FROZEN,
    }:
        raise PromptProgramRuleViolation("the diff baseline must be approved or frozen")
    if candidate_state.status not in {
        ProgramReleaseStatus.DRAFT,
        ProgramReleaseStatus.TESTED,
    }:
        raise PromptProgramRuleViolation("the diff candidate must be draft or tested")
    _assert_same_program(approved_release, candidate_release)
    if candidate_release.version <= approved_release.version:
        raise PromptProgramRuleViolation("candidate Release version must follow the baseline")

    approved_prompt = render_program_release(
        release=approved_release, variables=fixed_variables
    )
    candidate_prompt = render_program_release(
        release=candidate_release, variables=fixed_variables
    )
    baseline = approved_release.diffable_value()
    candidate = candidate_release.diffable_value()
    changed_fields = tuple(
        sorted(key for key in baseline if baseline[key] != candidate[key])
    )
    return ProgramReleaseDiff(
        base_release_id=approved_release.id,
        base_release_hash=approved_release.release_hash,
        candidate_release_id=candidate_release.id,
        candidate_release_hash=candidate_release.release_hash,
        changed_fields=changed_fields,
        fixed_input_hash=approved_prompt.variable_input_hash,
        base_system_hash=approved_prompt.compiled_system_hash,
        candidate_system_hash=candidate_prompt.compiled_system_hash,
        base_user_hash=approved_prompt.compiled_user_hash,
        candidate_user_hash=candidate_prompt.compiled_user_hash,
    )


def _assert_same_program(
    baseline: PromptProgramRelease, candidate: PromptProgramRelease
) -> None:
    identities = (
        "project_id",
        "program_id",
        "program_kind",
        "purpose",
    )
    if any(getattr(baseline, name) != getattr(candidate, name) for name in identities):
        raise PromptProgramRuleViolation(
            "Prompt Program diffs require the same project, Program kind and purpose"
        )


def _render_template(template: str, variables: Mapping[str, object]) -> str:
    missing = sorted(set(_VARIABLE.findall(template)) - set(variables))
    if missing:
        raise PromptProgramRuleViolation(f"missing Prompt Program variables: {', '.join(missing)}")
    return _VARIABLE.sub(
        lambda match: _render_value(variables[match.group(1)]),
        template,
    )


def _render_value(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
