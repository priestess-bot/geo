"""Internal-only project-scoped Recommendation routes."""

from __future__ import annotations

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, status

from geo_api.catalog_routes import _principal
from geo_api.foundation_services import FoundationServiceUnavailable
from geo_api.problems import ApiProblem
from geo_api.recommendation_contracts import (
    ApproveRecommendationRequest,
    ApprovedRecommendationResponse,
    CancelRecommendationGenerationRequest,
    CreateRecommendationRequest,
    EnqueueRecommendationGenerationRequest,
    InvalidatedRecommendationResponse,
    PrepareDraftActionRequest,
    PreparedDraftActionResponse,
    ReasonedRecommendationRequest,
    RecommendationCommandResponse,
    RecommendationGenerationJobResponse,
    RecommendationPageResponse,
    RecommendationWorkflowResponse,
    ReconcileRecommendationRequest,
    ReviewedRecommendationResponse,
    ReviewRecommendationRequest,
    VersionedRecommendationRequest,
)
from geo_api.recommendation_generation_presenters import (
    generation_job_response,
    generation_selection,
)
from geo_api.recommendation_presenters import (
    approved_response,
    decision_from_contract,
    invalidated_response,
    page_response,
    prepared_response,
    reviewed_response,
    selection_scope,
    selectors_from_contract,
    workflow_command_response,
    workflow_response,
)
from geo_api.recommendation_runtime import RecommendationApi
from geo_api.stable_routes import PROBLEM_RESPONSES
from geo_core.recommendations import (
    DownstreamDraftKind,
    InputChangeReason,
    RecommendationApplicationError,
    RecommendationConflict,
    RecommendationForbidden,
    RecommendationIdempotencyConflict,
    RecommendationNotFound,
    RecommendationPersistenceError,
    RecommendationReviewRequired,
    RecommendationRuleViolation,
    RecommendationSourceCheckRequired,
    RecommendationSourceStale,
    RecommendationType,
    RecommendationVersionConflict,
)
from geo_core.recommendations.generation_contracts import (
    RecommendationGenerationConflict,
    RecommendationGenerationError,
)


AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]
IdempotencyHeader = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]


def recommendation_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/recommendations",
        tags=["recommendations"],
        responses=PROBLEM_RESPONSES,
    )

    @router.post(
        "",
        response_model=RecommendationCommandResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createRecommendation",
    )
    def create_recommendation(
        project_id: UUID,
        payload: CreateRecommendationRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> RecommendationCommandResponse:
        result = _call(
            lambda: _api(request).create_recommendation(
                _principal(request, authorization),
                project_id=project_id,
                recommendation_type=RecommendationType(payload.recommendation_type),
                scope=selection_scope(project_id, payload.scope),
                decision=decision_from_contract(payload.decision),
                evidence_selectors=selectors_from_contract(payload.evidence_selectors),
                proposed_draft_kind=(
                    DownstreamDraftKind(payload.proposed_draft_kind)
                    if payload.proposed_draft_kind
                    else None
                ),
                valid_until=payload.valid_until,
                expected_version=payload.expected_version,
                idempotency_key=idempotency_key,
            )
        )
        return workflow_command_response(result)

    @router.post(
        "/generation-jobs",
        response_model=RecommendationGenerationJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="enqueueRecommendationGenerationJob",
    )
    def enqueue_generation_job(
        project_id: UUID,
        payload: EnqueueRecommendationGenerationRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> RecommendationGenerationJobResponse:
        result = _call(
            lambda: _api(request).enqueue_generation_job(
                _principal(request, authorization),
                selection=generation_selection(project_id, payload),
                idempotency_key=idempotency_key,
            )
        )
        return generation_job_response(result)

    @router.get(
        "/generation-jobs/{job_id}",
        response_model=RecommendationGenerationJobResponse,
        operation_id="getRecommendationGenerationJob",
    )
    def get_generation_job(
        project_id: UUID,
        job_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> RecommendationGenerationJobResponse:
        result = _call(
            lambda: _api(request).get_generation_job(
                _principal(request, authorization),
                project_id=project_id,
                job_id=job_id,
            )
        )
        return generation_job_response(result)

    @router.post(
        "/generation-jobs/{job_id}/cancel",
        response_model=RecommendationGenerationJobResponse,
        operation_id="cancelRecommendationGenerationJob",
    )
    def cancel_generation_job(
        project_id: UUID,
        job_id: UUID,
        payload: CancelRecommendationGenerationRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> RecommendationGenerationJobResponse:
        result = _call(
            lambda: _api(request).cancel_generation_job(
                _principal(request, authorization),
                project_id=project_id,
                job_id=job_id,
                expected_version=payload.expected_version,
                idempotency_key=idempotency_key,
            )
        )
        return generation_job_response(result)

    @router.get(
        "",
        response_model=RecommendationPageResponse,
        operation_id="listRecommendations",
    )
    def list_recommendations(
        project_id: UUID,
        request: Request,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
        authorization: AuthorizationHeader = None,
    ) -> RecommendationPageResponse:
        result = _call(
            lambda: _api(request).list_recommendations(
                _principal(request, authorization),
                project_id=project_id,
                limit=limit,
                offset=offset,
            )
        )
        return page_response(result)

    @router.get(
        "/{recommendation_id}",
        response_model=RecommendationWorkflowResponse,
        operation_id="getRecommendation",
    )
    def get_recommendation(
        project_id: UUID,
        recommendation_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> RecommendationWorkflowResponse:
        result = _call(
            lambda: _api(request).get_recommendation(
                _principal(request, authorization),
                project_id=project_id,
                recommendation_id=recommendation_id,
            )
        )
        return workflow_response(result)

    @router.post(
        "/{recommendation_id}/submit",
        response_model=RecommendationCommandResponse,
        operation_id="submitRecommendation",
    )
    def submit_recommendation(
        project_id: UUID,
        recommendation_id: UUID,
        payload: VersionedRecommendationRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> RecommendationCommandResponse:
        result = _call(
            lambda: _api(request).submit_recommendation(
                _principal(request, authorization),
                project_id=project_id,
                recommendation_id=recommendation_id,
                expected_version=payload.expected_version,
                idempotency_key=idempotency_key,
            )
        )
        return workflow_command_response(result)

    @router.post(
        "/{recommendation_id}/review",
        response_model=ReviewedRecommendationResponse,
        operation_id="reviewRecommendation",
    )
    def review_recommendation(
        project_id: UUID,
        recommendation_id: UUID,
        payload: ReviewRecommendationRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> ReviewedRecommendationResponse:
        result = _call(
            lambda: _api(request).review_recommendation(
                _principal(request, authorization),
                project_id=project_id,
                recommendation_id=recommendation_id,
                notes=payload.notes,
                expected_version=payload.expected_version,
                idempotency_key=idempotency_key,
            )
        )
        return reviewed_response(result)

    @router.post(
        "/{recommendation_id}/approve",
        response_model=ApprovedRecommendationResponse,
        operation_id="approveRecommendation",
    )
    def approve_recommendation(
        project_id: UUID,
        recommendation_id: UUID,
        payload: ApproveRecommendationRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> ApprovedRecommendationResponse:
        result = _call(
            lambda: _api(request).approve_recommendation(
                _principal(request, authorization),
                project_id=project_id,
                recommendation_id=recommendation_id,
                expected_version=payload.expected_version,
                idempotency_key=idempotency_key,
            )
        )
        return approved_response(result)

    @router.post(
        "/{recommendation_id}/reject",
        response_model=RecommendationCommandResponse,
        operation_id="rejectRecommendation",
    )
    def reject_recommendation(
        project_id: UUID,
        recommendation_id: UUID,
        payload: ReasonedRecommendationRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> RecommendationCommandResponse:
        result = _call(
            lambda: _api(request).reject_recommendation(
                _principal(request, authorization),
                project_id=project_id,
                recommendation_id=recommendation_id,
                reason=payload.reason,
                expected_version=payload.expected_version,
                idempotency_key=idempotency_key,
            )
        )
        return workflow_command_response(result)

    @router.post(
        "/{recommendation_id}/expire",
        response_model=InvalidatedRecommendationResponse,
        operation_id="expireRecommendation",
    )
    def expire_recommendation(
        project_id: UUID,
        recommendation_id: UUID,
        payload: ReasonedRecommendationRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> InvalidatedRecommendationResponse:
        result = _call(
            lambda: _api(request).expire_recommendation(
                _principal(request, authorization),
                project_id=project_id,
                recommendation_id=recommendation_id,
                reason=payload.reason,
                expected_version=payload.expected_version,
                idempotency_key=idempotency_key,
            )
        )
        return invalidated_response(result)

    @router.post(
        "/{recommendation_id}/reconcile-stale",
        response_model=InvalidatedRecommendationResponse,
        operation_id="reconcileStaleRecommendation",
    )
    def reconcile_stale(
        project_id: UUID,
        recommendation_id: UUID,
        payload: ReconcileRecommendationRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> InvalidatedRecommendationResponse:
        result = _call(
            lambda: _api(request).reconcile_stale(
                _principal(request, authorization),
                project_id=project_id,
                recommendation_id=recommendation_id,
                change_reason=InputChangeReason(payload.change_reason),
                expected_version=payload.expected_version,
                idempotency_key=idempotency_key,
            )
        )
        return invalidated_response(result)

    @router.post(
        "/{recommendation_id}/drafts/{draft_id}/prepare-action",
        response_model=PreparedDraftActionResponse,
        operation_id="prepareRecommendationDraftAction",
    )
    def prepare_draft_action(
        project_id: UUID,
        recommendation_id: UUID,
        draft_id: UUID,
        payload: PrepareDraftActionRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> PreparedDraftActionResponse:
        result = _call(
            lambda: _api(request).prepare_draft_action(
                _principal(request, authorization),
                project_id=project_id,
                recommendation_id=recommendation_id,
                draft_id=draft_id,
                change_reason=InputChangeReason(payload.change_reason),
                expected_version=payload.expected_version,
                idempotency_key=idempotency_key,
            )
        )
        return prepared_response(result)

    return router


def _api(request: Request) -> RecommendationApi:
    application = getattr(request.app.state, "recommendation_api", None)
    if application is None:
        raise FoundationServiceUnavailable(
            "Recommendation persistence is unavailable until its PostgreSQL builder is installed."
        )
    return cast(RecommendationApi, application)


def _call(operation: Any) -> Any:
    try:
        return operation()
    except RecommendationRuleViolation as error:
        raise _problem(422, "Unprocessable Content", error, "rule-violation") from error
    except RecommendationForbidden as error:
        raise _problem(403, "Forbidden", error, "forbidden") from error
    except RecommendationNotFound as error:
        raise _problem(404, "Not Found", error, "not-found") from error
    except (
        RecommendationIdempotencyConflict,
        RecommendationVersionConflict,
        RecommendationConflict,
        RecommendationSourceStale,
        RecommendationReviewRequired,
        RecommendationSourceCheckRequired,
    ) as error:
        raise _problem(409, "Conflict", error, "conflict") from error
    except RecommendationGenerationConflict as error:
        raise _problem(409, "Conflict", error, "generation-conflict") from error
    except RecommendationGenerationError as error:
        raise _problem(
            503, "Service Unavailable", error, "generation-unavailable"
        ) from error
    except RecommendationPersistenceError as error:
        raise _problem(503, "Service Unavailable", error, "persistence-unavailable") from error
    except RecommendationApplicationError as error:
        raise _problem(503, "Service Unavailable", error, "application-unavailable") from error


def _problem(status_code: int, title: str, error: Exception, suffix: str) -> ApiProblem:
    return ApiProblem(
        status=status_code,
        title=title,
        detail=str(error),
        type_uri=f"urn:geo:problem:recommendation-{suffix}",
        headers={"Retry-After": "30"} if status_code == 503 else None,
    )
