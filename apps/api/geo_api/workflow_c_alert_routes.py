"""Internal-only alert lifecycle and notification projection routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request

from geo_api.stable_routes import PROBLEM_RESPONSES
from geo_api.workflow_c_alert_contracts import (
    AlertCommandResponse,
    AlertPageResponse,
    AlertResponse,
    AlertTransitionRequest,
    NotificationProjectionResponse,
    SuppressAlertRequest,
)
from geo_api.workflow_c_presenters import (
    alert_command_response,
    alert_page_response,
    alert_response,
    notification_response,
)
from geo_api.workflow_c_routes import (
    AuthorizationHeader,
    IdempotencyHeader,
    READ_ROLES,
    WRITE_ROLES,
    authorize_workflow_c,
    workflow_c_api,
    workflow_c_call,
)


def workflow_c_alert_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/alerts",
        tags=["workflow C alerts"],
        responses=PROBLEM_RESPONSES,
    )

    @router.get("", response_model=AlertPageResponse, operation_id="listAlerts")
    def list_alerts(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> AlertPageResponse:
        authorize_workflow_c(request, authorization, project_id, READ_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).alerts.list_alerts(project_id=project_id)
        )
        return alert_page_response(result)

    @router.get(
        "/{alert_id}", response_model=AlertResponse, operation_id="getAlert"
    )
    def get_alert(
        project_id: UUID,
        alert_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> AlertResponse:
        authorize_workflow_c(request, authorization, project_id, READ_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).alerts.get_alert(
                project_id=project_id, alert_id=alert_id
            )
        )
        return alert_response(result)

    @router.get(
        "/{alert_id}/notifications",
        response_model=list[NotificationProjectionResponse],
        operation_id="listAlertNotificationProjections",
    )
    def list_notifications(
        project_id: UUID,
        alert_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> list[NotificationProjectionResponse]:
        authorize_workflow_c(request, authorization, project_id, READ_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).alerts.notifications(
                project_id=project_id, alert_id=alert_id
            )
        )
        return [notification_response(item) for item in result]

    @router.post(
        "/{alert_id}/acknowledge",
        response_model=AlertCommandResponse,
        operation_id="acknowledgeAlert",
    )
    def acknowledge(
        project_id: UUID,
        alert_id: UUID,
        payload: AlertTransitionRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> AlertCommandResponse:
        principal = authorize_workflow_c(
            request, authorization, project_id, WRITE_ROLES
        )
        result = workflow_c_call(
            lambda: workflow_c_api(request).alerts.acknowledge(
                project_id=project_id,
                alert_id=alert_id,
                actor_id=principal.actor_id,
                idempotency_key=idempotency_key,
                payload=payload,
            )
        )
        return alert_command_response(result)

    @router.post(
        "/{alert_id}/suppress",
        response_model=AlertCommandResponse,
        operation_id="suppressAlert",
    )
    def suppress(
        project_id: UUID,
        alert_id: UUID,
        payload: SuppressAlertRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> AlertCommandResponse:
        principal = authorize_workflow_c(
            request, authorization, project_id, WRITE_ROLES
        )
        result = workflow_c_call(
            lambda: workflow_c_api(request).alerts.suppress(
                project_id=project_id,
                alert_id=alert_id,
                actor_id=principal.actor_id,
                idempotency_key=idempotency_key,
                payload=payload,
            )
        )
        return alert_command_response(result)

    @router.post(
        "/{alert_id}/unsuppress",
        response_model=AlertCommandResponse,
        operation_id="unsuppressAlert",
    )
    def unsuppress(
        project_id: UUID,
        alert_id: UUID,
        payload: AlertTransitionRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> AlertCommandResponse:
        principal = authorize_workflow_c(
            request, authorization, project_id, WRITE_ROLES
        )
        result = workflow_c_call(
            lambda: workflow_c_api(request).alerts.unsuppress(
                project_id=project_id,
                alert_id=alert_id,
                actor_id=principal.actor_id,
                idempotency_key=idempotency_key,
                payload=payload,
            )
        )
        return alert_command_response(result)

    @router.post(
        "/{alert_id}/resolve",
        response_model=AlertCommandResponse,
        operation_id="resolveAlert",
    )
    def resolve(
        project_id: UUID,
        alert_id: UUID,
        payload: AlertTransitionRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> AlertCommandResponse:
        principal = authorize_workflow_c(
            request, authorization, project_id, WRITE_ROLES
        )
        result = workflow_c_call(
            lambda: workflow_c_api(request).alerts.resolve(
                project_id=project_id,
                alert_id=alert_id,
                actor_id=principal.actor_id,
                idempotency_key=idempotency_key,
                payload=payload,
            )
        )
        return alert_command_response(result)

    return router
