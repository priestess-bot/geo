"""Durable read adapter for Workflow C analytical result projections."""

from __future__ import annotations

from uuid import UUID

from geo_api.workflow_c_analysis_contracts import (
    AnalyzeComparisonFamilyRequest,
    ComputeDriftRequest,
    ComputeSemanticMetricsRequest,
)
from geo_api.workflow_c_analysis_runtime import (
    WorkflowCAnalysisNotFound,
    WorkflowCAnalysisUnavailable,
)
from geo_core.workflow_c_analysis_reads import (
    PostgresWorkflowCAnalysisReadRepository,
    StoredComparisonFamily,
    StoredDriftReport,
    StoredSemanticMetricSnapshot,
    WorkflowCAnalysisProjectionNotFound,
)


class PostgresWorkflowCAnalysisRuntime:
    """Expose worker-written projections without opening an unsafe compute path."""

    persistence = "durable"

    def __init__(self, *, reads: PostgresWorkflowCAnalysisReadRepository) -> None:
        self._reads = reads

    def compute_semantic_metrics(
        self, *, project_id: UUID, payload: ComputeSemanticMetricsRequest
    ) -> StoredSemanticMetricSnapshot:
        del project_id, payload
        raise WorkflowCAnalysisUnavailable(
            "semantic metric computation is not admitted by the durable API"
        )

    def analyze_comparisons(
        self, *, project_id: UUID, payload: AnalyzeComparisonFamilyRequest
    ) -> StoredComparisonFamily:
        del project_id, payload
        raise WorkflowCAnalysisUnavailable(
            "comparison computation is not admitted by the durable API"
        )

    def compute_drift(self, *, project_id: UUID, payload: ComputeDriftRequest) -> StoredDriftReport:
        del project_id, payload
        raise WorkflowCAnalysisUnavailable("drift computation is not admitted by the durable API")

    def get_semantic_snapshot(
        self, *, project_id: UUID, snapshot_hash: str
    ) -> StoredSemanticMetricSnapshot:
        try:
            return self._reads.get_semantic_snapshot(
                project_id=project_id, snapshot_hash=snapshot_hash
            )
        except WorkflowCAnalysisProjectionNotFound as error:
            raise WorkflowCAnalysisNotFound(str(error)) from error

    def list_semantic_snapshots(
        self, *, project_id: UUID
    ) -> tuple[StoredSemanticMetricSnapshot, ...]:
        return self._reads.list_semantic_snapshots(project_id=project_id)

    def get_comparison_family(
        self, *, project_id: UUID, family_hash: str
    ) -> StoredComparisonFamily:
        try:
            return self._reads.get_comparison_family(project_id=project_id, family_hash=family_hash)
        except WorkflowCAnalysisProjectionNotFound as error:
            raise WorkflowCAnalysisNotFound(str(error)) from error

    def list_comparison_families(self, *, project_id: UUID) -> tuple[StoredComparisonFamily, ...]:
        return self._reads.list_comparison_families(project_id=project_id)

    def get_drift_report(self, *, project_id: UUID, report_hash: str) -> StoredDriftReport:
        try:
            return self._reads.get_drift_report(project_id=project_id, report_hash=report_hash)
        except WorkflowCAnalysisProjectionNotFound as error:
            raise WorkflowCAnalysisNotFound(str(error)) from error

    def list_drift_reports(self, *, project_id: UUID) -> tuple[StoredDriftReport, ...]:
        return self._reads.list_drift_reports(project_id=project_id)


__all__ = ["PostgresWorkflowCAnalysisRuntime"]
