"""Fenced PostgreSQL Worker operation for one Workflow C alert notification."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from geo_core.alerts.delivery import NotificationDispatcher
from geo_core.alerts.domain import (
    AlertRuleKind,
    AlertSeverity,
    AlertStatus,
)
from geo_core.alerts.notifications import (
    NotificationChannel,
    NotificationDelivery,
    NotificationDeliveryStatus,
    NotificationOutboxCommand,
    NotificationSummary,
)
from geo_core.jobs.postgres import (
    JobCancellationRequested,
    LeaseHeartbeat,
    LostJobLease,
    PostgresDurableJobStore,
    WorkerLease,
)
from geo_core.workflow_c_job_specs import (
    PostgresWorkflowCJobSpecRepository,
    WorkflowCJobSpec,
    WorkflowCJobSpecError,
)


class WorkflowCAlertNotificationError(RuntimeError):
    """The persisted notification does not match its immutable Worker command."""


@dataclass(frozen=True)
class _ClaimedNotification:
    command: NotificationOutboxCommand
    delivery: NotificationDelivery


class PostgresWorkflowCAlertNotificationOperation:
    """Deliver an approved alert summary without holding a database lock over I/O."""

    kind = "workflow_c.alert.notify"

    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        specs: PostgresWorkflowCJobSpecRepository,
        dispatcher: NotificationDispatcher,
        lease_for: timedelta,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if lease_for < timedelta(seconds=30):
            raise ValueError("Workflow C alert notification lease must be at least 30 seconds")
        self._store = store
        self._specs = specs
        self._dispatcher = dispatcher
        self._lease_for = lease_for
        self._clock = clock

    def execute(self, lease: WorkerLease) -> Mapping[str, object]:
        if lease.kind != self.kind:
            raise WorkflowCAlertNotificationError("alert notification Worker kind is invalid")
        spec = self._specs.load(lease)
        claimed = self._claim(lease, spec)
        try:
            with LeaseHeartbeat(
                self._store,
                lease,
                lease_for=self._lease_for,
                interval=max(timedelta(seconds=5), self._lease_for / 3),
            ) as heartbeat:
                result = self._dispatcher.dispatch(
                    claimed.command,
                    claimed.delivery,
                    attempted_at=self._clock(),
                )
                heartbeat.raise_if_stopped()
        except (JobCancellationRequested, LostJobLease):
            raise
        except Exception as error:
            return self._record_unexpected_failure(lease, claimed, error)
        return self._record_delivery(lease, claimed, result.delivery)

    def _claim(self, lease: WorkerLease, spec: WorkflowCJobSpec) -> _ClaimedNotification:
        notification_id = _notification_id(spec)
        with self._store.fenced_transaction(lease) as connection:
            row = _one(
                connection.execute(
                    """SELECT id, project_id, alert_id, alert_version, channel, topic,
                              idempotency_key, payload_hash, payload, safe_summary,
                              status, attempt_count, last_attempt_at, next_attempt_at,
                              created_at
                       FROM workflow_c_alert_notifications
                      WHERE project_id = %s AND id = %s FOR UPDATE""",
                    (lease.project_id, notification_id),
                )
            )
            if row is None:
                raise WorkflowCAlertNotificationError("alert notification does not exist")
            if row["status"] not in {"pending", "retry_wait"}:
                raise WorkflowCAlertNotificationError("alert notification is not dispatchable")
            now = self._clock()
            next_attempt_at = _timestamp(row, "next_attempt_at")
            attempt_count = _integer(row, "attempt_count")
            last_attempt_at = _optional_timestamp(row, "last_attempt_at")
            if next_attempt_at > now:
                raise WorkflowCAlertNotificationError("alert notification is not due")
            command = _command_from_row(row)
            delivery = NotificationDelivery(
                command_id=command.id,
                status=(
                    NotificationDeliveryStatus.PENDING
                    if row["status"] == "pending"
                    else NotificationDeliveryStatus.RETRY_WAIT
                ),
                attempt_count=attempt_count,
                max_attempts=lease.max_attempts,
                last_attempt_at=last_attempt_at,
                retry_at=(next_attempt_at if row["status"] == "retry_wait" else None),
            )
            changed = connection.execute(
                """UPDATE workflow_c_alert_notifications
                       SET status = 'leased', lease_owner = %s, lease_token = %s,
                           lease_expires_at = clock_timestamp() + %s::interval,
                           fencing_generation = fencing_generation + 1
                     WHERE project_id = %s AND id = %s
                       AND status IN ('pending', 'retry_wait')""",
                (
                    lease.worker_id,
                    lease.lease_token,
                    f"{self._lease_for.total_seconds()} seconds",
                    lease.project_id,
                    notification_id,
                ),
            ).rowcount
            if changed != 1:
                raise WorkflowCAlertNotificationError("alert notification lease changed")
        return _ClaimedNotification(command, delivery)

    def _record_delivery(
        self,
        lease: WorkerLease,
        claimed: _ClaimedNotification,
        delivery: NotificationDelivery,
    ) -> Mapping[str, object]:
        now = self._clock()
        with self._store.fenced_transaction(lease) as connection:
            self._assert_notification_lease(connection, lease, claimed.command.id)
            if delivery.status is NotificationDeliveryStatus.DELIVERED:
                changed = connection.execute(
                    """UPDATE workflow_c_alert_notifications
                           SET status = 'delivered', attempt_count = %s,
                               lease_owner = NULL, lease_token = NULL,
                               lease_expires_at = NULL, delivered_at = %s,
                               last_attempt_at = %s, last_error_code = NULL
                         WHERE project_id = %s AND id = %s""",
                    (
                        delivery.attempt_count,
                        now,
                        delivery.last_attempt_at,
                        lease.project_id,
                        claimed.command.id,
                    ),
                ).rowcount
                if changed != 1:
                    raise WorkflowCAlertNotificationError("alert notification completion changed")
                self._store.complete_in_transaction(
                    connection,
                    lease,
                    result_ref=f"workflow-c-alert-notification:{claimed.command.id}",
                    details={"notification_id": str(claimed.command.id), "delivered": True},
                )
                return {
                    "status": "delivered",
                    "job_id": str(lease.job_id),
                    "notification_id": str(claimed.command.id),
                }
            if delivery.status is NotificationDeliveryStatus.RETRY_WAIT:
                assert delivery.retry_at is not None and delivery.error_code is not None
                self._update_retry(connection, lease, claimed.command.id, delivery)
                self._store.defer_in_transaction(
                    connection,
                    lease,
                    reason_code=delivery.error_code,
                    details={"notification_id": str(claimed.command.id), "retry": True},
                    retry_delay=max(delivery.retry_at - now, timedelta(seconds=1)),
                )
                return {
                    "status": "retry_wait",
                    "job_id": str(lease.job_id),
                    "notification_id": str(claimed.command.id),
                    "error_code": delivery.error_code,
                }
            if delivery.status is not NotificationDeliveryStatus.FAILED:
                raise WorkflowCAlertNotificationError("alert notification delivery state is invalid")
            assert delivery.error_code is not None
            self._mark_dead_letter(connection, lease, claimed.command.id, delivery)
            self._store.fail_in_transaction(
                connection,
                lease,
                error_code=delivery.error_code,
                details={"notification_id": str(claimed.command.id), "retry": False},
            )
        return {
            "status": "failed",
            "job_id": str(lease.job_id),
            "notification_id": str(claimed.command.id),
            "error_code": delivery.error_code,
        }

    def _record_unexpected_failure(
        self,
        lease: WorkerLease,
        claimed: _ClaimedNotification,
        error: Exception,
    ) -> Mapping[str, object]:
        safe_code = "notification_dispatch_error"
        delivery = NotificationDelivery(
            command_id=claimed.command.id,
            status=NotificationDeliveryStatus.FAILED,
            attempt_count=min(claimed.delivery.attempt_count + 1, lease.max_attempts),
            max_attempts=lease.max_attempts,
            last_attempt_at=self._clock(),
            error_code=safe_code,
        )
        del error
        return self._record_delivery(lease, claimed, delivery)

    @staticmethod
    def _assert_notification_lease(connection: Any, lease: WorkerLease, notification_id: UUID) -> None:
        row = _one(
            connection.execute(
                """SELECT id FROM workflow_c_alert_notifications
                   WHERE project_id = %s AND id = %s AND status = 'leased'
                     AND lease_token = %s AND lease_expires_at > clock_timestamp()""",
                (lease.project_id, notification_id, lease.lease_token),
            )
        )
        if row is None:
            raise WorkflowCAlertNotificationError("alert notification was fenced")

    @staticmethod
    def _update_retry(
        connection: Any,
        lease: WorkerLease,
        notification_id: UUID,
        delivery: NotificationDelivery,
    ) -> None:
        assert delivery.retry_at is not None and delivery.error_code is not None
        changed = connection.execute(
            """UPDATE workflow_c_alert_notifications
                   SET status = 'retry_wait', attempt_count = %s,
                       last_attempt_at = %s, next_attempt_at = %s, last_error_code = %s,
                       lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL
                 WHERE project_id = %s AND id = %s""",
            (
                delivery.attempt_count,
                delivery.last_attempt_at,
                delivery.retry_at,
                delivery.error_code,
                lease.project_id,
                notification_id,
            ),
        ).rowcount
        if changed != 1:
            raise WorkflowCAlertNotificationError("alert notification retry changed")

    @staticmethod
    def _mark_dead_letter(
        connection: Any,
        lease: WorkerLease,
        notification_id: UUID,
        delivery: NotificationDelivery,
    ) -> None:
        assert delivery.error_code is not None
        changed = connection.execute(
            """UPDATE workflow_c_alert_notifications
                   SET status = 'dead_lettered', attempt_count = %s,
                       last_attempt_at = %s, last_error_code = %s, lease_owner = NULL,
                       lease_token = NULL, lease_expires_at = NULL
                 WHERE project_id = %s AND id = %s""",
            (
                delivery.attempt_count,
                delivery.last_attempt_at,
                delivery.error_code,
                lease.project_id,
                notification_id,
            ),
        ).rowcount
        if changed != 1:
            raise WorkflowCAlertNotificationError("alert notification terminal state changed")


def _notification_id(spec: WorkflowCJobSpec) -> UUID:
    value = spec.payload.get("notification_id")
    if not isinstance(value, str):
        raise WorkflowCJobSpecError("alert notification Worker spec needs notification_id")
    try:
        return UUID(value)
    except ValueError as error:
        raise WorkflowCJobSpecError("alert notification Worker notification_id is invalid") from error


def _command_from_row(row: Mapping[str, object]) -> NotificationOutboxCommand:
    payload = row["payload"]
    if not isinstance(payload, Mapping) or set(payload) != {"summary"}:
        raise WorkflowCAlertNotificationError("alert notification payload is not a safe summary")
    summary = payload["summary"]
    if not isinstance(summary, Mapping):
        raise WorkflowCAlertNotificationError("alert notification summary is invalid")
    try:
        command_summary = NotificationSummary(
            alert_id=_uuid(row, "alert_id"),
            project_id=_uuid(row, "project_id"),
            rule_key=_text(summary, "rule_key"),
            rule_version=_integer(summary, "rule_version"),
            rule_kind=AlertRuleKind(_text(summary, "rule_kind")),
            severity=AlertSeverity(_text(summary, "severity")),
            status=AlertStatus(_text(summary, "status")),
            event_type=_text(summary, "event_type"),
            occurred_at=_payload_timestamp(summary, "occurred_at"),
            detail_link=_text(summary, "detail_link"),
        )
        return NotificationOutboxCommand(
            id=_uuid(row, "id"),
            project_id=_uuid(row, "project_id"),
            alert_id=_uuid(row, "alert_id"),
            alert_version=_integer(row, "alert_version"),
            channel=NotificationChannel(_text(row, "channel")),
            topic=_text(row, "topic"),
            summary=command_summary,
            idempotency_key=_text(row, "idempotency_key"),
            created_at=_timestamp(row, "created_at"),
            payload_hash=_text(row, "payload_hash"),
        )
    except (TypeError, ValueError) as error:
        raise WorkflowCAlertNotificationError("alert notification row violates its contract") from error


def _one(cursor: Any) -> Mapping[str, object] | None:
    row = cursor.fetchone()
    if row is None:
        return None
    if isinstance(row, Mapping):
        return dict(row)
    raise WorkflowCAlertNotificationError("alert notification query must use mapping rows")


def _uuid(values: Mapping[str, object], key: str) -> UUID:
    value = values.get(key)
    if not isinstance(value, UUID):
        raise WorkflowCAlertNotificationError(f"alert notification {key} is invalid")
    return value


def _integer(values: Mapping[str, object], key: str) -> int:
    value = values.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise WorkflowCAlertNotificationError(f"alert notification {key} is invalid")
    return value


def _text(values: Mapping[str, object], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str):
        raise WorkflowCAlertNotificationError(f"alert notification {key} is invalid")
    return value


def _timestamp(values: Mapping[str, object], key: str) -> datetime:
    value = values.get(key)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise WorkflowCAlertNotificationError(f"alert notification {key} is invalid")
    return value


def _optional_timestamp(values: Mapping[str, object], key: str) -> datetime | None:
    value = values.get(key)
    if value is None:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise WorkflowCAlertNotificationError(f"alert notification {key} is invalid")
    return value


def _payload_timestamp(values: Mapping[str, object], key: str) -> datetime:
    value = values.get(key)
    if not isinstance(value, str):
        raise WorkflowCAlertNotificationError(f"alert notification {key} is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise WorkflowCAlertNotificationError(
            f"alert notification {key} is invalid"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise WorkflowCAlertNotificationError(f"alert notification {key} is invalid")
    return parsed


__all__ = [
    "PostgresWorkflowCAlertNotificationOperation",
    "WorkflowCAlertNotificationError",
]
