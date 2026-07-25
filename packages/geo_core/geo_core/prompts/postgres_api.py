"""Internal API facade backed by project-scoped Prompt Program transactions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TypeVar
from uuid import UUID

import psycopg

from geo_core.access.models import AccessPrincipal
from geo_core.prompts.application import (
    BoundPromptProgram,
    CommandReceipt,
    CreatedPromptProgram,
    CreatedPromptRelease,
    PromptProgramApplication,
    PromptProgramForbidden,
    PromptProgramNotFound,
    PromptProgramRuntimeBlocked,
    TransitionedPromptProgram,
)
from geo_core.prompts.ports import (
    PromptBindingPageRead,
    PromptProgramPageRead,
    PromptProgramRepository,
    PromptReleasePageRead,
    PromptReleaseRead,
)
from geo_core.prompts.postgres_uow import (
    PsycopgPromptProgramUnitOfWork,
    prompt_program_uow_factory,
)
from geo_core.prompts.program import (
    ModelPolicySnapshot,
    ProgramKind,
    ProgramReleaseDiff,
    ProgramSchemaContract,
    PromptProgram,
)
from geo_core.prompts.test_artifacts import (
    PromptTestObjectStore,
    S3PromptTestEvidenceVerifier,
)
from geo_core.prompts.test_execution_application import PromptTestApplication
from geo_core.prompts.test_execution_contracts import (
    PromptTestEvidenceVerifier,
    PromptTestJobReceipt,
    PromptTestRouteRequest,
    PromptTestRuntimeOption,
    PromptTestRuntimeSelector,
)
from geo_core.prompts.test_execution_postgres import prompt_test_uow_factory


_READ_ROLES = frozenset({"owner", "admin", "analyst"})
_ResultT = TypeVar("_ResultT")


class PsycopgPromptProgramApi:
    """Transport-neutral facade enforcing path identity before each command."""

    def __init__(
        self,
        uow_factory: Callable[[UUID], PsycopgPromptProgramUnitOfWork],
        *,
        test_application: PromptTestApplication | None = None,
        test_runtime_selector: PromptTestRuntimeSelector | None = None,
        test_evidence_verifier: PromptTestEvidenceVerifier | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._test_application = test_application
        self._test_runtime_selector = test_runtime_selector
        self._test_evidence_verifier = test_evidence_verifier

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
        return self._command(
            project_id,
            lambda application: application.create_program(
                principal,
                project_id=project_id,
                program_kind=program_kind,
                purpose=purpose,
                system_template=system_template,
                user_template=user_template,
                schemas=schemas,
                model_policy=model_policy,
                test_set_id=test_set_id,
                test_set_version=test_set_version,
                test_set_hash=test_set_hash,
                compiler_version=compiler_version,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
            ),
        )

    def list_test_runtimes(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
    ) -> tuple[PromptTestRuntimeOption, ...]:
        _require_read_role(principal, project_id)
        if self._test_runtime_selector is None:
            raise PromptProgramRuntimeBlocked(
                "Prompt test runtime catalog is unavailable"
            )
        return self._test_runtime_selector.list_approved(project_id=project_id)

    def list_bindings(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_kind: ProgramKind | None,
        limit: int,
        offset: int,
    ) -> PromptBindingPageRead:
        _require_read_role(principal, project_id)
        with self._uow_factory(project_id) as unit_of_work:
            return unit_of_work.prompts.list_current_bindings(
                project_id=project_id,
                program_kind=program_kind,
                limit=limit,
                offset=offset,
            )

    def get_program(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
    ) -> PromptProgram:
        _require_read_role(principal, project_id)
        with self._uow_factory(project_id) as unit_of_work:
            return _required_program(unit_of_work.prompts, project_id, program_id)

    def list_programs(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        limit: int,
        offset: int,
    ) -> PromptProgramPageRead:
        _require_read_role(principal, project_id)
        with self._uow_factory(project_id) as unit_of_work:
            return unit_of_work.prompts.list_programs(
                project_id=project_id, limit=limit, offset=offset
            )

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
        return self._command(
            project_id,
            lambda application: application.create_release(
                principal,
                project_id=project_id,
                program_id=program_id,
                system_template=system_template,
                user_template=user_template,
                schemas=schemas,
                model_policy=model_policy,
                test_set_id=test_set_id,
                test_set_version=test_set_version,
                test_set_hash=test_set_hash,
                compiler_version=compiler_version,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
            ),
        )

    def list_releases(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
        limit: int,
        offset: int,
    ) -> PromptReleasePageRead:
        _require_read_role(principal, project_id)
        with self._uow_factory(project_id) as unit_of_work:
            _required_program(unit_of_work.prompts, project_id, program_id)
            return unit_of_work.prompts.list_releases(
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
        _require_read_role(principal, project_id)
        with self._uow_factory(project_id) as unit_of_work:
            return _required_release(
                unit_of_work.prompts,
                project_id=project_id,
                program_id=program_id,
                release_id=release_id,
            )

    def enqueue_test(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
        release_id: UUID,
        test_set_id: UUID,
        test_set_version: int,
        test_set_hash: str,
        route: PromptTestRouteRequest,
        expected_version: int,
        idempotency_key: str,
    ) -> PromptTestJobReceipt:
        if self._test_application is None:
            raise PromptProgramRuntimeBlocked(
                "Prompt test execution requires a durable Model Gateway runtime"
            )
        return self._test_application.enqueue(
            principal,
            project_id=project_id,
            program_id=program_id,
            release_id=release_id,
            test_set_id=test_set_id,
            test_set_version=test_set_version,
            test_set_hash=test_set_hash,
            route=route,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )

    def approve_release(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
        release_id: UUID,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[TransitionedPromptProgram]:
        return self._release_command(
            project_id=project_id,
            program_id=program_id,
            release_id=release_id,
            operation=lambda application: application.approve_release(
                principal,
                project_id=project_id,
                release_id=release_id,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
            ),
        )

    def freeze_release(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
        release_id: UUID,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[TransitionedPromptProgram]:
        return self._release_command(
            project_id=project_id,
            program_id=program_id,
            release_id=release_id,
            operation=lambda application: application.freeze_release(
                principal,
                project_id=project_id,
                release_id=release_id,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
            ),
        )

    def retire_release(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
        release_id: UUID,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[TransitionedPromptProgram]:
        return self._release_command(
            project_id=project_id,
            program_id=program_id,
            release_id=release_id,
            operation=lambda application: application.retire_release(
                principal,
                project_id=project_id,
                release_id=release_id,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
            ),
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
        return self._command(
            project_id,
            lambda application: application.diff_release(
                principal,
                project_id=project_id,
                program_id=program_id,
                candidate_release_id=candidate_release_id,
                baseline_release_id=baseline_release_id,
                fixed_variables=fixed_variables,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
            ),
        )

    def bind_release(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
        release_id: UUID,
        purpose: str,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[BoundPromptProgram]:
        return self._release_command(
            project_id=project_id,
            program_id=program_id,
            release_id=release_id,
            operation=lambda application: application.bind_release(
                principal,
                project_id=project_id,
                release_id=release_id,
                purpose=purpose,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
            ),
        )

    def _command(
        self,
        project_id: UUID,
        operation: Callable[[PromptProgramApplication], _ResultT],
    ) -> _ResultT:
        with self._uow_factory(project_id) as unit_of_work:
            result = operation(
                PromptProgramApplication(
                    unit_of_work.prompts,
                    test_evidence_verifier=self._test_evidence_verifier,
                )
            )
            unit_of_work.commit()
            return result

    def _release_command(
        self,
        *,
        project_id: UUID,
        program_id: UUID,
        release_id: UUID,
        operation: Callable[[PromptProgramApplication], _ResultT],
    ) -> _ResultT:
        with self._uow_factory(project_id) as unit_of_work:
            _required_release(
                unit_of_work.prompts,
                project_id=project_id,
                program_id=program_id,
                release_id=release_id,
            )
            result = operation(
                PromptProgramApplication(
                    unit_of_work.prompts,
                    test_evidence_verifier=self._test_evidence_verifier,
                )
            )
            unit_of_work.commit()
            return result


def build_prompt_program_api(
    *,
    database_url: str,
    runtime_selector: PromptTestRuntimeSelector | None = None,
    test_object_store: PromptTestObjectStore | None = None,
    connect_timeout: int = 5,
) -> PsycopgPromptProgramApi:
    normalized_url = database_url.strip()
    if not normalized_url:
        raise ValueError("database_url is required")

    def connect() -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(normalized_url, connect_timeout=connect_timeout)

    if (runtime_selector is None) != (test_object_store is None):
        raise ValueError(
            "Prompt test runtime selector and object store must be configured together"
        )
    test_application = (
        PromptTestApplication(
            uow_factory=prompt_test_uow_factory(normalized_url),
            runtime_selector=runtime_selector,
        )
        if runtime_selector is not None
        else None
    )
    verifier = (
        S3PromptTestEvidenceVerifier(test_object_store)
        if test_object_store is not None
        else None
    )
    return PsycopgPromptProgramApi(
        prompt_program_uow_factory(connect),
        test_application=test_application,
        test_runtime_selector=runtime_selector,
        test_evidence_verifier=verifier,
    )


def _required_program(
    repository: PromptProgramRepository,
    project_id: UUID,
    program_id: UUID,
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


def _require_read_role(principal: AccessPrincipal, project_id: UUID) -> None:
    membership = next(
        (
            item
            for item in principal.memberships
            if item.project_id == project_id and item.tenant_id == principal.tenant_id
        ),
        None,
    )
    if membership is None:
        raise PromptProgramNotFound(
            "The project does not exist in the authenticated Prompt Program scope."
        )
    if membership.role not in _READ_ROLES:
        raise PromptProgramForbidden(
            "The project role cannot read this Prompt Program resource."
        )


__all__ = ["PsycopgPromptProgramApi", "build_prompt_program_api"]
