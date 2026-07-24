"""Internal-only semantic metric, statistical comparison and drift routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request

from geo_api.stable_routes import PROBLEM_RESPONSES
from geo_api.workflow_c_analysis_contracts import (
    AnalyzeComparisonFamilyRequest,
    ComparisonFamilyPageResponse,
    ComparisonFamilyResponse,
    ComputeDriftRequest,
    ComputeSemanticMetricsRequest,
    DriftReportPageResponse,
    DriftReportResponse,
    SemanticMetricSnapshotPageResponse,
    SemanticMetricSnapshotResponse,
)
from geo_api.workflow_c_presenters import (
    comparison_family_page_response,
    comparison_family_response,
    drift_report_page_response,
    drift_report_response,
    semantic_snapshot_page_response,
    semantic_snapshot_response,
)
from geo_api.workflow_c_routes import (
    AuthorizationHeader,
    READ_ROLES,
    WRITE_ROLES,
    authorize_workflow_c,
    workflow_c_api,
    workflow_c_call,
)


def workflow_c_analysis_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/analysis",
        tags=["workflow C analysis"],
        responses=PROBLEM_RESPONSES,
    )

    @router.post(
        "/semantic-metrics/compute",
        response_model=SemanticMetricSnapshotResponse,
        operation_id="computeSemanticMetricSnapshot",
    )
    def compute_semantic_metrics(
        project_id: UUID,
        payload: ComputeSemanticMetricsRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> SemanticMetricSnapshotResponse:
        authorize_workflow_c(request, authorization, project_id, WRITE_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).analysis.compute_semantic_metrics(
                project_id=project_id, payload=payload
            )
        )
        return semantic_snapshot_response(project_id, result)

    @router.get(
        "/semantic-metrics",
        response_model=SemanticMetricSnapshotPageResponse,
        operation_id="listSemanticMetricSnapshots",
    )
    def list_semantic_metrics(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> SemanticMetricSnapshotPageResponse:
        authorize_workflow_c(request, authorization, project_id, READ_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).analysis.list_semantic_snapshots(
                project_id=project_id
            )
        )
        return semantic_snapshot_page_response(project_id, result)

    @router.get(
        "/semantic-metrics/{snapshot_hash}",
        response_model=SemanticMetricSnapshotResponse,
        operation_id="getSemanticMetricSnapshot",
    )
    def get_semantic_metrics(
        project_id: UUID,
        snapshot_hash: str,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> SemanticMetricSnapshotResponse:
        authorize_workflow_c(request, authorization, project_id, READ_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).analysis.get_semantic_snapshot(
                project_id=project_id, snapshot_hash=snapshot_hash
            )
        )
        return semantic_snapshot_response(project_id, result)

    @router.post(
        "/comparisons/analyze",
        response_model=ComparisonFamilyResponse,
        operation_id="analyzeComparisonFamily",
    )
    def analyze_comparisons(
        project_id: UUID,
        payload: AnalyzeComparisonFamilyRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> ComparisonFamilyResponse:
        authorize_workflow_c(request, authorization, project_id, WRITE_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).analysis.analyze_comparisons(
                project_id=project_id, payload=payload
            )
        )
        return comparison_family_response(project_id, result)

    @router.get(
        "/comparisons",
        response_model=ComparisonFamilyPageResponse,
        operation_id="listComparisonFamilies",
    )
    def list_comparisons(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> ComparisonFamilyPageResponse:
        authorize_workflow_c(request, authorization, project_id, READ_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).analysis.list_comparison_families(
                project_id=project_id
            )
        )
        return comparison_family_page_response(project_id, result)

    @router.get(
        "/comparisons/{family_hash}",
        response_model=ComparisonFamilyResponse,
        operation_id="getComparisonFamily",
    )
    def get_comparisons(
        project_id: UUID,
        family_hash: str,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> ComparisonFamilyResponse:
        authorize_workflow_c(request, authorization, project_id, READ_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).analysis.get_comparison_family(
                project_id=project_id, family_hash=family_hash
            )
        )
        return comparison_family_response(project_id, result)

    @router.post(
        "/drift/compute",
        response_model=DriftReportResponse,
        operation_id="computeDriftReport",
    )
    def compute_drift(
        project_id: UUID,
        payload: ComputeDriftRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> DriftReportResponse:
        authorize_workflow_c(request, authorization, project_id, WRITE_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).analysis.compute_drift(
                project_id=project_id, payload=payload
            )
        )
        return drift_report_response(project_id, result)

    @router.get(
        "/drift",
        response_model=DriftReportPageResponse,
        operation_id="listDriftReports",
    )
    def list_drift_reports(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> DriftReportPageResponse:
        authorize_workflow_c(request, authorization, project_id, READ_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).analysis.list_drift_reports(
                project_id=project_id
            )
        )
        return drift_report_page_response(project_id, result)

    @router.get(
        "/drift/{report_hash}",
        response_model=DriftReportResponse,
        operation_id="getDriftReport",
    )
    def get_drift(
        project_id: UUID,
        report_hash: str,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> DriftReportResponse:
        authorize_workflow_c(request, authorization, project_id, READ_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).analysis.get_drift_report(
                project_id=project_id, report_hash=report_hash
            )
        )
        return drift_report_response(project_id, result)

    return router
