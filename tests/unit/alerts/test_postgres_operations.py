from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import hashlib
import json
from uuid import UUID, uuid4

import pytest

from geo_core.alerts import AlertRuleKind, AlertRuleVersion, AlertSeverity
from geo_core.alerts.postgres_operations import (
    PostgresWorkflowCAlertEvaluateOperation,
    PostgresWorkflowCAlertScheduleOperation,
    WorkflowCAlertOperationError,
)
from geo_core.jobs.postgres import WorkerLease
from geo_core.workflow_c_job_specs import WorkflowCJobSpec, WorkflowCJobSpecError


NOW = datetime(2026, 7, 23, 9, 0, tzinfo=UTC)


def test_schedule_operation_atomically_enqueues_evaluation_and_successor() -> None:
    lease = _lease("workflow_c.alert.schedule")
    spec = _spec(lease, _schedule_payload(lease.project_id, scheduled_for=NOW))
    connection = _Connection()
    operation = PostgresWorkflowCAlertScheduleOperation(
        store=_Store(connection), specs=_Specs(spec), clock=lambda: NOW
    )

    result = operation.execute(lease)

    assert result["status"] == "scheduled"
    assert result["schedule_id"] == str(_schedule_id())
    assert result["next_run_at"] == (NOW + timedelta(minutes=5)).isoformat()
    query, params = connection.calls[0]
    assert "geo_enqueue_workflow_c_alert_evaluation" in query
    assert params[0:4] == (
        lease.job_id,
        lease.project_id,
        lease.lease_token,
        lease.fencing_generation,
    )
    assert '"kind":"workflow_c.alert.evaluate"' in str(params[9])
    assert '"kind":"workflow_c.alert.schedule"' in str(params[13])


def test_schedule_operation_refuses_to_run_before_its_frozen_time() -> None:
    lease = _lease("workflow_c.alert.schedule")
    spec = _spec(
        lease,
        _schedule_payload(lease.project_id, scheduled_for=NOW + timedelta(seconds=1)),
    )
    connection = _Connection()
    operation = PostgresWorkflowCAlertScheduleOperation(
        store=_Store(connection), specs=_Specs(spec), clock=lambda: NOW
    )

    with pytest.raises(WorkflowCAlertOperationError, match="not due"):
        operation.execute(lease)

    assert connection.calls == []


def test_schedule_operation_fails_closed_when_persistence_fence_is_lost() -> None:
    lease = _lease("workflow_c.alert.schedule")
    spec = _spec(lease, _schedule_payload(lease.project_id, scheduled_for=NOW))
    connection = _Connection(schedule_row=None)
    operation = PostgresWorkflowCAlertScheduleOperation(
        store=_Store(connection), specs=_Specs(spec), clock=lambda: NOW
    )

    with pytest.raises(WorkflowCAlertOperationError, match="was fenced"):
        operation.execute(lease)

    assert len(connection.calls) == 1
    assert "geo_enqueue_workflow_c_alert_evaluation" in connection.calls[0][0]


def test_evaluate_operation_persists_matched_result_alert_and_notify_jobs_via_rpc() -> None:
    lease = _lease("workflow_c.alert.evaluate")
    payload = _evaluation_payload(lease.project_id, observed_value="0.3")
    spec = _spec(lease, payload)
    connection = _Connection()
    operation = PostgresWorkflowCAlertEvaluateOperation(
        store=_Store(connection), specs=_Specs(spec), clock=lambda: NOW
    )

    result = operation.execute(lease)

    assert result["status"] == "matched"
    assert result["notification_count"] == 3
    query, params = connection.calls[0]
    assert "geo_complete_workflow_c_alert_evaluation" in query
    assert "INSERT INTO workflow_c_alert" not in query
    assert params[0:4] == (
        lease.job_id,
        lease.project_id,
        lease.lease_token,
        lease.fencing_generation,
    )
    assert params[11] == "matched"
    assert params[12] is True
    assert "workflow_c.alert.notify" in str(params[18])


def test_evaluate_operation_accepts_retry_replay_without_duplicate_notifications() -> None:
    lease = _lease("workflow_c.alert.evaluate")
    spec = _spec(lease, _evaluation_payload(lease.project_id, observed_value="0.3"))
    connection = _Connection(notification_count=0)
    operation = PostgresWorkflowCAlertEvaluateOperation(
        store=_Store(connection), specs=_Specs(spec), clock=lambda: NOW
    )

    result = operation.execute(lease)

    assert result["status"] == "matched"
    assert result["notification_count"] == 0
    assert "input_values" not in result
    assert "evidence" not in result


def test_evaluate_operation_fails_closed_when_result_rpc_does_not_echo_its_hash() -> None:
    lease = _lease("workflow_c.alert.evaluate")
    spec = _spec(lease, _evaluation_payload(lease.project_id, observed_value="0.3"))
    connection = _Connection(evaluation_hash="0" * 64)
    operation = PostgresWorkflowCAlertEvaluateOperation(
        store=_Store(connection), specs=_Specs(spec), clock=lambda: NOW
    )

    with pytest.raises(WorkflowCAlertOperationError, match="evaluation_hash changed"):
        operation.execute(lease)

    assert len(connection.calls) == 1
    assert "geo_complete_workflow_c_alert_evaluation" in connection.calls[0][0]


def test_evaluate_operation_persists_non_match_without_alert_or_notification_payload() -> None:
    lease = _lease("workflow_c.alert.evaluate")
    spec = _spec(lease, _evaluation_payload(lease.project_id, observed_value="0.7"))
    connection = _Connection()
    operation = PostgresWorkflowCAlertEvaluateOperation(
        store=_Store(connection), specs=_Specs(spec), clock=lambda: NOW
    )

    result = operation.execute(lease)

    assert result["status"] == "not_matched"
    assert result["alert_id"] is None
    assert result["notification_count"] == 0
    _, params = connection.calls[0]
    assert params[11] == "not_matched"
    assert params[12] is False
    assert params[15:19] == (None, None, "null", "[]")


def test_evaluate_operation_rejects_cross_project_scope_before_persistence() -> None:
    lease = _lease("workflow_c.alert.evaluate")
    payload = _evaluation_payload(lease.project_id, observed_value="0.3")
    payload["scope"]["project_id"] = str(uuid4())  # type: ignore[index]
    spec = _spec(lease, payload)
    connection = _Connection()
    operation = PostgresWorkflowCAlertEvaluateOperation(
        store=_Store(connection), specs=_Specs(spec), clock=lambda: NOW
    )

    with pytest.raises(WorkflowCJobSpecError, match="scope project"):
        operation.execute(lease)

    assert connection.calls == []


def test_alert_operation_spec_rejects_secret_material_before_a_worker_can_log_it() -> None:
    lease = _lease("workflow_c.alert.evaluate")
    payload = _evaluation_payload(lease.project_id, observed_value="0.3")
    payload["input_values"]["token"] = "must-not-persist"  # type: ignore[index]

    with pytest.raises(WorkflowCJobSpecError, match="secret or credential"):
        _spec(lease, payload)


def _lease(kind: str) -> WorkerLease:
    return WorkerLease(
        job_id=uuid4(),
        project_id=UUID("b0300000-0000-0000-0000-000000000001"),
        kind=kind,
        worker_id="workflow-c-alert-test",
        lease_token=uuid4(),
        fencing_generation=3,
        attempt_count=1,
        max_attempts=3,
    )


def _spec(lease: WorkerLease, payload: dict[str, object]) -> WorkflowCJobSpec:
    return WorkflowCJobSpec(
        project_id=lease.project_id,
        job_id=lease.job_id,
        kind=lease.kind,
        spec_hash=_hash(payload),
        payload=payload,
        created_at=NOW,
    )


def _schedule_id() -> UUID:
    return UUID("b0400000-0000-0000-0000-000000000001")


def _rule(project_id: UUID) -> dict[str, object]:
    rule = AlertRuleVersion(
        id=UUID("b0500000-0000-0000-0000-000000000001"),
        project_id=project_id,
        rule_key="recommendation-share-low",
        version=1,
        kind=AlertRuleKind.THRESHOLD,
        severity=AlertSeverity.WARNING,
        parameters={
            "schema_version": "alert-rule-threshold-v1",
            "metric_key": "recommendation_share",
            "operator": "lt",
            "threshold": "0.5",
        },
        frozen_by="admin-1",
        frozen_at=NOW,
    )
    return {
        "id": str(rule.id),
        "rule_key": rule.rule_key,
        "version": rule.version,
        "kind": rule.kind.value,
        "severity": rule.severity.value,
        "parameters": dict(rule.parameters),
        "frozen_by": rule.frozen_by,
        "frozen_at": rule.frozen_at.isoformat(),
        "rule_hash": rule.rule_hash,
    }


def _evaluation_payload(project_id: UUID, *, observed_value: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "workflow_c.alert.evaluate",
        "schedule_id": str(_schedule_id()),
        "schedule_version": 1,
        "rule": _rule(project_id),
        "scope": {
            "project_id": str(project_id),
            "resource_kind": "monitoring_report",
            "resource_key": "report:one",
            "dimensions": {"surface": "perplexity"},
        },
        "input_values": {
            "schema_version": "alert-input-threshold-v1",
            "metric_key": "recommendation_share",
            "observed_value": observed_value,
        },
        "evidence": [
            {
                "kind": "metric_snapshot",
                "resource_id": "snapshot:one",
                "version": "semantic-metrics-v1",
                "sha256": "a" * 64,
                "locator": "results[0]",
            }
        ],
        "channels": ["admin_inbox", "local_smtp", "internal_webhook"],
    }


def _schedule_payload(
    project_id: UUID, *, scheduled_for: datetime
) -> dict[str, object]:
    evaluation = _evaluation_payload(project_id, observed_value="0.3")
    return {
        "schema_version": 1,
        "kind": "workflow_c.alert.schedule",
        "schedule_id": str(_schedule_id()),
        "schedule_version": 1,
        "scheduled_for": scheduled_for.isoformat(),
        "interval_seconds": 300,
        "evaluation": {
            key: value
            for key, value in evaluation.items()
            if key not in {"schema_version", "kind"}
        },
    }


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


class _Specs:
    def __init__(self, spec: WorkflowCJobSpec) -> None:
        self._spec = spec

    def load(self, _lease: WorkerLease) -> WorkflowCJobSpec:
        return self._spec


class _Cursor:
    def __init__(self, row: Mapping[str, object] | None) -> None:
        self._row = row

    def fetchone(self) -> Mapping[str, object] | None:
        return self._row


class _Connection:
    def __init__(
        self,
        *,
        schedule_row: Mapping[str, object] | None | object = ...,
        evaluation_hash: str | None = None,
        notification_count: int | None = None,
    ) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self._schedule_row = schedule_row
        self._evaluation_hash = evaluation_hash
        self._notification_count = notification_count

    def execute(self, query: str, params: tuple[object, ...]) -> _Cursor:
        self.calls.append((query, params))
        if "geo_enqueue_workflow_c_alert_evaluation" in query:
            if self._schedule_row is None:
                return _Cursor(None)
            if self._schedule_row is not ...:
                return _Cursor(self._schedule_row)  # type: ignore[arg-type]
            return _Cursor(
                {
                    "status": "scheduled",
                    "evaluation_job_id": params[7],
                    "successor_job_id": params[11],
                }
            )
        if "geo_complete_workflow_c_alert_evaluation" in query:
            return _Cursor(
                {
                    "status": params[11],
                    "evaluation_hash": self._evaluation_hash or params[10],
                    "notification_count": (
                        self._notification_count
                        if self._notification_count is not None
                        else 3 if params[12] else 0
                    ),
                }
            )
        raise AssertionError(query)


class _Store:
    def __init__(self, connection: _Connection) -> None:
        self._connection = connection

    @contextmanager
    def fenced_transaction(self, _lease: WorkerLease):
        yield self._connection
