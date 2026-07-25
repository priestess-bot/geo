"""Metric Protocol routes installed on the Workflow C analysis router."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status

from geo_api.workflow_c_analysis_contracts import (
    CreateMetricProtocolRequest,
    MetricProtocolDecisionRequest,
    MetricProtocolPageResponse,
    MetricProtocolResponse,
    MetricProtocolTransitionRequest,
)
from geo_api.workflow_c_routes import (
    AuthorizationHeader,
    IdempotencyHeader,
    MANAGE_ROLES,
    READ_ROLES,
    authorize_workflow_c,
    workflow_c_api,
    workflow_c_call,
)
from geo_core.workflow_c_analysis_admission import (
    MetricProtocolStatus,
    MetricProtocolVersion,
)


def install_metric_protocol_routes(router: APIRouter) -> None:
    @router.post(
        "/metric-protocols",
        response_model=MetricProtocolResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createMetricProtocol",
    )
    def create_metric_protocol(
        project_id: UUID,
        payload: CreateMetricProtocolRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> MetricProtocolResponse:
        principal = authorize_workflow_c(request, authorization, project_id, MANAGE_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).analysis.create_metric_protocol(
                project_id=project_id,
                payload=payload,
                actor_id=principal.actor_id,
                idempotency_key=idempotency_key,
            )
        )
        return _metric_protocol_response(result)

    @router.get(
        "/metric-protocols",
        response_model=MetricProtocolPageResponse,
        operation_id="listMetricProtocols",
    )
    def list_metric_protocols(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> MetricProtocolPageResponse:
        authorize_workflow_c(request, authorization, project_id, READ_ROLES)
        values = workflow_c_call(
            lambda: workflow_c_api(request).analysis.list_metric_protocols(project_id=project_id)
        )
        items = [_metric_protocol_response(item) for item in values]
        return MetricProtocolPageResponse(items=items, total=len(items))

    @router.get(
        "/metric-protocols/{protocol_id}",
        response_model=MetricProtocolResponse,
        operation_id="getMetricProtocol",
    )
    def get_metric_protocol(
        project_id: UUID,
        protocol_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> MetricProtocolResponse:
        authorize_workflow_c(request, authorization, project_id, READ_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).analysis.get_metric_protocol(
                project_id=project_id, protocol_id=protocol_id
            )
        )
        return _metric_protocol_response(result)

    def transition_protocol(
        *,
        project_id: UUID,
        protocol_id: UUID,
        target: MetricProtocolStatus,
        payload: MetricProtocolTransitionRequest,
        request: Request,
        authorization: str | None,
        idempotency_key: str,
    ) -> MetricProtocolResponse:
        principal = authorize_workflow_c(request, authorization, project_id, MANAGE_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).analysis.transition_metric_protocol(
                project_id=project_id,
                protocol_id=protocol_id,
                target_status=target,
                payload=payload,
                actor_id=principal.actor_id,
                idempotency_key=idempotency_key,
            )
        )
        return _metric_protocol_response(result)

    @router.post(
        "/metric-protocols/{protocol_id}/submit",
        response_model=MetricProtocolResponse,
        operation_id="submitMetricProtocol",
    )
    def submit_metric_protocol_route(
        project_id: UUID,
        protocol_id: UUID,
        payload: MetricProtocolTransitionRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> MetricProtocolResponse:
        return transition_protocol(
            project_id=project_id,
            protocol_id=protocol_id,
            target=MetricProtocolStatus.IN_REVIEW,
            payload=payload,
            request=request,
            authorization=authorization,
            idempotency_key=idempotency_key,
        )

    @router.post(
        "/metric-protocols/{protocol_id}/approve",
        response_model=MetricProtocolResponse,
        operation_id="approveMetricProtocol",
    )
    def approve_metric_protocol_route(
        project_id: UUID,
        protocol_id: UUID,
        payload: MetricProtocolDecisionRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> MetricProtocolResponse:
        return transition_protocol(
            project_id=project_id,
            protocol_id=protocol_id,
            target=MetricProtocolStatus.APPROVED,
            payload=payload,
            request=request,
            authorization=authorization,
            idempotency_key=idempotency_key,
        )

    @router.post(
        "/metric-protocols/{protocol_id}/retire",
        response_model=MetricProtocolResponse,
        operation_id="retireMetricProtocol",
    )
    def retire_metric_protocol_route(
        project_id: UUID,
        protocol_id: UUID,
        payload: MetricProtocolDecisionRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> MetricProtocolResponse:
        return transition_protocol(
            project_id=project_id,
            protocol_id=protocol_id,
            target=MetricProtocolStatus.RETIRED,
            payload=payload,
            request=request,
            authorization=authorization,
            idempotency_key=idempotency_key,
        )


def _metric_protocol_response(value: MetricProtocolVersion) -> MetricProtocolResponse:
    return MetricProtocolResponse(
        id=value.id,
        project_id=value.project_id,
        series_id=value.series_id,
        version=value.version,
        supersedes_protocol_id=value.supersedes_protocol_id,
        status=value.status.value,
        protocol_hash=value.protocol_hash,
        definition=value.definition.canonical_value(),
        created_by=value.created_by,
        submitted_by=value.submitted_by,
        approved_by=value.approved_by,
        retired_by=value.retired_by,
        decision_reason=value.decision_reason,
        aggregate_version=value.aggregate_version,
        created_at=value.created_at,
        updated_at=value.updated_at,
        submitted_at=value.submitted_at,
        approved_at=value.approved_at,
        retired_at=value.retired_at,
    )
