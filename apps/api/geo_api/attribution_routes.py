"""Admin and public collector routes for local attribution."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Request, status

from geo_api.attribution_contracts import (
    AttributionCollectorCreatedResponse,
    AttributionEventAcceptedResponse,
    AttributionInventoryResponse,
    AttributionPolicyResponse,
    AttributionSnapshotResponse,
    AttributionTraceCreatedResponse,
    BusinessImportResponse,
    BusinessEventResponse,
    CollectAttributionEventRequest,
    CreateAttributionCollectorRequest,
    CreateAttributionPolicyRequest,
    CreateAttributionSnapshotRequest,
    IssueAttributionTraceRequest,
    ImportBusinessEventsRequest,
    RecordBusinessEventRequest,
)
from geo_api.catalog_routes import _principal
from geo_api.connector_routes import _require_admin
from geo_api.foundation_services import FoundationServiceUnavailable
from geo_api.problems import ApiProblem
from geo_api.stable_routes import PROBLEM_RESPONSES
from geo_core.attribution import AttributionError, AttributionService


AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]
OriginHeader = Annotated[str, Header(alias="Origin")]
CollectorKeyHeader = Annotated[str, Header(alias="X-GEO-Write-Key")]


def attribution_router() -> APIRouter:
    router = APIRouter(tags=["local attribution"], responses=PROBLEM_RESPONSES)

    @router.get(
        "/v1/projects/{project_id}/attribution",
        response_model=AttributionInventoryResponse,
        operation_id="getAttributionInventory",
    )
    def inventory(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> AttributionInventoryResponse:
        _require_admin(_principal(request, authorization), project_id)
        return AttributionInventoryResponse.model_validate(
            _call(lambda: _service(request).inventory(project_id=project_id))
        )

    @router.post(
        "/v1/projects/{project_id}/attribution/policies",
        response_model=AttributionPolicyResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_policy(
        project_id: UUID,
        payload: CreateAttributionPolicyRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> AttributionPolicyResponse:
        principal = _require_admin(_principal(request, authorization), project_id)
        return AttributionPolicyResponse.model_validate(
            _call(
                lambda: _service(request).create_policy(
                    project_id=project_id,
                    actor_id=principal.identity_id,
                    **payload.model_dump(),
                )
            )
        )

    @router.post(
        "/v1/projects/{project_id}/attribution/collectors",
        response_model=AttributionCollectorCreatedResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_collector(
        project_id: UUID,
        payload: CreateAttributionCollectorRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> AttributionCollectorCreatedResponse:
        principal = _require_admin(_principal(request, authorization), project_id)
        return AttributionCollectorCreatedResponse.model_validate(
            _call(
                lambda: _service(request).create_collector(
                    project_id=project_id,
                    actor_id=principal.identity_id,
                    **payload.model_dump(),
                )
            )
        )

    @router.post(
        "/v1/projects/{project_id}/attribution/traces",
        response_model=AttributionTraceCreatedResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def issue_trace(
        project_id: UUID,
        payload: IssueAttributionTraceRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> AttributionTraceCreatedResponse:
        principal = _require_admin(_principal(request, authorization), project_id)
        return AttributionTraceCreatedResponse.model_validate(
            _call(
                lambda: _service(request).issue_trace(
                    project_id=project_id,
                    actor_id=principal.identity_id,
                    **payload.model_dump(),
                )
            )
        )

    @router.post(
        "/v1/projects/{project_id}/attribution/business-events",
        response_model=BusinessEventResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def business_event(
        project_id: UUID,
        payload: RecordBusinessEventRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> BusinessEventResponse:
        _require_admin(_principal(request, authorization), project_id)
        item = _call(
            lambda: _service(request).record_business_event(
                project_id=project_id, **payload.model_dump()
            )
        )
        return BusinessEventResponse.model_validate(
            {key: item[key] for key in BusinessEventResponse.model_fields}
        )

    @router.post(
        "/v1/projects/{project_id}/attribution/snapshots",
        response_model=AttributionSnapshotResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def snapshot(
        project_id: UUID,
        payload: CreateAttributionSnapshotRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> AttributionSnapshotResponse:
        principal = _require_admin(_principal(request, authorization), project_id)
        return AttributionSnapshotResponse.model_validate(
            _call(
                lambda: _service(request).create_snapshot(
                    project_id=project_id,
                    actor_id=principal.identity_id,
                    **payload.model_dump(),
                )
            )
        )

    @router.post(
        "/v1/projects/{project_id}/attribution/imports",
        response_model=BusinessImportResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="importAttributionBusinessEvents",
    )
    def import_business_events(
        project_id: UUID,
        payload: ImportBusinessEventsRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> BusinessImportResponse:
        principal = _require_admin(_principal(request, authorization), project_id)
        return BusinessImportResponse.model_validate(
            _call(
                lambda: _service(request).import_business_rows(
                    project_id=project_id,
                    actor_id=principal.identity_id,
                    template_schema_version=payload.template_schema_version,
                    rows=[row.model_dump() for row in payload.rows],
                )
            )
        )

    @router.post(
        "/v1/collect/{project_id}/{collector_id}/events",
        response_model=AttributionEventAcceptedResponse,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="collectFirstPartyAttributionEvent",
    )
    def collect(
        project_id: UUID,
        collector_id: UUID,
        payload: CollectAttributionEventRequest,
        request: Request,
        origin: OriginHeader,
        write_key: CollectorKeyHeader,
    ) -> AttributionEventAcceptedResponse:
        return AttributionEventAcceptedResponse.model_validate(
            _call(
                lambda: _service(request).collect(
                    project_id=project_id,
                    collector_id=collector_id,
                    origin=origin,
                    write_key=write_key,
                    **payload.model_dump(),
                )
            )
        )
    return router


def _service(request: Request) -> AttributionService:
    service = getattr(request.app.state, "attribution_service", None)
    if not isinstance(service, AttributionService):
        raise FoundationServiceUnavailable("Local attribution persistence is unavailable.")
    return service


def _call(operation):
    try:
        return operation()
    except AttributionError as error:
        raise ApiProblem(
            status=409,
            title="Attribution Event Rejected",
            detail=str(error),
            type_uri="urn:geo:problem:attribution-rejected",
        ) from error


__all__ = ["attribution_router"]
