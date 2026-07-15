"""Campaign, destination, opportunity and brief routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status

from geo_api.placement_contracts import (
    BriefVersionCreate,
    BriefVersionView,
    CampaignCreate,
    CampaignCreated,
    CampaignView,
    DestinationCreate,
    DestinationView,
    MonitoringQueryCreate,
    MonitoringQueryView,
    OpportunityView,
)
from geo_api.placement_routes_shared import placement_services
from geo_api.problems import ApiProblem
from geo_api.stable_routes import PROBLEM_RESPONSES
from geo_core.placements.domain import AuthenticityRisk, ConsumerExperience


def campaign_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/geo",
        tags=["GEO placement campaigns"],
        responses=PROBLEM_RESPONSES,
    )

    @router.post(
        "/campaigns", response_model=CampaignCreated, status_code=status.HTTP_201_CREATED,
        operation_id="createGeoCampaign",
    )
    def create_campaign(
        project_id: UUID, payload: CampaignCreate, request: Request
    ) -> CampaignCreated:
        campaign, opportunities = placement_services(request).create_campaign(
            project_id=project_id,
            market_profile_id=payload.market_profile_id,
            primary_product_entity_id=payload.primary_product_entity_id,
            name=payload.name,
            objective=payload.objective,
            actor_id=payload.actor_id,
            destination_ids=tuple(payload.destination_ids),
            rationale=payload.opportunity_rationale,
        )
        return CampaignCreated(campaign=campaign, opportunities=list(opportunities))

    @router.get("/campaigns", response_model=list[CampaignView], operation_id="listGeoCampaigns")
    def list_campaigns(project_id: UUID, request: Request) -> tuple[object, ...]:
        return placement_services(request).list_campaigns(project_id=project_id)

    @router.get(
        "/campaigns/{campaign_id}", response_model=CampaignView, operation_id="getGeoCampaign"
    )
    def get_campaign(project_id: UUID, campaign_id: UUID, request: Request) -> object:
        campaign = placement_services(request).get_campaign(
            project_id=project_id, campaign_id=campaign_id
        )
        if campaign is None:
            raise ApiProblem(status=404, title="Not Found", detail="Campaign does not exist.")
        return campaign

    @router.post(
        "/campaigns/{campaign_id}/monitoring-queries",
        response_model=MonitoringQueryView,
        status_code=status.HTTP_201_CREATED,
        operation_id="createCampaignMonitoringQuery",
    )
    def create_query(
        project_id: UUID, campaign_id: UUID, payload: MonitoringQueryCreate, request: Request
    ) -> object:
        return placement_services(request).create_monitoring_query(
            project_id=project_id,
            campaign_id=campaign_id,
            market_profile_id=payload.market_profile_id,
            query_text=payload.query_text,
            query_kind=payload.query_kind,
            locale=payload.locale,
        )

    @router.get(
        "/campaigns/{campaign_id}/monitoring-queries",
        response_model=list[MonitoringQueryView],
        operation_id="listCampaignMonitoringQueries",
    )
    def list_queries(project_id: UUID, campaign_id: UUID, request: Request) -> tuple[object, ...]:
        return placement_services(request).list_monitoring_queries(
            project_id=project_id, campaign_id=campaign_id
        )

    @router.post(
        "/destinations", response_model=DestinationView, status_code=status.HTTP_201_CREATED,
        operation_id="createPublicationDestination",
    )
    def create_destination(
        project_id: UUID, payload: DestinationCreate, request: Request
    ) -> object:
        return placement_services(request).create_destination(project_id=project_id, **payload.model_dump())

    @router.get(
        "/destinations", response_model=list[DestinationView],
        operation_id="listPublicationDestinations",
    )
    def list_destinations(project_id: UUID, request: Request) -> tuple[object, ...]:
        return placement_services(request).list_destinations(project_id=project_id)

    @router.get(
        "/campaigns/{campaign_id}/opportunities", response_model=list[OpportunityView],
        operation_id="listPlacementOpportunities",
    )
    def list_opportunities(
        project_id: UUID, campaign_id: UUID, request: Request
    ) -> tuple[object, ...]:
        return placement_services(request).list_opportunities(
            project_id=project_id, campaign_id=campaign_id
        )

    @router.post(
        "/opportunities/{opportunity_id}/brief-versions",
        response_model=BriefVersionView,
        status_code=status.HTTP_201_CREATED,
        operation_id="createPlacementBriefVersion",
    )
    def create_brief(
        project_id: UUID, opportunity_id: UUID, payload: BriefVersionCreate, request: Request
    ) -> object:
        experience = (
            ConsumerExperience(**payload.consumer_experience.model_dump())
            if payload.consumer_experience else None
        )
        return placement_services(request).create_brief_version(
            project_id=project_id,
            opportunity_id=opportunity_id,
            primary_brand_entity_id=payload.primary_brand_entity_id,
            goals=payload.goals,
            constraints=payload.constraints,
            compared_entity_ids=tuple(payload.compared_entity_ids),
            allowed_subject_entity_ids=tuple(payload.allowed_subject_entity_ids),
            actor_id=payload.actor_id,
            base_version_id=payload.base_version_id,
            consumer_experience=experience,
            authenticity_risks=tuple(AuthenticityRisk(value) for value in payload.authenticity_risks),
        )

    @router.get(
        "/opportunities/{opportunity_id}/brief-versions",
        response_model=list[BriefVersionView],
        operation_id="listPlacementBriefVersions",
    )
    def list_briefs(
        project_id: UUID, opportunity_id: UUID, request: Request
    ) -> tuple[object, ...]:
        return placement_services(request).list_brief_versions(
            project_id=project_id, opportunity_id=opportunity_id
        )

    return router
