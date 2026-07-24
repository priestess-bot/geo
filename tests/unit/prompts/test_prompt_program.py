from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from types import MappingProxyType
from uuid import uuid4

import pytest

from geo_core.prompts.program import (
    AUXILIARY_PROGRAM_KINDS,
    CORE_FIRST_PHASE_PROGRAM_KINDS,
    FIRST_PHASE_PROGRAM_KINDS,
    ModelPolicySnapshot,
    ProgramKind,
    ProgramReleaseCommand,
    ProgramReleaseStatus,
    ProgramSchemaContract,
    PromptProgram,
    PromptProgramRelease,
    PromptProgramRuleViolation,
    assert_binding_scope,
    bind_frozen_release,
    compare_candidate_to_approved,
    create_initial_release_state,
    render_program_release,
    transition_release_state,
)


NOW = datetime(2026, 7, 23, tzinfo=UTC)


def test_first_phase_kinds_are_explicit_and_reference_translation_is_reserved() -> None:
    assert CORE_FIRST_PHASE_PROGRAM_KINDS == (
        ProgramKind.GENERATION,
        ProgramKind.CLAIM_EXTRACTION,
        ProgramKind.CONFLICT_CHECK,
        ProgramKind.REVISION,
        ProgramKind.STYLE_JUDGE,
        ProgramKind.ARBITER,
        ProgramKind.METRIC_JUDGE,
        ProgramKind.RECOMMENDATION,
    )
    assert AUXILIARY_PROGRAM_KINDS == (
        ProgramKind.STYLE_PROFILE,
        ProgramKind.OFFLINE_ANSWER,
    )
    assert FIRST_PHASE_PROGRAM_KINDS == (
        *CORE_FIRST_PHASE_PROGRAM_KINDS,
        *AUXILIARY_PROGRAM_KINDS,
    )
    assert ProgramKind.REFERENCE_TRANSLATION.value == "reference_translation"
    assert ProgramKind.REFERENCE_TRANSLATION not in FIRST_PHASE_PROGRAM_KINDS

    with pytest.raises(PromptProgramRuleViolation, match="reserved"):
        _program(kind=ProgramKind.REFERENCE_TRANSLATION)


@pytest.mark.parametrize("kind", FIRST_PHASE_PROGRAM_KINDS)
def test_each_first_phase_kind_compiles_through_the_shared_release_contract(
    kind: ProgramKind,
) -> None:
    program = _program(kind=kind)

    release = _release(program=program)

    assert release.program_kind == kind
    assert len(release.release_hash) == 64


def test_release_freezes_structured_contracts_and_reproducible_hashes() -> None:
    program = _program()
    schemas = _schemas()
    policy = _model_policy()
    test_set_id = uuid4()
    first = _release(
        program=program,
        schemas=schemas,
        policy=policy,
        test_set_id=test_set_id,
        version=1,
    )
    second = _release(
        program=program,
        schemas=schemas,
        policy=policy,
        test_set_id=test_set_id,
        version=2,
    )

    assert first.release_hash == second.release_hash
    assert first.system_template_hash != first.user_template_hash
    assert first.schemas.output_schema_version == "candidate-v1"
    assert first.model_policy.policy_hash == policy.policy_hash
    assert isinstance(first.schemas.variable_schema, MappingProxyType)
    assert isinstance(first.schemas.variable_schema["properties"], MappingProxyType)
    with pytest.raises(TypeError):
        first.schemas.variable_schema["type"] = "array"  # type: ignore[index]
    with pytest.raises(TypeError):
        first.model_policy.policy["fallback"] = True  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        first.user_template = "changed"  # type: ignore[misc]


def test_release_rejects_unstructured_or_undeclared_template_inputs() -> None:
    with pytest.raises(PromptProgramRuleViolation, match="JSON Schema object"):
        ProgramSchemaContract(
            variable_schema_version="vars-v1",
            variable_schema={"type": "array"},
            input_schema_version="input-v1",
            input_schema={"type": "object"},
            output_schema_version="output-v1",
            output_schema={"type": "object"},
        )

    with pytest.raises(PromptProgramRuleViolation, match="structured-output schema profile"):
        ProgramSchemaContract(
            variable_schema_version="vars-v1",
            variable_schema={
                "type": "object",
                "properties": {"scenario": {"type": "string"}},
                "required": ["scenario"],
            },
            input_schema_version="input-v1",
            input_schema={"type": "object"},
            output_schema_version="output-v1",
            output_schema={
                "type": "object",
                "properties": {"answer": {"type": "string", "contentEncoding": "base64"}},
            },
        )

    with pytest.raises(PromptProgramRuleViolation, match="not declared"):
        _release(user_template="Write {{scenario}} for {{undeclared}}")


def test_release_lifecycle_is_linear_and_requires_transition_evidence() -> None:
    release = _release()
    actor_id = uuid4()
    draft = create_initial_release_state(
        id=uuid4(), release=release, actor_id=actor_id, acted_at=NOW
    )

    with pytest.raises(PromptProgramRuleViolation, match="not allowed"):
        transition_release_state(
            id=uuid4(),
            release=release,
            current=draft,
            command=ProgramReleaseCommand.APPROVE,
            actor_id=actor_id,
            acted_at=NOW,
            evidence_ref="review:1",
        )
    with pytest.raises(PromptProgramRuleViolation, match="require evidence"):
        transition_release_state(
            id=uuid4(),
            release=release,
            current=draft,
            command=ProgramReleaseCommand.RECORD_TEST,
            actor_id=actor_id,
            acted_at=NOW,
            evidence_ref=" ",
        )

    tested = _transition(
        release,
        draft,
        ProgramReleaseCommand.RECORD_TEST,
        "test-run:fixed-suite-17",
    )
    approved = _transition(
        release,
        tested,
        ProgramReleaseCommand.APPROVE,
        "approval:operator-23",
    )
    frozen = _transition(
        release,
        approved,
        ProgramReleaseCommand.FREEZE,
        "freeze:change-42",
    )

    assert [draft.status, tested.status, approved.status, frozen.status] == [
        ProgramReleaseStatus.DRAFT,
        ProgramReleaseStatus.TESTED,
        ProgramReleaseStatus.APPROVED,
        ProgramReleaseStatus.FROZEN,
    ]
    assert frozen.version == 4
    assert frozen.previous_state_id == approved.id
    assert frozen.release_hash == release.release_hash
    with pytest.raises(PromptProgramRuleViolation, match="not allowed"):
        _transition(
            release,
            frozen,
            ProgramReleaseCommand.RECORD_TEST,
            "test-run:late",
        )


def test_fixed_input_diff_requires_an_approved_baseline_from_the_same_program() -> None:
    program = _program()
    test_set_id = uuid4()
    baseline = _release(program=program, test_set_id=test_set_id, version=1)
    candidate = _release(
        program=program,
        test_set_id=test_set_id,
        version=2,
        user_template="Draft a concise {{scenario}} for {{channel}}.",
    )
    baseline_state = _approved_state(baseline)
    candidate_state = create_initial_release_state(
        id=uuid4(), release=candidate, actor_id=uuid4(), acted_at=NOW
    )
    values = {"scenario": "robot vacuum review", "channel": "youtube"}

    result = compare_candidate_to_approved(
        approved_release=baseline,
        approved_state=baseline_state,
        candidate_release=candidate,
        candidate_state=candidate_state,
        fixed_variables=values,
    )

    assert result.changed_fields == ("user_template",)
    assert result.fixed_input_hash == render_program_release(
        release=baseline, variables=values
    ).variable_input_hash
    assert result.base_user_hash != result.candidate_user_hash
    assert result.base_system_hash == result.candidate_system_hash

    other_program_candidate = _release(program=_program(), version=2)
    with pytest.raises(PromptProgramRuleViolation, match="same project"):
        compare_candidate_to_approved(
            approved_release=baseline,
            approved_state=baseline_state,
            candidate_release=other_program_candidate,
            candidate_state=create_initial_release_state(
                id=uuid4(),
                release=other_program_candidate,
                actor_id=uuid4(),
                acted_at=NOW,
            ),
            fixed_variables=values,
        )


def test_binding_requires_exact_frozen_project_and_purpose_scope() -> None:
    release = _release()
    approved = _approved_state(release)
    with pytest.raises(PromptProgramRuleViolation, match="only a frozen"):
        bind_frozen_release(
            **_binding_arguments(release=release, state=approved),
        )

    frozen = _transition(
        release,
        approved,
        ProgramReleaseCommand.FREEZE,
        "freeze:change-42",
    )
    with pytest.raises(PromptProgramRuleViolation, match="across projects"):
        bind_frozen_release(
            **_binding_arguments(release=release, state=frozen, project_id=uuid4()),
        )
    with pytest.raises(PromptProgramRuleViolation, match="another purpose"):
        bind_frozen_release(
            **_binding_arguments(
                release=release,
                state=frozen,
                purpose="synthetic_lab.style_judge",
            ),
        )

    binding = bind_frozen_release(**_binding_arguments(release=release, state=frozen))

    assert binding.release_id == release.id
    assert binding.release_hash == release.release_hash
    assert binding.frozen_state_id == frozen.id
    assert_binding_scope(
        binding=binding,
        project_id=release.project_id,
        purpose=release.purpose,
        kind=ProgramKind.GENERATION,
    )
    with pytest.raises(PromptProgramRuleViolation, match="another purpose"):
        assert_binding_scope(
            binding=binding,
            project_id=release.project_id,
            purpose="synthetic_lab.revision",
            kind=ProgramKind.GENERATION,
        )


def _program(*, kind: ProgramKind = ProgramKind.GENERATION) -> PromptProgram:
    return PromptProgram(
        id=uuid4(),
        project_id=uuid4(),
        program_kind=kind,
        purpose="synthetic_lab.generation",
        owner_id=uuid4(),
    )


def _schemas() -> ProgramSchemaContract:
    variable_schema = {
        "type": "object",
        "properties": {
            "scenario": {"type": "string"},
            "channel": {"type": "string"},
        },
        "required": ["scenario", "channel"],
        "additionalProperties": False,
    }
    return ProgramSchemaContract(
        variable_schema_version="prompt-vars-v1",
        variable_schema=variable_schema,
        input_schema_version="generation-input-v1",
        input_schema=variable_schema,
        output_schema_version="candidate-v1",
        output_schema={
            "type": "object",
            "properties": {"candidate": {"type": "string"}},
            "required": ["candidate"],
            "additionalProperties": False,
        },
    )


def _model_policy() -> ModelPolicySnapshot:
    return ModelPolicySnapshot(
        version="synthetic-generation-v1",
        policy={
            "allowed_providers": ["openai", "deepseek"],
            "configured_model": "approved-generation-model",
            "fallback": False,
        },
    )


def _release(
    *,
    program: PromptProgram | None = None,
    schemas: ProgramSchemaContract | None = None,
    policy: ModelPolicySnapshot | None = None,
    test_set_id=None,
    version: int = 1,
    user_template: str = "Write {{scenario}} for {{channel}}.",
) -> PromptProgramRelease:
    return PromptProgramRelease.compile(
        id=uuid4(),
        program=program or _program(),
        version=version,
        system_template="Return structured Australian English for {{channel}}.",
        user_template=user_template,
        schemas=schemas or _schemas(),
        model_policy=policy or _model_policy(),
        test_set_id=test_set_id or uuid4(),
        test_set_version=1,
        test_set_hash="ab" * 32,
        compiler_version="geo-prompt-compiler-v2",
    )


def _transition(release, current, command, evidence_ref):
    return transition_release_state(
        id=uuid4(),
        release=release,
        current=current,
        command=command,
        actor_id=uuid4(),
        acted_at=NOW,
        evidence_ref=evidence_ref,
    )


def _approved_state(release):
    draft = create_initial_release_state(
        id=uuid4(), release=release, actor_id=uuid4(), acted_at=NOW
    )
    tested = _transition(
        release,
        draft,
        ProgramReleaseCommand.RECORD_TEST,
        "test-run:fixed-suite-17",
    )
    return _transition(
        release,
        tested,
        ProgramReleaseCommand.APPROVE,
        "approval:operator-23",
    )


def _binding_arguments(*, release, state, project_id=None, purpose=None):
    return {
        "id": uuid4(),
        "project_id": project_id or release.project_id,
        "purpose": purpose or release.purpose,
        "release": release,
        "state": state,
        "binding_version": 1,
        "previous_binding_id": None,
        "actor_id": uuid4(),
        "bound_at": NOW,
    }
