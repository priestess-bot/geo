"""Customer-safe, Campaign-scoped GEO reporting routes."""

from __future__ import annotations

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Header, Request

from geo_api.customer_geo_contracts import (
    CustomerApprovedMeasurementResponse,
    CustomerCampaignReadModelResponse,
    CustomerCampaignResponse,
    CustomerCampaignSummaryResponse,
)
from geo_api.monitoring_contracts import (
    MeasurementWindowResponse,
    MetricResponse,
    MonitoringReportResponse,
    VerifiedUrlResponse,
)
from geo_api.monitoring_dependencies import (
    authorize_monitoring_project as _principal,
    monitoring_application as _application,
    monitoring_call as _call,
)
from geo_api.monitoring_presenters import metric_response, report_response
from geo_api.stable_routes import PROBLEM_RESPONSES
from geo_core.access.models import AccessPrincipal
from geo_core.monitoring.application import MonitoringApplication
from geo_core.monitoring.customer_projection import (
    ApprovedReportSnapshot,
    CustomerCampaign,
)
from geo_core.monitoring.domain import READER_ROLES, REPORT_METHODOLOGY, VerifiedUrl


AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]


def customer_geo_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/geo",
        tags=["customer GEO reporting"],
        responses=PROBLEM_RESPONSES,
    )

    @router.get(
        "/campaigns",
        response_model=list[CustomerCampaignResponse],
        operation_id="listCustomerGeoCampaigns",
    )
    def campaigns(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> list[CustomerCampaignResponse]:
        principal = _authorize(request, authorization, project_id)
        items = _call(
            lambda: _application(request).list_customer_campaigns(
                principal, project_id=project_id
            )
        )
        return [_campaign_response(item) for item in items]

    @router.get(
        "/campaigns/{campaign_id}/read-model",
        response_model=CustomerCampaignReadModelResponse,
        operation_id="getCustomerGeoCampaignReadModel",
    )
    def campaign_read_model(
        project_id: UUID,
        campaign_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> CustomerCampaignReadModelResponse:
        principal = _authorize(request, authorization, project_id)
        campaign, approved, urls = _read_model(
            _application(request), principal, project_id, campaign_id
        )
        return CustomerCampaignReadModelResponse(
            campaign=_campaign_response(campaign),
            summary=_summary_response(campaign, approved, urls),
            approved_measurements=[_approved_response(item) for item in approved],
            verified_urls=[VerifiedUrlResponse(**item.__dict__) for item in urls],
        )

    @router.get(
        "/metrics", response_model=list[MetricResponse], operation_id="listCustomerGeoMetrics"
    )
    def metrics(
        project_id: UUID,
        campaign_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> list[MetricResponse]:
        approved = _approved(request, authorization, project_id, campaign_id)
        return [metric_response(item.snapshot) for item in approved]

    @router.get(
        "/measurement-windows",
        response_model=list[MeasurementWindowResponse],
        operation_id="listCustomerMeasurementWindows",
    )
    def windows(
        project_id: UUID,
        campaign_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> list[MeasurementWindowResponse]:
        approved = _approved(request, authorization, project_id, campaign_id)
        return [_window_response(item) for item in approved]

    @router.get(
        "/verified-urls",
        response_model=list[VerifiedUrlResponse],
        operation_id="listCustomerVerifiedUrls",
    )
    def verified_urls(
        project_id: UUID,
        campaign_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> list[VerifiedUrlResponse]:
        principal = _authorize(request, authorization, project_id)
        items = _call(
            lambda: _application(request).list_customer_approved_verified_urls(
                principal, project_id=project_id, campaign_id=campaign_id
            )
        )
        return [VerifiedUrlResponse(**item.__dict__) for item in items]

    @router.get(
        "/reports",
        response_model=list[MonitoringReportResponse],
        operation_id="listCustomerApprovedReports",
    )
    def reports(
        project_id: UUID,
        campaign_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> list[MonitoringReportResponse]:
        approved = _approved(request, authorization, project_id, campaign_id)
        return [report_response(item.report) for item in approved]

    @router.get(
        "/summary",
        response_model=CustomerCampaignSummaryResponse,
        operation_id="getCustomerGeoSummary",
    )
    def summary(
        project_id: UUID,
        campaign_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> CustomerCampaignSummaryResponse:
        principal = _authorize(request, authorization, project_id)
        campaign, approved, urls = _read_model(
            _application(request), principal, project_id, campaign_id
        )
        return _summary_response(campaign, approved, urls)

    return router


def _authorize(
    request: Request, authorization: str | None, project_id: UUID
) -> AccessPrincipal:
    return _principal(request, authorization, project_id, READER_ROLES)


def _approved(
    request: Request,
    authorization: str | None,
    project_id: UUID,
    campaign_id: UUID,
) -> tuple[ApprovedReportSnapshot, ...]:
    principal = _authorize(request, authorization, project_id)
    return _call(
        lambda: _application(request).list_customer_approved_report_snapshots(
            principal, project_id=project_id, campaign_id=campaign_id
        )
    )


def _read_model(
    application: MonitoringApplication,
    principal: AccessPrincipal,
    project_id: UUID,
    campaign_id: UUID,
) -> tuple[
    CustomerCampaign,
    tuple[ApprovedReportSnapshot, ...],
    tuple[VerifiedUrl, ...],
]:
    campaign = _call(
        lambda: application.get_customer_campaign(
            principal, project_id=project_id, campaign_id=campaign_id
        )
    )
    approved = _call(
        lambda: application.list_customer_approved_report_snapshots(
            principal, project_id=project_id, campaign_id=campaign_id
        )
    )
    urls = _call(
        lambda: application.list_customer_approved_verified_urls(
            principal, project_id=project_id, campaign_id=campaign_id
        )
    )
    return campaign, approved, urls


def _campaign_response(item: CustomerCampaign) -> CustomerCampaignResponse:
    return CustomerCampaignResponse(**item.__dict__)


def _approved_response(
    item: ApprovedReportSnapshot,
) -> CustomerApprovedMeasurementResponse:
    return CustomerApprovedMeasurementResponse(
        report=report_response(item.report),
        snapshot=metric_response(item.snapshot),
        snapshot_contract=item.snapshot_contract,
    )


def _window_response(item: ApprovedReportSnapshot) -> MeasurementWindowResponse:
    snapshot = item.snapshot
    return MeasurementWindowResponse(
        protocol_id=snapshot.protocol_id,
        campaign_id=snapshot.campaign_id,
        measurement_window=snapshot.measurement_window.value,
        expected_sample_count=snapshot.expected_sample_count,
        eligible_sample_count=snapshot.eligible_sample_count,
        status=cast(Any, snapshot.status),
        confounded_reasons=list(snapshot.confounded_reasons),
        computed_at=snapshot.computed_at,
    )


def _summary_response(
    campaign: CustomerCampaign,
    approved: tuple[ApprovedReportSnapshot, ...],
    urls: tuple[VerifiedUrl, ...],
) -> CustomerCampaignSummaryResponse:
    return CustomerCampaignSummaryResponse(
        project_id=campaign.project_id,
        campaign_id=campaign.id,
        campaign_name=campaign.name,
        campaign_objective=campaign.objective,
        campaign_status=campaign.status,
        frozen_protocol_count=len({item.snapshot.protocol_id for item in approved}),
        measurement_window_count=len(approved),
        verified_url_count=len(urls),
        approved_report_count=campaign.approved_report_count,
        latest_metrics=[metric_response(item.snapshot) for item in approved],
        interpretation=REPORT_METHODOLOGY,
    )
