"""Internal-only semantic metric, statistical comparison and drift routes."""

from __future__ import annotations

from typing import Any, NoReturn
from uuid import UUID

from fastapi import APIRouter, Request, Response, status

from geo_api.problems import ApiProblem
from geo_api.stable_routes import PROBLEM_RESPONSES
from geo_api.workflow_c_metric_protocol_routes import install_metric_protocol_routes
from geo_api.workflow_c_analysis_contracts import (
    AnalyzeComparisonFamilyRequest,
    ComparisonFamilyPageResponse,
    ComparisonFamilyResponse,
    ComputeDriftRequest,
    ComputeSemanticMetricsRequest,
    CreateStatisticalProtocolRequest,
    DriftReportPageResponse,
    DriftReportResponse,
    EnqueueComparisonJobRequest,
    EnqueueDriftJobRequest,
    EnqueueSemanticMetricsRequest,
    SemanticMetricSnapshotPageResponse,
    SemanticMetricSnapshotResponse,
    SemanticMetricsJobAccepted,
    StatisticalAnalysisJobAccepted,
    StatisticalProtocolDecisionRequest,
    StatisticalProtocolPageResponse,
    StatisticalProtocolResponse,
    StatisticalProtocolTransitionRequest,
)
from geo_core.workflow_c_statistical_protocols import (
    StatisticalProtocolStatus,
    StatisticalProtocolVersion,
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
    IdempotencyHeader,
    MANAGE_ROLES,
    READ_ROLES,
    WRITE_ROLES,
    authorize_workflow_c,
    workflow_c_api,
    workflow_c_call,
)


_SYNCHRONOUS_ANALYSIS_GONE_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_410_GONE: {
        "description": "Synchronous analysis has been removed; enqueue a durable job instead.",
        "content": {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemDetails"}
            }
        },
        "headers": {
            "Deprecation": {
                "description": "Always `true` for this removed compatibility endpoint.",
                "schema": {"type": "string"},
            },
            "Link": {
                "description": "The durable asynchronous successor endpoint.",
                "schema": {"type": "string"},
            },
        },
    }
}


def workflow_c_analysis_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/analysis",
        tags=["workflow C analysis"],
        responses=PROBLEM_RESPONSES,
    )

    install_metric_protocol_routes(router)

    @router.post(
        "/statistical-protocols",
        response_model=StatisticalProtocolResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createStatisticalProtocol",
    )
    def create_statistical_protocol(
        project_id: UUID,
        payload: CreateStatisticalProtocolRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> StatisticalProtocolResponse:
        principal = authorize_workflow_c(request, authorization, project_id, MANAGE_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).analysis.create_statistical_protocol(
                project_id=project_id,
                payload=payload,
                actor_id=principal.actor_id,
                idempotency_key=idempotency_key,
            )
        )
        return _statistical_protocol_response(result)

    @router.get(
        "/statistical-protocols",
        response_model=StatisticalProtocolPageResponse,
        operation_id="listStatisticalProtocols",
    )
    def list_statistical_protocols(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> StatisticalProtocolPageResponse:
        authorize_workflow_c(request, authorization, project_id, READ_ROLES)
        values = workflow_c_call(
            lambda: workflow_c_api(request).analysis.list_statistical_protocols(
                project_id=project_id
            )
        )
        items = [_statistical_protocol_response(item) for item in values]
        return StatisticalProtocolPageResponse(items=items, total=len(items))

    @router.get(
        "/statistical-protocols/{protocol_id}",
        response_model=StatisticalProtocolResponse,
        operation_id="getStatisticalProtocol",
    )
    def get_statistical_protocol(
        project_id: UUID,
        protocol_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> StatisticalProtocolResponse:
        authorize_workflow_c(request, authorization, project_id, READ_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).analysis.get_statistical_protocol(
                project_id=project_id, protocol_id=protocol_id
            )
        )
        return _statistical_protocol_response(result)

    def transition_statistical(
        *,
        project_id: UUID,
        protocol_id: UUID,
        target: StatisticalProtocolStatus,
        payload: StatisticalProtocolTransitionRequest,
        request: Request,
        authorization: str | None,
        idempotency_key: str,
    ) -> StatisticalProtocolResponse:
        principal = authorize_workflow_c(request, authorization, project_id, MANAGE_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).analysis.transition_statistical_protocol(
                project_id=project_id,
                protocol_id=protocol_id,
                target_status=target,
                payload=payload,
                actor_id=principal.actor_id,
                idempotency_key=idempotency_key,
            )
        )
        return _statistical_protocol_response(result)

    @router.post(
        "/statistical-protocols/{protocol_id}/submit",
        response_model=StatisticalProtocolResponse,
        operation_id="submitStatisticalProtocol",
    )
    def submit_statistical_protocol(
        project_id: UUID,
        protocol_id: UUID,
        payload: StatisticalProtocolTransitionRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> StatisticalProtocolResponse:
        return transition_statistical(
            project_id=project_id,
            protocol_id=protocol_id,
            target=StatisticalProtocolStatus.IN_REVIEW,
            payload=payload,
            request=request,
            authorization=authorization,
            idempotency_key=idempotency_key,
        )

    @router.post(
        "/statistical-protocols/{protocol_id}/approve",
        response_model=StatisticalProtocolResponse,
        operation_id="approveStatisticalProtocol",
    )
    def approve_statistical_protocol(
        project_id: UUID,
        protocol_id: UUID,
        payload: StatisticalProtocolDecisionRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> StatisticalProtocolResponse:
        return transition_statistical(
            project_id=project_id,
            protocol_id=protocol_id,
            target=StatisticalProtocolStatus.APPROVED,
            payload=payload,
            request=request,
            authorization=authorization,
            idempotency_key=idempotency_key,
        )

    @router.post(
        "/statistical-protocols/{protocol_id}/retire",
        response_model=StatisticalProtocolResponse,
        operation_id="retireStatisticalProtocol",
    )
    def retire_statistical_protocol(
        project_id: UUID,
        protocol_id: UUID,
        payload: StatisticalProtocolDecisionRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> StatisticalProtocolResponse:
        return transition_statistical(
            project_id=project_id,
            protocol_id=protocol_id,
            target=StatisticalProtocolStatus.RETIRED,
            payload=payload,
            request=request,
            authorization=authorization,
            idempotency_key=idempotency_key,
        )

    @router.post(
        "/semantic-metrics/jobs",
        response_model=SemanticMetricsJobAccepted,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="enqueueSemanticMetricJob",
    )
    def enqueue_semantic_metrics(
        project_id: UUID,
        payload: EnqueueSemanticMetricsRequest,
        request: Request,
        response: Response,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> SemanticMetricsJobAccepted:
        principal = authorize_workflow_c(request, authorization, project_id, WRITE_ROLES)
        receipt = workflow_c_call(
            lambda: workflow_c_api(request).analysis.enqueue_semantic_metrics(
                project_id=project_id,
                payload=payload,
                actor_id=principal.actor_id,
                idempotency_key=idempotency_key,
            )
        )
        status_url = f"/v1/jobs/{receipt.job_id}"
        response.headers["Location"] = status_url
        return SemanticMetricsJobAccepted(
            job_id=receipt.job_id,
            status_url=status_url,
            manifest_id=receipt.manifest_id,
            manifest_hash=receipt.manifest_hash,
            replayed=receipt.replayed,
        )

    @router.post(
        "/semantic-metrics/compute",
        status_code=status.HTTP_410_GONE,
        response_model=None,
        response_class=Response,
        responses=_SYNCHRONOUS_ANALYSIS_GONE_RESPONSES,
        deprecated=True,
        summary="Removed synchronous semantic metric computation",
        description=(
            "Compatibility endpoint only. It never computes a snapshot. Use "
            "`POST /v1/projects/{project_id}/analysis/semantic-metrics/jobs`."
        ),
        operation_id="computeSemanticMetricSnapshot",
    )
    def compute_semantic_metrics(
        project_id: UUID,
        payload: ComputeSemanticMetricsRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> NoReturn:
        authorize_workflow_c(request, authorization, project_id, WRITE_ROLES)
        del payload
        _raise_synchronous_analysis_gone(
            project_id=project_id,
            successor="semantic-metrics/jobs",
        )

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
            lambda: workflow_c_api(request).analysis.list_semantic_snapshots(project_id=project_id)
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
        "/comparisons/jobs",
        response_model=StatisticalAnalysisJobAccepted,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="enqueueComparisonJob",
    )
    def enqueue_comparison(
        project_id: UUID,
        payload: EnqueueComparisonJobRequest,
        request: Request,
        response: Response,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> StatisticalAnalysisJobAccepted:
        principal = authorize_workflow_c(request, authorization, project_id, WRITE_ROLES)
        receipt = workflow_c_call(
            lambda: workflow_c_api(request).analysis.enqueue_comparison(
                project_id=project_id,
                payload=payload,
                actor_id=principal.actor_id,
                idempotency_key=idempotency_key,
            )
        )
        status_url = f"/v1/jobs/{receipt.job_id}"
        response.headers["Location"] = status_url
        return StatisticalAnalysisJobAccepted(
            job_id=receipt.job_id,
            status_url=status_url,
            spec_hash=receipt.spec_hash,
            replayed=receipt.replayed,
        )

    @router.post(
        "/comparisons/analyze",
        status_code=status.HTTP_410_GONE,
        response_model=None,
        response_class=Response,
        responses=_SYNCHRONOUS_ANALYSIS_GONE_RESPONSES,
        deprecated=True,
        summary="Removed synchronous comparison analysis",
        description=(
            "Compatibility endpoint only. It never computes a comparison family. Use "
            "`POST /v1/projects/{project_id}/analysis/comparisons/jobs`."
        ),
        operation_id="analyzeComparisonFamily",
    )
    def analyze_comparisons(
        project_id: UUID,
        payload: AnalyzeComparisonFamilyRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> NoReturn:
        authorize_workflow_c(request, authorization, project_id, WRITE_ROLES)
        del payload
        _raise_synchronous_analysis_gone(
            project_id=project_id,
            successor="comparisons/jobs",
        )

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
            lambda: workflow_c_api(request).analysis.list_comparison_families(project_id=project_id)
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
        "/drift/jobs",
        response_model=StatisticalAnalysisJobAccepted,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="enqueueDriftJob",
    )
    def enqueue_drift(
        project_id: UUID,
        payload: EnqueueDriftJobRequest,
        request: Request,
        response: Response,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> StatisticalAnalysisJobAccepted:
        principal = authorize_workflow_c(request, authorization, project_id, WRITE_ROLES)
        receipt = workflow_c_call(
            lambda: workflow_c_api(request).analysis.enqueue_drift(
                project_id=project_id,
                payload=payload,
                actor_id=principal.actor_id,
                idempotency_key=idempotency_key,
            )
        )
        status_url = f"/v1/jobs/{receipt.job_id}"
        response.headers["Location"] = status_url
        return StatisticalAnalysisJobAccepted(
            job_id=receipt.job_id,
            status_url=status_url,
            spec_hash=receipt.spec_hash,
            replayed=receipt.replayed,
        )

    @router.post(
        "/drift/compute",
        status_code=status.HTTP_410_GONE,
        response_model=None,
        response_class=Response,
        responses=_SYNCHRONOUS_ANALYSIS_GONE_RESPONSES,
        deprecated=True,
        summary="Removed synchronous drift computation",
        description=(
            "Compatibility endpoint only. It never computes a drift report. Use "
            "`POST /v1/projects/{project_id}/analysis/drift/jobs`."
        ),
        operation_id="computeDriftReport",
    )
    def compute_drift(
        project_id: UUID,
        payload: ComputeDriftRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> NoReturn:
        authorize_workflow_c(request, authorization, project_id, WRITE_ROLES)
        del payload
        _raise_synchronous_analysis_gone(
            project_id=project_id,
            successor="drift/jobs",
        )

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
            lambda: workflow_c_api(request).analysis.list_drift_reports(project_id=project_id)
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


def _raise_synchronous_analysis_gone(*, project_id: UUID, successor: str) -> NoReturn:
    successor_path = f"/v1/projects/{project_id}/analysis/{successor}"
    raise ApiProblem(
        status=status.HTTP_410_GONE,
        title="Gone",
        detail=(
            "Synchronous Workflow C analysis has been removed. "
            f"Enqueue the durable job with POST {successor_path}."
        ),
        type_uri="urn:geo:problem:synchronous-analysis-removed",
        headers={
            "Deprecation": "true",
            "Link": f'<{successor_path}>; rel="successor-version"',
        },
    )


def _statistical_protocol_response(
    value: StatisticalProtocolVersion,
) -> StatisticalProtocolResponse:
    return StatisticalProtocolResponse(
        id=value.id,
        project_id=value.project_id,
        series_id=value.series_id,
        version=value.version,
        supersedes_protocol_id=value.supersedes_protocol_id,
        kind=value.kind.value,
        status=value.status.value,
        definition_hash=value.definition_hash,
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
