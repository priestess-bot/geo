"""Explicit publication, submission, verification and measurement routes."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request, status

from geo_api.contracts import JobAccepted, JobState
from geo_api.placement_contracts import (
    MeasurementCreate,
    MeasurementView,
    PublicationCreate,
    PublicationView,
    SubmissionCreate,
    StateReasonCreate,
    SubmissionUrlCreate,
    SubmissionView,
)
from geo_api.placement_access import PlacementEditor, PlacementPublisher, PlacementViewer
from geo_api.placement_routes_shared import IdempotencyHeader, placement_services
from geo_api.problems import ApiProblem
from geo_api.stable_routes import PROBLEM_RESPONSES


def publication_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/geo",
        tags=["GEO publication"],
        responses=PROBLEM_RESPONSES,
    )

    @router.post(
        "/package-versions/{version_id}/publication-requests",
        response_model=PublicationView,
        status_code=status.HTTP_201_CREATED,
        operation_id="requestPlacementPublication",
    )
    def request_publication(
        project_id: UUID,
        version_id: UUID,
        payload: PublicationCreate,
        request: Request,
        idempotency_key: IdempotencyHeader,
        principal: PlacementPublisher,
    ) -> object:
        return placement_services(request).request_publication(
            project_id=project_id,
            version_id=version_id,
            destination_id=payload.destination_id,
            requested_by=principal.identity_id,
            publication_attempt=payload.publication_attempt,
            idempotency_key=idempotency_key,
            restricted_policy_acknowledged=payload.restricted_policy_acknowledged,
            policy_basis=payload.policy_basis,
        )

    @router.get(
        "/package-versions/{version_id}/publication-requests",
        response_model=list[PublicationView],
        operation_id="listPlacementPublicationRequests",
    )
    def list_publications(
        project_id: UUID, version_id: UUID, request: Request, principal: PlacementViewer
    ) -> tuple[object, ...]:
        del principal
        return placement_services(request).list_publication_requests(
            project_id=project_id, version_id=version_id
        )

    @router.post(
        "/publication-requests/{publication_request_id}/submissions",
        response_model=SubmissionView,
        status_code=status.HTTP_201_CREATED,
        operation_id="recordPlacementSubmission",
    )
    def create_submission(
        project_id: UUID,
        publication_request_id: UUID,
        payload: SubmissionCreate,
        request: Request,
        principal: PlacementPublisher,
    ) -> object:
        del principal
        return placement_services(request).create_submission(
            project_id=project_id,
            publication_request_id=publication_request_id,
            submitted_url=payload.submitted_url,
            provider_submission_id=payload.provider_submission_id,
        )

    @router.get(
        "/publication-requests/{publication_request_id}/submissions",
        response_model=list[SubmissionView],
        operation_id="listPlacementSubmissions",
    )
    def list_submissions(
        project_id: UUID,
        publication_request_id: UUID,
        request: Request,
        principal: PlacementViewer,
    ) -> tuple[object, ...]:
        del principal
        return placement_services(request).list_submissions(
            project_id=project_id, publication_request_id=publication_request_id
        )

    @router.get(
        "/submissions/{submission_id}",
        response_model=SubmissionView,
        operation_id="getPlacementSubmission",
    )
    def get_submission(
        project_id: UUID, submission_id: UUID, request: Request, principal: PlacementViewer
    ) -> object:
        del principal
        submission = placement_services(request).get_submission(
            project_id=project_id, submission_id=submission_id
        )
        if submission is None:
            raise ApiProblem(status=404, title="Not Found", detail="Submission not found.")
        return submission

    @router.post(
        "/submissions/{submission_id}/url",
        response_model=SubmissionView,
        operation_id="backfillPlacementSubmissionUrl",
    )
    def backfill_submission_url(
        project_id: UUID,
        submission_id: UUID,
        payload: SubmissionUrlCreate,
        request: Request,
        principal: PlacementPublisher,
    ) -> object:
        return placement_services(request).backfill_submission_url(
            project_id=project_id,
            submission_id=submission_id,
            submitted_url=payload.submitted_url,
            actor_id=principal.identity_id,
        )

    @router.post(
        "/submissions/{submission_id}/block",
        response_model=SubmissionView,
        operation_id="blockPlacementSubmission",
    )
    def block_submission(
        project_id: UUID,
        submission_id: UUID,
        payload: StateReasonCreate,
        request: Request,
        principal: PlacementPublisher,
    ) -> object:
        return placement_services(request).transition_submission(
            project_id=project_id,
            submission_id=submission_id,
            status="blocked",
            reason=payload.reason,
            actor_id=principal.identity_id,
        )

    @router.post(
        "/publication-requests/{publication_request_id}/{command}",
        response_model=PublicationView,
        operation_id="terminatePlacementPublication",
    )
    def terminate_publication(
        project_id: UUID,
        publication_request_id: UUID,
        command: Literal["block", "cancel"],
        payload: StateReasonCreate,
        request: Request,
        principal: PlacementPublisher,
    ) -> object:
        return placement_services(request).transition_publication(
            project_id=project_id,
            publication_request_id=publication_request_id,
            status="blocked" if command == "block" else "cancelled",
            reason=payload.reason,
            actor_id=principal.identity_id,
        )

    @router.post(
        "/submissions/{submission_id}/verification-jobs",
        response_model=JobAccepted,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="requestPlacementSubmissionVerification",
    )
    def request_verification(
        project_id: UUID,
        submission_id: UUID,
        request: Request,
        idempotency_key: IdempotencyHeader,
        principal: PlacementPublisher,
    ) -> JobAccepted:
        del principal
        job = placement_services(request).request_verification(
            project_id=project_id,
            submission_id=submission_id,
            idempotency_key=idempotency_key,
        )
        return JobAccepted(
            job_id=job.id,
            status=JobState(job.status),
            status_url=f"/v1/jobs/{job.id}",
        )

    @router.post(
        "/submissions/{submission_id}/measurements",
        response_model=MeasurementView,
        status_code=status.HTTP_201_CREATED,
        operation_id="recordPlacementMeasurement",
    )
    def create_measurement(
        project_id: UUID,
        submission_id: UUID,
        payload: MeasurementCreate,
        request: Request,
        principal: PlacementEditor,
    ) -> object:
        del principal
        return placement_services(request).record_measurement(
            project_id=project_id, submission_id=submission_id, **payload.model_dump()
        )

    @router.get(
        "/submissions/{submission_id}/measurements",
        response_model=list[MeasurementView],
        operation_id="listPlacementMeasurements",
    )
    def list_measurements(
        project_id: UUID,
        submission_id: UUID,
        request: Request,
        principal: PlacementViewer,
    ) -> tuple[object, ...]:
        del principal
        return placement_services(request).list_measurements(
            project_id=project_id, submission_id=submission_id
        )

    return router
