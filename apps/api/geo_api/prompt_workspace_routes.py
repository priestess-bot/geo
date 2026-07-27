"""Working-draft routes for the operator-focused Prompt workspace."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, status

from geo_api.catalog_routes import _principal
from geo_api.prompt_program_contracts import (
    PromptFlowPage,
    PromptRenderPreviewRequest,
    PromptRenderPreviewResponse,
    PromptTestRunPage,
    PromptWorkingDraftResponse,
    PromptWorkingDraftSuiteResponse,
    PublishPromptWorkingDraftRequest,
    PublishedPromptWorkingDraftResponse,
    RunPromptWorkingDraftSuiteRequest,
    SavePromptWorkingDraftRequest,
)
from geo_api.prompt_program_presenters import (
    present_binding_option as _binding_option,
    present_flow as _flow,
    present_release as _release,
    present_render_preview as _render_preview,
    present_test_job as _test_job,
    present_test_run as _test_run,
    present_working_draft as _working_draft,
)
from geo_api.prompt_program_runtime import PromptProgramApi


AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]
IdempotencyHeader = Annotated[
    str, Header(alias="Idempotency-Key", min_length=1, max_length=200)
]
ApiGetter = Callable[[Request], PromptProgramApi]
OperationCall = Callable[[Any], Any]


def register_prompt_workspace_routes(
    router: APIRouter,
    *,
    api: ApiGetter,
    call: OperationCall,
) -> None:
    @router.get(
        "/prompt-flows",
        response_model=PromptFlowPage,
        operation_id="listPromptFlows",
    )
    def list_prompt_flows(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> PromptFlowPage:
        items = call(
            lambda: api(request).list_flow_workspace(
                _principal(request, authorization), project_id=project_id
            )
        )
        return PromptFlowPage(items=[_flow(item) for item in items], total=len(items))

    @router.get(
        "/prompt-programs/{program_id}/draft",
        response_model=PromptWorkingDraftResponse,
        operation_id="getPromptWorkingDraft",
    )
    def get_working_draft(
        project_id: UUID,
        program_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> PromptWorkingDraftResponse:
        result = call(
            lambda: api(request).get_working_draft(
                _principal(request, authorization),
                project_id=project_id,
                program_id=program_id,
            )
        )
        return _working_draft(result)

    @router.put(
        "/prompt-programs/{program_id}/draft",
        response_model=PromptWorkingDraftResponse,
        operation_id="savePromptWorkingDraft",
    )
    def save_working_draft(
        project_id: UUID,
        program_id: UUID,
        payload: SavePromptWorkingDraftRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> PromptWorkingDraftResponse:
        result = call(
            lambda: api(request).save_working_draft(
                _principal(request, authorization),
                project_id=project_id,
                program_id=program_id,
                display_name=payload.display_name,
                system_template=payload.system_template,
                user_template=payload.user_template,
                expected_revision=payload.expected_revision,
            )
        )
        return _working_draft(result)

    @router.post(
        "/prompt-programs/{program_id}/render-preview",
        response_model=PromptRenderPreviewResponse,
        operation_id="renderPromptWorkingDraft",
    )
    def render_working_draft(
        project_id: UUID,
        program_id: UUID,
        payload: PromptRenderPreviewRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> PromptRenderPreviewResponse:
        result = call(
            lambda: api(request).render_working_draft(
                _principal(request, authorization),
                project_id=project_id,
                program_id=program_id,
                fixture_id=payload.fixture_id,
            )
        )
        return _render_preview(result)

    @router.post(
        "/prompt-programs/{program_id}/suite-runs",
        response_model=PromptWorkingDraftSuiteResponse,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="runPromptWorkingDraftSuite",
    )
    def run_working_draft_suite(
        project_id: UUID,
        program_id: UUID,
        payload: RunPromptWorkingDraftSuiteRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> PromptWorkingDraftSuiteResponse:
        result = call(
            lambda: api(request).enqueue_working_draft_suite(
                _principal(request, authorization),
                project_id=project_id,
                program_id=program_id,
                runtime_selection_id=payload.runtime_selection_id,
                expected_revision=payload.expected_revision,
                idempotency_key=idempotency_key,
            )
        )
        return PromptWorkingDraftSuiteResponse(
            draft=_working_draft(result.draft),
            candidate_release=_release(result.candidate_release, result.candidate_state),
            job=_test_job(result.job),
        )

    @router.get(
        "/prompt-programs/{program_id}/test-runs",
        response_model=PromptTestRunPage,
        operation_id="listPromptWorkingDraftTests",
    )
    def list_working_draft_tests(
        project_id: UUID,
        program_id: UUID,
        request: Request,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        authorization: AuthorizationHeader = None,
    ) -> PromptTestRunPage:
        items = call(
            lambda: api(request).list_working_draft_tests(
                _principal(request, authorization),
                project_id=project_id,
                program_id=program_id,
                limit=limit,
            )
        )
        return PromptTestRunPage(items=[_test_run(item) for item in items], total=len(items))

    @router.post(
        "/prompt-programs/{program_id}/publish",
        response_model=PublishedPromptWorkingDraftResponse,
        operation_id="publishPromptWorkingDraft",
    )
    def publish_working_draft(
        project_id: UUID,
        program_id: UUID,
        payload: PublishPromptWorkingDraftRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> PublishedPromptWorkingDraftResponse:
        result = call(
            lambda: api(request).publish_working_draft(
                _principal(request, authorization),
                project_id=project_id,
                program_id=program_id,
                expected_revision=payload.expected_revision,
                idempotency_key=idempotency_key,
            )
        )
        return PublishedPromptWorkingDraftResponse(
            draft=_working_draft(result.draft),
            release=_release(result.release, result.state),
            binding=_binding_option(result.binding),
        )


__all__ = ["register_prompt_workspace_routes"]
