from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import TracebackType
from uuid import UUID, uuid4

import pytest

from geo_core.alerts import (
    Alert,
    AlertApplication,
    AlertConflict,
    AlertEvidenceReference,
    AlertRuleKind,
    AlertRuleVersion,
    AlertScope,
    AlertSeverity,
    AlertStatus,
    AlertTriggerSnapshot,
    NotificationOutboxCommand,
)


NOW = datetime(2026, 7, 23, 9, 0, tzinfo=UTC)
PROJECT_ID = UUID("30000000-0000-0000-0000-000000000001")
ALERT_ID = UUID("40000000-0000-0000-0000-000000000001")


def test_trigger_and_each_transition_commit_alert_with_outbox_atomically() -> None:
    state = _State()
    application = AlertApplication(_Factory(state), id_factory=lambda: ALERT_ID)

    opened = _trigger(application)

    assert opened.replayed is False
    assert opened.alert.status is AlertStatus.OPEN
    assert len(opened.notification_commands) == 3
    assert state.alerts == {ALERT_ID: opened.alert}
    assert len(state.outbox) == 3
    assert state.commits == 1

    acknowledged = application.acknowledge(
        project_id=PROJECT_ID,
        alert_id=ALERT_ID,
        expected_version=1,
        actor_id="operator-1",
        reason="triage_started",
        occurred_at=NOW + timedelta(minutes=1),
        command_key="ack:one",
    )

    assert acknowledged.alert.status is AlertStatus.ACKNOWLEDGED
    assert acknowledged.alert.version == 2
    assert len(acknowledged.notification_commands) == 3
    assert len(state.outbox) == 6
    assert state.commits == 2

    suppressed = application.suppress(
        project_id=PROJECT_ID,
        alert_id=ALERT_ID,
        expected_version=2,
        actor_id="operator-1",
        reason="planned_rollout",
        occurred_at=NOW + timedelta(minutes=2),
        suppressed_until=NOW + timedelta(hours=1),
        command_key="suppress:one",
    )
    reopened = application.expire_suppression(
        project_id=PROJECT_ID,
        alert_id=ALERT_ID,
        expected_version=3,
        actor_id="system-alert-expiry",
        occurred_at=NOW + timedelta(hours=1),
        command_key="expiry:one",
    )
    resolved = application.resolve(
        project_id=PROJECT_ID,
        alert_id=ALERT_ID,
        expected_version=4,
        actor_id="operator-2",
        reason="metric_recovered",
        occurred_at=NOW + timedelta(hours=1, minutes=1),
        command_key="resolve:one",
    )

    assert suppressed.alert.status is AlertStatus.SUPPRESSED
    assert reopened.alert.status is AlertStatus.OPEN
    assert resolved.alert.status is AlertStatus.RESOLVED
    assert state.alerts[ALERT_ID] == resolved.alert
    assert state.commits == 5
    assert len(state.outbox) == 15


def test_repeated_trigger_and_disposition_do_not_duplicate_business_or_outbox_rows() -> None:
    state = _State()
    application = AlertApplication(_Factory(state), id_factory=lambda: ALERT_ID)
    first = _trigger(application)
    replayed_trigger = _trigger(application)
    acknowledged = application.acknowledge(
        project_id=PROJECT_ID,
        alert_id=ALERT_ID,
        expected_version=1,
        actor_id="operator-1",
        reason="triage_started",
        occurred_at=NOW + timedelta(minutes=1),
        command_key="ack:one",
    )
    replayed_ack = application.acknowledge(
        project_id=PROJECT_ID,
        alert_id=ALERT_ID,
        expected_version=1,
        actor_id="operator-1",
        reason="triage_started",
        occurred_at=NOW + timedelta(minutes=20),
        command_key="ack:one",
    )

    assert replayed_trigger.replayed is True
    assert replayed_trigger.alert == first.alert
    assert replayed_trigger.notification_commands == ()
    assert replayed_ack.replayed is True
    assert replayed_ack.alert == acknowledged.alert
    assert replayed_ack.notification_commands == ()
    assert len(state.alerts) == 1
    assert len(state.outbox) == 6
    assert state.commits == 2


def test_concurrent_disposition_is_rejected_by_aggregate_and_repository_versions() -> None:
    state = _State()
    application = AlertApplication(_Factory(state), id_factory=lambda: ALERT_ID)
    _trigger(application)
    application.acknowledge(
        project_id=PROJECT_ID,
        alert_id=ALERT_ID,
        expected_version=1,
        actor_id="operator-1",
        reason="triage_started",
        occurred_at=NOW + timedelta(minutes=1),
        command_key="ack:one",
    )

    with pytest.raises(AlertConflict, match="version changed"):
        application.suppress(
            project_id=PROJECT_ID,
            alert_id=ALERT_ID,
            expected_version=1,
            actor_id="operator-2",
            reason="concurrent_stale_write",
            occurred_at=NOW + timedelta(minutes=2),
            suppressed_until=NOW + timedelta(hours=1),
            command_key="suppress:stale",
        )

    assert state.alerts[ALERT_ID].status is AlertStatus.ACKNOWLEDGED
    assert state.commits == 2


def test_outbox_enqueue_failure_rolls_back_the_new_business_alert() -> None:
    state = _State(fail_outbox=True)
    application = AlertApplication(_Factory(state), id_factory=lambda: ALERT_ID)

    with pytest.raises(RuntimeError, match="outbox unavailable"):
        _trigger(application)

    assert state.alerts == {}
    assert state.outbox == {}
    assert state.commits == 0


def test_evaluator_does_not_open_or_commit_when_rule_does_not_match() -> None:
    state = _State()
    application = AlertApplication(_Factory(state), id_factory=lambda: ALERT_ID)
    rule = AlertRuleVersion(
        id=uuid4(),
        project_id=PROJECT_ID,
        rule_key="recommendation-share-low-strict",
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
    evidence = (
        AlertEvidenceReference(
            kind="metric_snapshot",
            resource_id="metric:one",
            version="statistics-v2",
            sha256="a" * 64,
            locator="results[0]",
        ),
    )

    not_matched = application.evaluate_and_record(
        rule_version=rule,
        scope=_scope(),
        input_values={
            "schema_version": "alert-input-threshold-v1",
            "metric_key": "recommendation_share",
            "observed_value": "0.7",
        },
        evidence=evidence,
        evaluated_at=NOW,
    )

    assert not_matched.recorded is False
    assert not_matched.command is None
    assert state.alerts == {}
    assert state.outbox == {}
    assert state.commits == 0

    matched = application.evaluate_and_record(
        rule_version=rule,
        scope=_scope(),
        input_values={
            "schema_version": "alert-input-threshold-v1",
            "metric_key": "recommendation_share",
            "observed_value": "0.3",
        },
        evidence=evidence,
        evaluated_at=NOW,
    )

    assert matched.recorded is True
    assert matched.command is not None
    assert state.alerts == {ALERT_ID: matched.command.alert}
    assert len(state.outbox) == 3
    assert state.commits == 1


def _trigger(application: AlertApplication):
    return application.record_trigger(
        rule_version=_rule(),
        scope=_scope(),
        trigger_snapshot=AlertTriggerSnapshot(
            values={"metric_key": "recommendation_share", "value": Decimal("0.31")},
            captured_at=NOW,
        ),
        evidence=(
            AlertEvidenceReference(
                kind="metric_snapshot",
                resource_id="metric:one",
                version="statistics-v2",
                sha256="a" * 64,
            ),
        ),
        opened_at=NOW,
    )


def _rule() -> AlertRuleVersion:
    return AlertRuleVersion(
        id=uuid4(),
        project_id=PROJECT_ID,
        rule_key="recommendation-share-low",
        version=1,
        kind=AlertRuleKind.THRESHOLD,
        severity=AlertSeverity.WARNING,
        parameters={"metric_key": "recommendation_share", "threshold": Decimal("0.50")},
        frozen_by="admin-1",
        frozen_at=NOW,
    )


def _scope() -> AlertScope:
    return AlertScope(
        project_id=PROJECT_ID,
        resource_kind="question_cluster",
        resource_key="purchase-intent",
        dimensions=(("capture_method", "provider_api"),),
    )


@dataclass
class _State:
    alerts: dict[UUID, Alert] = field(default_factory=dict)
    outbox: dict[UUID, NotificationOutboxCommand] = field(default_factory=dict)
    commits: int = 0
    fail_outbox: bool = False


class _Alerts:
    def __init__(self, alerts: dict[UUID, Alert]) -> None:
        self._alerts = alerts

    def get(self, *, project_id: UUID, alert_id: UUID) -> Alert | None:
        alert = self._alerts.get(alert_id)
        return alert if alert is not None and alert.project_id == project_id else None

    def get_active_by_dedupe_key(
        self, *, project_id: UUID, dedupe_key: str
    ) -> Alert | None:
        return next(
            (
                alert
                for alert in self._alerts.values()
                if alert.project_id == project_id
                and alert.dedupe_key == dedupe_key
                and alert.status is not AlertStatus.RESOLVED
            ),
            None,
        )

    def add(self, alert: Alert) -> None:
        if alert.id in self._alerts:
            raise AlertConflict("alert id already exists")
        if self.get_active_by_dedupe_key(
            project_id=alert.project_id, dedupe_key=alert.dedupe_key
        ):
            raise AlertConflict("active alert dedupe key already exists")
        self._alerts[alert.id] = alert

    def save(self, alert: Alert, *, expected_version: int) -> None:
        current = self._alerts.get(alert.id)
        if current is None or current.version != expected_version:
            raise AlertConflict("alert repository version changed")
        self._alerts[alert.id] = alert


class _Outbox:
    def __init__(
        self,
        commands: dict[UUID, NotificationOutboxCommand],
        *,
        fail: bool,
    ) -> None:
        self._commands = commands
        self._fail = fail

    def enqueue(self, command: NotificationOutboxCommand) -> None:
        if self._fail:
            raise RuntimeError("outbox unavailable")
        existing = self._commands.get(command.id)
        if existing is not None and existing != command:
            raise AlertConflict("outbox idempotency identity changed")
        self._commands[command.id] = command


class _UnitOfWork:
    def __init__(self, state: _State) -> None:
        self._state = state
        self._alerts = dict(state.alerts)
        self._outbox = dict(state.outbox)
        self.alerts = _Alerts(self._alerts)
        self.outbox = _Outbox(self._outbox, fail=state.fail_outbox)

    def __enter__(self) -> _UnitOfWork:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def commit(self) -> None:
        self._state.alerts = dict(self._alerts)
        self._state.outbox = dict(self._outbox)
        self._state.commits += 1


class _Factory:
    def __init__(self, state: _State) -> None:
        self._state = state

    def __call__(self) -> _UnitOfWork:
        return _UnitOfWork(self._state)
