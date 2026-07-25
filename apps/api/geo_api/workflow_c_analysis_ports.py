"""Public runtime ports, projections and receipts for Workflow C analysis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeAlias
from uuid import UUID

from geo_api.workflow_c_analysis_contracts import (
    AnalyzeComparisonFamilyRequest,
    ComputeDriftRequest,
    ComputeSemanticMetricsRequest,
    CreateMetricProtocolRequest,
    CreateStatisticalProtocolRequest,
    EnqueueComparisonJobRequest,
    EnqueueDriftJobRequest,
    EnqueueSemanticMetricsRequest,
    MetricProtocolTransitionRequest,
    StatisticalProtocolTransitionRequest,
)
from geo_core.semantic_metrics import SemanticMetricSnapshot
from geo_core.statistical_methods import (
    ComparisonFamilyResult,
    DriftReport,
)
from geo_core.workflow_c_analysis_admission import (
    MetricProtocolStatus,
    MetricProtocolVersion,
)
from geo_core.workflow_c_analysis_reads import (
    StoredComparisonFamily,
    StoredDriftReport,
    StoredSemanticMetricSnapshot,
)
from geo_core.workflow_c_statistical_protocols import (
    StatisticalProtocolStatus,
    StatisticalProtocolVersion,
)


class WorkflowCAnalysisNotFound(RuntimeError):
    """A project-scoped selector or analysis projection does not exist."""


class WorkflowCAnalysisUnavailable(RuntimeError):
    """A durable analysis command has not yet been safely admitted."""


SemanticSnapshotProjection: TypeAlias = SemanticMetricSnapshot | StoredSemanticMetricSnapshot
ComparisonFamilyProjection: TypeAlias = ComparisonFamilyResult | StoredComparisonFamily
DriftReportProjection: TypeAlias = DriftReport | StoredDriftReport


@dataclass(frozen=True)
class SemanticAnalysisJobReceipt:
    job_id: UUID
    manifest_id: UUID
    manifest_hash: str
    replayed: bool


@dataclass(frozen=True)
class StatisticalAnalysisJobReceipt:
    job_id: UUID
    spec_hash: str
    replayed: bool


class WorkflowCAnalysisPort(Protocol):
    """The full API route shape, with durable reads and explicitly gated writes."""

    def compute_semantic_metrics(
        self, *, project_id: UUID, payload: ComputeSemanticMetricsRequest
    ) -> SemanticSnapshotProjection: ...

    def create_metric_protocol(
        self,
        *,
        project_id: UUID,
        payload: CreateMetricProtocolRequest,
        actor_id: str,
        idempotency_key: str,
    ) -> MetricProtocolVersion: ...

    def transition_metric_protocol(
        self,
        *,
        project_id: UUID,
        protocol_id: UUID,
        target_status: MetricProtocolStatus,
        payload: MetricProtocolTransitionRequest,
        actor_id: str,
        idempotency_key: str,
    ) -> MetricProtocolVersion: ...

    def get_metric_protocol(
        self, *, project_id: UUID, protocol_id: UUID
    ) -> MetricProtocolVersion: ...

    def list_metric_protocols(self, *, project_id: UUID) -> tuple[MetricProtocolVersion, ...]: ...

    def enqueue_semantic_metrics(
        self,
        *,
        project_id: UUID,
        payload: EnqueueSemanticMetricsRequest,
        actor_id: str,
        idempotency_key: str,
    ) -> SemanticAnalysisJobReceipt: ...

    def create_statistical_protocol(
        self,
        *,
        project_id: UUID,
        payload: CreateStatisticalProtocolRequest,
        actor_id: str,
        idempotency_key: str,
    ) -> StatisticalProtocolVersion: ...

    def transition_statistical_protocol(
        self,
        *,
        project_id: UUID,
        protocol_id: UUID,
        target_status: StatisticalProtocolStatus,
        payload: StatisticalProtocolTransitionRequest,
        actor_id: str,
        idempotency_key: str,
    ) -> StatisticalProtocolVersion: ...

    def get_statistical_protocol(
        self, *, project_id: UUID, protocol_id: UUID
    ) -> StatisticalProtocolVersion: ...

    def list_statistical_protocols(
        self, *, project_id: UUID
    ) -> tuple[StatisticalProtocolVersion, ...]: ...

    def enqueue_comparison(
        self,
        *,
        project_id: UUID,
        payload: EnqueueComparisonJobRequest,
        actor_id: str,
        idempotency_key: str,
    ) -> StatisticalAnalysisJobReceipt: ...

    def enqueue_drift(
        self,
        *,
        project_id: UUID,
        payload: EnqueueDriftJobRequest,
        actor_id: str,
        idempotency_key: str,
    ) -> StatisticalAnalysisJobReceipt: ...

    def analyze_comparisons(
        self, *, project_id: UUID, payload: AnalyzeComparisonFamilyRequest
    ) -> ComparisonFamilyProjection: ...

    def compute_drift(
        self, *, project_id: UUID, payload: ComputeDriftRequest
    ) -> DriftReportProjection: ...

    def get_semantic_snapshot(
        self, *, project_id: UUID, snapshot_hash: str
    ) -> SemanticSnapshotProjection: ...

    def list_semantic_snapshots(
        self, *, project_id: UUID
    ) -> tuple[SemanticSnapshotProjection, ...]: ...

    def get_comparison_family(
        self, *, project_id: UUID, family_hash: str
    ) -> ComparisonFamilyProjection: ...

    def list_comparison_families(
        self, *, project_id: UUID
    ) -> tuple[ComparisonFamilyProjection, ...]: ...

    def get_drift_report(self, *, project_id: UUID, report_hash: str) -> DriftReportProjection: ...

    def list_drift_reports(self, *, project_id: UUID) -> tuple[DriftReportProjection, ...]: ...
