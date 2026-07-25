"""Internal-only alert lifecycle and notification projection routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, Response, status

from geo_api.stable_routes import PROBLEM_RESPONSES
from geo_api.workflow_c_alert_contracts import (
    AlertCommandResponse,
    AlertEvaluationJobAccepted,
    AlertPageResponse,
    AlertRuleReleasePageResponse,
    AlertRuleReleaseResponse,
    AlertRuleTransitionRequest,
    AlertResponse,
    AlertTransitionRequest,
    CreateAlertRuleRequest,
    EnqueueAlertEvaluationRequest,
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
    MANAGE_ROLES,
    READ_ROLES,
    WRITE_ROLES,
    authorize_workflow_c,
    workflow_c_api,
    workflow_c_call,
)
from geo_core.workflow_c_alert_rules import AlertRuleRelease, AlertRuleReleaseStatus


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

    @router.post(
        "/rules",
        response_model=AlertRuleReleaseResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createAlertRuleRelease",
    )
    def create_rule(
        project_id: UUID,
        payload: CreateAlertRuleRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> AlertRuleReleaseResponse:
        principal = authorize_workflow_c(
            request, authorization, project_id, MANAGE_ROLES
        )
        result = workflow_c_call(
            lambda: workflow_c_api(request).alerts.create_rule(
                project_id=project_id,
                actor_id=principal.actor_id,
                idempotency_key=idempotency_key,
                payload=payload,
            )
        )
        return _rule_response(result)

    @router.get(
        "/rules",
        response_model=AlertRuleReleasePageResponse,
        operation_id="listAlertRuleReleases",
    )
    def list_rules(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> AlertRuleReleasePageResponse:
        authorize_workflow_c(request, authorization, project_id, READ_ROLES)
        items = workflow_c_call(
            lambda: workflow_c_api(request).alerts.list_rules(project_id=project_id)
        )
        return AlertRuleReleasePageResponse(
            items=[_rule_response(item) for item in items], total=len(items)
        )

    @router.get(
        "/rules/{rule_id}",
        response_model=AlertRuleReleaseResponse,
        operation_id="getAlertRuleRelease",
    )
    def get_rule(
        project_id: UUID,
        rule_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> AlertRuleReleaseResponse:
        authorize_workflow_c(request, authorization, project_id, READ_ROLES)
        return _rule_response(
            workflow_c_call(
                lambda: workflow_c_api(request).alerts.get_rule(
                    project_id=project_id, rule_id=rule_id
                )
            )
        )

    def transition_rule(
        *,
        project_id: UUID,
        rule_id: UUID,
        target_status: AlertRuleReleaseStatus,
        payload: AlertRuleTransitionRequest,
        request: Request,
        idempotency_key: str,
        authorization: str | None,
    ) -> AlertRuleReleaseResponse:
        principal = authorize_workflow_c(
            request, authorization, project_id, MANAGE_ROLES
        )
        return _rule_response(
            workflow_c_call(
                lambda: workflow_c_api(request).alerts.transition_rule(
                    project_id=project_id,
                    rule_id=rule_id,
                    actor_id=principal.actor_id,
                    idempotency_key=idempotency_key,
                    target_status=target_status,
                    payload=payload,
                )
            )
        )

    @router.post(
        "/rules/{rule_id}/approve",
        response_model=AlertRuleReleaseResponse,
        operation_id="approveAlertRuleRelease",
    )
    def approve_rule(
        project_id: UUID,
        rule_id: UUID,
        payload: AlertRuleTransitionRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> AlertRuleReleaseResponse:
        return transition_rule(
            project_id=project_id,
            rule_id=rule_id,
            target_status=AlertRuleReleaseStatus.APPROVED,
            payload=payload,
            request=request,
            idempotency_key=idempotency_key,
            authorization=authorization,
        )

    @router.post(
        "/rules/{rule_id}/retire",
        response_model=AlertRuleReleaseResponse,
        operation_id="retireAlertRuleRelease",
    )
    def retire_rule(
        project_id: UUID,
        rule_id: UUID,
        payload: AlertRuleTransitionRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> AlertRuleReleaseResponse:
        return transition_rule(
            project_id=project_id,
            rule_id=rule_id,
            target_status=AlertRuleReleaseStatus.RETIRED,
            payload=payload,
            request=request,
            idempotency_key=idempotency_key,
            authorization=authorization,
        )

    @router.post(
        "/evaluations/jobs",
        response_model=AlertEvaluationJobAccepted,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="enqueueAlertEvaluationFromFrozenOutput",
    )
    def enqueue_evaluation(
        project_id: UUID,
        payload: EnqueueAlertEvaluationRequest,
        request: Request,
        response: Response,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> AlertEvaluationJobAccepted:
        principal = authorize_workflow_c(
            request, authorization, project_id, MANAGE_ROLES
        )
        receipt = workflow_c_call(
            lambda: workflow_c_api(request).alerts.enqueue_evaluation(
                project_id=project_id,
                actor_id=principal.actor_id,
                idempotency_key=idempotency_key,
                payload=payload,
            )
        )
        status_url = f"/v1/jobs/{receipt.job_id}"
        response.headers["Location"] = status_url
        return AlertEvaluationJobAccepted(
            job_id=receipt.job_id,
            status_url=status_url,
            spec_hash=receipt.spec_hash,
            replayed=receipt.replayed,
        )

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


def _rule_response(release: AlertRuleRelease) -> AlertRuleReleaseResponse:
    rule = release.rule
    return AlertRuleReleaseResponse(
        id=rule.id,
        project_id=rule.project_id,
        rule_key=rule.rule_key,
        version=rule.version,
        kind=rule.kind.value,
        severity=rule.severity.value,
        parameters=dict(rule.parameters),
        rule_hash=rule.rule_hash,
        status=release.status.value,
        aggregate_version=release.aggregate_version,
        created_by=rule.frozen_by,
        created_at=rule.frozen_at,
        approved_by=release.approved_by,
        approved_at=release.approved_at,
        retired_by=release.retired_by,
        retired_at=release.retired_at,
        decision_reason=release.decision_reason,
    )
    CreateAlertRuleRequest,
    EnqueueAlertEvaluationRequest,
