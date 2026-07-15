"""Explicit publication, submission, verification and measurement routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status

from geo_api.contracts import JobAccepted
from geo_api.placement_contracts import (
    MeasurementCreate,
    MeasurementView,
    PublicationCreate,
    PublicationView,
    SubmissionCreate,
    SubmissionView,
)
from geo_api.placement_routes_shared import IdempotencyHeader, placement_services
from geo_api.stable_routes import PROBLEM_RESPONSES


def publication_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/geo",
        tags=["GEO publication"], responses=PROBLEM_RESPONSES,
    )

    @router.post(
        "/package-versions/{version_id}/publication-requests",
        response_model=PublicationView, status_code=status.HTTP_201_CREATED,
        operation_id="requestPlacementPublication",
    )
    def request_publication(
        project_id: UUID, version_id: UUID, payload: PublicationCreate,
        request: Request, idempotency_key: IdempotencyHeader,
    ) -> object:
        return placement_services(request).request_publication(
            project_id=project_id, version_id=version_id,
            destination_id=payload.destination_id, requested_by=payload.requested_by,
            publication_attempt=payload.publication_attempt, idempotency_key=idempotency_key,
        )

    @router.post(
        "/publication-requests/{publication_request_id}/submissions",
        response_model=SubmissionView, status_code=status.HTTP_201_CREATED,
        operation_id="recordPlacementSubmission",
    )
    def create_submission(
        project_id: UUID, publication_request_id: UUID,
        payload: SubmissionCreate, request: Request,
    ) -> object:
        return placement_services(request).create_submission(
            project_id=project_id, publication_request_id=publication_request_id,
            submitted_url=payload.submitted_url,
            provider_submission_id=payload.provider_submission_id,
        )

    @router.post(
        "/submissions/{submission_id}/verification-jobs",
        response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED,
        operation_id="requestPlacementSubmissionVerification",
    )
    def request_verification(
        project_id: UUID, submission_id: UUID, request: Request,
        idempotency_key: IdempotencyHeader,
    ) -> JobAccepted:
        job = placement_services(request).request_verification(
            project_id=project_id, submission_id=submission_id,
            idempotency_key=idempotency_key,
        )
        return JobAccepted(job_id=job.id, status=job.status, status_url=f"/v1/jobs/{job.id}")

    @router.post(
        "/submissions/{submission_id}/measurements",
        response_model=MeasurementView, status_code=status.HTTP_201_CREATED,
        operation_id="recordPlacementMeasurement",
    )
    def create_measurement(
        project_id: UUID, submission_id: UUID, payload: MeasurementCreate, request: Request
    ) -> object:
        return placement_services(request).record_measurement(
            project_id=project_id, submission_id=submission_id, **payload.model_dump()
        )

    @router.get(
        "/submissions/{submission_id}/measurements", response_model=list[MeasurementView],
        operation_id="listPlacementMeasurements",
    )
    def list_measurements(
        project_id: UUID, submission_id: UUID, request: Request
    ) -> tuple[object, ...]:
        return placement_services(request).list_measurements(
            project_id=project_id, submission_id=submission_id
        )

    return router
