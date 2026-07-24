"""Shared-dispatcher contract for every durable Workflow C job kind."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from geo_core.jobs.postgres import WorkerLease
from geo_core.placements.worker_composition import JobHandler


WORKFLOW_C_REQUIRED_JOB_KINDS = frozenset(
    {
        "sampling.provider_execute",
        "sampling.manual_import",
        "workflow_c.analysis.semantic_metrics",
        "workflow_c.metric_judge",
        "workflow_c.metric_arbiter",
        "workflow_c.analysis.comparison",
        "workflow_c.analysis.drift",
        "workflow_c.alert.schedule",
        "workflow_c.alert.evaluate",
        "workflow_c.alert.notify",
    }
)

WORKFLOW_C_MAINTENANCE_REQUIRED_JOB_KINDS = frozenset(
    {"workflow_c.artifact_maintenance"}
)


class WorkflowCWorkerOperation(Protocol):
    def execute(self, lease: WorkerLease) -> Mapping[str, object]: ...


@dataclass(frozen=True)
class WorkflowCProductionOperations:
    """The complete real-operation set accepted by the shared Worker.

    The composition root must supply every named operation from its PostgreSQL
    implementation. There are intentionally no no-op defaults: accepting an
    incomplete mapping would make a live route enqueue durable work that cannot
    be processed. Artifact retention has a dedicated, least-privilege Worker and
    is therefore excluded from this shared-process set.
    """

    provider_execute: WorkflowCWorkerOperation
    manual_import: WorkflowCWorkerOperation
    semantic_metrics: WorkflowCWorkerOperation
    metric_judge: WorkflowCWorkerOperation
    metric_arbiter: WorkflowCWorkerOperation
    comparison: WorkflowCWorkerOperation
    drift: WorkflowCWorkerOperation
    alert_schedule: WorkflowCWorkerOperation
    alert_evaluate: WorkflowCWorkerOperation
    alert_notify: WorkflowCWorkerOperation

    def as_mapping(self) -> Mapping[str, WorkflowCWorkerOperation]:
        return {
            "sampling.provider_execute": self.provider_execute,
            "sampling.manual_import": self.manual_import,
            "workflow_c.analysis.semantic_metrics": self.semantic_metrics,
            "workflow_c.metric_judge": self.metric_judge,
            "workflow_c.metric_arbiter": self.metric_arbiter,
            "workflow_c.analysis.comparison": self.comparison,
            "workflow_c.analysis.drift": self.drift,
            "workflow_c.alert.schedule": self.alert_schedule,
            "workflow_c.alert.evaluate": self.alert_evaluate,
            "workflow_c.alert.notify": self.alert_notify,
        }


@dataclass(frozen=True)
class _WorkflowCJobHandler:
    operation: WorkflowCWorkerOperation

    def handle(self, lease: WorkerLease) -> Mapping[str, object]:
        return self.operation.execute(lease)


def build_workflow_c_worker_handlers(
    *,
    operations: WorkflowCProductionOperations,
) -> Mapping[str, JobHandler]:
    mapped = operations.as_mapping()
    kinds = frozenset(mapped)
    missing = WORKFLOW_C_REQUIRED_JOB_KINDS - kinds
    unexpected = kinds - WORKFLOW_C_REQUIRED_JOB_KINDS
    if missing or unexpected:
        raise RuntimeError(
            "Workflow C Worker operation registry mismatch: "
            f"missing={sorted(missing)!r} unexpected={sorted(unexpected)!r}"
        )
    return {
        kind: _WorkflowCJobHandler(mapped[kind])
        for kind in sorted(WORKFLOW_C_REQUIRED_JOB_KINDS)
    }


def assert_workflow_c_handlers_registered(handlers: Mapping[str, JobHandler]) -> None:
    missing = WORKFLOW_C_REQUIRED_JOB_KINDS - frozenset(handlers)
    if missing:
        raise RuntimeError(
            f"Workflow C production handlers are unavailable: {sorted(missing)!r}"
        )


__all__ = [
    "WORKFLOW_C_REQUIRED_JOB_KINDS",
    "WORKFLOW_C_MAINTENANCE_REQUIRED_JOB_KINDS",
    "WorkflowCProductionOperations",
    "WorkflowCWorkerOperation",
    "assert_workflow_c_handlers_registered",
    "build_workflow_c_worker_handlers",
]
