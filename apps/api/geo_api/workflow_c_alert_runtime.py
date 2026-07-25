"""Explicit memory runtime for governed alert lifecycle and notification projection."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from uuid import UUID, uuid5

from geo_api.workflow_c_alert_contracts import (
    AlertRuleTransitionRequest,
    AlertTransitionRequest,
    CreateAlertRuleRequest,
    EnqueueAlertEvaluationRequest,
    SuppressAlertRequest,
)
from geo_core.alerts import (
    Alert,
    AlertCommandResult,
    AlertConflict,
    AlertEvaluationCommandResult,
    AlertEvidenceReference,
    AlertNotFound,
    AlertRuleKind,
    AlertSeverity,
    AlertRuleVersion,
    AlertScope,
    AlertStatus,
    AlertTriggerSnapshot,
    NotificationChannel,
    NotificationOutboxCommand,
    acknowledge_alert,
    alert_dedupe_key,
    build_notification_commands,
    evaluate_alert_rule,
    open_alert,
    release_suppression,
    resolve_alert,
    suppress_alert,
)
from geo_core.workflow_c_alert_admission import AlertEvaluationSelector
from geo_core.workflow_c_alert_rules import (
    AlertRuleRelease,
    AlertRuleReleaseStatus,
    WorkflowCAlertRuleError,
    WorkflowCAlertRuleNotFound,
    new_alert_rule_release,
    transition_alert_rule_release,
)


ALERT_API_NAMESPACE = UUID("ac521951-fad6-5cc0-a293-1890a87916b2")


class WorkflowCAlertUnavailable(RuntimeError):
    """Durable frozen-output alert admission is not connected."""


@dataclass(frozen=True)
class AlertEvaluationJobReceipt:
    job_id: UUID
    spec_hash: str
    replayed: bool


class WorkflowCAlertRuntime:
    """One lock models the aggregate + outbox transaction in memory."""

    def __init__(self, *, clock: Callable[[], datetime]) -> None:
        self._lock = RLock()
        self._clock = clock
        self._alerts: dict[tuple[UUID, UUID], Alert] = {}
        self._trigger_commands: dict[tuple[UUID, str], UUID] = {}
        self._notifications: dict[tuple[UUID, UUID], NotificationOutboxCommand] = {}
        self._rule_channels: dict[
            tuple[UUID, str], tuple[NotificationChannel, ...]
        ] = {}
        self._rule_releases: dict[tuple[UUID, UUID], AlertRuleRelease] = {}

    def create_rule(
        self,
        *,
        project_id: UUID,
        actor_id: str,
        idempotency_key: str,
        payload: CreateAlertRuleRequest,
    ) -> AlertRuleRelease:
        release = new_alert_rule_release(
            project_id=project_id,
            rule_key=payload.rule_key,
            version=payload.version,
            kind=AlertRuleKind(payload.kind),
            severity=AlertSeverity(payload.severity),
            parameters=payload.parameters,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            occurred_at=self._clock(),
        )
        with self._lock:
            key = (project_id, release.id)
            prior = self._rule_releases.get(key)
            if prior is not None and prior != release:
                raise WorkflowCAlertRuleError(
                    "alert rule Idempotency-Key was reused with different input"
                )
            if prior is not None:
                return prior
            if any(
                item.project_id == project_id
                and item.rule.rule_key == release.rule.rule_key
                and item.rule.version == release.rule.version
                for item in self._rule_releases.values()
            ):
                raise WorkflowCAlertRuleError("alert rule key/version already exists")
            self._rule_releases[key] = release
            return release

    def transition_rule(
        self,
        *,
        project_id: UUID,
        rule_id: UUID,
        actor_id: str,
        idempotency_key: str,
        target_status: AlertRuleReleaseStatus,
        payload: AlertRuleTransitionRequest,
    ) -> AlertRuleRelease:
        del idempotency_key
        with self._lock:
            current = self._rule_releases.get((project_id, rule_id))
            if current is None:
                raise WorkflowCAlertRuleNotFound("alert rule does not exist")
            if current.aggregate_version != payload.expected_aggregate_version:
                if (
                    current.aggregate_version == payload.expected_aggregate_version + 1
                    and current.status is target_status
                    and current.decision_reason == payload.reason
                    and (
                        current.approved_by == actor_id
                        or current.retired_by == actor_id
                    )
                ):
                    return current
                raise WorkflowCAlertRuleError("alert rule aggregate version is stale")
            updated = transition_alert_rule_release(
                current,
                target_status=target_status,
                actor_id=actor_id,
                reason=payload.reason,
                occurred_at=self._clock(),
            )
            self._rule_releases[(project_id, rule_id)] = updated
            return updated

    def get_rule(self, *, project_id: UUID, rule_id: UUID) -> AlertRuleRelease:
        with self._lock:
            result = self._rule_releases.get((project_id, rule_id))
        if result is None:
            raise WorkflowCAlertRuleNotFound("alert rule does not exist")
        return result

    def list_rules(self, *, project_id: UUID) -> tuple[AlertRuleRelease, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (
                        item
                        for item in self._rule_releases.values()
                        if item.project_id == project_id
                    ),
                    key=lambda item: (item.rule.frozen_at, str(item.id)),
                    reverse=True,
                )
            )

    def enqueue_evaluation(
        self,
        *,
        project_id: UUID,
        actor_id: str,
        idempotency_key: str,
        payload: EnqueueAlertEvaluationRequest,
    ) -> AlertEvaluationJobReceipt:
        del project_id, actor_id, idempotency_key
        AlertEvaluationSelector(
            alert_rule_id=payload.alert_rule_id,
            source_hash=payload.source_hash,
            baseline_source_hash=payload.baseline_source_hash,
            source_item_key=payload.source_item_key,
            channels=tuple(NotificationChannel(item) for item in payload.channels),
            max_attempts=payload.max_attempts,
        )
        raise WorkflowCAlertUnavailable(
            "durable frozen-output alert admission is unavailable in the memory runtime"
        )

    def evaluate_rule(
        self,
        *,
        project_id: UUID,
        idempotency_key: str,
        rule_version: AlertRuleVersion,
        scope: AlertScope,
        input_values: Mapping[str, object],
        evidence: Sequence[AlertEvidenceReference],
        evaluated_at: datetime,
        channels: Sequence[NotificationChannel],
    ) -> AlertEvaluationCommandResult:
        if rule_version.project_id != project_id or scope.project_id != project_id:
            raise AlertConflict("alert evaluation project identity changed")
        evaluation = evaluate_alert_rule(
            rule_version=rule_version,
            scope=scope,
            input_values=input_values,
            evidence=evidence,
            evaluated_at=evaluated_at,
        )
        frozen_channels = tuple(dict.fromkeys(channels))
        if not frozen_channels:
            raise AlertConflict("alert rule binding has no notification channels")
        with self._lock:
            key = (project_id, rule_version.rule_hash)
            existing_channels = self._rule_channels.get(key)
            if existing_channels is not None and existing_channels != frozen_channels:
                raise AlertConflict("alert rule notification binding changed in place")
            self._rule_channels[key] = frozen_channels
        if evaluation.trigger_snapshot is None:
            return AlertEvaluationCommandResult(evaluation=evaluation, command=None)
        command = self._record_evaluated_trigger(
            project_id=project_id,
            idempotency_key=idempotency_key,
            rule_version=rule_version,
            scope=scope,
            trigger=evaluation.trigger_snapshot,
            evidence=evaluation.evidence,
            opened_at=evaluated_at,
            channels=channels,
        )
        return AlertEvaluationCommandResult(evaluation=evaluation, command=command)

    def _record_evaluated_trigger(
        self,
        *,
        project_id: UUID,
        idempotency_key: str,
        rule_version: AlertRuleVersion,
        scope: AlertScope,
        trigger: AlertTriggerSnapshot,
        evidence: tuple[AlertEvidenceReference, ...],
        opened_at: datetime,
        channels: Sequence[NotificationChannel],
    ) -> AlertCommandResult:
        command_key = (project_id, idempotency_key)
        with self._lock:
            prior_id = self._trigger_commands.get(command_key)
            if prior_id is not None:
                prior = self._alerts[(project_id, prior_id)]
                if (
                    prior.rule_version != rule_version
                    or prior.scope != scope
                    or prior.trigger_snapshot != trigger
                    or prior.evidence != evidence
                ):
                    raise AlertConflict(
                        "alert trigger Idempotency-Key was reused with different input"
                    )
                return AlertCommandResult(prior, (), True)
            dedupe = alert_dedupe_key(rule_version, scope)
            active = next(
                (
                    item
                    for (item_project, _), item in self._alerts.items()
                    if item_project == project_id
                    and item.dedupe_key == dedupe
                    and item.status is not AlertStatus.RESOLVED
                ),
                None,
            )
            if active is not None:
                self._trigger_commands[command_key] = active.id
                return AlertCommandResult(active, (), True)
            alert = open_alert(
                alert_id=_command_id(project_id, "alert", idempotency_key),
                rule_version=rule_version,
                scope=scope,
                trigger_snapshot=trigger,
                evidence=evidence,
                opened_at=opened_at,
            )
            commands = build_notification_commands(
                alert,
                event_type="opened",
                created_at=opened_at,
                channels=channels,
            )
            self._alerts[(project_id, alert.id)] = alert
            self._trigger_commands[command_key] = alert.id
            self._store_notifications(commands)
            return AlertCommandResult(alert, commands, False)

    def get_alert(self, *, project_id: UUID, alert_id: UUID) -> Alert:
        with self._lock:
            alert = self._alerts.get((project_id, alert_id))
        if alert is None:
            raise AlertNotFound("alert does not exist in this project")
        return alert

    def list_alerts(self, *, project_id: UUID) -> tuple[Alert, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (
                        item
                        for (item_project, _), item in self._alerts.items()
                        if item_project == project_id
                    ),
                    key=lambda item: (item.updated_at, str(item.id)),
                    reverse=True,
                )
            )

    def notifications(
        self, *, project_id: UUID, alert_id: UUID
    ) -> tuple[NotificationOutboxCommand, ...]:
        self.get_alert(project_id=project_id, alert_id=alert_id)
        with self._lock:
            return tuple(
                sorted(
                    (
                        item
                        for (item_project, _), item in self._notifications.items()
                        if item_project == project_id and item.alert_id == alert_id
                    ),
                    key=lambda item: (item.alert_version, item.channel.value),
                )
            )

    def acknowledge(
        self,
        *,
        project_id: UUID,
        alert_id: UUID,
        actor_id: str,
        idempotency_key: str,
        payload: AlertTransitionRequest,
    ) -> AlertCommandResult:
        occurred_at = self._clock()
        return self._transition(
            project_id=project_id,
            alert_id=alert_id,
            operation=lambda item: acknowledge_alert(
                item,
                expected_version=payload.expected_version,
                actor_id=actor_id,
                reason=payload.reason,
                occurred_at=occurred_at,
                command_key=idempotency_key,
            ),
            event_type="acknowledged",
            occurred_at=occurred_at,
        )

    def suppress(
        self,
        *,
        project_id: UUID,
        alert_id: UUID,
        actor_id: str,
        idempotency_key: str,
        payload: SuppressAlertRequest,
    ) -> AlertCommandResult:
        occurred_at = self._clock()
        return self._transition(
            project_id=project_id,
            alert_id=alert_id,
            operation=lambda item: suppress_alert(
                item,
                expected_version=payload.expected_version,
                actor_id=actor_id,
                reason=payload.reason,
                occurred_at=occurred_at,
                suppressed_until=payload.suppressed_until,
                command_key=idempotency_key,
            ),
            event_type="suppressed",
            occurred_at=occurred_at,
        )

    def unsuppress(
        self,
        *,
        project_id: UUID,
        alert_id: UUID,
        actor_id: str,
        idempotency_key: str,
        payload: AlertTransitionRequest,
    ) -> AlertCommandResult:
        occurred_at = self._clock()
        return self._transition(
            project_id=project_id,
            alert_id=alert_id,
            operation=lambda item: release_suppression(
                item,
                expected_version=payload.expected_version,
                actor_id=actor_id,
                reason=payload.reason,
                occurred_at=occurred_at,
                command_key=idempotency_key,
            ),
            event_type="unsuppressed",
            occurred_at=occurred_at,
        )

    def resolve(
        self,
        *,
        project_id: UUID,
        alert_id: UUID,
        actor_id: str,
        idempotency_key: str,
        payload: AlertTransitionRequest,
    ) -> AlertCommandResult:
        occurred_at = self._clock()
        return self._transition(
            project_id=project_id,
            alert_id=alert_id,
            operation=lambda item: resolve_alert(
                item,
                expected_version=payload.expected_version,
                actor_id=actor_id,
                reason=payload.reason,
                occurred_at=occurred_at,
                command_key=idempotency_key,
            ),
            event_type="resolved",
            occurred_at=occurred_at,
        )

    def _transition(
        self,
        *,
        project_id: UUID,
        alert_id: UUID,
        operation: Callable[[Alert], Alert],
        event_type: str,
        occurred_at: datetime,
    ) -> AlertCommandResult:
        with self._lock:
            current = self._alerts.get((project_id, alert_id))
            if current is None:
                raise AlertNotFound("alert does not exist in this project")
            updated = operation(current)
            if updated is current:
                return AlertCommandResult(current, (), True)
            commands = build_notification_commands(
                updated,
                event_type=event_type,
                created_at=occurred_at,
                channels=self._bound_channels(updated),
            )
            self._alerts[(project_id, alert_id)] = updated
            self._store_notifications(commands)
            return AlertCommandResult(updated, commands, False)

    def _bound_channels(self, alert: Alert) -> tuple[NotificationChannel, ...]:
        channels = self._rule_channels.get((alert.project_id, alert.rule_version.rule_hash))
        if channels is None:
            raise AlertConflict("alert rule notification binding is unavailable")
        return channels

    def _store_notifications(
        self, commands: tuple[NotificationOutboxCommand, ...]
    ) -> None:
        for command in commands:
            key = (command.project_id, command.id)
            existing = self._notifications.get(key)
            if existing is not None and existing != command:
                raise AlertConflict("notification identity has different immutable input")
            self._notifications[key] = command


def _command_id(project_id: UUID, operation: str, idempotency_key: str) -> UUID:
    key = idempotency_key.strip()
    if not key:
        raise AlertConflict("Idempotency-Key is required")
    return uuid5(ALERT_API_NAMESPACE, f"{project_id}:{operation}:{key}")
