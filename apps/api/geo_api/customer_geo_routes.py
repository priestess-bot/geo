"""Customer-safe, read-only GEO measurement and approved reporting routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Request

from geo_api.monitoring_contracts import (
    CustomerGeoSummaryResponse,
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
from geo_core.monitoring.domain import READER_ROLES, REPORT_METHODOLOGY


AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]


def customer_geo_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/geo",
        tags=["customer GEO reporting"],
        responses=PROBLEM_RESPONSES,
    )

    @router.get("/metrics", response_model=list[MetricResponse], operation_id="listCustomerGeoMetrics")
    def metrics(
        project_id: UUID,
        request: Request,
        campaign_id: UUID | None = None,
        authorization: AuthorizationHeader = None,
    ) -> list[MetricResponse]:
        principal = _principal(request, authorization, project_id, READER_ROLES)
        items = _call(
            lambda: _application(request).list_metrics(principal, project_id=project_id)
        )
        return [
            metric_response(item)
            for item in items
            if campaign_id is None or item.campaign_id == campaign_id
        ]

    @router.get(
        "/measurement-windows",
        response_model=list[MeasurementWindowResponse],
        operation_id="listCustomerMeasurementWindows",
    )
    def windows(
        project_id: UUID,
        request: Request,
        campaign_id: UUID | None = None,
        authorization: AuthorizationHeader = None,
    ) -> list[MeasurementWindowResponse]:
        principal = _principal(request, authorization, project_id, READER_ROLES)
        items = _call(
            lambda: _application(request).list_metrics(principal, project_id=project_id)
        )
        return [
            MeasurementWindowResponse(
                protocol_id=item.protocol_id,
                campaign_id=item.campaign_id,
                measurement_window=item.measurement_window.value,
                expected_sample_count=item.expected_sample_count,
                eligible_sample_count=item.eligible_sample_count,
                status=item.status,
                confounded_reasons=list(item.confounded_reasons),
                computed_at=item.computed_at,
            )
            for item in items
            if campaign_id is None or item.campaign_id == campaign_id
        ]

    @router.get(
        "/verified-urls",
        response_model=list[VerifiedUrlResponse],
        operation_id="listCustomerVerifiedUrls",
    )
    def verified_urls(
        project_id: UUID,
        request: Request,
        campaign_id: UUID | None = None,
        authorization: AuthorizationHeader = None,
    ) -> list[VerifiedUrlResponse]:
        principal = _principal(request, authorization, project_id, READER_ROLES)
        items = _call(
            lambda: _application(request).list_verified_urls(principal, project_id=project_id)
        )
        return [
            VerifiedUrlResponse(**item.__dict__)
            for item in items
            if campaign_id is None or item.campaign_id == campaign_id
        ]

    @router.get(
        "/reports",
        response_model=list[MonitoringReportResponse],
        operation_id="listCustomerApprovedReports",
    )
    def reports(
        project_id: UUID,
        request: Request,
        campaign_id: UUID | None = None,
        authorization: AuthorizationHeader = None,
    ) -> list[MonitoringReportResponse]:
        principal = _principal(request, authorization, project_id, READER_ROLES)
        items = _call(
            lambda: _application(request).list_reports(
                principal, project_id=project_id, approved_only=True
            )
        )
        return [
            report_response(item)
            for item in items
            if campaign_id is None or item.campaign_id == campaign_id
        ]

    @router.get(
        "/summary",
        response_model=CustomerGeoSummaryResponse,
        operation_id="getCustomerGeoSummary",
    )
    def summary(
        project_id: UUID,
        request: Request,
        campaign_id: UUID | None = None,
        authorization: AuthorizationHeader = None,
    ) -> CustomerGeoSummaryResponse:
        principal = _principal(request, authorization, project_id, READER_ROLES)
        application = _application(request)
        metrics = _call(lambda: application.list_metrics(principal, project_id=project_id))
        urls = _call(lambda: application.list_verified_urls(principal, project_id=project_id))
        reports = _call(
            lambda: application.list_reports(
                principal, project_id=project_id, approved_only=True
            )
        )
        protocols = _call(
            lambda: application.list_protocols(principal, project_id=project_id)
        )
        if campaign_id is not None:
            metrics = tuple(item for item in metrics if item.campaign_id == campaign_id)
            urls = tuple(item for item in urls if item.campaign_id == campaign_id)
            reports = tuple(item for item in reports if item.campaign_id == campaign_id)
            protocols = tuple(item for item in protocols if item.campaign_id == campaign_id)
        return CustomerGeoSummaryResponse(
            project_id=project_id,
            campaign_id=campaign_id,
            frozen_protocol_count=sum(item.status.value == "frozen" for item in protocols),
            measurement_window_count=len(metrics),
            verified_url_count=len(urls),
            approved_report_count=len(reports),
            latest_metrics=[metric_response(item) for item in metrics],
            interpretation=REPORT_METHODOLOGY,
        )

    return router
