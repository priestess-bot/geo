from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import hashlib
import json
from uuid import UUID, uuid4, uuid5

from geo_core.alerts.delivery import NotificationDispatcher
from geo_core.alerts.domain import AlertRuleKind, AlertSeverity, AlertStatus
from geo_core.alerts.notifications import (
    ALERT_NOTIFICATION_NAMESPACE,
    NotificationChannel,
    NotificationOutboxCommand,
    NotificationSummary,
    notification_idempotency_key,
)
from geo_core.alerts.postgres_worker import PostgresWorkflowCAlertNotificationOperation
from geo_core.jobs.postgres import WorkerLease
from geo_core.workflow_c_job_specs import WorkflowCJobSpec


def test_alert_notification_worker_uses_fenced_claim_then_completes_job() -> None:
    lease = _lease()
    command = _command(project_id=lease.project_id)
    connection = _NotificationConnection(command)
    store = _Store(connection)
    operation = PostgresWorkflowCAlertNotificationOperation(
        store=store,
        specs=_Specs(_spec(lease, command.id)),
        dispatcher=NotificationDispatcher({NotificationChannel.ADMIN_INBOX: _Transport()}),
        lease_for=timedelta(seconds=30),
        clock=lambda: _NOW,
    )

    result = operation.execute(lease)

    assert result == {
        "status": "delivered",
        "job_id": str(lease.job_id),
        "notification_id": str(command.id),
    }
    assert store.completed == [command.id]
    queries = "\n".join(connection.queries)
    assert "FOR UPDATE" in queries
    assert "SET status = 'leased'" in queries
    assert "SET status = 'delivered'" in queries


_NOW = datetime(2026, 7, 23, 8, 0, tzinfo=UTC)


def _lease() -> WorkerLease:
    return WorkerLease(
        job_id=uuid4(),
        project_id=uuid4(),
        kind="workflow_c.alert.notify",
        worker_id="workflow-c-test",
        lease_token=uuid4(),
        fencing_generation=3,
        attempt_count=1,
        max_attempts=3,
    )


def _command(*, project_id: UUID) -> NotificationOutboxCommand:
    alert_id = uuid4()
    summary = NotificationSummary(
        alert_id=alert_id,
        project_id=project_id,
        rule_key="completion_freshness",
        rule_version=1,
        rule_kind=AlertRuleKind.COMPLETION_FRESHNESS,
        severity=AlertSeverity.WARNING,
        status=AlertStatus.OPEN,
        event_type="opened",
        occurred_at=_NOW,
        detail_link=f"/admin/projects/{project_id}/alerts/{alert_id}",
    )
    key = notification_idempotency_key(
        alert_id=alert_id,
        alert_version=1,
        event_type="opened",
        channel=NotificationChannel.ADMIN_INBOX,
    )
    return NotificationOutboxCommand(
        id=uuid5(ALERT_NOTIFICATION_NAMESPACE, key),
        project_id=project_id,
        alert_id=alert_id,
        alert_version=1,
        channel=NotificationChannel.ADMIN_INBOX,
        topic="alerts.notify.admin_inbox",
        summary=summary,
        idempotency_key=key,
        created_at=_NOW,
        payload_hash=_hash(summary.payload()),
    )


def _spec(lease: WorkerLease, notification_id: UUID) -> WorkflowCJobSpec:
    payload: dict[str, object] = {
        "schema_version": 1,
        "kind": lease.kind,
        "notification_id": str(notification_id),
    }
    return WorkflowCJobSpec(
        project_id=lease.project_id,
        job_id=lease.job_id,
        kind=lease.kind,
        spec_hash=_hash(payload),
        payload=payload,
        created_at=_NOW,
    )


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class _Specs:
    def __init__(self, spec: WorkflowCJobSpec) -> None:
        self._spec = spec

    def load(self, _lease: WorkerLease) -> WorkflowCJobSpec:
        return self._spec


class _Transport:
    def deliver(self, _command: NotificationOutboxCommand, *, attempted_at: datetime) -> None:
        assert attempted_at == _NOW


class _Cursor:
    def __init__(self, row: dict[str, object] | None = None, *, rowcount: int = 1) -> None:
        self._row = row
        self.rowcount = rowcount

    def fetchone(self) -> dict[str, object] | None:
        return self._row


class _NotificationConnection:
    def __init__(self, command: NotificationOutboxCommand) -> None:
        self.command = command
        self.queries: list[str] = []

    def execute(self, query: str, _params: object = None) -> _Cursor:
        self.queries.append(query)
        if "FROM workflow_c_alert_notifications" in query and "FOR UPDATE" in query:
            return _Cursor(
                {
                    "id": self.command.id,
                    "project_id": self.command.project_id,
                    "alert_id": self.command.alert_id,
                    "alert_version": self.command.alert_version,
                    "channel": self.command.channel.value,
                    "topic": self.command.topic,
                    "idempotency_key": self.command.idempotency_key,
                    "payload_hash": self.command.payload_hash,
                    "payload": {"summary": self.command.summary.payload()},
                    "safe_summary": "safe",
                    "status": "pending",
                    "attempt_count": 0,
                    "last_attempt_at": None,
                    "next_attempt_at": _NOW,
                    "created_at": self.command.created_at,
                }
            )
        if "SELECT id FROM workflow_c_alert_notifications" in query:
            return _Cursor({"id": self.command.id})
        return _Cursor()


class _Store:
    def __init__(self, connection: _NotificationConnection) -> None:
        self._connection = connection
        self.completed: list[UUID] = []

    @contextmanager
    def fenced_transaction(self, _lease: WorkerLease) -> Iterator[_NotificationConnection]:
        yield self._connection

    def complete_in_transaction(
        self,
        _connection: _NotificationConnection,
        _lease: WorkerLease,
        *,
        result_ref: str,
        details: dict[str, object],
    ) -> None:
        assert result_ref.startswith("workflow-c-alert-notification:")
        assert details["delivered"] is True
        self.completed.append(UUID(str(details["notification_id"])))

    def heartbeat(self, _lease: WorkerLease, *, lease_for: timedelta) -> None:
        assert lease_for >= timedelta(seconds=30)
