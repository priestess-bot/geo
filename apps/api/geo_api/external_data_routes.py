"""Admin lifecycle and Customer-safe reads for external data."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Request, status

from geo_api.catalog_routes import _principal
from geo_api.connector_routes import _require_admin
from geo_api.external_data_contracts import (
    CreateAttributionExternalReportRequest,
    CreateConnectorExternalReportRequest,
    CreateOfficialExternalReportRequest,
    CustomerExternalDataResponse,
    DecideExternalReportRequest,
    ExternalReportResponse,
    ExternalOperationalAlertInputResponse,
    InvalidateExternalReportRequest,
)
from geo_api.foundation_services import FoundationServiceUnavailable
from geo_api.monitoring_dependencies import authorize_monitoring_project
from geo_api.problems import ApiProblem
from geo_api.stable_routes import PROBLEM_RESPONSES
from geo_core.connectors.external_data import ExternalDataError, ExternalDataService
from geo_core.monitoring.domain import READER_ROLES


AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]


def external_data_admin_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/external-data",
        tags=["external data"],
        responses=PROBLEM_RESPONSES,
    )

    @router.get("/reports", response_model=list[ExternalReportResponse])
    def reports(
        project_id: UUID,
        request: Request,
        campaign_id: UUID | None = None,
        authorization: AuthorizationHeader = None,
    ) -> list[ExternalReportResponse]:
        _require_admin(_principal(request, authorization), project_id)
        return [
            ExternalReportResponse.model_validate(item)
            for item in _call(
                lambda: _service(request).list_reports(
                    project_id=project_id, campaign_id=campaign_id
                )
            )
        ]

    @router.get(
        "/operational-alert-inputs",
        response_model=list[ExternalOperationalAlertInputResponse],
        operation_id="listExternalOperationalAlertInputs",
    )
    def operational_alert_inputs(
        project_id: UUID,
        request: Request,
        limit: int = 100,
        authorization: AuthorizationHeader = None,
    ) -> list[ExternalOperationalAlertInputResponse]:
        _require_admin(_principal(request, authorization), project_id)
        return [
            ExternalOperationalAlertInputResponse.model_validate(item)
            for item in _call(
                lambda: _service(request).list_operational_alert_inputs(
                    project_id=project_id, limit=limit
                )
            )
        ]

    @router.post(
        "/connector-reports",
        response_model=ExternalReportResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def connector_report(
        project_id: UUID,
        payload: CreateConnectorExternalReportRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> ExternalReportResponse:
        principal = _require_admin(_principal(request, authorization), project_id)
        item = _call(
            lambda: _service(request).create_connector_report(
                project_id=project_id,
                actor_id=principal.identity_id,
                **payload.model_dump(),
            )
        )
        return _report_response(item)

    @router.post(
        "/official-reports",
        response_model=ExternalReportResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def official_report(
        project_id: UUID,
        payload: CreateOfficialExternalReportRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> ExternalReportResponse:
        principal = _require_admin(_principal(request, authorization), project_id)
        item = _call(
            lambda: _service(request).create_official_report(
                project_id=project_id,
                actor_id=principal.identity_id,
                **payload.model_dump(),
            )
        )
        return _report_response(item)

    @router.post(
        "/attribution-reports",
        response_model=ExternalReportResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createAttributionExternalReport",
    )
    def attribution_report(
        project_id: UUID,
        payload: CreateAttributionExternalReportRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> ExternalReportResponse:
        principal = _require_admin(_principal(request, authorization), project_id)
        item = _call(
            lambda: _service(request).create_attribution_report(
                project_id=project_id,
                actor_id=principal.identity_id,
                **payload.model_dump(),
            )
        )
        return _report_response(item)

    @router.post("/reports/{report_id}/submit", response_model=ExternalReportResponse)
    def submit(
        project_id: UUID,
        report_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> ExternalReportResponse:
        _require_admin(_principal(request, authorization), project_id)
        return _report_response(
            _call(lambda: _service(request).submit(project_id=project_id, report_id=report_id))
        )

    @router.post("/reports/{report_id}/decide", response_model=ExternalReportResponse)
    def decide(
        project_id: UUID,
        report_id: UUID,
        payload: DecideExternalReportRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> ExternalReportResponse:
        principal = _require_admin(_principal(request, authorization), project_id)
        return _report_response(
            _call(
                lambda: _service(request).decide(
                    project_id=project_id,
                    report_id=report_id,
                    actor_id=principal.identity_id,
                    **payload.model_dump(),
                )
            )
        )

    @router.post("/reports/{report_id}/invalidate", response_model=ExternalReportResponse)
    def invalidate(
        project_id: UUID,
        report_id: UUID,
        payload: InvalidateExternalReportRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> ExternalReportResponse:
        principal = _require_admin(_principal(request, authorization), project_id)
        return _report_response(
            _call(
                lambda: _service(request).invalidate(
                    project_id=project_id,
                    report_id=report_id,
                    actor_id=principal.identity_id,
                    **payload.model_dump(),
                )
            )
        )
    return router


def external_data_customer_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/geo/external-data",
        tags=["customer external data"],
        responses=PROBLEM_RESPONSES,
    )

    @router.get("", response_model=list[CustomerExternalDataResponse])
    def latest(
        project_id: UUID,
        campaign_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> list[CustomerExternalDataResponse]:
        authorize_monitoring_project(request, authorization, project_id, READER_ROLES)
        return [
            CustomerExternalDataResponse.model_validate(item)
            for item in _call(
                lambda: _service(request).latest(
                    project_id=project_id, campaign_id=campaign_id
                )
            )
        ]
    return router


def _service(request: Request) -> ExternalDataService:
    service = getattr(request.app.state, "external_data_service", None)
    if not isinstance(service, ExternalDataService):
        raise FoundationServiceUnavailable("External Data persistence is unavailable.")
    return service


def _report_response(item) -> ExternalReportResponse:
    return ExternalReportResponse.model_validate(
        {key: item[key] for key in ExternalReportResponse.model_fields if key in item}
    )


def _call(operation):
    try:
        return operation()
    except ExternalDataError as error:
        raise ApiProblem(
            status=409,
            title="External Data State Conflict",
            detail=str(error),
            type_uri="urn:geo:problem:external-data-conflict",
        ) from error


__all__ = ["external_data_admin_router", "external_data_customer_router"]
