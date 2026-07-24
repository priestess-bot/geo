"""Production composition for every durable Workflow C Worker operation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any, cast

import psycopg
from psycopg.rows import dict_row

from geo_core.alerts.postgres_inbox import PostgresWorkflowCAdminInboxWriter
from geo_core.alerts.postgres_operations import build_workflow_c_alert_operations
from geo_core.alerts.postgres_worker import PostgresWorkflowCAlertNotificationOperation
from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.placements.worker_composition import JobHandler
from geo_core.workflow_c_analysis_worker import build_workflow_c_analysis_operations
from geo_core.workflow_c_job_specs import PostgresWorkflowCJobSpecRepository
from geo_core.workflow_c_metric_judge_worker import build_workflow_c_metric_judge_operations
from geo_worker.workflow_c_delivery import build_workflow_c_notification_dispatcher
from geo_worker.workflow_c_handlers import (
    WorkflowCProductionOperations,
    WorkflowCWorkerOperation,
    build_workflow_c_worker_handlers,
)
from geo_worker.workflow_c_sampling_production import (
    build_workflow_c_sampling_operations,
)


class WorkflowCProductionCompositionError(RuntimeError):
    """A required durable Workflow C operation was not composed."""


def build_workflow_c_production_worker_handlers(
    *,
    database_url: str,
    store: PostgresDurableJobStore,
    model_runtime: Any,
    provider_result_recovery: Any,
    workflow_c_artifact_keyring_path: str,
    lease_for: timedelta,
) -> Mapping[str, JobHandler]:
    """Build the closed Workflow C registry before the Worker consumes Jobs.

    Every builder validates its own credentials, artifact keyring and frozen
    PostgreSQL repositories. No handler is registered until all ten durable
    operations have been assembled, so an incomplete deployment fails during
    process boot rather than acknowledging an admitted Job.
    """

    normalized_database_url = database_url.strip()
    if not normalized_database_url:
        raise ValueError("Workflow C PostgreSQL URL is required")

    def connect() -> Any:
        return psycopg.connect(normalized_database_url, row_factory=dict_row)

    specs = PostgresWorkflowCJobSpecRepository(connect)
    sampling = build_workflow_c_sampling_operations(
        database_url=normalized_database_url,
        store=store,
        model_runtime=model_runtime,
        provider_result_recovery=provider_result_recovery,
        workflow_c_artifact_keyring_path=workflow_c_artifact_keyring_path,
        lease_for=lease_for,
    )
    provider_execute = _operation(sampling, "sampling.provider_execute")
    manual_import = _operation(sampling, "sampling.manual_import")
    metric_children = build_workflow_c_metric_judge_operations(
        database_url=normalized_database_url,
        store=store,
        model_runtime=model_runtime,
        workflow_c_artifact_keyring_path=workflow_c_artifact_keyring_path,
        lease_for=lease_for,
    )
    metric_judge = _operation(metric_children, "workflow_c.metric_judge")
    metric_arbiter = _operation(metric_children, "workflow_c.metric_arbiter")
    analysis = build_workflow_c_analysis_operations(
        store=store,
        specs=specs,
        lease_for=lease_for,
        workflow_c_artifact_keyring_path=workflow_c_artifact_keyring_path,
    )
    alerts = build_workflow_c_alert_operations(store=store, specs=specs)
    notification = PostgresWorkflowCAlertNotificationOperation(
        store=store,
        specs=specs,
        dispatcher=build_workflow_c_notification_dispatcher(
            inbox_writer=PostgresWorkflowCAdminInboxWriter(connect)
        ),
        lease_for=lease_for,
    )
    return build_workflow_c_worker_handlers(
        operations=WorkflowCProductionOperations(
            provider_execute=provider_execute,
            manual_import=manual_import,
            semantic_metrics=analysis.semantic_metrics,
            metric_judge=metric_judge,
            metric_arbiter=metric_arbiter,
            comparison=analysis.comparison,
            drift=analysis.drift,
            alert_schedule=alerts.schedule,
            alert_evaluate=alerts.evaluate,
            alert_notify=notification,
        )
    )


def _operation(operations: Mapping[str, object], kind: str) -> WorkflowCWorkerOperation:
    value = operations.get(kind)
    if value is None or not callable(getattr(value, "execute", None)):
        raise WorkflowCProductionCompositionError(
            f"Workflow C production operation is missing: {kind}"
        )
    return cast(WorkflowCWorkerOperation, value)


__all__ = [
    "WorkflowCProductionCompositionError",
    "build_workflow_c_production_worker_handlers",
]
