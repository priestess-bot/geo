"""Server-resolved deterministic semantic, comparison and drift runtime."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from threading import RLock
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
from geo_api.workflow_c_analysis_memory import (
    ResolvedComparisonAnalysis,
    ResolvedDriftAnalysis,
    ResolvedSemanticAnalysis,
    WorkflowCAnalysisInputResolver,
    _MemoryAnalysisInputResolver,
)
from geo_api.workflow_c_analysis_ports import (
    ComparisonFamilyProjection as ComparisonFamilyProjection,
    DriftReportProjection as DriftReportProjection,
    SemanticAnalysisJobReceipt,
    SemanticSnapshotProjection as SemanticSnapshotProjection,
    StatisticalAnalysisJobReceipt,
    WorkflowCAnalysisNotFound,
    WorkflowCAnalysisPort as WorkflowCAnalysisPort,
    WorkflowCAnalysisUnavailable,
)
from geo_core.semantic_metrics import (
    FrozenMetricSuite,
    MetricInputSet,
    SemanticMetricSnapshot,
    compute_semantic_metric_snapshot,
)
from geo_core.statistical_methods import (
    ComparisonFamilyResult,
    ComparisonInput,
    DriftObservation,
    DriftReport,
    analyze_comparison_family,
    compute_drift_report,
)
from geo_core.workflow_c_analysis_admission import (
    MetricProtocolStatus,
    MetricProtocolVersion,
    WorkflowCAnalysisAdmissionError,
    approve_metric_protocol,
    metric_protocol_definition,
    new_metric_protocol,
    retire_metric_protocol,
    submit_metric_protocol,
)
from geo_core.workflow_c_statistical_protocols import (
    StatisticalProtocolStatus,
    StatisticalProtocolVersion,
    new_statistical_protocol,
    parse_statistical_protocol_definition,
    transition_statistical_protocol,
)


class WorkflowCAnalysisRuntime:
    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        input_resolver: WorkflowCAnalysisInputResolver | None = None,
    ) -> None:
        self._lock = RLock()
        self._clock = clock
        self._input_resolver = input_resolver or _MemoryAnalysisInputResolver()
        self._semantic: dict[tuple[UUID, str], SemanticMetricSnapshot] = {}
        self._comparisons: dict[tuple[UUID, str], ComparisonFamilyResult] = {}
        self._drift: dict[tuple[UUID, str], DriftReport] = {}
        self._metric_protocols: dict[tuple[UUID, UUID], MetricProtocolVersion] = {}
        self._statistical_protocols: dict[tuple[UUID, UUID], StatisticalProtocolVersion] = {}

    def create_metric_protocol(
        self,
        *,
        project_id: UUID,
        payload: CreateMetricProtocolRequest,
        actor_id: str,
        idempotency_key: str,
    ) -> MetricProtocolVersion:
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
        key = (project_id, protocol.id)
        with self._lock:
            existing = self._metric_protocols.get(key)
            if existing is not None and existing != protocol:
                raise WorkflowCAnalysisAdmissionError("Metric Protocol idempotency key conflicts")
            self._metric_protocols[key] = protocol
        return protocol

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
        del idempotency_key
        current = self.get_metric_protocol(project_id=project_id, protocol_id=protocol_id)
        if current.aggregate_version != payload.expected_aggregate_version:
            raise WorkflowCAnalysisAdmissionError("Metric Protocol aggregate version changed")
        if target_status is MetricProtocolStatus.IN_REVIEW:
            updated = submit_metric_protocol(current, actor_id=actor_id, occurred_at=self._clock())
        elif target_status is MetricProtocolStatus.APPROVED:
            updated = approve_metric_protocol(
                current,
                actor_id=actor_id,
                reason=payload.reason or "approved",
                occurred_at=self._clock(),
            )
        elif target_status is MetricProtocolStatus.RETIRED:
            updated = retire_metric_protocol(
                current,
                actor_id=actor_id,
                reason=payload.reason or "retired",
                occurred_at=self._clock(),
            )
        else:
            raise WorkflowCAnalysisAdmissionError("Metric Protocol transition target is invalid")
        with self._lock:
            self._metric_protocols[(project_id, protocol_id)] = updated
        return updated

    def get_metric_protocol(self, *, project_id: UUID, protocol_id: UUID) -> MetricProtocolVersion:
        try:
            return self._metric_protocols[(project_id, protocol_id)]
        except KeyError as error:
            raise WorkflowCAnalysisNotFound("Metric Protocol does not exist") from error

    def list_metric_protocols(self, *, project_id: UUID) -> tuple[MetricProtocolVersion, ...]:
        return tuple(
            sorted(
                (
                    protocol
                    for (stored_project_id, _), protocol in self._metric_protocols.items()
                    if stored_project_id == project_id
                ),
                key=lambda item: (item.created_at, item.id),
                reverse=True,
            )
        )

    def enqueue_semantic_metrics(
        self,
        *,
        project_id: UUID,
        payload: EnqueueSemanticMetricsRequest,
        actor_id: str,
        idempotency_key: str,
    ) -> SemanticAnalysisJobReceipt:
        del project_id, payload, actor_id, idempotency_key
        raise WorkflowCAnalysisUnavailable(
            "semantic v2 Job admission requires the durable PostgreSQL runtime"
        )

    def create_statistical_protocol(
        self,
        *,
        project_id: UUID,
        payload: CreateStatisticalProtocolRequest,
        actor_id: str,
        idempotency_key: str,
    ) -> StatisticalProtocolVersion:
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
        key = (project_id, protocol.id)
        with self._lock:
            existing = self._statistical_protocols.get(key)
            if existing is not None and existing != protocol:
                raise WorkflowCAnalysisAdmissionError(
                    "statistical protocol idempotency key conflicts"
                )
            self._statistical_protocols[key] = protocol
        return protocol

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
        del idempotency_key
        current = self.get_statistical_protocol(project_id=project_id, protocol_id=protocol_id)
        if current.aggregate_version != payload.expected_aggregate_version:
            raise WorkflowCAnalysisAdmissionError("statistical protocol aggregate version changed")
        updated = transition_statistical_protocol(
            current,
            target_status=target_status,
            actor_id=actor_id,
            occurred_at=self._clock(),
            reason=payload.reason,
        )
        with self._lock:
            self._statistical_protocols[(project_id, protocol_id)] = updated
        return updated

    def get_statistical_protocol(
        self, *, project_id: UUID, protocol_id: UUID
    ) -> StatisticalProtocolVersion:
        try:
            return self._statistical_protocols[(project_id, protocol_id)]
        except KeyError as error:
            raise WorkflowCAnalysisNotFound("statistical protocol does not exist") from error

    def list_statistical_protocols(
        self, *, project_id: UUID
    ) -> tuple[StatisticalProtocolVersion, ...]:
        return tuple(
            sorted(
                (
                    protocol
                    for (stored_project_id, _), protocol in (self._statistical_protocols.items())
                    if stored_project_id == project_id
                ),
                key=lambda item: (item.created_at, item.id),
                reverse=True,
            )
        )

    def enqueue_comparison(
        self,
        *,
        project_id: UUID,
        payload: EnqueueComparisonJobRequest,
        actor_id: str,
        idempotency_key: str,
    ) -> StatisticalAnalysisJobReceipt:
        del project_id, payload, actor_id, idempotency_key
        raise WorkflowCAnalysisUnavailable(
            "comparison Job admission requires the durable PostgreSQL runtime"
        )

    def enqueue_drift(
        self,
        *,
        project_id: UUID,
        payload: EnqueueDriftJobRequest,
        actor_id: str,
        idempotency_key: str,
    ) -> StatisticalAnalysisJobReceipt:
        del project_id, payload, actor_id, idempotency_key
        raise WorkflowCAnalysisUnavailable(
            "drift Job admission requires the durable PostgreSQL runtime"
        )

    def install_semantic_inputs(
        self,
        *,
        project_id: UUID,
        selector: ComputeSemanticMetricsRequest,
        input_set: MetricInputSet,
        metric_suite: FrozenMetricSuite,
    ) -> None:
        judge = metric_suite.judge_version
        if (
            selector.metric_protocol_hash != metric_suite.suite_hash
            or selector.prompt_release_id != judge.prompt_release_id
            or selector.prompt_release_hash != judge.prompt_release_hash
            or selector.corpus_version_hash != input_set.approved_corpus_hash
        ):
            raise ValueError("semantic selector differs from its frozen server input")
        resolver = self._memory_resolver()
        resolver.install_semantic(
            project_id=project_id,
            selector=selector,
            resolved=ResolvedSemanticAnalysis(input_set, metric_suite),
        )

    def install_comparison_inputs(
        self,
        *,
        project_id: UUID,
        selector: AnalyzeComparisonFamilyRequest,
        comparisons: tuple[ComparisonInput, ...],
    ) -> None:
        resolver = self._memory_resolver()
        resolver.install_comparison(
            project_id=project_id,
            selector=selector,
            resolved=ResolvedComparisonAnalysis(comparisons),
        )

    def install_drift_inputs(
        self,
        *,
        project_id: UUID,
        selector: ComputeDriftRequest,
        baseline: tuple[DriftObservation, ...],
        current: tuple[DriftObservation, ...],
    ) -> None:
        resolver = self._memory_resolver()
        resolver.install_drift(
            project_id=project_id,
            selector=selector,
            resolved=ResolvedDriftAnalysis(baseline, current),
        )

    def compute_semantic_metrics(
        self, *, project_id: UUID, payload: ComputeSemanticMetricsRequest
    ) -> SemanticMetricSnapshot:
        resolved = self._input_resolver.semantic(project_id=project_id, selector=payload)
        snapshot = compute_semantic_metric_snapshot(
            input_set=resolved.input_set,
            suite=resolved.metric_suite,
            computed_at=self._clock(),
        )
        with self._lock:
            self._semantic[(project_id, snapshot.snapshot_hash)] = snapshot
        return snapshot

    def analyze_comparisons(
        self, *, project_id: UUID, payload: AnalyzeComparisonFamilyRequest
    ) -> ComparisonFamilyResult:
        resolved = self._input_resolver.comparison(project_id=project_id, selector=payload)
        result = analyze_comparison_family(resolved.comparisons)
        with self._lock:
            self._comparisons[(project_id, result.family_hash)] = result
        return result

    def compute_drift(self, *, project_id: UUID, payload: ComputeDriftRequest) -> DriftReport:
        resolved = self._input_resolver.drift(project_id=project_id, selector=payload)
        result = compute_drift_report(
            baseline=resolved.baseline,
            current=resolved.current,
        )
        with self._lock:
            self._drift[(project_id, result.report_hash)] = result
        return result

    def get_semantic_snapshot(
        self, *, project_id: UUID, snapshot_hash: str
    ) -> SemanticMetricSnapshot:
        return self._projection(
            self._semantic,
            (project_id, snapshot_hash),
            "semantic metric snapshot",
        )

    def list_semantic_snapshots(self, *, project_id: UUID) -> tuple[SemanticMetricSnapshot, ...]:
        return self._project_values(self._semantic, project_id)

    def get_comparison_family(
        self, *, project_id: UUID, family_hash: str
    ) -> ComparisonFamilyResult:
        return self._projection(
            self._comparisons,
            (project_id, family_hash),
            "comparison family result",
        )

    def list_comparison_families(self, *, project_id: UUID) -> tuple[ComparisonFamilyResult, ...]:
        return self._project_values(self._comparisons, project_id)

    def get_drift_report(self, *, project_id: UUID, report_hash: str) -> DriftReport:
        return self._projection(
            self._drift,
            (project_id, report_hash),
            "drift report",
        )

    def list_drift_reports(self, *, project_id: UUID) -> tuple[DriftReport, ...]:
        return self._project_values(self._drift, project_id)

    def _memory_resolver(self) -> _MemoryAnalysisInputResolver:
        if not isinstance(self._input_resolver, _MemoryAnalysisInputResolver):
            raise RuntimeError("only the memory resolver accepts test fixtures")
        return self._input_resolver

    def _projection(self, values: dict, key: tuple[UUID, str], label: str):
        with self._lock:
            result = values.get(key)
        if result is None:
            raise WorkflowCAnalysisNotFound(f"{label} does not exist")
        return result

    def _project_values(self, values: dict, project_id: UUID) -> tuple:
        with self._lock:
            matches = tuple(
                item for (item_project, _), item in values.items() if item_project == project_id
            )
        return tuple(sorted(matches, key=_projection_hash))


def _projection_hash(value: object) -> str:
    for name in ("snapshot_hash", "family_hash", "report_hash"):
        candidate = getattr(value, name, None)
        if isinstance(candidate, str):
            return candidate
    raise TypeError("analysis projection does not expose an immutable hash")
