"""Prompt Program release creation, read and deterministic diff operations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import TypeVar
from uuid import UUID

from geo_core.access.models import AccessPrincipal
from geo_core.prompts.application_access import CONTRIBUTOR_ROLES, require_project_role
from geo_core.prompts.application_models import (
    CommandReceipt,
    CreatedPromptRelease,
    PromptProgramNotFound,
)
from geo_core.prompts.application_support import (
    command_record,
    idempotency_key_hash,
    request_hash,
    require_expected_version,
)
from geo_core.prompts.ports import (
    PromptCommandOperation,
    PromptProgramIdempotencyConflict,
    PromptProgramPageRead,
    PromptProgramPersistenceError,
    PromptProgramRepository,
    PromptProgramVersionConflict,
    PromptReleasePageRead,
    PromptReleaseRead,
    StoredPromptCommand,
)
from geo_core.prompts.program import (
    ModelPolicySnapshot,
    ProgramReleaseDiff,
    ProgramSchemaContract,
    PromptProgram,
    PromptProgramRelease,
    compare_candidate_to_approved,
    create_initial_release_state,
)


_ResultT = TypeVar("_ResultT")


class PromptProgramReleaseOperationsMixin:
    _repository: PromptProgramRepository
    _id_factory: Callable[[], UUID]
    _clock: Callable[[], datetime]

    def create_release(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
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
    ) -> CommandReceipt[CreatedPromptRelease]:
        require_project_role(principal, project_id, allowed=CONTRIBUTOR_ROLES)
        key_hash = idempotency_key_hash(idempotency_key)
        digest = request_hash(
            operation=PromptCommandOperation.CREATE_RELEASE,
            actor_id=principal.identity_id,
            project_id=project_id,
            expected_version=expected_version,
            values={
                "program_id": str(program_id),
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
        replay = _recover(
            self._repository,
            project_id=project_id,
            key_hash=key_hash,
            operation=PromptCommandOperation.CREATE_RELEASE,
            request_hash=digest,
            result_type=CreatedPromptRelease,
        )
        if replay is not None:
            return replay

        program = _required_program(self._repository, project_id, program_id)
        latest_page = self._repository.list_releases(
            project_id=project_id, program_id=program_id, limit=1, offset=0
        )
        if not latest_page.items:
            raise PromptProgramPersistenceError(
                "Prompt Program has no initial Release lineage"
            )
        latest = latest_page.items[0].release
        if latest.version != expected_version:
            raise PromptProgramVersionConflict(
                "Prompt Program latest Release changed after it was read"
            )
        if (
            latest.program_id != program.id
            or latest.project_id != program.project_id
            or latest.program_kind != program.program_kind
            or latest.purpose != program.purpose
            or latest.owner_id != program.owner_id
        ):
            raise PromptProgramPersistenceError(
                "Prompt Program latest Release identity is inconsistent"
            )
        release = PromptProgramRelease.compile(
            id=self._id_factory(),
            program=program,
            version=expected_version + 1,
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
        result = CreatedPromptRelease(release, state)
        stored = self._repository.store_created_release(
            project_id=project_id,
            release=release,
            state=state,
            expected_version=expected_version,
            command=command_record(
                project_id=project_id,
                key_hash=key_hash,
                operation=PromptCommandOperation.CREATE_RELEASE,
                request_hash=digest,
                result=result,
            ),
        )
        return _stored_receipt(stored, CreatedPromptRelease)

    def list_programs(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        limit: int,
        offset: int,
    ) -> PromptProgramPageRead:
        require_project_role(principal, project_id, allowed=CONTRIBUTOR_ROLES)
        return self._repository.list_programs(
            project_id=project_id, limit=limit, offset=offset
        )

    def get_program(
        self, principal: AccessPrincipal, *, project_id: UUID, program_id: UUID
    ) -> PromptProgram:
        require_project_role(principal, project_id, allowed=CONTRIBUTOR_ROLES)
        return _required_program(self._repository, project_id, program_id)

    def list_releases(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
        limit: int,
        offset: int,
    ) -> PromptReleasePageRead:
        require_project_role(principal, project_id, allowed=CONTRIBUTOR_ROLES)
        _required_program(self._repository, project_id, program_id)
        return self._repository.list_releases(
            project_id=project_id,
            program_id=program_id,
            limit=limit,
            offset=offset,
        )

    def get_release(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
        release_id: UUID,
    ) -> PromptReleaseRead:
        require_project_role(principal, project_id, allowed=CONTRIBUTOR_ROLES)
        _required_program(self._repository, project_id, program_id)
        return _required_release(
            self._repository,
            project_id=project_id,
            program_id=program_id,
            release_id=release_id,
        )

    def diff_release(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
        candidate_release_id: UUID,
        baseline_release_id: UUID,
        fixed_variables: Mapping[str, object],
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[ProgramReleaseDiff]:
        require_project_role(principal, project_id, allowed=CONTRIBUTOR_ROLES)
        key_hash = idempotency_key_hash(idempotency_key)
        digest = request_hash(
            operation=PromptCommandOperation.DIFF,
            actor_id=principal.identity_id,
            project_id=project_id,
            expected_version=expected_version,
            values={
                "program_id": str(program_id),
                "candidate_release_id": str(candidate_release_id),
                "baseline_release_id": str(baseline_release_id),
                "fixed_variables": fixed_variables,
            },
        )
        replay = _recover(
            self._repository,
            project_id=project_id,
            key_hash=key_hash,
            operation=PromptCommandOperation.DIFF,
            request_hash=digest,
            result_type=ProgramReleaseDiff,
        )
        if replay is not None:
            return replay

        _required_program(self._repository, project_id, program_id)
        candidate = _required_release(
            self._repository,
            project_id=project_id,
            program_id=program_id,
            release_id=candidate_release_id,
        )
        baseline = _required_release(
            self._repository,
            project_id=project_id,
            program_id=program_id,
            release_id=baseline_release_id,
        )
        require_expected_version(candidate.state, expected_version)
        result = compare_candidate_to_approved(
            approved_release=baseline.release,
            approved_state=baseline.state,
            candidate_release=candidate.release,
            candidate_state=candidate.state,
            fixed_variables=fixed_variables,
        )
        stored = self._repository.store_diff(
            project_id=project_id,
            candidate_release_id=candidate_release_id,
            expected_version=expected_version,
            command=command_record(
                project_id=project_id,
                key_hash=key_hash,
                operation=PromptCommandOperation.DIFF,
                request_hash=digest,
                result=result,
            ),
        )
        return _stored_receipt(stored, ProgramReleaseDiff)


def _required_program(
    repository: PromptProgramRepository, project_id: UUID, program_id: UUID
) -> PromptProgram:
    program = repository.get_program(project_id=project_id, program_id=program_id)
    if program is None:
        raise PromptProgramNotFound("The Prompt Program does not exist.")
    return program


def _required_release(
    repository: PromptProgramRepository,
    *,
    project_id: UUID,
    program_id: UUID,
    release_id: UUID,
) -> PromptReleaseRead:
    release = repository.get_release(project_id=project_id, release_id=release_id)
    state = repository.get_current_release_state(
        project_id=project_id, release_id=release_id
    )
    if release is None or state is None or release.program_id != program_id:
        raise PromptProgramNotFound("The Prompt Program Release does not exist.")
    return PromptReleaseRead(release, state)


def _recover(
    repository: PromptProgramRepository,
    *,
    project_id: UUID,
    key_hash: str,
    operation: PromptCommandOperation,
    request_hash: str,
    result_type: type[_ResultT],
) -> CommandReceipt[_ResultT] | None:
    existing = repository.get_command(
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
