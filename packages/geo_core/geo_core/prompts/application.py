"""Project-scoped Prompt Program command application service."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TypeVar
from uuid import UUID, uuid4

from geo_core.access.models import AccessPrincipal
from geo_core.prompts.application_access import (
    APPROVER_ROLES as _APPROVER_ROLES,
    CONTRIBUTOR_ROLES as _CONTRIBUTOR_ROLES,
    require_project_role as _require_project_role,
)
from geo_core.prompts.application_models import (
    BoundPromptProgram,
    CommandReceipt,
    CreatedPromptProgram,
    CreatedPromptRelease,
    PromptProgramApplicationError,
    PromptProgramForbidden,
    PromptProgramNotFound,
    PromptProgramRuntimeBlocked,
    RuntimePromptProgram,
    TestedPromptProgram,
    TransitionedPromptProgram,
)
from geo_core.prompts.application_release_operations import (
    PromptProgramReleaseOperationsMixin,
)
from geo_core.prompts.application_support import (
    command_record as _command_record,
    idempotency_key_hash as _idempotency_key_hash,
    request_hash as _request_hash,
    require_expected_version as _require_expected_version,
)
from geo_core.prompts.ports import (
    PromptCommandOperation,
    PromptProgramIdempotencyConflict,
    PromptProgramPersistenceError,
    PromptProgramRepository,
    PromptProgramVersionConflict,
    StoredPromptCommand,
)
from geo_core.prompts.program import (
    ModelPolicySnapshot,
    ProgramKind,
    ProgramReleaseCommand,
    ProgramReleaseState,
    ProgramReleaseStatus,
    ProgramSchemaContract,
    ProgramTestEvidence,
    PromptProgram,
    PromptProgramRelease,
    PromptProgramRuleViolation,
    assert_binding_scope,
    bind_frozen_release,
    create_initial_release_state,
    transition_release_state,
)
from geo_core.prompts.test_execution_contracts import (
    PromptTestEvidenceVerifier,
    PromptTestExecutionError,
)


_ResultT = TypeVar("_ResultT")


class PromptProgramApplication(PromptProgramReleaseOperationsMixin):
    """Authorize, deduplicate and atomically persist Prompt Program commands."""

    def __init__(
        self,
        repository: PromptProgramRepository,
        *,
        test_evidence_verifier: PromptTestEvidenceVerifier | None = None,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._test_evidence_verifier = test_evidence_verifier
        self._id_factory = id_factory
        self._clock = clock

    def create_program(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_kind: ProgramKind,
        purpose: str,
        system_template: str,
        user_template: str,
        schemas: ProgramSchemaContract,
        model_policy: ModelPolicySnapshot,
        test_set_id: UUID,
        test_set_version: int,
        test_set_hash: str,
        compiler_version: str,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[CreatedPromptProgram]:
        _require_project_role(principal, project_id, allowed=_CONTRIBUTOR_ROLES)
        key_hash = _idempotency_key_hash(idempotency_key)
        try:
            parsed_kind = ProgramKind(program_kind)
        except ValueError as exc:
            raise PromptProgramRuleViolation("unknown Prompt Program kind") from exc
        request_hash = _request_hash(
            operation=PromptCommandOperation.CREATE,
            actor_id=principal.identity_id,
            project_id=project_id,
            expected_version=expected_version,
            values={
                "program_kind": parsed_kind.value,
                "purpose": purpose.strip(),
                "system_template": system_template.strip(),
                "user_template": user_template.strip(),
                "schemas": schemas.canonical_value(),
                "model_policy": model_policy.canonical_value(),
                "test_set_id": str(test_set_id),
                "test_set_version": test_set_version,
                "test_set_hash": test_set_hash,
                "compiler_version": compiler_version.strip(),
            },
        )
        replay = self._recover(
            project_id=project_id,
            key_hash=key_hash,
            operation=PromptCommandOperation.CREATE,
            request_hash=request_hash,
            result_type=CreatedPromptProgram,
        )
        if replay is not None:
            return replay

        program = PromptProgram(
            id=self._id_factory(),
            project_id=project_id,
            program_kind=parsed_kind,
            purpose=purpose,
            owner_id=principal.identity_id,
        )
        release = PromptProgramRelease.compile(
            id=self._id_factory(),
            program=program,
            version=1,
            system_template=system_template,
            user_template=user_template,
            schemas=schemas,
            model_policy=model_policy,
            test_set_id=test_set_id,
            test_set_version=test_set_version,
            test_set_hash=test_set_hash,
            compiler_version=compiler_version,
        )
        state = create_initial_release_state(
            id=self._id_factory(),
            release=release,
            actor_id=principal.identity_id,
            acted_at=self._clock(),
        )
        result = CreatedPromptProgram(program, release, state)
        stored = self._repository.store_created_program(
            project_id=project_id,
            program=program,
            release=release,
            state=state,
            expected_version=expected_version,
            command=_command_record(
                project_id=project_id,
                key_hash=key_hash,
                operation=PromptCommandOperation.CREATE,
                request_hash=request_hash,
                result=result,
            ),
        )
        return _stored_receipt(stored, CreatedPromptProgram)

    def record_test(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        release_id: UUID,
        output_artifact_ref: str,
        output_hash: str,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[TestedPromptProgram]:
        _require_project_role(principal, project_id, allowed=_CONTRIBUTOR_ROLES)
        key_hash = _idempotency_key_hash(idempotency_key)
        request_hash = _request_hash(
            operation=PromptCommandOperation.TEST,
            actor_id=principal.identity_id,
            project_id=project_id,
            expected_version=expected_version,
            values={
                "release_id": str(release_id),
                "output_artifact_ref": output_artifact_ref.strip(),
                "output_hash": output_hash,
            },
        )
        replay = self._recover(
            project_id=project_id,
            key_hash=key_hash,
            operation=PromptCommandOperation.TEST,
            request_hash=request_hash,
            result_type=TestedPromptProgram,
        )
        if replay is not None:
            return replay

        release, current = self._release_and_state(project_id, release_id)
        _require_expected_version(current, expected_version)
        state_id = self._id_factory()
        evidence = ProgramTestEvidence(
            id=self._id_factory(),
            project_id=project_id,
            release_id=release.id,
            release_hash=release.release_hash,
            tested_state_id=state_id,
            test_set_id=release.test_set_id,
            test_set_version=release.test_set_version,
            output_artifact_ref=output_artifact_ref,
            output_hash=output_hash,
            tested_by=principal.identity_id,
            tested_at=self._clock(),
        )
        state = transition_release_state(
            id=state_id,
            release=release,
            current=current,
            command=ProgramReleaseCommand.RECORD_TEST,
            actor_id=principal.identity_id,
            acted_at=evidence.tested_at,
            evidence_ref=evidence.state_evidence_ref,
        )
        result = TestedPromptProgram(release, state, evidence)
        stored = self._repository.store_release_transition(
            project_id=project_id,
            release=release,
            state=state,
            expected_version=expected_version,
            test_evidence=evidence,
            command=_command_record(
                project_id=project_id,
                key_hash=key_hash,
                operation=PromptCommandOperation.TEST,
                request_hash=request_hash,
                result=result,
            ),
        )
        return _stored_receipt(stored, TestedPromptProgram)

    def approve_release(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        release_id: UUID,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[TransitionedPromptProgram]:
        _require_project_role(principal, project_id, allowed=_APPROVER_ROLES)
        return self._transition_governed_release(
            principal,
            project_id=project_id,
            release_id=release_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            operation=PromptCommandOperation.APPROVE,
            command=ProgramReleaseCommand.APPROVE,
        )

    def freeze_release(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        release_id: UUID,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[TransitionedPromptProgram]:
        _require_project_role(principal, project_id, allowed=_APPROVER_ROLES)
        return self._transition_governed_release(
            principal,
            project_id=project_id,
            release_id=release_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            operation=PromptCommandOperation.FREEZE,
            command=ProgramReleaseCommand.FREEZE,
        )

    def bind_release(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        release_id: UUID,
        purpose: str,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[BoundPromptProgram]:
        _require_project_role(principal, project_id, allowed=_APPROVER_ROLES)
        key_hash = _idempotency_key_hash(idempotency_key)
        request_hash = _request_hash(
            operation=PromptCommandOperation.BIND,
            actor_id=principal.identity_id,
            project_id=project_id,
            expected_version=expected_version,
            values={"release_id": str(release_id), "purpose": purpose.strip()},
        )
        replay = self._recover(
            project_id=project_id,
            key_hash=key_hash,
            operation=PromptCommandOperation.BIND,
            request_hash=request_hash,
            result_type=BoundPromptProgram,
        )
        if replay is not None:
            return replay

        release, state = self._release_and_state(project_id, release_id)
        current = self._repository.get_current_binding(
            project_id=project_id, purpose=purpose.strip()
        )
        current_version = current.binding_version if current is not None else 0
        if current_version != expected_version:
            raise PromptProgramVersionConflict(
                "Prompt Program binding changed after it was read"
            )
        binding = bind_frozen_release(
            id=self._id_factory(),
            project_id=project_id,
            purpose=purpose,
            release=release,
            state=state,
            binding_version=expected_version + 1,
            previous_binding_id=current.id if current is not None else None,
            actor_id=principal.identity_id,
            bound_at=self._clock(),
        )
        result = BoundPromptProgram(release, state, binding)
        stored = self._repository.store_binding(
            project_id=project_id,
            binding=binding,
            expected_version=expected_version,
            command=_command_record(
                project_id=project_id,
                key_hash=key_hash,
                operation=PromptCommandOperation.BIND,
                request_hash=request_hash,
                result=result,
            ),
        )
        return _stored_receipt(stored, BoundPromptProgram)

    def resolve_runtime_binding(
        self, *, project_id: UUID, purpose: str
    ) -> RuntimePromptProgram:
        """Resolve an exact frozen binding for an internal runtime, failing closed."""

        normalized_purpose = purpose.strip()
        binding = self._repository.get_current_binding(
            project_id=project_id, purpose=normalized_purpose
        )
        if binding is None:
            raise PromptProgramNotFound("No Prompt Program is bound for this purpose.")
        release = self._repository.get_release(
            project_id=project_id, release_id=binding.release_id
        )
        state = self._repository.get_current_release_state(
            project_id=project_id, release_id=binding.release_id
        )
        if release is None or state is None:
            raise PromptProgramRuntimeBlocked("Prompt Program binding lineage is incomplete")
        try:
            assert_binding_scope(
                binding=binding,
                project_id=project_id,
                purpose=normalized_purpose,
                kind=release.program_kind,
            )
        except PromptProgramRuleViolation as exc:
            raise PromptProgramRuntimeBlocked(str(exc)) from exc
        if (
            state.status != ProgramReleaseStatus.FROZEN
            or state.id != binding.frozen_state_id
            or state.release_hash != binding.release_hash
            or release.release_hash != binding.release_hash
            or release.program_id != binding.program_id
            or release.version != binding.release_version
        ):
            raise PromptProgramRuntimeBlocked(
                "Prompt Program runtime requires an exact frozen Release binding"
            )
        return RuntimePromptProgram(release, state, binding)

    def _transition_governed_release(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        release_id: UUID,
        expected_version: int,
        idempotency_key: str,
        operation: PromptCommandOperation,
        command: ProgramReleaseCommand,
    ) -> CommandReceipt[TransitionedPromptProgram]:
        key_hash = _idempotency_key_hash(idempotency_key)
        request_hash = _request_hash(
            operation=operation,
            actor_id=principal.identity_id,
            project_id=project_id,
            expected_version=expected_version,
            values={"release_id": str(release_id)},
        )
        replay = self._recover(
            project_id=project_id,
            key_hash=key_hash,
            operation=operation,
            request_hash=request_hash,
            result_type=TransitionedPromptProgram,
        )
        if replay is not None:
            return replay

        release, current = self._release_and_state(project_id, release_id)
        _require_expected_version(current, expected_version)
        admitted_evidence: ProgramTestEvidence | None = None
        if operation == PromptCommandOperation.APPROVE:
            if principal.identity_id == release.owner_id:
                raise PromptProgramForbidden(
                    "Prompt Program owners cannot approve their own Release."
                )
            admitted_evidence = self._repository.get_latest_passed_test_evidence(
                project_id=project_id,
                release_id=release.id,
                release_hash=release.release_hash,
                test_set_id=release.test_set_id,
                test_set_version=release.test_set_version,
            )
            if (
                admitted_evidence is None
                or current.evidence_ref != admitted_evidence.state_evidence_ref
                or admitted_evidence.tested_state_id != current.id
                or admitted_evidence.release_hash != release.release_hash
                or admitted_evidence.test_set_id != release.test_set_id
                or admitted_evidence.test_set_version != release.test_set_version
            ):
                raise PromptProgramRuntimeBlocked(
                    "Prompt Program approval requires intact frozen test evidence"
                )
            if self._test_evidence_verifier is None:
                raise PromptProgramRuntimeBlocked(
                    "Prompt Program approval requires a durable test evidence verifier"
                )
            try:
                self._test_evidence_verifier.verify(
                    release=release,
                    evidence=admitted_evidence,
                )
            except PromptTestExecutionError as error:
                raise PromptProgramRuntimeBlocked(
                    "Prompt Program approval requires valid server-evaluated test evidence"
                ) from error
            evidence_ref = (
                f"approval:{admitted_evidence.id}:{admitted_evidence.evidence_hash}"
            )
        else:
            evidence_ref = f"freeze:{current.id}:{current.release_hash}"

        state = transition_release_state(
            id=self._id_factory(),
            release=release,
            current=current,
            command=command,
            actor_id=principal.identity_id,
            acted_at=self._clock(),
            evidence_ref=evidence_ref,
        )
        result = TransitionedPromptProgram(release, state, admitted_evidence)
        stored = self._repository.store_release_transition(
            project_id=project_id,
            release=release,
            state=state,
            expected_version=expected_version,
            test_evidence=None,
            command=_command_record(
                project_id=project_id,
                key_hash=key_hash,
                operation=operation,
                request_hash=request_hash,
                result=result,
            ),
        )
        return _stored_receipt(stored, TransitionedPromptProgram)

    def _release_and_state(
        self, project_id: UUID, release_id: UUID
    ) -> tuple[PromptProgramRelease, ProgramReleaseState]:
        release = self._repository.get_release(
            project_id=project_id, release_id=release_id
        )
        state = self._repository.get_current_release_state(
            project_id=project_id, release_id=release_id
        )
        if release is None or state is None:
            raise PromptProgramNotFound("The Prompt Program Release does not exist.")
        return release, state

    def _recover(
        self,
        *,
        project_id: UUID,
        key_hash: str,
        operation: PromptCommandOperation,
        request_hash: str,
        result_type: type[_ResultT],
    ) -> CommandReceipt[_ResultT] | None:
        existing = self._repository.get_command(
            project_id=project_id, idempotency_key_hash=key_hash
        )
        if existing is None:
            return None
        if existing.operation != operation or existing.request_hash != request_hash:
            raise PromptProgramIdempotencyConflict(
                "Prompt Program idempotency key was reused for another command"
            )
        if not isinstance(existing.result, result_type):
            raise PromptProgramPersistenceError(
                "Prompt Program command result type does not match its operation"
            )
        return CommandReceipt(existing.result, replayed=True)


def _stored_receipt(
    stored: StoredPromptCommand, result_type: type[_ResultT]
) -> CommandReceipt[_ResultT]:
    if not isinstance(stored.record.result, result_type):
        raise PromptProgramPersistenceError(
            "Prompt Program stored command result type does not match its operation"
        )
    return CommandReceipt(stored.record.result, stored.replayed)


__all__ = [
    "BoundPromptProgram",
    "CommandReceipt",
    "CreatedPromptProgram",
    "CreatedPromptRelease",
    "PromptProgramApplication",
    "PromptProgramApplicationError",
    "PromptProgramForbidden",
    "PromptProgramNotFound",
    "PromptProgramRuntimeBlocked",
    "RuntimePromptProgram",
    "TestedPromptProgram",
    "TransitionedPromptProgram",
]
