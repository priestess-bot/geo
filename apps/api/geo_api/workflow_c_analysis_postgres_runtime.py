"""Durable read adapter for Workflow C analytical result projections."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
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
from geo_api.workflow_c_analysis_runtime import (
    SemanticAnalysisJobReceipt,
    StatisticalAnalysisJobReceipt,
    WorkflowCAnalysisNotFound,
    WorkflowCAnalysisUnavailable,
)
from geo_core.workflow_c_analysis_admission import (
    MetricProtocolStatus,
    MetricProtocolVersion,
    metric_protocol_definition,
    new_metric_protocol,
)
from geo_core.workflow_c_analysis_protocols import (
    PostgresWorkflowCMetricProtocolRepository,
    WorkflowCMetricProtocolNotFound,
)
from geo_core.workflow_c_analysis_reads import (
    PostgresWorkflowCAnalysisReadRepository,
    StoredComparisonFamily,
    StoredDriftReport,
    StoredSemanticMetricSnapshot,
    WorkflowCAnalysisProjectionNotFound,
)
from geo_core.workflow_c_semantic_admission import (
    PostgresWorkflowCSemanticAdmissionRepository,
)
from geo_core.workflow_c_statistical_admission import (
    PostgresWorkflowCStatisticalAdmissionRepository,
)
from geo_core.workflow_c_statistical_protocols import (
    PostgresWorkflowCStatisticalProtocolRepository,
    StatisticalProtocolNotFound,
    StatisticalProtocolStatus,
    StatisticalProtocolVersion,
    new_statistical_protocol,
    parse_statistical_protocol_definition,
)


class PostgresWorkflowCAnalysisRuntime:
    """Expose worker-written projections without opening an unsafe compute path."""

    persistence = "durable"

    def __init__(
        self,
        *,
        reads: PostgresWorkflowCAnalysisReadRepository,
        protocols: PostgresWorkflowCMetricProtocolRepository | None = None,
        semantic_admission: PostgresWorkflowCSemanticAdmissionRepository | None = None,
        statistical_protocols: PostgresWorkflowCStatisticalProtocolRepository
        | None = None,
        statistical_admission: PostgresWorkflowCStatisticalAdmissionRepository
        | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._reads = reads
        self._protocols = protocols
        self._semantic_admission = semantic_admission
        self._statistical_protocols = statistical_protocols
        self._statistical_admission = statistical_admission
        self._clock = clock

    def create_metric_protocol(
        self,
        *,
        project_id: UUID,
        payload: CreateMetricProtocolRequest,
        actor_id: str,
        idempotency_key: str,
    ) -> MetricProtocolVersion:
        protocols = self._require_protocols()
        predecessor = (
            self.get_metric_protocol(
                project_id=project_id,
                protocol_id=payload.supersedes_protocol_id,
            )
            if payload.supersedes_protocol_id is not None
            else None
        )
        protocol = new_metric_protocol(
            project_id=project_id,
            definition=metric_protocol_definition(payload.definition),
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            occurred_at=self._clock(),
            predecessor=predecessor,
        )
        return protocols.create(protocol, idempotency_key=idempotency_key)

    def transition_metric_protocol(
        self,
        *,
        project_id: UUID,
        protocol_id: UUID,
        target_status: MetricProtocolStatus,
        payload: MetricProtocolTransitionRequest,
        actor_id: str,
        idempotency_key: str,
    ) -> MetricProtocolVersion:
        return self._require_protocols().transition(
            project_id=project_id,
            protocol_id=protocol_id,
            expected_aggregate_version=payload.expected_aggregate_version,
            target_status=target_status,
            actor_id=actor_id,
            reason=payload.reason,
            idempotency_key=idempotency_key,
        )

    def get_metric_protocol(
        self, *, project_id: UUID, protocol_id: UUID
    ) -> MetricProtocolVersion:
        try:
            return self._require_protocols().get(
                project_id=project_id, protocol_id=protocol_id
            )
        except WorkflowCMetricProtocolNotFound as error:
            raise WorkflowCAnalysisNotFound(str(error)) from error

    def list_metric_protocols(
        self, *, project_id: UUID
    ) -> tuple[MetricProtocolVersion, ...]:
        return self._require_protocols().list(project_id=project_id)

    def enqueue_semantic_metrics(
        self,
        *,
        project_id: UUID,
        payload: EnqueueSemanticMetricsRequest,
        actor_id: str,
        idempotency_key: str,
    ) -> SemanticAnalysisJobReceipt:
        semantic_admission = self._semantic_admission
        if semantic_admission is None:
            raise WorkflowCAnalysisUnavailable(
                "semantic v2 Job admission is not configured"
            )
        admitted = semantic_admission.enqueue(
            project_id=project_id,
            sampling_run_id=payload.sampling_run_id,
            metric_protocol_id=payload.metric_protocol_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            max_attempts=payload.max_attempts,
        )
        return SemanticAnalysisJobReceipt(
            job_id=admitted.job.job_id,
            manifest_id=admitted.manifest.id,
            manifest_hash=admitted.manifest.manifest_hash,
            replayed=admitted.job.replayed,
        )

    def compute_semantic_metrics(
        self, *, project_id: UUID, payload: ComputeSemanticMetricsRequest
    ) -> StoredSemanticMetricSnapshot:
        del project_id, payload
        raise WorkflowCAnalysisUnavailable(
            "semantic metric computation is not admitted by the durable API"
        )

    def create_statistical_protocol(
        self,
        *,
        project_id: UUID,
        payload: CreateStatisticalProtocolRequest,
        actor_id: str,
        idempotency_key: str,
    ) -> StatisticalProtocolVersion:
        protocols = self._require_statistical_protocols()
        predecessor = (
            self.get_statistical_protocol(
                project_id=project_id,
                protocol_id=payload.supersedes_protocol_id,
            )
            if payload.supersedes_protocol_id is not None
            else None
        )
        protocol = new_statistical_protocol(
            project_id=project_id,
            definition=parse_statistical_protocol_definition(payload.definition),
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            occurred_at=self._clock(),
            predecessor=predecessor,
        )
        return protocols.create(protocol, idempotency_key=idempotency_key)

    def transition_statistical_protocol(
        self,
        *,
        project_id: UUID,
        protocol_id: UUID,
        target_status: StatisticalProtocolStatus,
        payload: StatisticalProtocolTransitionRequest,
        actor_id: str,
        idempotency_key: str,
    ) -> StatisticalProtocolVersion:
        return self._require_statistical_protocols().transition(
            project_id=project_id,
            protocol_id=protocol_id,
            expected_aggregate_version=payload.expected_aggregate_version,
            target_status=target_status,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            reason=payload.reason,
        )

    def get_statistical_protocol(
        self, *, project_id: UUID, protocol_id: UUID
    ) -> StatisticalProtocolVersion:
        try:
            return self._require_statistical_protocols().get(
                project_id=project_id, protocol_id=protocol_id
            )
        except StatisticalProtocolNotFound as error:
            raise WorkflowCAnalysisNotFound(str(error)) from error

    def list_statistical_protocols(
        self, *, project_id: UUID
    ) -> tuple[StatisticalProtocolVersion, ...]:
        return self._require_statistical_protocols().list(project_id=project_id)

    def enqueue_comparison(
        self,
        *,
        project_id: UUID,
        payload: EnqueueComparisonJobRequest,
        actor_id: str,
        idempotency_key: str,
    ) -> StatisticalAnalysisJobReceipt:
        admission = self._require_statistical_admission()
        job = admission.enqueue_comparison(
            project_id=project_id,
            comparison_plan_id=payload.comparison_plan_id,
            baseline_snapshot_hash=payload.baseline_metric_snapshot_hash,
            candidate_snapshot_hash=payload.candidate_metric_snapshot_hash,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            max_attempts=payload.max_attempts,
        )
        return StatisticalAnalysisJobReceipt(
            job_id=job.job_id,
            spec_hash=job.spec_hash,
            replayed=job.replayed,
        )

    def enqueue_drift(
        self,
        *,
        project_id: UUID,
        payload: EnqueueDriftJobRequest,
        actor_id: str,
        idempotency_key: str,
    ) -> StatisticalAnalysisJobReceipt:
        admission = self._require_statistical_admission()
        job = admission.enqueue_drift(
            project_id=project_id,
            drift_protocol_id=payload.drift_protocol_id,
            baseline_snapshot_hash=payload.baseline_metric_snapshot_hash,
            current_snapshot_hash=payload.current_metric_snapshot_hash,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            max_attempts=payload.max_attempts,
        )
        return StatisticalAnalysisJobReceipt(
            job_id=job.job_id,
            spec_hash=job.spec_hash,
            replayed=job.replayed,
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

    def _require_protocols(self) -> PostgresWorkflowCMetricProtocolRepository:
        if self._protocols is None:
            raise WorkflowCAnalysisUnavailable(
                "Metric Protocol governance is not configured"
            )
        return self._protocols

    def _require_statistical_protocols(
        self,
    ) -> PostgresWorkflowCStatisticalProtocolRepository:
        if self._statistical_protocols is None:
            raise WorkflowCAnalysisUnavailable(
                "statistical protocol governance is not configured"
            )
        return self._statistical_protocols

    def _require_statistical_admission(
        self,
    ) -> PostgresWorkflowCStatisticalAdmissionRepository:
        if self._statistical_admission is None:
            raise WorkflowCAnalysisUnavailable(
                "statistical Job admission is not configured"
            )
        return self._statistical_admission


__all__ = ["PostgresWorkflowCAnalysisRuntime"]
