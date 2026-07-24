"""Project-scoped PostgreSQL repository for manual Workflow C alert control."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from geo_core.alerts.application import AlertCommandResult
from geo_core.alerts.domain import (
    Alert,
    AlertConflict,
    AlertDisposition,
    AlertDispositionKind,
    AlertNotFound,
    AlertRuleKind,
    AlertRuleViolation,
    AlertSeverity,
    AlertStatus,
    AlertTriggerSnapshot,
)
from geo_core.alerts.lifecycle import (
    acknowledge_alert,
    release_suppression,
    resolve_alert,
    suppress_alert,
)
from geo_core.alerts.notifications import (
    NotificationChannel,
    NotificationOutboxCommand,
    NotificationSummary,
    build_notification_commands,
)
from geo_core.alerts.postgres_operation_values import (
    canonical_hash,
    deterministic_id,
    parse_evidence,
    parse_rule,
    parse_scope,
    timestamp_value,
)
from geo_core.project_scope import set_project_scope


class PostgresWorkflowCAlertError(AlertConflict):
    """The durable alert lifecycle cannot safely satisfy an API command."""


class PostgresWorkflowCAlertRepository:
    """Use the database command boundary for every manual alert disposition."""

    def __init__(
        self,
        *,
        connect: Callable[[], Any],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._connect = connect
        self._clock = clock

    def get(self, *, project_id: UUID, alert_id: UUID) -> Alert:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            alert = _load_alert(connection, project_id=project_id, alert_id=alert_id)
            connection.rollback()
            return alert
        except psycopg.Error as error:
            connection.rollback()
            raise PostgresWorkflowCAlertError("Workflow C alert could not be read") from error
        finally:
            connection.close()

    def list(self, *, project_id: UUID) -> tuple[Alert, ...]:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            rows = connection.execute(
                """SELECT id FROM workflow_c_alerts
                   WHERE project_id = %s
                   ORDER BY updated_at DESC, id DESC""",
                (project_id,),
            ).fetchall()
            alerts = tuple(
                _load_alert(connection, project_id=project_id, alert_id=_uuid(row, "id"))
                for row in rows
            )
            connection.rollback()
            return alerts
        except psycopg.Error as error:
            connection.rollback()
            raise PostgresWorkflowCAlertError("Workflow C alerts could not be listed") from error
        finally:
            connection.close()

    def notifications(
        self, *, project_id: UUID, alert_id: UUID
    ) -> tuple[NotificationOutboxCommand, ...]:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            _load_alert(connection, project_id=project_id, alert_id=alert_id)
            rows = connection.execute(
                """SELECT * FROM workflow_c_alert_notifications
                   WHERE project_id = %s AND alert_id = %s
                   ORDER BY alert_version, channel""",
                (project_id, alert_id),
            ).fetchall()
            commands = tuple(_notification(_mapping(row)) for row in rows)
            connection.rollback()
            return commands
        except psycopg.Error as error:
            connection.rollback()
            raise PostgresWorkflowCAlertError(
                "Workflow C alert notifications could not be listed"
            ) from error
        finally:
            connection.close()

    def transition(
        self,
        *,
        project_id: UUID,
        alert_id: UUID,
        expected_version: int,
        operation: str,
        actor_id: str,
        reason: str,
        command_key: str,
        suppressed_until: datetime | None = None,
        occurred_at: datetime | None = None,
    ) -> AlertCommandResult:
        at = occurred_at or self._clock()
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            current = _load_alert(connection, project_id=project_id, alert_id=alert_id)
            updated = _transition_domain(
                current,
                expected_version=expected_version,
                operation=operation,
                actor_id=actor_id,
                reason=reason,
                command_key=command_key,
                occurred_at=at,
                suppressed_until=suppressed_until,
            )
            if updated is current:
                connection.rollback()
                return AlertCommandResult(current, (), True)
            commands = build_notification_commands(
                updated,
                event_type=_event_type(operation),
                created_at=at,
            )
            disposition = updated.dispositions[-1]
            command_payload = {
                "actor_id": disposition.actor_id,
                "disposition": disposition.disposition.value,
                "reason": disposition.reason,
                "suppressed_until": (
                    disposition.suppressed_until.isoformat()
                    if disposition.suppressed_until is not None
                    else None
                ),
            }
            row = connection.execute(
                """SELECT * FROM geo_transition_workflow_c_alert(
                       %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s::jsonb
                   )""",
                (
                    project_id,
                    alert_id,
                    expected_version,
                    command_key,
                    disposition.command_hash,
                    Jsonb(command_payload),
                    operation,
                    disposition.actor_id,
                    disposition.reason,
                    at,
                    disposition.suppressed_until,
                    Jsonb([_notification_value(command) for command in commands]),
                ),
            ).fetchone()
            if row is None or _uuid(row, "alert_id") != alert_id:
                raise PostgresWorkflowCAlertError(
                    "Workflow C alert disposition did not return its aggregate"
                )
            if bool(_mapping(row).get("replayed")):
                raise PostgresWorkflowCAlertError(
                    "Workflow C alert disposition unexpectedly replayed"
                )
            persisted = _load_alert(connection, project_id=project_id, alert_id=alert_id)
            connection.commit()
            return AlertCommandResult(persisted, commands, False)
        except AlertNotFound:
            connection.rollback()
            raise
        except (AlertConflict, AlertRuleViolation):
            connection.rollback()
            raise
        except psycopg.Error as error:
            connection.rollback()
            raise PostgresWorkflowCAlertError(
                "PostgreSQL rejected the Workflow C alert disposition"
            ) from error
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


def _load_alert(connection: Any, *, project_id: UUID, alert_id: UUID) -> Alert:
    row = connection.execute(
        """SELECT alert.*, rule.rule_hash AS stored_rule_hash,
                  rule.status AS stored_rule_status
           FROM workflow_c_alerts AS alert
           JOIN workflow_c_alert_rule_versions AS rule
             ON rule.project_id = alert.project_id AND rule.id = alert.rule_version_id
           WHERE alert.project_id = %s AND alert.id = %s""",
        (project_id, alert_id),
    ).fetchone()
    if row is None:
        raise AlertNotFound("alert does not exist in this project")
    values = _mapping(row)
    payload = _mapping(values.get("payload"))
    if (
        set(payload)
        != {
            "schema_version",
            "rule",
            "scope",
            "trigger_snapshot",
            "evidence",
        }
        or payload.get("schema_version") != "workflow-c-alert-v1"
    ):
        raise PostgresWorkflowCAlertError("Workflow C alert payload schema is invalid")
    try:
        rule = parse_rule(payload["rule"], project_id)
        scope = parse_scope(payload["scope"], project_id)
        evidence = parse_evidence(payload["evidence"])
    except (TypeError, ValueError) as error:
        raise PostgresWorkflowCAlertError("Workflow C alert frozen payload is invalid") from error
    if (
        rule.id != _uuid(values, "rule_version_id")
        or rule.rule_hash != _text(values, "stored_rule_hash")
        or _text(values, "stored_rule_status") not in {"approved", "retired"}
    ):
        raise PostgresWorkflowCAlertError("Workflow C alert rule lineage is corrupt")
    trigger_raw = _mapping(payload.get("trigger_snapshot"))
    if set(trigger_raw) != {"values", "captured_at", "snapshot_hash"}:
        raise PostgresWorkflowCAlertError("Workflow C alert trigger schema is invalid")
    values_raw = trigger_raw.get("values")
    if not isinstance(values_raw, Mapping):
        raise PostgresWorkflowCAlertError("Workflow C alert trigger values are invalid")
    try:
        trigger = AlertTriggerSnapshot(
            values=dict(values_raw),
            captured_at=timestamp_value(
                {"captured_at": trigger_raw.get("captured_at")},
                "captured_at",
                "alert trigger capture time",
            ),
        )
    except (TypeError, ValueError) as error:
        raise PostgresWorkflowCAlertError("Workflow C alert trigger is invalid") from error
    if trigger.snapshot_hash != _text_from(
        trigger_raw, "snapshot_hash"
    ) or trigger.snapshot_hash != _text(values, "trigger_snapshot_hash"):
        raise PostgresWorkflowCAlertError("Workflow C alert trigger hash is corrupt")
    disposition_rows = connection.execute(
        """SELECT * FROM workflow_c_alert_dispositions
           WHERE project_id = %s AND alert_id = %s
           ORDER BY resulting_version""",
        (project_id, alert_id),
    ).fetchall()
    dispositions = tuple(_disposition(_mapping(item)) for item in disposition_rows)
    resolved_at = _optional_datetime(values, "resolved_at")
    status = AlertStatus(_text(values, "status"))
    if (status is AlertStatus.RESOLVED) != (resolved_at is not None):
        raise PostgresWorkflowCAlertError("Workflow C alert resolved time is corrupt")
    if resolved_at is not None and resolved_at != _datetime(values, "updated_at"):
        raise PostgresWorkflowCAlertError("Workflow C alert resolved time is inconsistent")
    try:
        return Alert(
            id=_uuid(values, "id"),
            project_id=_uuid(values, "project_id"),
            rule_version=rule,
            scope=scope,
            trigger_snapshot=trigger,
            evidence=evidence,
            severity=AlertSeverity(_text(values, "severity")),
            dedupe_key=_text(values, "dedupe_key"),
            status=status,
            opened_at=_datetime(values, "opened_at"),
            updated_at=_datetime(values, "updated_at"),
            version=_integer(values, "version"),
            dispositions=dispositions,
            suppressed_until=_suppressed_until(status, dispositions),
            suppression_reason=_suppression_reason(status, dispositions),
        )
    except (TypeError, ValueError) as error:
        raise PostgresWorkflowCAlertError("Workflow C alert aggregate is invalid") from error


def _transition_domain(
    alert: Alert,
    *,
    expected_version: int,
    operation: str,
    actor_id: str,
    reason: str,
    command_key: str,
    occurred_at: datetime,
    suppressed_until: datetime | None,
) -> Alert:
    if operation == "acknowledge":
        return acknowledge_alert(
            alert,
            expected_version=expected_version,
            actor_id=actor_id,
            reason=reason,
            occurred_at=occurred_at,
            command_key=command_key,
        )
    if operation == "suppress":
        if suppressed_until is None:
            raise AlertRuleViolation("alert suppression expiry is required")
        return suppress_alert(
            alert,
            expected_version=expected_version,
            actor_id=actor_id,
            reason=reason,
            occurred_at=occurred_at,
            suppressed_until=suppressed_until,
            command_key=command_key,
        )
    if operation == "unsuppress":
        if suppressed_until is not None:
            raise AlertRuleViolation("unsuppress cannot contain an expiry")
        return release_suppression(
            alert,
            expected_version=expected_version,
            actor_id=actor_id,
            reason=reason,
            occurred_at=occurred_at,
            command_key=command_key,
        )
    if operation == "resolve":
        if suppressed_until is not None:
            raise AlertRuleViolation("resolve cannot contain an expiry")
        return resolve_alert(
            alert,
            expected_version=expected_version,
            actor_id=actor_id,
            reason=reason,
            occurred_at=occurred_at,
            command_key=command_key,
        )
    raise AlertRuleViolation("Workflow C alert operation is unsupported")


def _event_type(operation: str) -> str:
    return {
        "acknowledge": "acknowledged",
        "suppress": "suppressed",
        "unsuppress": "unsuppressed",
        "resolve": "resolved",
    }.get(operation, "")


def _notification_value(command: NotificationOutboxCommand) -> Mapping[str, object]:
    spec_payload: dict[str, object] = {
        "schema_version": 1,
        "kind": "workflow_c.alert.notify",
        "notification_id": str(command.id),
    }
    job_key = f"workflow-c-alert-notify:{command.idempotency_key}"
    return {
        "id": str(command.id),
        "alert_id": str(command.alert_id),
        "alert_version": command.alert_version,
        "channel": command.channel.value,
        "topic": command.topic,
        "idempotency_key": command.idempotency_key,
        "payload_hash": command.payload_hash,
        "payload": {"summary": command.summary.payload()},
        "safe_summary": (
            f"Workflow C {command.summary.severity.value} alert "
            f"{command.alert_id} {command.summary.event_type}"
        ),
        "created_at": command.created_at.isoformat(),
        "notify_job_id": str(deterministic_id(command.project_id, "notify", job_key)),
        "notify_spec_hash": canonical_hash(spec_payload),
        "notify_spec_payload": spec_payload,
    }


def _disposition(row: Mapping[str, object]) -> AlertDisposition:
    try:
        result = AlertDisposition(
            disposition=AlertDispositionKind(_text(row, "kind")),
            from_status=AlertStatus(_text(row, "from_status")),
            to_status=AlertStatus(_text(row, "to_status")),
            actor_id=_text(row, "actor_id"),
            occurred_at=_datetime(row, "occurred_at"),
            reason=_text(row, "reason"),
            command_key=_text(row, "command_key"),
            resulting_version=_integer(row, "resulting_version"),
            suppressed_until=_optional_datetime(row, "suppressed_until"),
        )
    except (TypeError, ValueError) as error:
        raise PostgresWorkflowCAlertError("Workflow C alert disposition is invalid") from error
    if result.command_hash != _text(row, "command_hash"):
        raise PostgresWorkflowCAlertError("Workflow C alert disposition hash is corrupt")
    return result


def _notification(row: Mapping[str, object]) -> NotificationOutboxCommand:
    payload = _mapping(row.get("payload"))
    summary = _mapping(payload.get("summary"))
    if set(payload) != {"summary"} or set(summary) != {
        "alert_id",
        "project_id",
        "rule_key",
        "rule_version",
        "rule_kind",
        "severity",
        "status",
        "event_type",
        "occurred_at",
        "detail_link",
    }:
        raise PostgresWorkflowCAlertError("Workflow C alert notification payload is invalid")
    try:
        result = NotificationOutboxCommand(
            id=_uuid(row, "id"),
            project_id=_uuid(row, "project_id"),
            alert_id=_uuid(row, "alert_id"),
            alert_version=_integer(row, "alert_version"),
            channel=NotificationChannel(_text(row, "channel")),
            topic=_text(row, "topic"),
            summary=NotificationSummary(
                alert_id=_uuid(summary, "alert_id"),
                project_id=_uuid(summary, "project_id"),
                rule_key=_text(summary, "rule_key"),
                rule_version=_integer(summary, "rule_version"),
                rule_kind=AlertRuleKind(_text(summary, "rule_kind")),
                severity=AlertSeverity(_text(summary, "severity")),
                status=AlertStatus(_text(summary, "status")),
                event_type=_text(summary, "event_type"),
                occurred_at=_datetime_from(summary, "occurred_at"),
                detail_link=_text(summary, "detail_link"),
            ),
            idempotency_key=_text(row, "idempotency_key"),
            created_at=_datetime(row, "created_at"),
            payload_hash=_text(row, "payload_hash"),
        )
    except (TypeError, ValueError) as error:
        raise PostgresWorkflowCAlertError("Workflow C alert notification is invalid") from error
    return result


def _suppressed_until(
    status: AlertStatus, dispositions: tuple[AlertDisposition, ...]
) -> datetime | None:
    return dispositions[-1].suppressed_until if status is AlertStatus.SUPPRESSED else None


def _suppression_reason(
    status: AlertStatus, dispositions: tuple[AlertDisposition, ...]
) -> str | None:
    return dispositions[-1].reason if status is AlertStatus.SUPPRESSED else None


def _mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    raise PostgresWorkflowCAlertError("Workflow C alert row is malformed")


def _uuid(row: Mapping[str, object], field: str) -> UUID:
    value = row.get(field)
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as error:
        raise PostgresWorkflowCAlertError(f"Workflow C alert {field} is malformed") from error


def _integer(row: Mapping[str, object], field: str) -> int:
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise PostgresWorkflowCAlertError(f"Workflow C alert {field} is malformed")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise PostgresWorkflowCAlertError(f"Workflow C alert {field} is malformed") from error
    if result < 1:
        raise PostgresWorkflowCAlertError(f"Workflow C alert {field} is malformed")
    return result


def _datetime(row: Mapping[str, object], field: str) -> datetime:
    value = row.get(field)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PostgresWorkflowCAlertError(f"Workflow C alert {field} is malformed")
    return value


def _datetime_from(row: Mapping[str, object], field: str) -> datetime:
    try:
        return timestamp_value({field: row.get(field)}, field, f"Workflow C alert {field}")
    except (TypeError, ValueError) as error:
        raise PostgresWorkflowCAlertError(f"Workflow C alert {field} is malformed") from error


def _optional_datetime(row: Mapping[str, object], field: str) -> datetime | None:
    return None if row.get(field) is None else _datetime(row, field)


def _text(row: Mapping[str, object], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise PostgresWorkflowCAlertError(f"Workflow C alert {field} is malformed")
    return value


def _text_from(row: Mapping[str, object], field: str) -> str:
    return _text(row, field)


__all__ = [
    "PostgresWorkflowCAlertError",
    "PostgresWorkflowCAlertRepository",
]
