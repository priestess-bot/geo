from dataclasses import dataclass

import pytest

from geo_worker.workflow_c_handlers import (
    WORKFLOW_C_MAINTENANCE_REQUIRED_JOB_KINDS,
    WORKFLOW_C_REQUIRED_JOB_KINDS,
    WorkflowCProductionOperations,
    assert_workflow_c_handlers_registered,
    build_workflow_c_worker_handlers,
)
from geo_worker.workflow_c_maintenance_worker import (
    WORKFLOW_C_MAINTENANCE_ACTOR,
    WORKFLOW_C_MAINTENANCE_QUEUE,
)


@dataclass
class _Operation:
    kind: str

    def execute(self, lease):
        return {"kind": self.kind, "job_id": str(lease.job_id)}


def test_workflow_c_handler_builder_requires_every_production_kind() -> None:
    operations = _operation_set()
    handlers = build_workflow_c_worker_handlers(operations=operations)

    assert frozenset(handlers) == WORKFLOW_C_REQUIRED_JOB_KINDS
    assert_workflow_c_handlers_registered(handlers)


def test_workflow_c_handler_builder_fails_closed_on_missing_or_unknown_kind() -> None:
    with pytest.raises(TypeError):
        WorkflowCProductionOperations(  # type: ignore[call-arg]
            provider_execute=_Operation("sampling.provider_execute"),
            manual_import=_Operation("sampling.manual_import"),
            semantic_metrics=_Operation("workflow_c.analysis.semantic_metrics"),
            metric_judge=_Operation("workflow_c.metric_judge"),
            metric_arbiter=_Operation("workflow_c.metric_arbiter"),
            comparison=_Operation("workflow_c.analysis.comparison"),
            drift=_Operation("workflow_c.analysis.drift"),
            alert_schedule=_Operation("workflow_c.alert.schedule"),
            alert_evaluate=_Operation("workflow_c.alert.evaluate"),
        )


def _operation_set() -> WorkflowCProductionOperations:
    return WorkflowCProductionOperations(
        provider_execute=_Operation("sampling.provider_execute"),
        manual_import=_Operation("sampling.manual_import"),
        semantic_metrics=_Operation("workflow_c.analysis.semantic_metrics"),
        metric_judge=_Operation("workflow_c.metric_judge"),
        metric_arbiter=_Operation("workflow_c.metric_arbiter"),
        comparison=_Operation("workflow_c.analysis.comparison"),
        drift=_Operation("workflow_c.analysis.drift"),
        alert_schedule=_Operation("workflow_c.alert.schedule"),
        alert_evaluate=_Operation("workflow_c.alert.evaluate"),
        alert_notify=_Operation("workflow_c.alert.notify"),
    )


def test_artifact_maintenance_has_a_dedicated_actor_and_queue() -> None:
    assert WORKFLOW_C_MAINTENANCE_REQUIRED_JOB_KINDS == {
        "workflow_c.artifact_maintenance"
    }
    assert WORKFLOW_C_MAINTENANCE_REQUIRED_JOB_KINDS.isdisjoint(
        WORKFLOW_C_REQUIRED_JOB_KINDS
    )
    assert WORKFLOW_C_MAINTENANCE_QUEUE == "workflow-c-maintenance"
    assert WORKFLOW_C_MAINTENANCE_ACTOR == "process_workflow_c_maintenance_job"
