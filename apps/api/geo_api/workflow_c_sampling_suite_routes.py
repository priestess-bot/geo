"""Authoritative Sampling Suite inventory and Run-start routes."""

from uuid import UUID

from fastapi import APIRouter, Request, status

from geo_api.workflow_c_routes import (
    AuthorizationHeader,
    IdempotencyHeader,
    READ_ROLES,
    WRITE_ROLES,
    authorize_workflow_c,
    workflow_c_api,
    workflow_c_call,
)
from geo_api.workflow_c_sampling_contracts import (
    CreateSamplingSuiteRequest,
    SamplingRunDetailResponse,
    SamplingRunPageResponse,
    SamplingSuiteInputOptionPageResponse,
    SamplingSuitePageResponse,
    SamplingSuiteResponse,
    StartSamplingRunRequest,
)
from geo_api.workflow_c_sampling_presenters import (
    run_detail_response,
    run_page_response,
    suite_input_option_page_response,
    suite_page_response,
    suite_response,
)


def workflow_c_sampling_suite_router() -> APIRouter:
    router = APIRouter()

    @router.get(
        "/suite-input-options",
        response_model=SamplingSuiteInputOptionPageResponse,
        operation_id="listSamplingSuiteInputOptions",
    )
    def list_suite_input_options(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> SamplingSuiteInputOptionPageResponse:
        authorize_workflow_c(request, authorization, project_id, READ_ROLES)
        items = workflow_c_call(
            lambda: workflow_c_api(request).sampling.suite_inputs.list(
                project_id=project_id
            )
        )
        return suite_input_option_page_response(items)

    @router.get(
        "/suites",
        response_model=SamplingSuitePageResponse,
        operation_id="listSamplingSuites",
    )
    def list_suites(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> SamplingSuitePageResponse:
        authorize_workflow_c(request, authorization, project_id, READ_ROLES)
        items = workflow_c_call(
            lambda: workflow_c_api(request).sampling.list_suites(project_id=project_id)
        )
        return suite_page_response(items)

    @router.post(
        "/suites",
        response_model=SamplingSuiteResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createSamplingSuite",
    )
    def create_suite(
        project_id: UUID,
        payload: CreateSamplingSuiteRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> SamplingSuiteResponse:
        principal = authorize_workflow_c(request, authorization, project_id, WRITE_ROLES)
        item = workflow_c_call(
            lambda: workflow_c_api(request).sampling.create_suite(
                project_id=project_id,
                actor_id=principal.actor_id,
                idempotency_key=idempotency_key,
                payload=payload,
            )
        )
        return suite_response(item)

    @router.get(
        "/suites/{suite_id}",
        response_model=SamplingSuiteResponse,
        operation_id="getSamplingSuite",
    )
    def get_suite(
        project_id: UUID,
        suite_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> SamplingSuiteResponse:
        authorize_workflow_c(request, authorization, project_id, READ_ROLES)
        item = workflow_c_call(
            lambda: workflow_c_api(request).sampling.get_suite(
                project_id=project_id,
                suite_id=suite_id,
            )
        )
        return suite_response(item)

    @router.post(
        "/suites/{suite_id}/runs",
        response_model=SamplingRunDetailResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="startSamplingRun",
    )
    def start_run(
        project_id: UUID,
        suite_id: UUID,
        payload: StartSamplingRunRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> SamplingRunDetailResponse:
        authorize_workflow_c(request, authorization, project_id, WRITE_ROLES)
        run, _ = workflow_c_call(
            lambda: workflow_c_api(request).sampling.start_run(
                project_id=project_id,
                suite_id=suite_id,
                idempotency_key=idempotency_key,
                payload=payload,
            )
        )
        view = workflow_c_call(
            lambda: workflow_c_api(request).sampling.get_run_view(
                project_id=project_id,
                run_id=run.id,
            )
        )
        return run_detail_response(
            suite=view.suite,
            run=view.run,
            tasks=view.tasks,
            attempts=view.attempts,
            observations=view.observations,
            assessment=view.assessment,
        )

    @router.get(
        "/runs",
        response_model=SamplingRunPageResponse,
        operation_id="listSamplingRuns",
    )
    def list_runs(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> SamplingRunPageResponse:
        authorize_workflow_c(request, authorization, project_id, READ_ROLES)
        items = workflow_c_call(
            lambda: workflow_c_api(request).sampling.list_runs(project_id=project_id)
        )
        return run_page_response(items)

    return router
