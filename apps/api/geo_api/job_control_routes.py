"""Authorized internal controls for project-scoped durable jobs."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request

from geo_api.placement_access import PlacementEditor, PlacementOwnerAdmin, PlacementViewer
from geo_api.placement_contracts import PlacementJobEventView, PlacementJobView
from geo_api.placement_routes_shared import IdempotencyHeader, placement_services
from geo_api.stable_routes import PROBLEM_RESPONSES


def job_control_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/geo/jobs",
        tags=["GEO durable job controls"],
        responses=PROBLEM_RESPONSES,
    )

    @router.post("/{job_id}/cancel", response_model=PlacementJobView)
    def cancel_job(
        project_id: UUID, job_id: UUID, request: Request, principal: PlacementEditor
    ) -> object:
        return placement_services(request).cancel_job(
            project_id=project_id, job_id=job_id, actor_id=principal.identity_id
        )

    @router.post("/{job_id}/retry-now", response_model=PlacementJobView)
    def retry_job_now(
        project_id: UUID,
        job_id: UUID,
        request: Request,
        idempotency_key: IdempotencyHeader,
        principal: PlacementEditor,
    ) -> object:
        return placement_services(request).retry_job_now(
            project_id=project_id,
            job_id=job_id,
            actor_id=principal.identity_id,
            idempotency_key=idempotency_key,
        )

    @router.post("/{job_id}/replays", response_model=PlacementJobView, status_code=201)
    def replay_job(
        project_id: UUID,
        job_id: UUID,
        request: Request,
        idempotency_key: IdempotencyHeader,
        principal: PlacementOwnerAdmin,
    ) -> object:
        return placement_services(request).replay_job(
            project_id=project_id,
            source_job_id=job_id,
            actor_id=principal.identity_id,
            idempotency_key=idempotency_key,
        )

    @router.get("/{job_id}/events", response_model=list[PlacementJobEventView])
    def list_job_events(
        project_id: UUID, job_id: UUID, request: Request, principal: PlacementViewer
    ) -> tuple[object, ...]:
        del principal
        return placement_services(request).list_job_events(project_id=project_id, job_id=job_id)

    return router
