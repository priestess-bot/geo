"""Application commands that atomically persist alerts and notification outbox rows."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from geo_core.alerts.domain import (
    Alert,
    AlertEvidenceReference,
    AlertNotFound,
    AlertRuleVersion,
    AlertScope,
    AlertTriggerSnapshot,
    alert_dedupe_key,
)
from geo_core.alerts.lifecycle import (
    acknowledge_alert,
    open_alert,
    release_expired_suppression,
    release_suppression,
    resolve_alert,
    suppress_alert,
)
from geo_core.alerts.evaluation import AlertEvaluation, evaluate_alert_rule
from geo_core.alerts.notifications import (
    DEFAULT_NOTIFICATION_CHANNELS,
    NotificationChannel,
    NotificationOutboxCommand,
    build_notification_commands,
)
from geo_core.alerts.ports import AlertUnitOfWorkFactory


@dataclass(frozen=True)
class AlertCommandResult:
    alert: Alert
    notification_commands: tuple[NotificationOutboxCommand, ...]
    replayed: bool


@dataclass(frozen=True)
class AlertEvaluationCommandResult:
    evaluation: AlertEvaluation
    command: AlertCommandResult | None

    @property
    def recorded(self) -> bool:
        return self.command is not None


class AlertApplication:
    """Coordinates one aggregate write and its notification commands per transaction."""

    def __init__(
        self,
        unit_of_work_factory: AlertUnitOfWorkFactory,
        *,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._id_factory = id_factory

    def evaluate_and_record(
        self,
        *,
        rule_version: AlertRuleVersion,
        scope: AlertScope,
        input_values: Mapping[str, object],
        evidence: Sequence[AlertEvidenceReference],
        evaluated_at: datetime,
        channels: Sequence[NotificationChannel] = DEFAULT_NOTIFICATION_CHANNELS,
    ) -> AlertEvaluationCommandResult:
        evaluation = evaluate_alert_rule(
            rule_version=rule_version,
            scope=scope,
            input_values=input_values,
            evidence=evidence,
            evaluated_at=evaluated_at,
        )
        if evaluation.trigger_snapshot is None:
            return AlertEvaluationCommandResult(evaluation=evaluation, command=None)
        command = self.record_trigger(
            rule_version=rule_version,
            scope=scope,
            trigger_snapshot=evaluation.trigger_snapshot,
            evidence=evaluation.evidence,
            opened_at=evaluated_at,
            channels=channels,
        )
        return AlertEvaluationCommandResult(evaluation=evaluation, command=command)

    def record_trigger(
        self,
        *,
        rule_version: AlertRuleVersion,
        scope: AlertScope,
        trigger_snapshot: AlertTriggerSnapshot,
        evidence: Sequence[AlertEvidenceReference],
        opened_at: datetime,
        channels: Sequence[NotificationChannel] = DEFAULT_NOTIFICATION_CHANNELS,
    ) -> AlertCommandResult:
        dedupe_key = alert_dedupe_key(rule_version, scope)
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.alerts.get_active_by_dedupe_key(
                project_id=scope.project_id,
                dedupe_key=dedupe_key,
            )
            if existing is not None:
                return AlertCommandResult(existing, (), True)
            alert = open_alert(
                alert_id=self._id_factory(),
                rule_version=rule_version,
                scope=scope,
                trigger_snapshot=trigger_snapshot,
                evidence=evidence,
                opened_at=opened_at,
            )
            commands = build_notification_commands(
                alert,
                event_type="opened",
                created_at=opened_at,
                channels=channels,
            )
            unit_of_work.alerts.add(alert)
            for command in commands:
                unit_of_work.outbox.enqueue(command)
            unit_of_work.commit()
            return AlertCommandResult(alert, commands, False)

    def acknowledge(
        self,
        *,
        project_id: UUID,
        alert_id: UUID,
        expected_version: int,
        actor_id: str,
        reason: str,
        occurred_at: datetime,
        command_key: str,
        channels: Sequence[NotificationChannel] = DEFAULT_NOTIFICATION_CHANNELS,
    ) -> AlertCommandResult:
        return self._apply_transition(
            project_id=project_id,
            alert_id=alert_id,
            operation=lambda alert: acknowledge_alert(
                alert,
                expected_version=expected_version,
                actor_id=actor_id,
                reason=reason,
                occurred_at=occurred_at,
                command_key=command_key,
            ),
            event_type="acknowledged",
            occurred_at=occurred_at,
            channels=channels,
        )

    def suppress(
        self,
        *,
        project_id: UUID,
        alert_id: UUID,
        expected_version: int,
        actor_id: str,
        reason: str,
        occurred_at: datetime,
        suppressed_until: datetime,
        command_key: str,
        channels: Sequence[NotificationChannel] = DEFAULT_NOTIFICATION_CHANNELS,
    ) -> AlertCommandResult:
        return self._apply_transition(
            project_id=project_id,
            alert_id=alert_id,
            operation=lambda alert: suppress_alert(
                alert,
                expected_version=expected_version,
                actor_id=actor_id,
                reason=reason,
                occurred_at=occurred_at,
                suppressed_until=suppressed_until,
                command_key=command_key,
            ),
            event_type="suppressed",
            occurred_at=occurred_at,
            channels=channels,
        )

    def unsuppress(
        self,
        *,
        project_id: UUID,
        alert_id: UUID,
        expected_version: int,
        actor_id: str,
        reason: str,
        occurred_at: datetime,
        command_key: str,
        channels: Sequence[NotificationChannel] = DEFAULT_NOTIFICATION_CHANNELS,
    ) -> AlertCommandResult:
        return self._apply_transition(
            project_id=project_id,
            alert_id=alert_id,
            operation=lambda alert: release_suppression(
                alert,
                expected_version=expected_version,
                actor_id=actor_id,
                reason=reason,
                occurred_at=occurred_at,
                command_key=command_key,
            ),
            event_type="unsuppressed",
            occurred_at=occurred_at,
            channels=channels,
        )

    def expire_suppression(
        self,
        *,
        project_id: UUID,
        alert_id: UUID,
        expected_version: int,
        actor_id: str,
        occurred_at: datetime,
        command_key: str,
        channels: Sequence[NotificationChannel] = DEFAULT_NOTIFICATION_CHANNELS,
    ) -> AlertCommandResult:
        return self._apply_transition(
            project_id=project_id,
            alert_id=alert_id,
            operation=lambda alert: release_expired_suppression(
                alert,
                expected_version=expected_version,
                actor_id=actor_id,
                occurred_at=occurred_at,
                command_key=command_key,
            ),
            event_type="unsuppressed",
            occurred_at=occurred_at,
            channels=channels,
        )

    def resolve(
        self,
        *,
        project_id: UUID,
        alert_id: UUID,
        expected_version: int,
        actor_id: str,
        reason: str,
        occurred_at: datetime,
        command_key: str,
        channels: Sequence[NotificationChannel] = DEFAULT_NOTIFICATION_CHANNELS,
    ) -> AlertCommandResult:
        return self._apply_transition(
            project_id=project_id,
            alert_id=alert_id,
            operation=lambda alert: resolve_alert(
                alert,
                expected_version=expected_version,
                actor_id=actor_id,
                reason=reason,
                occurred_at=occurred_at,
                command_key=command_key,
            ),
            event_type="resolved",
            occurred_at=occurred_at,
            channels=channels,
        )

    def _apply_transition(
        self,
        *,
        project_id: UUID,
        alert_id: UUID,
        operation: Callable[[Alert], Alert],
        event_type: str,
        occurred_at: datetime,
        channels: Sequence[NotificationChannel],
    ) -> AlertCommandResult:
        with self._unit_of_work_factory() as unit_of_work:
            current = unit_of_work.alerts.get(project_id=project_id, alert_id=alert_id)
            if current is None:
                raise AlertNotFound("alert does not exist in this project")
            updated = operation(current)
            if updated is current:
                return AlertCommandResult(current, (), True)
            commands = build_notification_commands(
                updated,
                event_type=event_type,
                created_at=occurred_at,
                channels=channels,
            )
            unit_of_work.alerts.save(updated, expected_version=current.version)
            for command in commands:
                unit_of_work.outbox.enqueue(command)
            unit_of_work.commit()
            return AlertCommandResult(updated, commands, False)
