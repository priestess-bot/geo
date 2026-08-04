"""Durable Job routes for the Internal Synthetic Lab surface."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from geo_api.catalog_routes import _principal
from geo_api.synthetic_lab_contracts import (
    CancelSyntheticJobRequest,
    EnqueueCorpusFinalizeRequest,
    EnqueueOfflineExperimentRequest,
    EnqueueReviewCaseRunRequest,
    EnqueueStyleCollectionRequest,
    EnqueueStyleProfileBuildRequest,
    EnqueueSyntheticJobRequest,
    FinalizeSyntheticJobRequest,
    JobKind,
    SyntheticJobResponse,
    SyntheticJobPageResponse,
    SyntheticJobStatus,
    StyleCollectionAdmissionResponse,
)
from geo_api.synthetic_lab_direct_contracts import (
    EnqueueDirectGenerationRequest,
    SyntheticReviewResultResponse,
)
from geo_api.synthetic_lab_direct_presenters import review_result_response
from geo_api.synthetic_lab_presenters import (
    job_page,
    job_response,
    style_collection_admission_response,
)
from geo_api.synthetic_lab_route_support import (
    AuthorizationHeader,
    IdempotencyHeader,
    LimitQuery,
    OffsetQuery,
    run as _run,
    run_write as _run_write,
)


def synthetic_lab_job_router() -> APIRouter:
    router = APIRouter()

    @router.get(
        "/jobs",
        response_model=SyntheticJobPageResponse,
        operation_id="listSyntheticLabJobs",
    )
    def list_jobs(
        project_id: UUID,
        request: Request,
        limit: LimitQuery = 50,
        offset: OffsetQuery = 0,
        kind: JobKind | None = None,
        job_status: SyntheticJobStatus | None = Query(default=None, alias="status"),
        authorization: AuthorizationHeader = None,
    ) -> SyntheticJobPageResponse:
        return job_page(
            _run(
                request,
                "list_jobs",
                _principal(request, authorization),
                project_id=project_id,
                limit=limit,
                offset=offset,
                kind=kind,
                status=job_status,
            )
        )

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
        "/jobs/profile-build",
        response_model=SyntheticJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="enqueueSyntheticStyleProfileBuildJob",
    )
    def enqueue_profile_build(
        project_id: UUID,
        payload: EnqueueStyleProfileBuildRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> SyntheticJobResponse:
        return job_response(
            _run_write(
                request,
                "enqueue_profile_build",
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
        payload: EnqueueReviewCaseRunRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> SyntheticJobResponse:
        return job_response(
            _run_write(
                request,
                "enqueue_review_case",
                _principal(request, authorization),
                idempotency_key,
                project_id=project_id,
                payload=payload,
            )
        )

    @router.post(
        "/jobs/direct-generation",
        response_model=SyntheticJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="enqueueSyntheticDirectGenerationJob",
    )
    def enqueue_direct_generation(
        project_id: UUID,
        payload: EnqueueDirectGenerationRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> SyntheticJobResponse:
        return job_response(
            _run_write(
                request,
                "enqueue_direct_generation",
                _principal(request, authorization),
                idempotency_key,
                project_id=project_id,
                payload=payload,
            )
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
        payload: EnqueueCorpusFinalizeRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> SyntheticJobResponse:
        return job_response(
            _run_write(
                request,
                "enqueue_corpus_finalize",
                _principal(request, authorization),
                idempotency_key,
                project_id=project_id,
                payload=payload,
            )
        )

    @router.post(
        "/jobs/offline-experiment",
        response_model=SyntheticJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="enqueueSyntheticOfflineExperimentJob",
    )
    def enqueue_experiment(
        project_id: UUID,
        payload: EnqueueOfflineExperimentRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> SyntheticJobResponse:
        return job_response(
            _run_write(
                request,
                "enqueue_offline_experiment",
                _principal(request, authorization),
                idempotency_key,
                project_id=project_id,
                payload=payload,
            )
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

    @router.get(
        "/jobs/{job_id}/result",
        response_model=SyntheticReviewResultResponse,
        operation_id="getSyntheticLabReviewResult",
    )
    def get_job_result(
        project_id: UUID,
        job_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> SyntheticReviewResultResponse:
        return review_result_response(
            _run(
                request,
                "get_job_result",
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
