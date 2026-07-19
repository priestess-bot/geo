"""Internal Campaign-scoped routes for governed GEO QuestionSets."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, status

from geo_api.catalog_routes import _principal
from geo_api.knowledge_question_contracts import (
    CreateQuestionGenerationRequest,
    QuestionCandidateView,
    QuestionGenerationResponse,
    QuestionGenerationView,
    QuestionSetCreateRequest,
    QuestionSetView,
    ReviewQuestionCandidateRequest,
)
from geo_api.knowledge_routes import (
    AuthorizationHeader,
    IdempotencyHeader,
    _application,
    _call,
)
from geo_api.stable_routes import PROBLEM_RESPONSES
from geo_core.knowledge.question_domain import QuestionDimensionDraft


def knowledge_question_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/knowledge/campaigns/{campaign_id}",
        tags=["GEO question sets"],
        responses=PROBLEM_RESPONSES,
    )

    @router.post(
        "/question-generations",
        response_model=QuestionGenerationResponse,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="createKnowledgeQuestionGeneration",
    )
    def create_generation(
        project_id: UUID,
        campaign_id: UUID,
        payload: CreateQuestionGenerationRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> Any:
        return _call(
            lambda: _application(request).create_question_generation(
                _principal(request, authorization),
                project_id=project_id,
                campaign_id=campaign_id,
                dimensions=tuple(
                    QuestionDimensionDraft(**item.model_dump())
                    for item in payload.dimensions
                ),
                fact_candidate_ids=tuple(payload.fact_candidate_ids),
                graph_entity_ids=tuple(payload.graph_entity_ids),
                configured_model=payload.configured_model,
                model_call_budget=payload.model_call_budget,
                semantic_duplicate_threshold=payload.semantic_duplicate_threshold,
                idempotency_key=idempotency_key,
            )
        )

    @router.get(
        "/question-generations",
        response_model=list[QuestionGenerationView],
        operation_id="listKnowledgeQuestionGenerations",
    )
    def list_generations(
        project_id: UUID,
        campaign_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> Any:
        return _call(
            lambda: _application(request).list_question_generations(
                _principal(request, authorization),
                project_id=project_id,
                campaign_id=campaign_id,
            )
        )

    @router.get(
        "/question-candidates",
        response_model=list[QuestionCandidateView],
        operation_id="listKnowledgeQuestionCandidates",
    )
    def list_candidates(
        project_id: UUID,
        campaign_id: UUID,
        generation_job_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> Any:
        return _call(
            lambda: _application(request).list_question_candidates(
                _principal(request, authorization),
                project_id=project_id,
                campaign_id=campaign_id,
                generation_job_id=generation_job_id,
            )
        )

    @router.patch(
        "/question-candidates/{candidate_id}",
        operation_id="reviewKnowledgeQuestionCandidate",
    )
    def review_candidate(
        project_id: UUID,
        campaign_id: UUID,
        candidate_id: UUID,
        payload: ReviewQuestionCandidateRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> Any:
        return _call(
            lambda: _application(request).review_question_candidate(
                _principal(request, authorization),
                project_id=project_id,
                campaign_id=campaign_id,
                candidate_id=candidate_id,
                decision=payload.decision,
                notes=payload.notes,
            )
        )

    @router.post(
        "/question-sets",
        response_model=QuestionSetView,
        status_code=status.HTTP_201_CREATED,
        operation_id="createKnowledgeQuestionSet",
    )
    def create_question_set(
        project_id: UUID,
        campaign_id: UUID,
        payload: QuestionSetCreateRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> Any:
        return _call(
            lambda: _application(request).create_question_set(
                _principal(request, authorization),
                project_id=project_id,
                campaign_id=campaign_id,
                name=payload.name,
                generation_job_id=payload.generation_job_id,
                candidate_ids=tuple(payload.candidate_ids),
                series_id=payload.series_id,
                previous_version_id=payload.previous_version_id,
                idempotency_key=idempotency_key,
            )
        )

    @router.get(
        "/question-sets",
        response_model=list[QuestionSetView],
        operation_id="listKnowledgeQuestionSets",
    )
    def list_question_sets(
        project_id: UUID,
        campaign_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> Any:
        return _call(
            lambda: _application(request).list_question_sets(
                _principal(request, authorization),
                project_id=project_id,
                campaign_id=campaign_id,
            )
        )

    @router.post(
        "/question-sets/{question_set_id}/approve",
        response_model=QuestionSetView,
        operation_id="approveKnowledgeQuestionSet",
    )
    def approve_question_set(
        project_id: UUID,
        campaign_id: UUID,
        question_set_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> Any:
        return _call(
            lambda: _application(request).approve_question_set(
                _principal(request, authorization),
                project_id=project_id,
                campaign_id=campaign_id,
                question_set_id=question_set_id,
            )
        )

    @router.post(
        "/question-sets/{question_set_id}/freeze",
        response_model=QuestionSetView,
        operation_id="freezeKnowledgeQuestionSet",
    )
    def freeze_question_set(
        project_id: UUID,
        campaign_id: UUID,
        question_set_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> Any:
        return _call(
            lambda: _application(request).freeze_question_set(
                _principal(request, authorization),
                project_id=project_id,
                campaign_id=campaign_id,
                question_set_id=question_set_id,
            )
        )

    return router
