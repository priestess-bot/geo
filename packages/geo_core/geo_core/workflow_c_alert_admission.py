"""Server-resolved alert evaluation admission from frozen Workflow C outputs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid5

from psycopg.types.json import Jsonb

from geo_core.alerts import AlertRuleKind
from geo_core.alerts.postgres_operation_values import rule_value
from geo_core.project_scope import set_project_scope
from geo_core.workflow_c_alert_admission_contracts import (
    ALERT_ADMISSION_NAMESPACE,
    AlertEvaluationSelector,
    WorkflowCAlertAdmissionError,
    _ResolvedAlertInput,
)
from geo_core.workflow_c_alert_inputs import (
    _baseline_input,
    _canonical_hash,
    _canonical_json,
    _comparison_source,
    _completion_input,
    _drift_input,
    _drift_source,
    _external_health_input,
    _external_health_source,
    _negative_question_input,
    _row,
    _semantic_source,
    _text,
    _threshold_input,
)
from geo_core.workflow_c_alert_rules import (
    AlertRuleReleaseStatus,
    WorkflowCAlertRuleError,
    WorkflowCAlertRuleNotFound,
    alert_rule_release_from_row,
)
from geo_core.workflow_c_job_specs import (
    WorkflowCEnqueuedJob,
    enqueue_workflow_c_job_spec_in_transaction,
)


class PostgresWorkflowCAlertAdmissionRepository:
    """Resolve immutable projections and enqueue one one-shot evaluation atomically."""

    def __init__(
        self,
        *,
        connect: Callable[[], Any],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._connect = connect
        self._clock = clock

    def enqueue(
        self,
        *,
        project_id: UUID,
        selector: AlertEvaluationSelector,
        actor_id: str,
        idempotency_key: str,
    ) -> WorkflowCEnqueuedJob:
        actor = _text(actor_id, "alert admission actor", maximum=200)
        key = _text(idempotency_key, "Idempotency-Key", maximum=200)
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            rule_row = _row(
                connection.execute(
                    """SELECT * FROM workflow_c_alert_rule_versions
                        WHERE project_id = %s AND id = %s""",
                    (project_id, selector.alert_rule_id),
                ).fetchone()
            )
            if rule_row is None:
                raise WorkflowCAlertRuleNotFound("alert rule does not exist")
            release = alert_rule_release_from_row(rule_row)
            if release.status is not AlertRuleReleaseStatus.APPROVED:
                raise WorkflowCAlertRuleError("only an approved alert rule can be evaluated")
            resolved = self._resolve(
                connection,
                project_id=project_id,
                kind=release.rule.kind,
                parameters=release.rule.parameters,
                selector=selector,
            )
            selector_hash = _canonical_hash(selector.canonical_value())
            schedule_id = uuid5(
                ALERT_ADMISSION_NAMESPACE,
                f"{project_id}:{release.id}:{selector_hash}",
            )
            now = self._clock()
            if now.tzinfo is None or now.utcoffset() is None:
                raise WorkflowCAlertAdmissionError("alert admission clock must be timezone-aware")
            schedule_payload = {
                "schema_version": 1,
                "mode": "one_shot_frozen_output",
                "selector": selector.canonical_value(),
                "requested_by": actor,
            }
            connection.execute(
                """INSERT INTO workflow_c_alert_schedules(
                       id, project_id, rule_version_id, snapshot_selector_hash,
                       status, next_run_at, version, payload, created_at, updated_at
                   ) VALUES (%s, %s, %s, %s, 'retired', %s, 1, %s, %s, %s)
                   ON CONFLICT (project_id, rule_version_id, snapshot_selector_hash)
                   DO NOTHING""",
                (
                    schedule_id,
                    project_id,
                    release.id,
                    selector_hash,
                    now,
                    Jsonb(schedule_payload),
                    now,
                    now,
                ),
            )
            stored_schedule = _row(
                connection.execute(
                    """SELECT id, version, status, payload
                         FROM workflow_c_alert_schedules
                        WHERE project_id = %s AND rule_version_id = %s
                          AND snapshot_selector_hash = %s""",
                    (project_id, release.id, selector_hash),
                ).fetchone()
            )
            if (
                stored_schedule is None
                or stored_schedule.get("id") != schedule_id
                or stored_schedule.get("version") != 1
                or stored_schedule.get("status") != "retired"
                or _canonical_json(stored_schedule.get("payload"))
                != _canonical_json(schedule_payload)
            ):
                raise WorkflowCAlertAdmissionError("alert selector identity was reused")
            payload: dict[str, object] = {
                "schema_version": 1,
                "kind": "workflow_c.alert.evaluate",
                "schedule_id": str(schedule_id),
                "schedule_version": 1,
                "rule": rule_value(release.rule),
                "scope": resolved.scope.canonical_value()
                | {"dimensions": dict(resolved.scope.dimensions)},
                "input_values": dict(resolved.values),
                "evidence": [item.canonical_value() for item in resolved.evidence],
                "channels": [item.value for item in selector.channels],
            }
            result = enqueue_workflow_c_job_spec_in_transaction(
                connection,
                project_id=project_id,
                kind="workflow_c.alert.evaluate",
                payload=payload,
                idempotency_key=key,
                max_attempts=selector.max_attempts,
            )
            connection.commit()
            return result
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _resolve(
        self,
        connection: Any,
        *,
        project_id: UUID,
        kind: AlertRuleKind,
        parameters: Mapping[str, object],
        selector: AlertEvaluationSelector,
    ) -> _ResolvedAlertInput:
        if kind is AlertRuleKind.THRESHOLD:
            return _threshold_input(
                _semantic_source(connection, project_id, selector.source_hash),
                parameters=parameters,
                selector=selector,
                project_id=project_id,
            )
        if kind is AlertRuleKind.COMPLETION_FRESHNESS:
            return _completion_input(
                _semantic_source(connection, project_id, selector.source_hash),
                selector=selector,
                project_id=project_id,
            )
        if kind is AlertRuleKind.BASELINE_DELTA:
            if selector.baseline_source_hash is None:
                raise WorkflowCAlertAdmissionError("baseline delta requires a baseline snapshot")
            baseline = _semantic_source(connection, project_id, selector.baseline_source_hash)
            current = _semantic_source(connection, project_id, selector.source_hash)
            return _baseline_input(
                baseline,
                current,
                parameters=parameters,
                selector=selector,
                project_id=project_id,
            )
        if kind is AlertRuleKind.NEGATIVE_QUESTION:
            return _negative_question_input(
                _comparison_source(connection, project_id, selector.source_hash),
                parameters=parameters,
                selector=selector,
                project_id=project_id,
            )
        if kind is AlertRuleKind.EXTERNAL_HEALTH:
            return _external_health_input(
                _external_health_source(connection, project_id, selector.source_hash),
                selector=selector,
                project_id=project_id,
            )
        return _drift_input(
            _drift_source(connection, project_id, selector.source_hash),
            kind=kind,
            selector=selector,
            project_id=project_id,
        )


__all__ = [
    "ALERT_ADMISSION_NAMESPACE",
    "AlertEvaluationSelector",
    "PostgresWorkflowCAlertAdmissionRepository",
    "WorkflowCAlertAdmissionError",
]
