"""Durable operations for frozen Workflow C analytical jobs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from geo_core.jobs.postgres import LeaseHeartbeat, PostgresDurableJobStore, WorkerLease
from geo_core.secrets import EnvelopeCipher, load_master_keyring_from_docker_secret
from geo_core.semantic_metrics import MetricStatus, compute_semantic_metric_snapshot
from geo_core.statistical_methods import analyze_comparison_family, compute_drift_report
from geo_core.workflow_c_analysis_common import WorkflowCAnalysisWorkerError
from geo_core.workflow_c_analysis_persistence import (
    family_status,
    persist_comparison_family,
    persist_drift_report,
    persist_semantic_snapshot,
)
from geo_core.workflow_c_semantic_specs import semantic_inputs
from geo_core.workflow_c_metric_parent_orchestration import (
    PostgresWorkflowCMetricParentOrchestrator,
)
from geo_core.workflow_c_metric_parent_specs import metric_model_program_admission
from geo_core.workflow_c_statistical_specs import comparison_inputs, drift_inputs
from geo_core.workflow_c_job_specs import PostgresWorkflowCJobSpecRepository


@dataclass(frozen=True)
class WorkflowCAnalysisOperations:
    semantic_metrics: PostgresWorkflowCSemanticMetricOperation
    comparison: PostgresWorkflowCComparisonOperation
    drift: PostgresWorkflowCDriftOperation


def build_workflow_c_analysis_operations(
    *,
    store: PostgresDurableJobStore,
    specs: PostgresWorkflowCJobSpecRepository,
    lease_for: timedelta,
    workflow_c_artifact_keyring_path: str | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> WorkflowCAnalysisOperations:
    """Build the three non-model analytical operations from one frozen reader."""

    keyring_path = (workflow_c_artifact_keyring_path or "").strip()
    metric_parent = (
        PostgresWorkflowCMetricParentOrchestrator(
            store=store,
            cipher=EnvelopeCipher(load_master_keyring_from_docker_secret(keyring_path)),
            lease_for=lease_for,
            clock=clock,
        )
        if keyring_path
        else None
    )
    return WorkflowCAnalysisOperations(
        semantic_metrics=PostgresWorkflowCSemanticMetricOperation(
            store=store,
            specs=specs,
            lease_for=lease_for,
            metric_parent=metric_parent,
            clock=clock,
        ),
        comparison=PostgresWorkflowCComparisonOperation(
            store=store, specs=specs, lease_for=lease_for, clock=clock
        ),
        drift=PostgresWorkflowCDriftOperation(
            store=store, specs=specs, lease_for=lease_for, clock=clock
        ),
    )


class PostgresWorkflowCComparisonOperation:
    """Compute and persist one fully frozen paired-comparison family."""

    kind = "workflow_c.analysis.comparison"

    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        specs: PostgresWorkflowCJobSpecRepository,
        lease_for: timedelta,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        _validate_lease_for(lease_for)
        self._store = store
        self._specs = specs
        self._lease_for = lease_for
        self._clock = clock

    def execute(self, lease: WorkerLease) -> Mapping[str, object]:
        _require_kind(lease, self.kind)
        comparisons = comparison_inputs(self._specs.load(lease))
        with _heartbeat(self._store, lease, self._lease_for) as heartbeat:
            family = analyze_comparison_family(comparisons)
            heartbeat.raise_if_stopped()
        persist_comparison_family(
            self._store,
            lease,
            family=family,
            comparisons=comparisons,
            computed_at=_aware_now(self._clock),
        )
        return {
            "status": family_status(family.results),
            "job_id": str(lease.job_id),
            "family_hash": family.family_hash,
        }


class PostgresWorkflowCSemanticMetricOperation:
    """Compute a full semantic snapshot and retain every denominator/result row."""

    kind = "workflow_c.analysis.semantic_metrics"

    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        specs: PostgresWorkflowCJobSpecRepository,
        lease_for: timedelta,
        metric_parent: PostgresWorkflowCMetricParentOrchestrator | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        _validate_lease_for(lease_for)
        self._store = store
        self._specs = specs
        self._lease_for = lease_for
        self._metric_parent = metric_parent
        self._clock = clock

    def execute(self, lease: WorkerLease) -> Mapping[str, object]:
        _require_kind(lease, self.kind)
        spec = self._specs.load(lease)
        metadata, input_set, suite = semantic_inputs(spec)
        model_program = metric_model_program_admission(spec)
        if model_program is not None:
            if self._metric_parent is None:
                raise WorkflowCAnalysisWorkerError("Metric model parent runtime is unavailable")
            return self._metric_parent.execute(
                lease=lease,
                parent_input_hash=spec.spec_hash,
                metadata=metadata,
                input_set=input_set,
                suite=suite,
                program=model_program,
            )
        with _heartbeat(self._store, lease, self._lease_for) as heartbeat:
            snapshot = compute_semantic_metric_snapshot(
                input_set=input_set, suite=suite, computed_at=_aware_now(self._clock)
            )
            heartbeat.raise_if_stopped()
        status = (
            "complete"
            if all(item.status is MetricStatus.COMPLETE for item in snapshot.results)
            else "insufficient_evidence"
        )
        persist_semantic_snapshot(
            self._store,
            lease,
            snapshot=snapshot,
            run_id=metadata.run_id,
            source_stratum_hash=metadata.source_stratum_hash,
            capture_method=metadata.capture_method,
            warning_ratio=metadata.warning_ratio,
            test_only=metadata.test_only,
            synthetic=metadata.synthetic,
            evidence_status=status,
        )
        return {
            "status": status,
            "job_id": str(lease.job_id),
            "snapshot_hash": snapshot.snapshot_hash,
        }


class PostgresWorkflowCDriftOperation:
    """Compute a strict-stratum drift report from two immutable cohorts."""

    kind = "workflow_c.analysis.drift"

    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        specs: PostgresWorkflowCJobSpecRepository,
        lease_for: timedelta,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        _validate_lease_for(lease_for)
        self._store = store
        self._specs = specs
        self._lease_for = lease_for
        self._clock = clock

    def execute(self, lease: WorkerLease) -> Mapping[str, object]:
        _require_kind(lease, self.kind)
        source_hash, target_hash, baseline, current = drift_inputs(self._specs.load(lease))
        with _heartbeat(self._store, lease, self._lease_for) as heartbeat:
            report = compute_drift_report(baseline=baseline, current=current)
            heartbeat.raise_if_stopped()
        persist_drift_report(
            self._store,
            lease,
            report=report,
            source_snapshot_hash=source_hash,
            target_snapshot_hash=target_hash,
            computed_at=_aware_now(self._clock),
        )
        return {
            "status": "complete",
            "job_id": str(lease.job_id),
            "report_hash": report.report_hash,
        }


def _heartbeat(
    store: PostgresDurableJobStore, lease: WorkerLease, lease_for: timedelta
) -> LeaseHeartbeat:
    return LeaseHeartbeat(
        store,
        lease,
        lease_for=lease_for,
        interval=max(timedelta(seconds=5), lease_for / 3),
    )


def _require_kind(lease: WorkerLease, expected: str) -> None:
    if lease.kind != expected:
        raise WorkflowCAnalysisWorkerError("Workflow C analysis Worker kind is invalid")


def _validate_lease_for(value: timedelta) -> None:
    if value < timedelta(seconds=30):
        raise ValueError("Workflow C analysis Worker lease must be at least 30 seconds")


def _aware_now(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise WorkflowCAnalysisWorkerError("Workflow C analysis clock must be timezone-aware")
    return value


__all__ = [
    "PostgresWorkflowCComparisonOperation",
    "PostgresWorkflowCDriftOperation",
    "PostgresWorkflowCSemanticMetricOperation",
    "WorkflowCAnalysisOperations",
    "WorkflowCAnalysisWorkerError",
    "build_workflow_c_analysis_operations",
]
