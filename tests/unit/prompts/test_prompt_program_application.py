from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.prompts.application import (
    PromptProgramApplication,
    PromptProgramForbidden,
    PromptProgramRuntimeBlocked,
)
from geo_core.prompts.memory import InMemoryPromptProgramRepository
from geo_core.prompts.ports import (
    PromptCommandOperation,
    PromptCommandRecord,
    PromptProgramIdempotencyConflict,
    PromptProgramVersionConflict,
)
from geo_core.prompts.program import (
    ModelPolicySnapshot,
    ProgramBinding,
    ProgramKind,
    ProgramReleaseStatus,
    ProgramSchemaContract,
)


NOW = datetime(2026, 7, 23, 9, 0, tzinfo=UTC)


def test_create_is_project_authorized_idempotent_and_optimistically_versioned() -> None:
    project_id, tenant_id = uuid4(), uuid4()
    creator = _principal(project_id, tenant_id, "analyst")
    viewer = _principal(project_id, tenant_id, "viewer")
    repository = InMemoryPromptProgramRepository()
    application = _application(repository)
    values = _create_values()

    first = application.create_program(
        creator,
        project_id=project_id,
        expected_version=0,
        idempotency_key="create:generation:v1",
        **values,
    )
    replay = application.create_program(
        creator,
        project_id=project_id,
        expected_version=0,
        idempotency_key="create:generation:v1",
        **values,
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.value is first.value
    assert first.value.program.owner_id == creator.identity_id
    assert first.value.state.status == ProgramReleaseStatus.DRAFT

    with pytest.raises(PromptProgramIdempotencyConflict, match="reused"):
        application.create_program(
            creator,
            project_id=project_id,
            expected_version=0,
            idempotency_key="create:generation:v1",
            **{**values, "user_template": "Changed {{scenario}} for {{channel}}."},
        )
    with pytest.raises(PromptProgramVersionConflict, match="expected_version=0"):
        application.create_program(
            creator,
            project_id=project_id,
            expected_version=1,
            idempotency_key="create:generation:wrong-version",
            **values,
        )
    with pytest.raises(PromptProgramForbidden, match="role"):
        application.create_program(
            viewer,
            project_id=project_id,
            expected_version=0,
            idempotency_key="create:generation:viewer",
            **values,
        )


def test_repository_identity_and_idempotency_are_scoped_per_project() -> None:
    tenant_id, first_project_id, second_project_id = uuid4(), uuid4(), uuid4()
    identity_id = uuid4()
    principal = AccessPrincipal(
        identity_id=identity_id,
        actor_id=str(identity_id),
        tenant_id=tenant_id,
        memberships=(
            MembershipRecord(first_project_id, tenant_id, "admin"),
            MembershipRecord(second_project_id, tenant_id, "admin"),
        ),
        auth_method="test",
    )
    repository = InMemoryPromptProgramRepository()
    application = _application(repository)
    values = _create_values()

    first = application.create_program(
        principal,
        project_id=first_project_id,
        expected_version=0,
        idempotency_key="same-project-local-key",
        **values,
    )
    second = application.create_program(
        principal,
        project_id=second_project_id,
        expected_version=0,
        idempotency_key="same-project-local-key",
        **values,
    )

    assert first.value.release.id != second.value.release.id
    assert repository.get_release(
        project_id=second_project_id, release_id=first.value.release.id
    ) is None


def test_test_command_freezes_output_evidence_and_replays_before_version_checks() -> None:
    project_id, tenant_id = uuid4(), uuid4()
    creator = _principal(project_id, tenant_id, "analyst")
    repository = InMemoryPromptProgramRepository()
    application = _application(repository)
    created = _create(application, creator, project_id)
    release = created.value.release

    first = application.record_test(
        creator,
        project_id=project_id,
        release_id=release.id,
        output_artifact_ref="s3://prompt-tests/generation/run-17.json",
        output_hash="a" * 64,
        expected_version=1,
        idempotency_key="test:generation:v1",
    )
    replay = application.record_test(
        creator,
        project_id=project_id,
        release_id=release.id,
        output_artifact_ref="s3://prompt-tests/generation/run-17.json",
        output_hash="a" * 64,
        expected_version=1,
        idempotency_key="test:generation:v1",
    )

    assert first.value.state.status == ProgramReleaseStatus.TESTED
    assert first.value.state.evidence_ref == first.value.evidence.state_evidence_ref
    assert first.value.evidence.output_hash == "a" * 64
    assert first.value.evidence.release_hash == release.release_hash
    assert replay.replayed is True
    assert replay.value is first.value
    with pytest.raises(FrozenInstanceError):
        first.value.evidence.output_hash = "b" * 64  # type: ignore[misc]

    with pytest.raises(PromptProgramIdempotencyConflict, match="reused"):
        application.record_test(
            creator,
            project_id=project_id,
            release_id=release.id,
            output_artifact_ref="s3://prompt-tests/generation/run-17.json",
            output_hash="b" * 64,
            expected_version=1,
            idempotency_key="test:generation:v1",
        )
    with pytest.raises(PromptProgramVersionConflict, match="changed"):
        application.record_test(
            creator,
            project_id=project_id,
            release_id=release.id,
            output_artifact_ref="s3://prompt-tests/generation/run-18.json",
            output_hash="c" * 64,
            expected_version=1,
            idempotency_key="test:generation:stale",
        )


def test_single_operator_can_approve_then_freeze_and_bind() -> None:
    project_id, tenant_id = uuid4(), uuid4()
    author = _principal(project_id, tenant_id, "admin")
    approver = _principal(project_id, tenant_id, "admin")
    analyst = _principal(project_id, tenant_id, "analyst")
    repository = InMemoryPromptProgramRepository()
    application = _application(repository)
    created = _create(application, author, project_id)
    release = created.value.release
    application.record_test(
        author,
        project_id=project_id,
        release_id=release.id,
        output_artifact_ref="s3://prompt-tests/generation/run-20.json",
        output_hash="d" * 64,
        expected_version=1,
        idempotency_key="test:generation:approval",
    )

    with pytest.raises(PromptProgramForbidden, match="role"):
        application.approve_release(
            analyst,
            project_id=project_id,
            release_id=release.id,
            expected_version=2,
            idempotency_key="approve:generation:analyst",
        )

    approved = application.approve_release(
        author,
        project_id=project_id,
        release_id=release.id,
        expected_version=2,
        idempotency_key="approve:generation:self",
    )
    approval_replay = application.approve_release(
        author,
        project_id=project_id,
        release_id=release.id,
        expected_version=2,
        idempotency_key="approve:generation:self",
    )
    assert approved.value.state.status == ProgramReleaseStatus.APPROVED
    assert approved.value.admitted_test_evidence is not None
    assert approval_replay.replayed is True
    assert approval_replay.value is approved.value

    frozen = application.freeze_release(
        approver,
        project_id=project_id,
        release_id=release.id,
        expected_version=3,
        idempotency_key="freeze:generation:v1",
    )
    freeze_replay = application.freeze_release(
        approver,
        project_id=project_id,
        release_id=release.id,
        expected_version=3,
        idempotency_key="freeze:generation:v1",
    )
    assert frozen.value.state.status == ProgramReleaseStatus.FROZEN
    assert freeze_replay.replayed is True
    assert freeze_replay.value is frozen.value

    bound = application.bind_release(
        approver,
        project_id=project_id,
        release_id=release.id,
        purpose=release.purpose,
        expected_version=0,
        idempotency_key="bind:generation:v1",
    )
    binding_replay = application.bind_release(
        approver,
        project_id=project_id,
        release_id=release.id,
        purpose=release.purpose,
        expected_version=0,
        idempotency_key="bind:generation:v1",
    )
    runtime = application.resolve_runtime_binding(
        project_id=project_id, purpose=release.purpose
    )

    assert bound.value.binding.frozen_state_id == frozen.value.state.id
    assert binding_replay.replayed is True
    assert binding_replay.value is bound.value
    assert runtime.binding == bound.value.binding
    assert runtime.release == release
    retired = application.retire_release(
        approver,
        project_id=project_id,
        release_id=release.id,
        expected_version=4,
        idempotency_key="retire:generation:v1",
    )
    retirement_replay = application.retire_release(
        approver,
        project_id=project_id,
        release_id=release.id,
        expected_version=4,
        idempotency_key="retire:generation:v1",
    )
    assert retired.value.state.status == ProgramReleaseStatus.RETIRED
    assert retired.value.state.evidence_ref == (
        f"retire:{frozen.value.state.id}:{release.release_hash}"
    )
    assert retirement_replay.replayed is True
    assert repository.list_current_bindings(
        project_id=project_id,
        program_kind=None,
        limit=10,
        offset=0,
    ).items == ()
    with pytest.raises(PromptProgramRuntimeBlocked, match="exact frozen"):
        application.resolve_runtime_binding(
            project_id=project_id, purpose=release.purpose
        )
    with pytest.raises(PromptProgramVersionConflict, match="changed"):
        application.bind_release(
            approver,
            project_id=project_id,
            release_id=release.id,
            purpose=release.purpose,
            expected_version=0,
            idempotency_key="bind:generation:stale",
        )


def test_runtime_rejects_a_repository_binding_to_a_non_frozen_release() -> None:
    project_id, tenant_id = uuid4(), uuid4()
    author = _principal(project_id, tenant_id, "admin")
    approver = _principal(project_id, tenant_id, "admin")
    repository = InMemoryPromptProgramRepository()
    application = _application(repository)
    created = _create(application, author, project_id)
    release = created.value.release
    application.record_test(
        author,
        project_id=project_id,
        release_id=release.id,
        output_artifact_ref="s3://prompt-tests/generation/run-30.json",
        output_hash="e" * 64,
        expected_version=1,
        idempotency_key="test:generation:non-frozen",
    )
    approved = application.approve_release(
        approver,
        project_id=project_id,
        release_id=release.id,
        expected_version=2,
        idempotency_key="approve:generation:non-frozen",
    ).value
    forged = ProgramBinding(
        id=uuid4(),
        project_id=project_id,
        purpose=release.purpose,
        program_kind=release.program_kind,
        program_id=release.program_id,
        release_id=release.id,
        release_version=release.version,
        release_hash=release.release_hash,
        frozen_state_id=approved.state.id,
        binding_version=1,
        previous_binding_id=None,
        bound_by=approver.identity_id,
        bound_at=NOW,
    )
    repository.store_binding(
        project_id=project_id,
        binding=forged,
        expected_version=0,
        command=PromptCommandRecord(
            project_id=project_id,
            idempotency_key_hash="1" * 64,
            operation=PromptCommandOperation.BIND,
            request_hash="2" * 64,
            result=forged,
        ),
    )

    with pytest.raises(PromptProgramRuntimeBlocked, match="exact frozen"):
        application.resolve_runtime_binding(
            project_id=project_id, purpose=release.purpose
        )


def test_next_release_and_diff_are_reachable_idempotent_and_project_scoped() -> None:
    project_id, tenant_id = uuid4(), uuid4()
    author = _principal(project_id, tenant_id, "admin")
    approver = _principal(project_id, tenant_id, "admin")
    repository = InMemoryPromptProgramRepository()
    application = _application(repository)
    created = _create(application, author, project_id).value
    baseline = created.release
    application.record_test(
        author,
        project_id=project_id,
        release_id=baseline.id,
        output_artifact_ref="s3://prompt-tests/generation/baseline.json",
        output_hash="f" * 64,
        expected_version=1,
        idempotency_key="test:generation:baseline",
    )
    application.approve_release(
        approver,
        project_id=project_id,
        release_id=baseline.id,
        expected_version=2,
        idempotency_key="approve:generation:baseline",
    )
    release_values = _release_values(
        user_template="Draft a concise {{scenario}} for {{channel}}.",
        test_set_id=baseline.test_set_id,
    )

    candidate = application.create_release(
        author,
        project_id=project_id,
        program_id=created.program.id,
        expected_version=1,
        idempotency_key="create-release:generation:v2",
        **release_values,
    )
    replay = application.create_release(
        author,
        project_id=project_id,
        program_id=created.program.id,
        expected_version=1,
        idempotency_key="create-release:generation:v2",
        **release_values,
    )

    assert candidate.value.release.version == 2
    assert candidate.value.release.program_id == created.program.id
    assert candidate.value.release.program_kind == created.program.program_kind
    assert candidate.value.release.purpose == created.program.purpose
    assert candidate.value.release.owner_id == created.program.owner_id
    assert candidate.value.state.version == 1
    assert candidate.value.state.status == ProgramReleaseStatus.DRAFT
    assert replay.replayed is True and replay.value is candidate.value

    programs = application.list_programs(
        author, project_id=project_id, limit=20, offset=0
    )
    releases = application.list_releases(
        author,
        project_id=project_id,
        program_id=created.program.id,
        limit=20,
        offset=0,
    )
    fetched = application.get_release(
        author,
        project_id=project_id,
        program_id=created.program.id,
        release_id=candidate.value.release.id,
    )
    assert programs.items == (created.program,)
    assert [item.release.version for item in releases.items] == [2, 1]
    assert fetched.release == candidate.value.release

    values = {"scenario": "robot mower review", "channel": "youtube"}
    diff = application.diff_release(
        approver,
        project_id=project_id,
        program_id=created.program.id,
        candidate_release_id=candidate.value.release.id,
        baseline_release_id=baseline.id,
        fixed_variables=values,
        expected_version=1,
        idempotency_key="diff:generation:v2-v1",
    )
    diff_replay = application.diff_release(
        approver,
        project_id=project_id,
        program_id=created.program.id,
        candidate_release_id=candidate.value.release.id,
        baseline_release_id=baseline.id,
        fixed_variables=values,
        expected_version=1,
        idempotency_key="diff:generation:v2-v1",
    )
    assert diff.value.changed_fields == ("user_template",)
    assert diff.value.candidate_release_id == candidate.value.release.id
    assert diff_replay.replayed is True and diff_replay.value is diff.value

    with pytest.raises(PromptProgramIdempotencyConflict, match="reused"):
        application.diff_release(
            approver,
            project_id=project_id,
            program_id=created.program.id,
            candidate_release_id=candidate.value.release.id,
            baseline_release_id=baseline.id,
            fixed_variables={**values, "scenario": "different"},
            expected_version=1,
            idempotency_key="diff:generation:v2-v1",
        )
    with pytest.raises(PromptProgramVersionConflict, match="latest Release changed"):
        application.create_release(
            author,
            project_id=project_id,
            program_id=created.program.id,
            expected_version=1,
            idempotency_key="create-release:generation:stale",
            **_release_values(),
        )


def _application(
    repository: InMemoryPromptProgramRepository,
) -> PromptProgramApplication:
    return PromptProgramApplication(
        repository,
        test_evidence_verifier=_AcceptingEvidenceVerifier(),
        clock=lambda: NOW,
    )


class _AcceptingEvidenceVerifier:
    def verify(self, **values: object) -> None:
        del values


def _principal(
    project_id: UUID, tenant_id: UUID, role: str
) -> AccessPrincipal:
    identity_id = uuid4()
    return AccessPrincipal(
        identity_id=identity_id,
        actor_id=str(identity_id),
        tenant_id=tenant_id,
        memberships=(MembershipRecord(project_id, tenant_id, role),),
        auth_method="test",
    )


def _create_values() -> dict[str, object]:
    variable_schema = {
        "type": "object",
        "properties": {
            "scenario": {"type": "string"},
            "channel": {"type": "string"},
        },
        "required": ["scenario", "channel"],
        "additionalProperties": False,
    }
    return {
        "program_kind": ProgramKind.GENERATION,
        "purpose": "synthetic_lab.generation",
        "system_template": "Return structured Australian English for {{channel}}.",
        "user_template": "Write {{scenario}} for {{channel}}.",
        "schemas": ProgramSchemaContract(
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
        ),
        "model_policy": ModelPolicySnapshot(
            version="synthetic-generation-v1",
            policy={
                "allowed_providers": ["openai", "deepseek"],
                "configured_model": "approved-generation-model",
                "fallback": False,
            },
        ),
        "test_set_id": uuid4(),
        "test_set_version": 1,
        "test_set_hash": "ab" * 32,
        "compiler_version": "geo-prompt-compiler-v2",
    }


def _release_values(
    *,
    user_template: str = "Write {{scenario}} for {{channel}}.",
    test_set_id: UUID | None = None,
) -> dict[str, object]:
    values = _create_values()
    return {
        "system_template": values["system_template"],
        "user_template": user_template,
        "schemas": values["schemas"],
        "model_policy": values["model_policy"],
        "test_set_id": test_set_id or values["test_set_id"],
        "test_set_version": values["test_set_version"],
        "test_set_hash": values["test_set_hash"],
        "compiler_version": values["compiler_version"],
    }


def _create(
    application: PromptProgramApplication,
    principal: AccessPrincipal,
    project_id: UUID,
):
    return application.create_program(
        principal,
        project_id=project_id,
        expected_version=0,
        idempotency_key=f"create:{principal.identity_id}",
        **_create_values(),
    )
