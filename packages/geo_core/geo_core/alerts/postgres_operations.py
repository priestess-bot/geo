"""Fenced, durable Workflow C alert scheduling and evaluation operations.

The broker carries only a Job/project wakeup.  Schedule and evaluation inputs
are reconstructed from :class:`WorkflowCJobSpec` after claiming a durable
lease, and the PostgreSQL RPCs atomically persist both the domain result and
the next durable wakeups.  The functions are intentionally Worker-only: a
stale process cannot advance a schedule or create an alert after its fence has
changed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from geo_core.alerts.domain import (
    AlertEvidenceReference,
    AlertRuleVersion,
    AlertScope,
)
from geo_core.alerts.evaluation import AlertEvaluation, evaluate_alert_rule
from geo_core.alerts.lifecycle import open_alert
from geo_core.alerts.notifications import (
    NotificationChannel,
    build_notification_commands,
)
from geo_core.alerts.postgres_notification_values import _notification_value
from geo_core.alerts.postgres_operation_values import (
    ALERT_OPERATION_NAMESPACE,
    canonical_hash,
    deterministic_id,
    exact_mapping,
    json_mapping,
    json_text,
    json_value,
    parse_channels,
    parse_evidence,
    parse_rule,
    parse_scope,
    positive_int,
    rule_value,
    timestamp_value,
    uuid_value,
)
from geo_core.jobs.postgres import WorkerLease
from geo_core.workflow_c_job_specs import (
    WorkflowCJobSpec,
    WorkflowCJobSpecError,
)


SCHEDULE_SCHEMA_VERSION = "workflow-c-alert-schedule-v1"
EVALUATION_RESULT_SCHEMA_VERSION = "workflow-c-alert-evaluation-v1"


class WorkflowCAlertOperationError(RuntimeError):
    """A persisted Workflow C alert command is malformed or was fenced."""


class _FencedJobStore(Protocol):
    def fenced_transaction(self, lease: WorkerLease) -> AbstractContextManager[Any]: ...


class _WorkflowCJobSpecReader(Protocol):
    def load(self, lease: WorkerLease) -> WorkflowCJobSpec: ...


@dataclass(frozen=True)
class WorkflowCAlertOperations:
    """The two non-delivery operations needed by the Workflow C composer."""

    schedule: "PostgresWorkflowCAlertScheduleOperation"
    evaluate: "PostgresWorkflowCAlertEvaluateOperation"


def build_workflow_c_alert_operations(
    *,
    store: _FencedJobStore,
    specs: _WorkflowCJobSpecReader,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> WorkflowCAlertOperations:
    """Construct the real schedule/evaluation operations with one clock."""

    return WorkflowCAlertOperations(
        schedule=PostgresWorkflowCAlertScheduleOperation(
            store=store, specs=specs, clock=clock
        ),
        evaluate=PostgresWorkflowCAlertEvaluateOperation(
            store=store, specs=specs, clock=clock
        ),
    )


class PostgresWorkflowCAlertScheduleOperation:
    """Advance one active schedule and atomically enqueue evaluation + successor."""

    kind = "workflow_c.alert.schedule"

    def __init__(
        self,
        *,
        store: _FencedJobStore,
        specs: _WorkflowCJobSpecReader,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._specs = specs
        self._clock = clock

    def execute(self, lease: WorkerLease) -> Mapping[str, object]:
        _require_kind(lease, self.kind)
        command = _schedule_command(self._specs.load(lease), lease)
        now = _aware_now(self._clock)
        if command.scheduled_for > now:
            raise WorkflowCAlertOperationError("alert schedule command is not due")
        next_run_at = now + timedelta(seconds=command.interval_seconds)
        evaluation_payload = command.evaluation_payload()
        successor_payload = command.successor_payload(next_run_at)
        evaluation_hash = canonical_hash(evaluation_payload)
        successor_hash = canonical_hash(successor_payload)
        evaluation_idempotency_key = (
            f"workflow-c-alert-evaluate:{command.schedule_id}:"
            f"v{command.schedule_version}:{command.scheduled_for.isoformat()}"
        )
        successor_idempotency_key = (
            f"workflow-c-alert-schedule:{command.schedule_id}:"
            f"v{command.schedule_version}:{next_run_at.isoformat()}"
        )

        # This Worker-only RPC verifies the durable lease/fence and schedule
        # CAS, creates both immutable Job specs/outbox records, advances
        # next_run_at, and marks this schedule job succeeded in one commit.
        with self._store.fenced_transaction(lease) as connection:
            row = _mapping_row(
                connection.execute(
                    """SELECT * FROM geo_enqueue_workflow_c_alert_evaluation(
                           %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s::jsonb, %s,
                           %s, %s, %s::jsonb, %s, %s
                       )""",
                    (
                        lease.job_id,
                        lease.project_id,
                        lease.lease_token,
                        lease.fencing_generation,
                        command.schedule_id,
                        command.schedule_version,
                        command.scheduled_for,
                        deterministic_id(
                            lease.project_id, "evaluate", evaluation_idempotency_key
                        ),
                        evaluation_hash,
                        json_text(evaluation_payload),
                        evaluation_idempotency_key,
                        deterministic_id(
                            lease.project_id, "schedule", successor_idempotency_key
                        ),
                        successor_hash,
                        json_text(successor_payload),
                        successor_idempotency_key,
                        next_run_at,
                    ),
                )
            )
        if row is None:
            raise WorkflowCAlertOperationError("alert schedule enqueue was fenced")
        _expect_text(row, "status", "scheduled")
        evaluation_job_id = _expect_uuid(row, "evaluation_job_id")
        successor_job_id = _expect_uuid(row, "successor_job_id")
        return {
            "status": "scheduled",
            "job_id": str(lease.job_id),
            "schedule_id": str(command.schedule_id),
            "evaluation_job_id": str(evaluation_job_id),
            "successor_job_id": str(successor_job_id),
            "next_run_at": next_run_at.isoformat(),
        }


class PostgresWorkflowCAlertEvaluateOperation:
    """Evaluate one frozen rule and atomically persist its alert side effects."""

    kind = "workflow_c.alert.evaluate"

    def __init__(
        self,
        *,
        store: _FencedJobStore,
        specs: _WorkflowCJobSpecReader,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._specs = specs
        self._clock = clock

    def execute(self, lease: WorkerLease) -> Mapping[str, object]:
        _require_kind(lease, self.kind)
        command = _evaluation_command(self._specs.load(lease), lease)
        evaluated_at = _aware_now(self._clock)
        evaluation = evaluate_alert_rule(
            rule_version=command.rule_version,
            scope=command.scope,
            input_values=command.input_values,
            evidence=command.evidence,
            evaluated_at=evaluated_at,
        )
        completion = _evaluation_completion(
            lease=lease,
            command=command,
            evaluation=evaluation,
        )

        # The RPC is the only writer of workflow_c alert state.  It verifies
        # this exact lease/fence, persists the immutable result row, opens or
        # replays the deduped alert, inserts notification rows and their
        # durable notify Jobs, then completes this durable Job atomically.
        with self._store.fenced_transaction(lease) as connection:
            row = _mapping_row(
                connection.execute(
                    """SELECT * FROM geo_complete_workflow_c_alert_evaluation(
                           %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s, %s::jsonb, %s,
                           %s, %s, %s::jsonb, %s::jsonb
                       )""",
                    (
                        lease.job_id,
                        lease.project_id,
                        lease.lease_token,
                        lease.fencing_generation,
                        completion.evaluation_id,
                        command.schedule_id,
                        command.schedule_version,
                        command.rule_version.id,
                        command.rule_version.rule_hash,
                        evaluation.input_hash,
                        evaluation.evaluation_hash,
                        completion.status,
                        evaluation.matched,
                        json_text(completion.evaluation_payload),
                        evaluated_at,
                        completion.alert_id,
                        completion.alert_dedupe_key,
                        json_text(completion.alert_payload),
                        json_text(completion.notification_payload),
                    ),
                )
            )
        if row is None:
            raise WorkflowCAlertOperationError("alert evaluation completion was fenced")
        _expect_text(row, "status", completion.status)
        persisted_hash = _expect_text(row, "evaluation_hash", evaluation.evaluation_hash)
        if persisted_hash != evaluation.evaluation_hash:
            raise WorkflowCAlertOperationError("alert evaluation result hash changed")
        notification_count = _expect_int(row, "notification_count")
        return {
            "status": completion.status,
            "job_id": str(lease.job_id),
            "evaluation_id": str(completion.evaluation_id),
            "evaluation_hash": evaluation.evaluation_hash,
            "alert_id": str(completion.alert_id) if completion.alert_id is not None else None,
            "notification_count": notification_count,
        }


@dataclass(frozen=True)
class _ScheduleCommand:
    schedule_id: UUID
    schedule_version: int
    scheduled_for: datetime
    interval_seconds: int
    evaluation: "_EvaluationCommand"

    def evaluation_payload(self) -> dict[str, object]:
        return self.evaluation.payload()

    def successor_payload(self, scheduled_for: datetime) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": PostgresWorkflowCAlertScheduleOperation.kind,
            "schedule_id": str(self.schedule_id),
            "schedule_version": self.schedule_version,
            "scheduled_for": scheduled_for.isoformat(),
            "interval_seconds": self.interval_seconds,
            "evaluation": self.evaluation.embedded_value(),
        }


@dataclass(frozen=True)
class _EvaluationCommand:
    schedule_id: UUID
    schedule_version: int
    rule_version: AlertRuleVersion
    scope: AlertScope
    input_values: Mapping[str, object]
    evidence: tuple[AlertEvidenceReference, ...]
    channels: tuple[NotificationChannel, ...]

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": PostgresWorkflowCAlertEvaluateOperation.kind,
            **self.embedded_value(),
        }

    def embedded_value(self) -> dict[str, object]:
        return {
            "schedule_id": str(self.schedule_id),
            "schedule_version": self.schedule_version,
            "rule": rule_value(self.rule_version),
            "scope": self.scope.canonical_value() | {
                "dimensions": dict(self.scope.dimensions)
            },
            "input_values": json_value(self.input_values),
            "evidence": [item.canonical_value() for item in self.evidence],
            "channels": [item.value for item in self.channels],
        }


@dataclass(frozen=True)
class _EvaluationCompletion:
    evaluation_id: UUID
    status: str
    evaluation_payload: Mapping[str, object]
    alert_id: UUID | None
    alert_dedupe_key: str | None
    alert_payload: Mapping[str, object] | None
    notification_payload: tuple[Mapping[str, object], ...]


def _schedule_command(spec: WorkflowCJobSpec, lease: WorkerLease) -> _ScheduleCommand:
    values = exact_mapping(
        spec.payload,
        {
            "schema_version",
            "kind",
            "schedule_id",
            "schedule_version",
            "scheduled_for",
            "interval_seconds",
            "evaluation",
        },
        "alert schedule Worker spec",
    )
    schedule_id = uuid_value(values, "schedule_id", "alert schedule id")
    schedule_version = positive_int(values, "schedule_version", "alert schedule version")
    scheduled_for = timestamp_value(values, "scheduled_for", "alert schedule run time")
    interval = positive_int(values, "interval_seconds", "alert schedule interval")
    if not 60 <= interval <= 86_400:
        raise WorkflowCJobSpecError("alert schedule interval must be between 60 and 86400")
    evaluation = _embedded_evaluation(
        values["evaluation"], lease, schedule_id=schedule_id, schedule_version=schedule_version
    )
    return _ScheduleCommand(
        schedule_id=schedule_id,
        schedule_version=schedule_version,
        scheduled_for=scheduled_for,
        interval_seconds=interval,
        evaluation=evaluation,
    )


def _evaluation_command(spec: WorkflowCJobSpec, lease: WorkerLease) -> _EvaluationCommand:
    values = exact_mapping(
        spec.payload,
        {
            "schema_version",
            "kind",
            "schedule_id",
            "schedule_version",
            "rule",
            "scope",
            "input_values",
            "evidence",
            "channels",
        },
        "alert evaluation Worker spec",
    )
    embedded = {
        key: values[key]
        for key in (
            "schedule_id",
            "schedule_version",
            "rule",
            "scope",
            "input_values",
            "evidence",
            "channels",
        )
    }
    return _embedded_evaluation(
        embedded,
        lease,
        schedule_id=uuid_value(values, "schedule_id", "alert schedule id"),
        schedule_version=positive_int(values, "schedule_version", "alert schedule version"),
    )


def _embedded_evaluation(
    raw: object,
    lease: WorkerLease,
    *,
    schedule_id: UUID,
    schedule_version: int,
) -> _EvaluationCommand:
    values = exact_mapping(
        raw,
        {"schedule_id", "schedule_version", "rule", "scope", "input_values", "evidence", "channels"},
        "alert evaluation input",
    )
    embedded_schedule_id = uuid_value(values, "schedule_id", "alert schedule id")
    embedded_schedule_version = positive_int(
        values, "schedule_version", "alert schedule version"
    )
    if embedded_schedule_id != schedule_id or embedded_schedule_version != schedule_version:
        raise WorkflowCJobSpecError("alert schedule identity changed in embedded evaluation")
    rule = parse_rule(values["rule"], lease.project_id)
    scope = parse_scope(values["scope"], lease.project_id)
    raw_input = values["input_values"]
    if not isinstance(raw_input, Mapping) or not raw_input:
        raise WorkflowCJobSpecError("alert evaluation input values must be a non-empty object")
    input_values = json_mapping(raw_input, "alert evaluation input values")
    evidence = parse_evidence(values["evidence"])
    channels = parse_channels(values["channels"])
    return _EvaluationCommand(
        schedule_id=schedule_id,
        schedule_version=schedule_version,
        rule_version=rule,
        scope=scope,
        input_values=input_values,
        evidence=evidence,
        channels=channels,
    )


def _evaluation_completion(
    *,
    lease: WorkerLease,
    command: _EvaluationCommand,
    evaluation: AlertEvaluation,
) -> _EvaluationCompletion:
    evaluation_id = deterministic_id(
        lease.project_id, "alert-evaluation", evaluation.evaluation_hash
    )
    evaluation_payload: dict[str, object] = {
        "schema_version": EVALUATION_RESULT_SCHEMA_VERSION,
        **evaluation.canonical_value(),
        "trigger_snapshot": (
            {
                "values": json_value(evaluation.trigger_snapshot.values),
                "captured_at": evaluation.trigger_snapshot.captured_at.isoformat(),
                "snapshot_hash": evaluation.trigger_snapshot.snapshot_hash,
            }
            if evaluation.trigger_snapshot is not None
            else None
        ),
        "evaluation_hash": evaluation.evaluation_hash,
        "rule": rule_value(command.rule_version),
        "schedule": {
            "id": str(command.schedule_id),
            "version": command.schedule_version,
        },
    }
    if evaluation.trigger_snapshot is None:
        return _EvaluationCompletion(
            evaluation_id=evaluation_id,
            status="not_matched",
            evaluation_payload=evaluation_payload,
            alert_id=None,
            alert_dedupe_key=None,
            alert_payload=None,
            notification_payload=(),
        )
    alert_id = deterministic_id(
        lease.project_id, "alert", evaluation.evaluation_hash
    )
    alert = open_alert(
        alert_id=alert_id,
        rule_version=command.rule_version,
        scope=command.scope,
        trigger_snapshot=evaluation.trigger_snapshot,
        evidence=evaluation.evidence,
        opened_at=evaluation.evaluated_at,
    )
    notifications = build_notification_commands(
        alert,
        event_type="opened",
        created_at=evaluation.evaluated_at,
        channels=command.channels,
    )
    alert_payload = {
        "schema_version": "workflow-c-alert-v1",
        "rule": rule_value(alert.rule_version),
        "scope": alert.scope.canonical_value() | {"dimensions": dict(alert.scope.dimensions)},
        "trigger_snapshot": {
            "values": json_value(alert.trigger_snapshot.values),
            "captured_at": alert.trigger_snapshot.captured_at.isoformat(),
            "snapshot_hash": alert.trigger_snapshot.snapshot_hash,
        },
        "evidence": [item.canonical_value() for item in alert.evidence],
    }
    return _EvaluationCompletion(
        evaluation_id=evaluation_id,
        status="matched",
        evaluation_payload=evaluation_payload,
        alert_id=alert.id,
        alert_dedupe_key=alert.dedupe_key,
        alert_payload=alert_payload,
        notification_payload=tuple(
            _notification_value(item, lease.project_id) for item in notifications
        ),
    )


def _mapping_row(cursor: Any) -> Mapping[str, object] | None:
    row = cursor.fetchone()
    if row is None:
        return None
    if isinstance(row, Mapping):
        return dict(row)
    raise WorkflowCAlertOperationError("Workflow C alert RPC must return a mapping row")


def _require_kind(lease: WorkerLease, expected: str) -> None:
    if lease.kind != expected:
        raise WorkflowCAlertOperationError("Workflow C alert Worker kind is invalid")


def _aware_now(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise WorkflowCAlertOperationError("Workflow C alert clock must be timezone-aware")
    return value




def _expect_uuid(row: Mapping[str, object], key: str) -> UUID:
    value = row.get(key)
    if not isinstance(value, UUID):
        raise WorkflowCAlertOperationError(f"Workflow C alert RPC {key} is invalid")
    return value


def _expect_text(row: Mapping[str, object], key: str, expected: str | None = None) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise WorkflowCAlertOperationError(f"Workflow C alert RPC {key} is invalid")
    if expected is not None and value != expected:
        raise WorkflowCAlertOperationError(f"Workflow C alert RPC {key} changed")
    return value


def _expect_int(row: Mapping[str, object], key: str) -> int:
    value = row.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise WorkflowCAlertOperationError(f"Workflow C alert RPC {key} is invalid")
    return value


__all__ = [
    "ALERT_OPERATION_NAMESPACE",
    "EVALUATION_RESULT_SCHEMA_VERSION",
    "SCHEDULE_SCHEMA_VERSION",
    "PostgresWorkflowCAlertEvaluateOperation",
    "PostgresWorkflowCAlertScheduleOperation",
    "WorkflowCAlertOperationError",
    "WorkflowCAlertOperations",
    "build_workflow_c_alert_operations",
]
