"""Durable Job routes for the Internal Synthetic Lab surface."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status

from geo_api.catalog_routes import _principal
from geo_api.synthetic_lab_contracts import (
    CancelSyntheticJobRequest,
    EnqueueStyleCollectionRequest,
    EnqueueSyntheticJobRequest,
    FinalizeSyntheticJobRequest,
    SyntheticJobResponse,
    StyleCollectionAdmissionResponse,
)
from geo_api.synthetic_lab_presenters import job_response, style_collection_admission_response
from geo_api.synthetic_lab_route_support import (
    AuthorizationHeader,
    IdempotencyHeader,
    run as _run,
    run_write as _run_write,
)


def synthetic_lab_job_router() -> APIRouter:
    router = APIRouter()

    @router.post(
        "/jobs/style-collection",
        response_model=StyleCollectionAdmissionResponse,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="admitSyntheticStyleCollection",
    )
    def admit_style_collection(
        project_id: UUID,
        payload: EnqueueStyleCollectionRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> StyleCollectionAdmissionResponse:
        return style_collection_admission_response(
            _run_write(
                request,
                "admit_style_collection",
                _principal(request, authorization),
                idempotency_key,
                project_id=project_id,
                payload=payload,
            )
        )

    @router.post(
        "/jobs/generation",
        response_model=SyntheticJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="enqueueSyntheticGenerationJob",
    )
    def enqueue_generation(
        project_id: UUID,
        payload: EnqueueSyntheticJobRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> SyntheticJobResponse:
        return _enqueue(
            request,
            authorization,
            project_id,
            payload,
            idempotency_key,
            "candidate_generation",
        )

    @router.post(
        "/jobs/revision",
        response_model=SyntheticJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="enqueueSyntheticRevisionJob",
    )
    def enqueue_revision(
        project_id: UUID,
        payload: EnqueueSyntheticJobRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> SyntheticJobResponse:
        return _enqueue(
            request,
            authorization,
            project_id,
            payload,
            idempotency_key,
            "candidate_revision",
        )

    @router.post(
        "/jobs/corpus",
        response_model=SyntheticJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="enqueueSyntheticCorpusJob",
    )
    def enqueue_corpus(
        project_id: UUID,
        payload: EnqueueSyntheticJobRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> SyntheticJobResponse:
        return _enqueue(
            request,
            authorization,
            project_id,
            payload,
            idempotency_key,
            "corpus_finalize",
        )

    @router.post(
        "/jobs/offline-experiment",
        response_model=SyntheticJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="enqueueSyntheticOfflineExperimentJob",
    )
    def enqueue_experiment(
        project_id: UUID,
        payload: EnqueueSyntheticJobRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> SyntheticJobResponse:
        return _enqueue(
            request,
            authorization,
            project_id,
            payload,
            idempotency_key,
            "offline_experiment",
        )

    @router.get(
        "/jobs/{job_id}",
        response_model=SyntheticJobResponse,
        operation_id="getSyntheticLabJob",
    )
    def get_job(
        project_id: UUID,
        job_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> SyntheticJobResponse:
        return job_response(
            _run(
                request,
                "get_job",
                _principal(request, authorization),
                project_id=project_id,
                job_id=job_id,
            )
        )

    @router.post(
        "/jobs/{job_id}/cancel",
        response_model=SyntheticJobResponse,
        operation_id="cancelSyntheticLabJob",
    )
    def cancel_job(
        project_id: UUID,
        job_id: UUID,
        payload: CancelSyntheticJobRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> SyntheticJobResponse:
        return job_response(
            _run_write(
                request,
                "cancel_job",
                _principal(request, authorization),
                idempotency_key,
                project_id=project_id,
                job_id=job_id,
                payload=payload,
            )
        )

    @router.post(
        "/jobs/{job_id}/finalize",
        response_model=SyntheticJobResponse,
        operation_id="finalizeSyntheticLabJob",
    )
    def finalize_job(
        project_id: UUID,
        job_id: UUID,
        payload: FinalizeSyntheticJobRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> SyntheticJobResponse:
        return job_response(
            _run_write(
                request,
                "finalize_job",
                _principal(request, authorization),
                idempotency_key,
                project_id=project_id,
                job_id=job_id,
                payload=payload,
            )
        )

    return router


def _enqueue(
    request: Request,
    authorization: str | None,
    project_id: UUID,
    payload: EnqueueSyntheticJobRequest,
    idempotency_key: str,
    job_kind: str,
) -> SyntheticJobResponse:
    return job_response(
        _run_write(
            request,
            "enqueue_job",
            _principal(request, authorization),
            idempotency_key,
            project_id=project_id,
            job_kind=job_kind,
            payload=payload,
        )
    )


__all__ = ["synthetic_lab_job_router"]
