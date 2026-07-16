"""Internal-only routes for non-publishable prompt simulations."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, Response, status

from geo_api.contracts import JobState
from geo_api.placement_access import PlacementEditor, PlacementViewer
from geo_api.placement_routes_shared import IdempotencyHeader, placement_services
from geo_api.placement_simulation_contracts import (
    PromptSimulationCreate,
    PromptSimulationCreated,
    PromptSimulationView,
)
from geo_api.problems import ApiProblem
from geo_api.stable_routes import PROBLEM_RESPONSES


def simulation_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/geo/prompt-simulations",
        tags=["GEO prompt simulations"],
        responses=PROBLEM_RESPONSES,
    )

    @router.post(
        "",
        response_model=PromptSimulationCreated,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="createPromptSimulation",
    )
    def create_simulation(
        project_id: UUID,
        payload: PromptSimulationCreate,
        request: Request,
        idempotency_key: IdempotencyHeader,
        principal: PlacementEditor,
    ) -> PromptSimulationCreated:
        simulation, job = placement_services(request).create_prompt_simulation(
            project_id=project_id,
            destination_id=payload.destination_id,
            template_release_id=payload.template_release_id,
            primary_brand_entity_id=payload.primary_brand_entity_id,
            product_entity_id=payload.product_entity_id,
            authenticity_mode=payload.authenticity_mode,
            evidence_item_ids=tuple(payload.evidence_item_ids),
            goals=payload.goals,
            constraints=payload.constraints,
            variables=payload.variables,
            model_policy_hash=payload.model_policy_hash,
            configured_model=payload.configured_model,
            model_call_budget=payload.model_call_budget,
            requested_by=principal.identity_id,
            idempotency_key=idempotency_key,
        )
        return PromptSimulationCreated(
            simulation=PromptSimulationView.model_validate(simulation),
            job_id=job.id,
            status=JobState(job.status),
            status_url=f"/v1/jobs/{job.id}",
        )

    @router.get(
        "",
        response_model=list[PromptSimulationView],
        operation_id="listPromptSimulations",
    )
    def list_simulations(
        project_id: UUID, request: Request, principal: PlacementViewer
    ) -> tuple[object, ...]:
        del principal
        return placement_services(request).list_prompt_simulations(project_id=project_id)

    @router.get(
        "/{simulation_id}",
        response_model=PromptSimulationView,
        operation_id="getPromptSimulation",
    )
    def get_simulation(
        project_id: UUID,
        simulation_id: UUID,
        request: Request,
        principal: PlacementViewer,
    ) -> object:
        del principal
        simulation = placement_services(request).get_prompt_simulation(
            project_id=project_id, simulation_id=simulation_id
        )
        if simulation is None:
            raise ApiProblem(
                status=404,
                title="Not Found",
                detail="Prompt simulation does not exist.",
            )
        return simulation

    @router.get(
        "/{simulation_id}/artifact",
        response_class=Response,
        operation_id="downloadPromptSimulationArtifact",
    )
    def download_artifact(
        project_id: UUID,
        simulation_id: UUID,
        request: Request,
        principal: PlacementViewer,
    ) -> Response:
        del principal
        artifact = placement_services(request).download_prompt_simulation_artifact(
            project_id=project_id, simulation_id=simulation_id
        )
        return Response(
            content=artifact.content,
            media_type=artifact.content_type,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="geo-prompt-simulation-{simulation_id}.json"'
                ),
                "ETag": artifact.content_hash,
                "X-GEO-Test-Only": "true",
                "X-GEO-Publication-Eligible": "false",
            },
        )

    return router
