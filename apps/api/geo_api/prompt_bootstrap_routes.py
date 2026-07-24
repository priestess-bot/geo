"""Internal-only routes for governed Prompt bootstrap preview and draft creation."""

from __future__ import annotations

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Header, Request

from geo_api.catalog_routes import _principal
from geo_api.prompt_bootstrap_contracts import (
    BootstrapCaseEvaluationResponse,
    BootstrapCatalogPreviewResponse,
    BootstrapCreateDraftsRequest,
    BootstrapCreateDraftsResponse,
    BootstrapDraftFailureResponse,
    BootstrapDraftItemResponse,
    BootstrapEvaluationRequest,
    BootstrapEvaluationResponse,
    BootstrapFixturePreviewResponse,
    BootstrapKindPreviewResponse,
    BootstrapKindValue,
    BootstrapRubricCriterionResponse,
)
from geo_api.prompt_program_presenters import (
    present_program as _program,
    present_release as _release,
)
from geo_api.prompt_program_routes import _api, _call
from geo_api.stable_routes import PROBLEM_RESPONSES
from geo_core.prompts.bootstrap_catalog import (
    default_prompt_bootstrap_spec,
    prompt_bootstrap_catalog_hash,
)
from geo_core.prompts.bootstrap_contracts import (
    BOOTSTRAP_CATALOG_VERSION,
    BOOTSTRAP_TEST_SET_VERSION,
    PromptBootstrapSpec,
    thaw_mapping,
)
from geo_core.prompts.bootstrap_evaluation import PromptTestSetEvaluation
from geo_core.prompts.bootstrap_workflow import (
    BootstrapDraftBatch,
    BootstrapDraftFailure,
    BootstrapDraftReceipt,
    create_prompt_bootstrap_drafts,
    evaluate_prompt_bootstrap,
    preview_prompt_bootstrap,
)
from geo_core.prompts.program import ProgramKind


AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]
IdempotencyHeader = Annotated[
    str, Header(alias="Idempotency-Key", min_length=1, max_length=200)
]


def prompt_bootstrap_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/prompt-bootstrap",
        tags=["prompt bootstrap"],
        responses=PROBLEM_RESPONSES,
    )

    @router.get(
        "",
        response_model=BootstrapCatalogPreviewResponse,
        operation_id="previewPromptBootstrapCatalog",
    )
    def preview_catalog(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> BootstrapCatalogPreviewResponse:
        specs = _call(
            lambda: preview_prompt_bootstrap(
                _principal(request, authorization), project_id=project_id
            )
        )
        return _catalog_preview(specs)

    @router.post(
        "/evaluate",
        response_model=BootstrapEvaluationResponse,
        operation_id="evaluatePromptBootstrapOutputs",
    )
    def evaluate_outputs(
        project_id: UUID,
        payload: BootstrapEvaluationRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> BootstrapEvaluationResponse:
        kind = ProgramKind(payload.program_kind)
        result = _call(
            lambda: evaluate_prompt_bootstrap(
                _principal(request, authorization),
                project_id=project_id,
                program_kind=kind,
                catalog_hash=payload.catalog_hash,
                spec_hash=payload.spec_hash,
                test_set_hash=payload.test_set_hash,
                outputs=payload.outputs,
            )
        )
        return _evaluation(default_prompt_bootstrap_spec(kind), result)

    @router.post(
        "/drafts",
        response_model=BootstrapCreateDraftsResponse,
        operation_id="createPromptBootstrapDrafts",
    )
    def create_drafts(
        project_id: UUID,
        payload: BootstrapCreateDraftsRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> BootstrapCreateDraftsResponse:
        result = _call(
            lambda: create_prompt_bootstrap_drafts(
                _api(request),
                _principal(request, authorization),
                project_id=project_id,
                catalog_hash=payload.catalog_hash,
                idempotency_key=idempotency_key,
            )
        )
        return _draft_batch(result)

    return router


def _catalog_preview(
    specs: tuple[PromptBootstrapSpec, ...],
) -> BootstrapCatalogPreviewResponse:
    return BootstrapCatalogPreviewResponse(
        catalog_version=BOOTSTRAP_CATALOG_VERSION,
        catalog_hash=prompt_bootstrap_catalog_hash(),
        items=[_kind_preview(spec) for spec in specs],
    )


def _kind_preview(spec: PromptBootstrapSpec) -> BootstrapKindPreviewResponse:
    return BootstrapKindPreviewResponse(
        program_kind=cast(BootstrapKindValue, spec.program_kind.value),
        purpose=spec.purpose,
        spec_version=spec.spec_version,
        spec_hash=spec.spec_hash,
        test_set_id=spec.test_set_id,
        test_set_version=BOOTSTRAP_TEST_SET_VERSION,
        test_set_hash=spec.test_set_hash,
        variable_schema_version=spec.schemas.variable_schema_version,
        variable_schema=thaw_mapping(spec.schemas.variable_schema),
        input_schema_version=spec.schemas.input_schema_version,
        input_schema=thaw_mapping(spec.schemas.input_schema),
        output_schema_version=spec.schemas.output_schema_version,
        output_schema=thaw_mapping(spec.schemas.output_schema),
        output_schema_hash=spec.schemas.output_schema_hash,
        application_output_schema_version=(
            spec.schemas.application_output_schema_version
        ),
        application_output_schema=thaw_mapping(
            spec.schemas.application_output_schema
        ),
        application_output_schema_hash=(
            spec.schemas.application_output_schema_hash
        ),
        model_policy_version=spec.model_policy.version,
        model_policy=thaw_mapping(spec.model_policy.policy),
        model_policy_hash=spec.model_policy.policy_hash,
        application_rules=list(spec.application_rules),
        rubric=_rubric(spec),
        minimum_score=spec.minimum_score,
        fixtures=[
            BootstrapFixturePreviewResponse(
                fixture_id=fixture.fixture_id,
                scenario=cast(Any, fixture.scenario.value),
                description=fixture.description,
                input_value=thaw_mapping(fixture.input_value),
            )
            for fixture in spec.fixtures
        ],
    )


def _rubric(spec: PromptBootstrapSpec) -> list[BootstrapRubricCriterionResponse]:
    return [
        BootstrapRubricCriterionResponse(
            code=item.code,
            description=item.description,
            weight=item.weight,
            blocking=item.blocking,
        )
        for item in spec.rubric
    ]


def _evaluation(
    spec: PromptBootstrapSpec, result: PromptTestSetEvaluation
) -> BootstrapEvaluationResponse:
    scenarios = {fixture.fixture_id: fixture.scenario.value for fixture in spec.fixtures}
    return BootstrapEvaluationResponse(
        catalog_hash=prompt_bootstrap_catalog_hash(),
        program_kind=cast(BootstrapKindValue, spec.program_kind.value),
        spec_hash=result.spec_hash,
        test_set_id=spec.test_set_id,
        test_set_hash=result.test_set_hash,
        rubric=_rubric(spec),
        minimum_score=spec.minimum_score,
        case_results=[
            BootstrapCaseEvaluationResponse(
                fixture_id=item.fixture_id,
                scenario=cast(Any, scenarios[item.fixture_id]),
                output_hash=item.output_hash,
                score=item.score,
                passed=item.passed,
                error_code=item.error_code,
                failed_criteria=list(item.failed_criteria),
                blocking_failure=item.blocking_failure,
            )
            for item in result.case_results
        ],
        score=result.score,
        passed=result.passed,
        result_hash=result.result_hash,
    )


def _draft_batch(result: BootstrapDraftBatch) -> BootstrapCreateDraftsResponse:
    items = [_draft_item(item) for item in result.items]
    created_count = sum(item.status == "created" for item in items)
    replayed_count = sum(item.status == "replayed" for item in items)
    failed_count = sum(item.status == "failed" for item in items)
    return BootstrapCreateDraftsResponse(
        catalog_hash=result.catalog_hash,
        completion_status=cast(Any, result.completion_status),
        items=items,
        created_count=created_count,
        replayed_count=replayed_count,
        failed_count=failed_count,
    )


def _draft_item(
    item: BootstrapDraftReceipt | BootstrapDraftFailure,
) -> BootstrapDraftItemResponse:
    program_kind = cast(BootstrapKindValue, item.program_kind.value)
    if isinstance(item, BootstrapDraftFailure):
        return BootstrapDraftItemResponse(
            program_kind=program_kind,
            spec_hash=item.spec_hash,
            test_set_hash=item.test_set_hash,
            idempotency_key_hash=item.idempotency_key_hash,
            status="failed",
            program=None,
            release=None,
            failure=BootstrapDraftFailureResponse(
                code=cast(Any, item.code),
                detail=item.detail,
                retryable=item.retryable,
            ),
        )
    created = item.receipt.value
    return BootstrapDraftItemResponse(
        program_kind=program_kind,
        spec_hash=item.spec_hash,
        test_set_hash=item.test_set_hash,
        idempotency_key_hash=item.idempotency_key_hash,
        status="replayed" if item.receipt.replayed else "created",
        program=_program(created.program),
        release=_release(created.release, created.state),
        failure=None,
    )
