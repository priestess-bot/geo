"""Internal-only Workflow C report approval routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status

from geo_api.stable_routes import PROBLEM_RESPONSES
from geo_api.workflow_c_report_contracts import (
    CreateWorkflowCReportRequest,
    WorkflowCReportTerminalTransitionRequest,
    WorkflowCReportTransitionRequest,
    WorkflowCReportVersionPageResponse,
    WorkflowCReportVersionResponse,
)
from geo_api.workflow_c_report_payload_contracts import WorkflowCCustomerSafePayload
from geo_api.workflow_c_routes import (
    AuthorizationHeader,
    IdempotencyHeader,
    MANAGE_ROLES,
    READ_ROLES,
    authorize_workflow_c,
    workflow_c_api,
    workflow_c_call,
)
from geo_core.workflow_c_reports import WorkflowCReportSnapshotVersion


def workflow_c_report_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/analysis/reports",
        tags=["workflow C reports"],
        responses=PROBLEM_RESPONSES,
    )

    @router.post(
        "",
        response_model=WorkflowCReportVersionResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createWorkflowCReportDraft",
    )
    def create(
        project_id: UUID,
        payload: CreateWorkflowCReportRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> WorkflowCReportVersionResponse:
        principal = authorize_workflow_c(request, authorization, project_id, MANAGE_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).reports.create_draft(
                project_id=project_id,
                payload=payload,
                actor_id=principal.identity_id,
                idempotency_key=idempotency_key,
            )
        )
        return _response(result)

    @router.get("", response_model=WorkflowCReportVersionPageResponse, operation_id="listWorkflowCReports")
    def list_reports(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> WorkflowCReportVersionPageResponse:
        authorize_workflow_c(request, authorization, project_id, READ_ROLES)
        items = workflow_c_call(
            lambda: workflow_c_api(request).reports.list(project_id=project_id)
        )
        return WorkflowCReportVersionPageResponse(
            items=[_response(item) for item in items], total=len(items)
        )

    @router.get(
        "/{report_id}",
        response_model=WorkflowCReportVersionResponse,
        operation_id="getWorkflowCReport",
    )
    def get_report(
        project_id: UUID,
        report_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> WorkflowCReportVersionResponse:
        authorize_workflow_c(request, authorization, project_id, READ_ROLES)
        return _response(
            workflow_c_call(
                lambda: workflow_c_api(request).reports.get(
                    project_id=project_id, report_id=report_id
                )
            )
        )

    def transition(
        *,
        project_id: UUID,
        report_id: UUID,
        target: str,
        expected_version: int,
        reason: str | None,
        idempotency_key: str,
        request: Request,
        authorization: str | None,
    ) -> WorkflowCReportVersionResponse:
        principal = authorize_workflow_c(request, authorization, project_id, MANAGE_ROLES)
        return _response(
            workflow_c_call(
                lambda: workflow_c_api(request).reports.transition(
                    project_id=project_id,
                    report_id=report_id,
                    expected_version=expected_version,
                    target_status=target,  # type: ignore[arg-type]
                    actor_id=principal.identity_id,
                    reason=reason,
                    idempotency_key=idempotency_key,
                )
            )
        )

    @router.post("/{report_id}/submit", response_model=WorkflowCReportVersionResponse, operation_id="submitWorkflowCReport")
    def submit(
        project_id: UUID,
        report_id: UUID,
        payload: WorkflowCReportTransitionRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> WorkflowCReportVersionResponse:
        return transition(
            project_id=project_id, report_id=report_id, target="in_review",
            expected_version=payload.expected_version, reason=None,
            idempotency_key=idempotency_key,
            request=request, authorization=authorization,
        )

    @router.post("/{report_id}/approve", response_model=WorkflowCReportVersionResponse, operation_id="approveWorkflowCReport")
    def approve(
        project_id: UUID,
        report_id: UUID,
        payload: WorkflowCReportTransitionRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> WorkflowCReportVersionResponse:
        return transition(
            project_id=project_id, report_id=report_id, target="approved",
            expected_version=payload.expected_version, reason=payload.reason,
            idempotency_key=idempotency_key,
            request=request, authorization=authorization,
        )

    def terminal_route(target: str):
        def command(
            project_id: UUID,
            report_id: UUID,
            payload: WorkflowCReportTerminalTransitionRequest,
            request: Request,
            idempotency_key: IdempotencyHeader,
            authorization: AuthorizationHeader = None,
        ) -> WorkflowCReportVersionResponse:
            return transition(
                project_id=project_id, report_id=report_id, target=target,
                expected_version=payload.expected_version, reason=payload.reason,
                idempotency_key=idempotency_key,
                request=request, authorization=authorization,
            )
        return command

    router.add_api_route(
        "/{report_id}/stale", terminal_route("stale"), methods=["POST"],
        response_model=WorkflowCReportVersionResponse, operation_id="markWorkflowCReportStale",
    )
    router.add_api_route(
        "/{report_id}/supersede", terminal_route("superseded"), methods=["POST"],
        response_model=WorkflowCReportVersionResponse, operation_id="supersedeWorkflowCReport",
    )
    router.add_api_route(
        "/{report_id}/revoke", terminal_route("revoked"), methods=["POST"],
        response_model=WorkflowCReportVersionResponse, operation_id="revokeWorkflowCReport",
    )
    return router


def _response(item: WorkflowCReportSnapshotVersion) -> WorkflowCReportVersionResponse:
    return WorkflowCReportVersionResponse(
        report_id=item.report_id,
        project_id=item.project_id,
        version=item.version,
        status=item.status,
        campaign_id=item.campaign_id,
        monitoring_report_id=item.monitoring_report_id,
        monitoring_report_hash=item.monitoring_report_hash,
        semantic_snapshot_hash=item.semantic_snapshot_hash,
        source_kind=item.source_kind,
        approved_safe_payload=WorkflowCCustomerSafePayload.model_validate(
            item.approved_safe_payload
        ),
        approved_safe_payload_hash=item.approved_safe_payload_hash,
        version_hash=item.version_hash,
        actor_id=item.actor_id,
        reason=item.reason,
        occurred_at=item.occurred_at,
    )


__all__ = ["workflow_c_report_router"]
