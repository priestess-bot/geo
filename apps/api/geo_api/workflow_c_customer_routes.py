"""Customer-only reader for approved, non-manual Workflow C reports."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Request

from geo_api.customer_geo_contracts import StrictModel
from geo_api.monitoring_dependencies import authorize_monitoring_project
from geo_api.problems import ApiProblem
from geo_api.stable_routes import PROBLEM_RESPONSES
from geo_api.workflow_c_customer_contracts import WorkflowCCustomerReportResponse
from geo_core.monitoring.domain import READER_ROLES
from geo_core.workflow_c_reports import WorkflowCCustomerReportReader


AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]


class WorkflowCCustomerReportPageResponse(StrictModel):
    items: list[WorkflowCCustomerReportResponse]
    total: int


def workflow_c_customer_router(
    *, reader: WorkflowCCustomerReportReader | None
) -> APIRouter:
    """Mount a stable Customer contract without ever using a memory fallback."""

    if reader is not None and reader.persistence != "durable":
        raise ValueError("Workflow C Customer reader must be durable")
    router = APIRouter(
        prefix="/v1/projects/{project_id}/geo",
        tags=["customer Workflow C reporting"],
        responses=PROBLEM_RESPONSES,
    )

    @router.get(
        "/workflow-c-reports",
        response_model=WorkflowCCustomerReportPageResponse,
        operation_id="listCustomerWorkflowCApprovedReports",
    )
    def reports(
        project_id: UUID,
        campaign_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> WorkflowCCustomerReportPageResponse:
        authorize_monitoring_project(
            request, authorization, project_id, READER_ROLES
        )
        if reader is None:
            raise ApiProblem(
                status=503,
                title="Service Unavailable",
                detail="Workflow C Customer report reader is not configured.",
                type_uri="urn:geo:problem:workflow-c-customer-unavailable",
                headers={"Retry-After": "30"},
            )
        reports = reader.list_approved_reports(
            project_id=project_id,
            campaign_id=campaign_id,
        )
        return WorkflowCCustomerReportPageResponse(
            items=[
                WorkflowCCustomerReportResponse(
                    id=item.id,
                    project_id=item.project_id,
                    campaign_id=item.campaign_id,
                    semantic_snapshot_hash=item.semantic_snapshot_hash,
                    report_hash=item.report_hash,
                    source_kind=item.source_kind,
                    approved_safe_payload=dict(item.approved_safe_payload),
                    approved_at=item.approved_at,
                )
                for item in reports
            ],
            total=len(reports),
        )

    return router


__all__ = [
    "WorkflowCCustomerReportPageResponse",
    "workflow_c_customer_router",
]
