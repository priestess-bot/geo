"""Internal-only project-scoped routes for governed Prompt Programs."""

from __future__ import annotations

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, status

from geo_api.catalog_routes import _principal
from geo_api.foundation_services import FoundationServiceUnavailable
from geo_api.problems import ApiProblem
from geo_api.prompt_program_contracts import (
    BindPromptProgramReleaseRequest,
    CreatedPromptProgramReleaseResponse,
    CreatedPromptProgramResponse,
    CreatePromptProgramRequest,
    CreatePromptProgramReleaseRequest,
    DiffPromptProgramReleaseRequest,
    ProgramKindValue,
    PromptProgramBindingResponse,
    PromptProgramBindingOptionPage,
    PromptProgramDiffResponse,
    PromptProgramPage,
    PromptProgramReleasePage,
    PromptProgramReleaseDetailResponse,
    PromptProgramSummaryResponse,
    PromptTestJobResponse,
    PromptTestRuntimeOptionPage,
    TestPromptProgramReleaseRequest,
    TransitionedPromptProgramResponse,
    TransitionPromptProgramReleaseRequest,
)
from geo_api.prompt_program_presenters import (
    present_binding as _binding,
    present_binding_option as _binding_option,
    present_created as _created,
    present_diff as _diff,
    present_program as _program,
    present_release as _release,
    present_release_detail as _release_detail,
    present_test_job as _test_job,
    present_test_runtime as _test_runtime,
    present_transitioned as _transitioned,
)
from geo_api.prompt_program_runtime import PromptProgramApi
from geo_api.prompt_workspace_routes import register_prompt_workspace_routes
from geo_api.stable_routes import PROBLEM_RESPONSES
from geo_core.prompts.application import (
    PromptProgramApplicationError,
    PromptProgramForbidden,
    PromptProgramNotFound,
    PromptProgramRuntimeBlocked,
)
from geo_core.prompts.ports import (
    PromptProgramIdempotencyConflict,
    PromptProgramPersistenceError,
    PromptProgramVersionConflict,
)
from geo_core.prompts.program import (
    ModelPolicySnapshot,
    ProgramKind,
    ProgramSchemaContract,
    PromptProgramRuleViolation,
)
from geo_core.prompts.test_execution_contracts import (
    PromptTestExecutionError,
    PromptTestRouteRequest,
)


AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]
IdempotencyHeader = Annotated[
    str, Header(alias="Idempotency-Key", min_length=1, max_length=200)
]


def prompt_program_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}",
        tags=["prompt programs"],
        responses=PROBLEM_RESPONSES,
    )

    @router.post(
        "/prompt-programs",
        response_model=CreatedPromptProgramResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createPromptProgram",
    )
    def create_program(
        project_id: UUID,
        payload: CreatePromptProgramRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> CreatedPromptProgramResponse:
        schemas = payload.schemas
        policy = payload.model_policy
        result = _call(
            lambda: _api(request).create_program(
                _principal(request, authorization),
                project_id=project_id,
                program_kind=ProgramKind(payload.program_kind),
                purpose=payload.purpose,
                system_template=payload.system_template,
                user_template=payload.user_template,
                schemas=ProgramSchemaContract(
                    variable_schema_version=schemas.variable_schema_version,
                    variable_schema=schemas.variable_schema,
                    input_schema_version=schemas.input_schema_version,
                    input_schema=schemas.input_schema,
                    output_schema_version=schemas.output_schema_version,
                    output_schema=schemas.output_schema,
                    application_output_schema_version=(
                        schemas.application_output_schema_version
                    ),
                    application_output_schema=schemas.application_output_schema,
                ),
                model_policy=ModelPolicySnapshot(
                    version=policy.version, policy=policy.policy
                ),
                test_set_id=payload.test_set_id,
                test_set_version=payload.test_set_version,
                test_set_hash=payload.test_set_hash,
                compiler_version=payload.compiler_version,
                expected_version=payload.expected_version,
                idempotency_key=idempotency_key,
            )
        )
        return _created(result)

    register_prompt_workspace_routes(router, api=_api, call=_call)

    @router.get(
        "/prompt-programs",
        response_model=PromptProgramPage,
        operation_id="listPromptPrograms",
    )
    def list_programs(
        project_id: UUID,
        request: Request,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
        authorization: AuthorizationHeader = None,
    ) -> PromptProgramPage:
        result = _call(
            lambda: _api(request).list_programs(
                _principal(request, authorization),
                project_id=project_id,
                limit=limit,
                offset=offset,
            )
        )
        return PromptProgramPage(
            items=[_program(item) for item in result.items],
            total=result.total,
            limit=limit,
            offset=offset,
        )

    @router.get(
        "/prompt-program-test-options",
        response_model=PromptTestRuntimeOptionPage,
        operation_id="listPromptProgramTestRuntimes",
    )
    def list_test_runtimes(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> PromptTestRuntimeOptionPage:
        items = _call(
            lambda: _api(request).list_test_runtimes(
                _principal(request, authorization),
                project_id=project_id,
            )
        )
        return PromptTestRuntimeOptionPage(
            items=[_test_runtime(item) for item in items],
            total=len(items),
        )

    @router.get(
        "/prompt-programs/{program_id}",
        response_model=PromptProgramSummaryResponse,
        operation_id="getPromptProgram",
    )
    def get_program(
        project_id: UUID,
        program_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> PromptProgramSummaryResponse:
        result = _call(
            lambda: _api(request).get_program(
                _principal(request, authorization),
                project_id=project_id,
                program_id=program_id,
            )
        )
        return _program(result)

    @router.get(
        "/prompt-programs/{program_id}/releases",
        response_model=PromptProgramReleasePage,
        operation_id="listPromptProgramReleases",
    )
    def list_releases(
        project_id: UUID,
        program_id: UUID,
        request: Request,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
        authorization: AuthorizationHeader = None,
    ) -> PromptProgramReleasePage:
        result = _call(
            lambda: _api(request).list_releases(
                _principal(request, authorization),
                project_id=project_id,
                program_id=program_id,
                limit=limit,
                offset=offset,
            )
        )
        return PromptProgramReleasePage(
            items=[_release(item.release, item.state) for item in result.items],
            total=result.total,
            limit=limit,
            offset=offset,
        )

    @router.post(
        "/prompt-programs/{program_id}/releases",
        response_model=CreatedPromptProgramReleaseResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createPromptProgramRelease",
    )
    def create_release(
        project_id: UUID,
        program_id: UUID,
        payload: CreatePromptProgramReleaseRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> CreatedPromptProgramReleaseResponse:
        schemas = payload.schemas
        policy = payload.model_policy
        result = _call(
            lambda: _api(request).create_release(
                _principal(request, authorization),
                project_id=project_id,
                program_id=program_id,
                system_template=payload.system_template,
                user_template=payload.user_template,
                schemas=ProgramSchemaContract(
                    variable_schema_version=schemas.variable_schema_version,
                    variable_schema=schemas.variable_schema,
                    input_schema_version=schemas.input_schema_version,
                    input_schema=schemas.input_schema,
                    output_schema_version=schemas.output_schema_version,
                    output_schema=schemas.output_schema,
                    application_output_schema_version=(
                        schemas.application_output_schema_version
                    ),
                    application_output_schema=schemas.application_output_schema,
                ),
                model_policy=ModelPolicySnapshot(
                    version=policy.version, policy=policy.policy
                ),
                test_set_id=payload.test_set_id,
                test_set_version=payload.test_set_version,
                test_set_hash=payload.test_set_hash,
                compiler_version=payload.compiler_version,
                expected_version=payload.expected_version,
                idempotency_key=idempotency_key,
            )
        )
        value = result.value
        return CreatedPromptProgramReleaseResponse(
            release=_release(value.release, value.state), replayed=result.replayed
        )

    @router.get(
        "/prompt-programs/{program_id}/releases/{release_id}",
        response_model=PromptProgramReleaseDetailResponse,
        operation_id="getPromptProgramRelease",
    )
    def get_release(
        project_id: UUID,
        program_id: UUID,
        release_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> PromptProgramReleaseDetailResponse:
        result = _call(
            lambda: _api(request).get_release(
                _principal(request, authorization),
                project_id=project_id,
                program_id=program_id,
                release_id=release_id,
            )
        )
        return _release_detail(result.release, result.state)

    @router.post(
        "/prompt-programs/{program_id}/releases/{release_id}/tests",
        response_model=PromptTestJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="testPromptProgramRelease",
    )
    def test_release(
        project_id: UUID,
        program_id: UUID,
        release_id: UUID,
        payload: TestPromptProgramReleaseRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> PromptTestJobResponse:
        result = _call(
            lambda: _api(request).enqueue_test(
                _principal(request, authorization),
                project_id=project_id,
                program_id=program_id,
                release_id=release_id,
                test_set_id=payload.test_set_id,
                test_set_version=payload.test_set_version,
                test_set_hash=payload.test_set_hash,
                route=PromptTestRouteRequest(
                    runtime_selection_id=payload.runtime_selection_id,
                ),
                expected_version=payload.expected_version,
                idempotency_key=idempotency_key,
            )
        )
        return _test_job(result)

    @router.post(
        "/prompt-programs/{program_id}/releases/{release_id}/approve",
        response_model=TransitionedPromptProgramResponse,
        operation_id="approvePromptProgramRelease",
    )
    def approve_release(
        project_id: UUID,
        program_id: UUID,
        release_id: UUID,
        payload: TransitionPromptProgramReleaseRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> TransitionedPromptProgramResponse:
        result = _call(
            lambda: _api(request).approve_release(
                _principal(request, authorization),
                project_id=project_id,
                program_id=program_id,
                release_id=release_id,
                expected_version=payload.expected_version,
                idempotency_key=idempotency_key,
            )
        )
        return _transitioned(result)

    @router.post(
        "/prompt-programs/{program_id}/releases/{release_id}/freeze",
        response_model=TransitionedPromptProgramResponse,
        operation_id="freezePromptProgramRelease",
    )
    def freeze_release(
        project_id: UUID,
        program_id: UUID,
        release_id: UUID,
        payload: TransitionPromptProgramReleaseRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> TransitionedPromptProgramResponse:
        result = _call(
            lambda: _api(request).freeze_release(
                _principal(request, authorization),
                project_id=project_id,
                program_id=program_id,
                release_id=release_id,
                expected_version=payload.expected_version,
                idempotency_key=idempotency_key,
            )
        )
        return _transitioned(result)

    @router.post(
        "/prompt-programs/{program_id}/releases/{release_id}/retire",
        response_model=TransitionedPromptProgramResponse,
        operation_id="retirePromptProgramRelease",
    )
    def retire_release(
        project_id: UUID,
        program_id: UUID,
        release_id: UUID,
        payload: TransitionPromptProgramReleaseRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> TransitionedPromptProgramResponse:
        result = _call(
            lambda: _api(request).retire_release(
                _principal(request, authorization),
                project_id=project_id,
                program_id=program_id,
                release_id=release_id,
                expected_version=payload.expected_version,
                idempotency_key=idempotency_key,
            )
        )
        return _transitioned(result)

    @router.post(
        "/prompt-programs/{program_id}/releases/{release_id}/diff",
        response_model=PromptProgramDiffResponse,
        operation_id="diffPromptProgramRelease",
    )
    def diff_release(
        project_id: UUID,
        program_id: UUID,
        release_id: UUID,
        payload: DiffPromptProgramReleaseRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> PromptProgramDiffResponse:
        result = _call(
            lambda: _api(request).diff_release(
                _principal(request, authorization),
                project_id=project_id,
                program_id=program_id,
                candidate_release_id=release_id,
                baseline_release_id=payload.baseline_release_id,
                fixed_variables=payload.fixed_variables,
                expected_version=payload.expected_version,
                idempotency_key=idempotency_key,
            )
        )
        return _diff(result)

    @router.get(
        "/prompt-program-bindings",
        response_model=PromptProgramBindingOptionPage,
        operation_id="listPromptProgramBindings",
    )
    def list_bindings(
        project_id: UUID,
        request: Request,
        program_kind: ProgramKindValue | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        authorization: AuthorizationHeader = None,
    ) -> PromptProgramBindingOptionPage:
        result = _call(
            lambda: _api(request).list_bindings(
                _principal(request, authorization),
                project_id=project_id,
                program_kind=ProgramKind(program_kind) if program_kind else None,
                limit=limit,
                offset=offset,
            )
        )
        return PromptProgramBindingOptionPage(
            items=[_binding_option(item) for item in result.items],
            total=result.total,
            limit=limit,
            offset=offset,
        )

    @router.post(
        "/prompt-program-bindings",
        response_model=PromptProgramBindingResponse,
        operation_id="bindPromptProgramRelease",
    )
    def bind_release(
        project_id: UUID,
        payload: BindPromptProgramReleaseRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> PromptProgramBindingResponse:
        result = _call(
            lambda: _api(request).bind_release(
                _principal(request, authorization),
                project_id=project_id,
                program_id=payload.program_id,
                release_id=payload.release_id,
                purpose=payload.purpose,
                expected_version=payload.expected_version,
                idempotency_key=idempotency_key,
            )
        )
        return _binding(result)

    return router


def _api(request: Request) -> PromptProgramApi:
    application = getattr(request.app.state, "prompt_program_application", None)
    if application is None:
        raise FoundationServiceUnavailable(
            "Prompt Program persistence is unavailable until its migration-backed adapter is installed."
        )
    return cast(PromptProgramApi, application)


def _call(operation: Any) -> Any:
    try:
        return operation()
    except PromptProgramRuleViolation as error:
        raise _problem(422, "Unprocessable Content", error, "rule-violation") from error
    except ValueError as error:
        raise _problem(422, "Unprocessable Content", error, "invalid-input") from error
    except PromptTestExecutionError as error:
        raise _problem(422, "Unprocessable Content", error, "test-contract") from error
    except PromptProgramForbidden as error:
        raise _problem(403, "Forbidden", error, "forbidden") from error
    except PromptProgramNotFound as error:
        raise _problem(404, "Not Found", error, "not-found") from error
    except (PromptProgramIdempotencyConflict, PromptProgramVersionConflict) as error:
        raise _problem(409, "Conflict", error, "conflict") from error
    except PromptProgramRuntimeBlocked as error:
        raise _problem(409, "Conflict", error, "runtime-blocked") from error
    except PromptProgramPersistenceError as error:
        raise _problem(503, "Service Unavailable", error, "persistence-unavailable") from error
    except PromptProgramApplicationError as error:
        raise _problem(503, "Service Unavailable", error, "application-unavailable") from error


def _problem(status_code: int, title: str, error: Exception, suffix: str) -> ApiProblem:
    return ApiProblem(
        status=status_code,
        title=title,
        detail=str(error),
        type_uri=f"urn:geo:problem:prompt-program-{suffix}",
        headers={"Retry-After": "30"} if status_code == 503 else None,
    )
