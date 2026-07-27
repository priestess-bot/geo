"""Admission service for durable, server-evaluated Prompt Program tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4, uuid5

from geo_core.access.models import AccessPrincipal
from geo_core.prompts.application_access import CONTRIBUTOR_ROLES, require_project_role
from geo_core.prompts.application_models import PromptProgramNotFound
from geo_core.prompts.application_support import (
    idempotency_key_hash,
    require_expected_version,
)
from geo_core.prompts.bootstrap_catalog import (
    default_prompt_bootstrap_spec,
    prompt_bootstrap_catalog_hash,
)
from geo_core.prompts.bootstrap_contracts import BOOTSTRAP_TEST_SET_VERSION
from geo_core.prompts.bootstrap_contracts import PromptBootstrapSpec
from geo_core.prompts.program import (
    ProgramReleaseStatus,
    PromptProgramRelease,
    PromptProgramRuleViolation,
)
from geo_core.prompts.workspace import workspace_schema_contract
from geo_core.prompts.test_execution_contracts import (
    PromptTestExecutionError,
    PromptTestJobReceipt,
    PromptTestRouteRequest,
    PromptTestRunTask,
    PromptTestRuntimeSelector,
    PromptTestUnitOfWorkFactory,
)


class PromptTestApplication:
    """Freeze exact test inputs and atomically enqueue one durable execution."""

    def __init__(
        self,
        *,
        uow_factory: PromptTestUnitOfWorkFactory,
        runtime_selector: PromptTestRuntimeSelector,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory = uow_factory
        self._runtime_selector = runtime_selector
        self._id_factory = id_factory
        self._clock = clock

    def enqueue(
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
        require_project_role(principal, project_id, allowed=CONTRIBUTOR_ROLES)
        key_hash = idempotency_key_hash(idempotency_key)
        with self._uow_factory(project_id=project_id) as uow:
            release = uow.prompts.get_release(
                project_id=project_id,
                release_id=release_id,
            )
            state = uow.prompts.get_current_release_state(
                project_id=project_id,
                release_id=release_id,
            )
            if release is None or state is None or release.program_id != program_id:
                raise PromptProgramNotFound("The Prompt Program Release does not exist.")
            require_expected_version(state, expected_version)
            if state.status is not ProgramReleaseStatus.DRAFT:
                raise PromptProgramRuleViolation(
                    "Prompt Program tests can only be enqueued for the current draft state"
                )
            spec = _exact_test_spec(
                release=release,
                test_set_id=test_set_id,
                test_set_version=test_set_version,
                test_set_hash=test_set_hash,
            )
            model = self._runtime_selector.select(
                project_id=project_id,
                request=route,
            )
            if model.provider_secret_handle.project_id != project_id:
                raise PromptTestExecutionError(
                    "Prompt test Model runtime belongs to another Project"
                )
            task = PromptTestRunTask(
                project_id=project_id,
                job_id=uuid5(project_id, f"prompt-test-job:{key_hash}"),
                program_id=program_id,
                release_id=release.id,
                release_version=release.version,
                release_hash=release.release_hash,
                expected_state_id=state.id,
                expected_state_version=state.version,
                requested_by=principal.identity_id,
                requested_at=self._clock(),
                test_spec=spec,
                catalog_hash=prompt_bootstrap_catalog_hash(),
                model=model,
            )
            stored = uow.test_runs.enqueue(
                task=task,
                idempotency_key_hash=key_hash,
                outbox_id=self._id_factory(),
            )
            uow.commit()
        return PromptTestJobReceipt(stored.job, stored.replayed)


def _exact_test_spec(
    *,
    release: PromptProgramRelease,
    test_set_id: UUID,
    test_set_version: int,
    test_set_hash: str,
) -> PromptBootstrapSpec:
    spec = default_prompt_bootstrap_spec(release.program_kind)
    workspace_schema = workspace_schema_contract(release)
    legacy_workspace_schema = workspace_schema_contract(
        release, require_context_slots=False
    )
    immutable_schema_matches = (
        release.schemas.input_schema_version == spec.schemas.input_schema_version
        and release.schemas.input_schema == spec.schemas.input_schema
        and release.schemas.output_schema_version == spec.schemas.output_schema_version
        and release.schemas.output_schema == spec.schemas.output_schema
        and (
            release.schemas.application_output_schema_version
            == spec.schemas.application_output_schema_version
        )
        and (
            release.schemas.application_output_schema
            == spec.schemas.application_output_schema
        )
    )
    variable_schema_matches = (
        (
            release.schemas.variable_schema_version
            == spec.schemas.variable_schema_version
            and release.schemas.variable_schema == spec.schemas.variable_schema
        )
        or (
            release.schemas.variable_schema_version
            == workspace_schema.variable_schema_version
            and release.schemas.variable_schema in (
                workspace_schema.variable_schema,
                legacy_workspace_schema.variable_schema,
            )
        )
    )
    if (
        release.purpose != spec.purpose
        or release.test_set_id != spec.test_set_id
        or release.test_set_version != BOOTSTRAP_TEST_SET_VERSION
        or release.test_set_hash != spec.test_set_hash
        or not immutable_schema_matches
        or not variable_schema_matches
        or test_set_id != release.test_set_id
        or test_set_version != release.test_set_version
        or test_set_hash != release.test_set_hash
    ):
        raise PromptTestExecutionError(
            "Prompt test selector does not resolve the Release's immutable TestSet"
        )
    return spec


__all__ = ["PromptTestApplication"]
