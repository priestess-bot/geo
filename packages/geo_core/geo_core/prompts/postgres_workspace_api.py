"""Operator Prompt workspace use cases for the PostgreSQL API facade."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import json
from uuid import UUID, uuid5

from geo_core.access.models import AccessPrincipal
from geo_core.prompts.application import (
    PromptProgramApplication,
    PromptProgramNotFound,
    PromptProgramRuntimeBlocked,
)
from geo_core.prompts.application_access import (
    APPROVER_ROLES,
    CONTRIBUTOR_ROLES,
    require_project_role,
)
from geo_core.prompts.bootstrap_catalog import default_prompt_bootstrap_spec
from geo_core.prompts.ports import PromptProgramVersionConflict
from geo_core.prompts.postgres_api_support import (
    child_key,
    required_program,
    require_read_role,
)
from geo_core.prompts.postgres_uow import PsycopgPromptProgramUnitOfWork
from geo_core.prompts.program import (
    ProgramReleaseStatus,
    PromptProgramRelease,
    render_program_release,
)
from geo_core.prompts.program_contracts import _canonical_value
from geo_core.prompts.test_execution_application import PromptTestApplication
from geo_core.prompts.test_execution_contracts import (
    PromptTestEvidenceVerifier,
    PromptTestRouteRequest,
)
from geo_core.prompts.workspace import (
    PromptFlowWorkspaceItem,
    PromptRenderPreview,
    PromptSuiteRunReceipt,
    PromptTestRunSummary,
    PromptWorkingDraft,
    PublishedPromptDraft,
    default_prompt_flow_definitions,
    workspace_schema_contract,
)


class PromptWorkspaceApiMixin:
    _uow_factory: Callable[[UUID], PsycopgPromptProgramUnitOfWork]
    _test_application: PromptTestApplication | None
    _test_evidence_verifier: PromptTestEvidenceVerifier | None

    def list_flow_workspace(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
    ) -> tuple[PromptFlowWorkspaceItem, ...]:
        require_read_role(principal, project_id)
        with self._uow_factory(project_id) as unit_of_work:
            repository = unit_of_work.prompts
            programs = repository.list_programs(
                project_id=project_id, limit=200, offset=0
            ).items
            by_purpose = {item.purpose: item for item in programs}
            items: list[PromptFlowWorkspaceItem] = []
            for definition in default_prompt_flow_definitions():
                program = by_purpose.get(definition.purpose)
                if program is None:
                    items.append(
                        PromptFlowWorkspaceItem(
                            definition=definition,
                            program=None,
                            draft=None,
                            latest_release=None,
                            current_release_id=None,
                            current_release_version=None,
                            candidate_status=None,
                            latest_test_job_id=None,
                            latest_test_status=None,
                            latest_test_score=None,
                        )
                    )
                    continue
                releases = repository.list_releases(
                    project_id=project_id,
                    program_id=program.id,
                    limit=1,
                    offset=0,
                ).items
                latest = releases[0].release if releases else None
                draft = repository.get_working_draft(
                    project_id=project_id, program_id=program.id
                )
                binding = repository.get_current_binding(
                    project_id=project_id, purpose=program.purpose
                )
                candidate_status = None
                if draft is not None and draft.candidate_release_id is not None:
                    state = repository.get_current_release_state(
                        project_id=project_id,
                        release_id=draft.candidate_release_id,
                    )
                    candidate_status = state.status.value if state is not None else None
                runs = repository.list_prompt_test_runs(
                    project_id=project_id, program_id=program.id, limit=1
                )
                latest_run = runs[0] if runs else None
                items.append(
                    PromptFlowWorkspaceItem(
                        definition=definition,
                        program=program,
                        draft=draft,
                        latest_release=latest,
                        current_release_id=binding.release_id if binding else None,
                        current_release_version=(
                            binding.release_version if binding else None
                        ),
                        candidate_status=candidate_status,
                        latest_test_job_id=latest_run.job_id if latest_run else None,
                        latest_test_status=latest_run.status if latest_run else None,
                        latest_test_score=latest_run.score if latest_run else None,
                    )
                )
            return tuple(items)

    def get_working_draft(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
    ) -> PromptWorkingDraft:
        require_read_role(principal, project_id)
        with self._uow_factory(project_id) as unit_of_work:
            required_program(unit_of_work.prompts, project_id, program_id)
            draft = unit_of_work.prompts.get_working_draft(
                project_id=project_id, program_id=program_id
            )
            if draft is None:
                raise PromptProgramNotFound("The Prompt working draft does not exist.")
            return draft

    def save_working_draft(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
        display_name: str,
        system_template: str,
        user_template: str,
        expected_revision: int,
    ) -> PromptWorkingDraft:
        require_project_role(principal, project_id, allowed=CONTRIBUTOR_ROLES)
        with self._uow_factory(project_id) as unit_of_work:
            required_program(unit_of_work.prompts, project_id, program_id)
            draft = unit_of_work.prompts.save_working_draft(
                project_id=project_id,
                program_id=program_id,
                display_name=display_name,
                system_template=system_template,
                user_template=user_template,
                expected_revision=expected_revision,
                updated_by=principal.identity_id,
                updated_at=datetime.now(UTC),
            )
            unit_of_work.commit()
            return draft

    def render_working_draft(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
        fixture_id: str | None,
    ) -> PromptRenderPreview:
        require_read_role(principal, project_id)
        with self._uow_factory(project_id) as unit_of_work:
            repository = unit_of_work.prompts
            program = required_program(repository, project_id, program_id)
            draft = repository.get_working_draft(
                project_id=project_id, program_id=program_id
            )
            if draft is None:
                raise PromptProgramNotFound("The Prompt working draft does not exist.")
            releases = repository.list_releases(
                project_id=project_id, program_id=program_id, limit=1, offset=0
            ).items
            if not releases:
                raise PromptProgramNotFound("The Prompt Program has no Release.")
            latest = releases[0].release
            spec = default_prompt_bootstrap_spec(program.program_kind)
            fixture = next(
                (item for item in spec.fixtures if item.fixture_id == fixture_id),
                spec.fixtures[0] if fixture_id is None else None,
            )
            if fixture is None:
                raise PromptProgramNotFound("The Prompt preview fixture does not exist.")
            preview_release = PromptProgramRelease.compile(
                id=uuid5(program.id, f"workspace-preview:{draft.draft_hash}"),
                program=program,
                version=latest.version + 1,
                system_template=draft.system_template,
                user_template=draft.user_template,
                schemas=workspace_schema_contract(latest),
                model_policy=latest.model_policy,
                test_set_id=latest.test_set_id,
                test_set_version=latest.test_set_version,
                test_set_hash=latest.test_set_hash,
                compiler_version=latest.compiler_version,
            )
            request_json = json.dumps(
                _canonical_value(fixture.input_value),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            binding = repository.get_current_binding(
                project_id=project_id, purpose=program.purpose
            )
            current_release = (
                repository.get_release(
                    project_id=project_id, release_id=binding.release_id
                )
                if binding is not None
                else repository.get_release(
                    project_id=project_id, release_id=draft.base_release_id
                )
            )
            return PromptRenderPreview(
                fixture_id=fixture.fixture_id,
                fixture_label=fixture.description,
                input_value=fixture.input_value,
                draft=render_program_release(
                    release=preview_release,
                    variables={"request_json": request_json},
                ),
                current=(
                    render_program_release(
                        release=current_release,
                        variables={"request_json": request_json},
                    )
                    if current_release is not None
                    else None
                ),
                current_release_version=(
                    current_release.version if current_release is not None else None
                ),
            )

    def enqueue_working_draft_suite(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
        runtime_selection_id: UUID,
        expected_revision: int,
        idempotency_key: str,
    ) -> PromptSuiteRunReceipt:
        require_project_role(principal, project_id, allowed=CONTRIBUTOR_ROLES)
        if self._test_application is None:
            raise PromptProgramRuntimeBlocked(
                "Prompt test execution requires a durable Model Gateway runtime"
            )
        with self._uow_factory(project_id) as unit_of_work:
            repository = unit_of_work.prompts
            required_program(repository, project_id, program_id)
            draft = repository.get_working_draft(
                project_id=project_id, program_id=program_id
            )
            if draft is None or draft.revision != expected_revision:
                raise PromptProgramVersionConflict(
                    "Prompt working draft changed before testing"
                )
            candidate = (
                repository.get_release(
                    project_id=project_id, release_id=draft.candidate_release_id
                )
                if draft.candidate_release_id is not None
                else None
            )
            state = (
                repository.get_current_release_state(
                    project_id=project_id, release_id=candidate.id
                )
                if candidate is not None
                else None
            )
            if candidate is not None and (
                candidate.program_id != program_id
                or candidate.system_template != draft.system_template
                or candidate.user_template != draft.user_template
            ):
                candidate = None
                state = None
            if state is not None and state.status is ProgramReleaseStatus.TESTED:
                raise PromptProgramRuntimeBlocked(
                    "This exact Prompt draft already passed its fixed suite and can be published."
                )
            if candidate is None or state is None:
                releases = repository.list_releases(
                    project_id=project_id, program_id=program_id, limit=1, offset=0
                ).items
                if not releases:
                    raise PromptProgramNotFound("The Prompt Program has no Release.")
                latest = releases[0].release
                created = PromptProgramApplication(
                    repository,
                    test_evidence_verifier=self._test_evidence_verifier,
                ).create_release(
                    principal,
                    project_id=project_id,
                    program_id=program_id,
                    system_template=draft.system_template,
                    user_template=draft.user_template,
                    schemas=workspace_schema_contract(latest),
                    model_policy=latest.model_policy,
                    test_set_id=latest.test_set_id,
                    test_set_version=latest.test_set_version,
                    test_set_hash=latest.test_set_hash,
                    compiler_version=latest.compiler_version,
                    expected_version=latest.version,
                    idempotency_key=child_key(idempotency_key, "candidate"),
                ).value
                candidate = created.release
                state = created.state
                draft = repository.set_working_draft_candidate(
                    project_id=project_id,
                    program_id=program_id,
                    expected_revision=expected_revision,
                    candidate_release_id=candidate.id,
                    updated_by=principal.identity_id,
                    updated_at=datetime.now(UTC),
                )
            unit_of_work.commit()
        job = self._test_application.enqueue(
            principal,
            project_id=project_id,
            program_id=program_id,
            release_id=candidate.id,
            test_set_id=candidate.test_set_id,
            test_set_version=candidate.test_set_version,
            test_set_hash=candidate.test_set_hash,
            route=PromptTestRouteRequest(runtime_selection_id=runtime_selection_id),
            expected_version=state.version,
            idempotency_key=child_key(idempotency_key, "suite"),
        )
        return PromptSuiteRunReceipt(draft, candidate, state, job)

    def list_working_draft_tests(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
        limit: int,
    ) -> tuple[PromptTestRunSummary, ...]:
        require_read_role(principal, project_id)
        with self._uow_factory(project_id) as unit_of_work:
            required_program(unit_of_work.prompts, project_id, program_id)
            return unit_of_work.prompts.list_prompt_test_runs(
                project_id=project_id, program_id=program_id, limit=limit
            )

    def publish_working_draft(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
        expected_revision: int,
        idempotency_key: str,
    ) -> PublishedPromptDraft:
        require_project_role(principal, project_id, allowed=APPROVER_ROLES)
        with self._uow_factory(project_id) as unit_of_work:
            repository = unit_of_work.prompts
            program = required_program(repository, project_id, program_id)
            draft = repository.get_working_draft(
                project_id=project_id, program_id=program_id
            )
            if (
                draft is not None
                and draft.revision == expected_revision
                and draft.candidate_release_id is None
            ):
                current = repository.get_current_binding(
                    project_id=project_id, purpose=program.purpose
                )
                published_release = (
                    repository.get_release(
                        project_id=project_id, release_id=current.release_id
                    )
                    if current is not None
                    else None
                )
                published_state = (
                    repository.get_current_release_state(
                        project_id=project_id, release_id=current.release_id
                    )
                    if current is not None
                    else None
                )
                if (
                    current is not None
                    and published_release is not None
                    and published_state is not None
                    and draft.base_release_id == current.release_id
                    and published_release.program_id == program_id
                    and published_release.system_template == draft.system_template
                    and published_release.user_template == draft.user_template
                    and published_state.status is ProgramReleaseStatus.FROZEN
                ):
                    return PublishedPromptDraft(
                        draft=draft,
                        release=published_release,
                        state=published_state,
                        binding=current,
                    )
            if (
                draft is None
                or draft.revision != expected_revision
                or draft.candidate_release_id is None
            ):
                raise PromptProgramVersionConflict(
                    "Prompt draft changed or has no tested candidate"
                )
            candidate = repository.get_release(
                project_id=project_id, release_id=draft.candidate_release_id
            )
            state = repository.get_current_release_state(
                project_id=project_id, release_id=draft.candidate_release_id
            )
            if (
                candidate is None
                or state is None
                or candidate.program_id != program_id
                or candidate.system_template != draft.system_template
                or candidate.user_template != draft.user_template
                or state.status is not ProgramReleaseStatus.TESTED
            ):
                raise PromptProgramRuntimeBlocked(
                    "Publishing requires the exact current draft to pass its fixed suite."
                )
            application = PromptProgramApplication(
                repository,
                test_evidence_verifier=self._test_evidence_verifier,
            )
            approved = application.approve_release(
                principal,
                project_id=project_id,
                release_id=candidate.id,
                expected_version=state.version,
                idempotency_key=child_key(idempotency_key, "approve"),
            ).value
            frozen = application.freeze_release(
                principal,
                project_id=project_id,
                release_id=candidate.id,
                expected_version=approved.state.version,
                idempotency_key=child_key(idempotency_key, "freeze"),
            ).value
            current = repository.get_current_binding(
                project_id=project_id, purpose=program.purpose
            )
            bound = application.bind_release(
                principal,
                project_id=project_id,
                release_id=candidate.id,
                purpose=program.purpose,
                expected_version=current.binding_version if current else 0,
                idempotency_key=child_key(idempotency_key, "bind"),
            ).value
            draft = repository.mark_working_draft_published(
                project_id=project_id,
                program_id=program_id,
                expected_revision=expected_revision,
                release_id=candidate.id,
                updated_by=principal.identity_id,
                updated_at=datetime.now(UTC),
            )
            unit_of_work.commit()
            return PublishedPromptDraft(
                draft=draft,
                release=candidate,
                state=frozen.state,
                binding=bound.binding,
            )


__all__ = ["PromptWorkspaceApiMixin"]
