from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
from types import MappingProxyType
from uuid import UUID, uuid4

import pytest

from geo_core.alerts import (
    NOTIFICATION_SUMMARY_FIELDS,
    AlertConflict,
    AlertDispositionKind,
    AlertEvidenceReference,
    AlertRuleKind,
    AlertRuleVersion,
    AlertRuleViolation,
    AlertScope,
    AlertSeverity,
    AlertStatus,
    AlertTriggerSnapshot,
    NotificationChannel,
    NotificationDeliveryStatus,
    acknowledge_alert,
    alert_dedupe_key,
    build_notification_commands,
    open_alert,
    record_notification_failure,
    record_notification_success,
    release_expired_suppression,
    release_suppression,
    resolve_alert,
    start_notification_delivery,
    suppress_alert,
)


NOW = datetime(2026, 7, 23, 8, 0, tzinfo=UTC)
PROJECT_ID = UUID("10000000-0000-0000-0000-000000000001")
ALERT_ID = UUID("20000000-0000-0000-0000-000000000001")


@pytest.mark.parametrize("kind", tuple(AlertRuleKind))
def test_all_non_connector_rule_kinds_have_immutable_versions(kind: AlertRuleKind) -> None:
    rule = _rule(kind=kind)

    assert rule.kind is kind
    assert len(rule.rule_hash) == 64
    assert isinstance(rule.parameters, MappingProxyType)
    assert isinstance(rule.parameters["condition"], MappingProxyType)
    with pytest.raises(TypeError):
        rule.parameters["threshold"] = "0.5"  # type: ignore[index]


def test_rule_and_scope_produce_a_stable_semantic_dedupe_key() -> None:
    first_rule = _rule()
    equivalent_rule = replace(
        first_rule,
        id=uuid4(),
        frozen_by="another-admin",
        frozen_at=NOW + timedelta(hours=1),
    )
    first_scope = _scope(
        dimensions=(
            ("capture_method", "provider_api"),
            ("question_cluster", "purchase-intent"),
        )
    )
    reordered_scope = _scope(
        dimensions=(
            ("question_cluster", "purchase-intent"),
            ("capture_method", "provider_api"),
        )
    )

    first = alert_dedupe_key(first_rule, first_scope)

    assert first == alert_dedupe_key(equivalent_rule, reordered_scope)
    assert first.startswith("alert:")
    assert len(first) == len("alert:") + 64
    assert first != alert_dedupe_key(replace(first_rule, version=2), first_scope)
    assert first != alert_dedupe_key(first_rule, _scope(resource_key="cluster:other"))


def test_full_lifecycle_records_actor_time_reason_and_disposition() -> None:
    opened = _alert()
    acknowledged = acknowledge_alert(
        opened,
        expected_version=1,
        actor_id="operator-1",
        reason="triage_started",
        occurred_at=NOW + timedelta(minutes=1),
        command_key="ack:one",
    )
    suppressed = suppress_alert(
        acknowledged,
        expected_version=2,
        actor_id="operator-1",
        reason="known_model_rollout",
        occurred_at=NOW + timedelta(minutes=2),
        suppressed_until=NOW + timedelta(days=1),
        command_key="suppress:one",
    )
    reopened = release_suppression(
        suppressed,
        expected_version=3,
        actor_id="operator-2",
        reason="rollout_finished",
        occurred_at=NOW + timedelta(minutes=3),
        command_key="unsuppress:one",
    )
    suppressed_again = suppress_alert(
        reopened,
        expected_version=4,
        actor_id="operator-2",
        reason="planned_recheck",
        occurred_at=NOW + timedelta(minutes=4),
        suppressed_until=NOW + timedelta(days=2),
        command_key="suppress:two",
    )
    resolved = resolve_alert(
        suppressed_again,
        expected_version=5,
        actor_id="operator-3",
        reason="metric_recovered",
        occurred_at=NOW + timedelta(minutes=5),
        command_key="resolve:one",
    )

    assert resolved.status is AlertStatus.RESOLVED
    assert resolved.version == 6
    assert resolved.suppressed_until is None
    assert resolved.suppression_reason is None
    assert [item.disposition for item in resolved.dispositions] == [
        AlertDispositionKind.ACKNOWLEDGED,
        AlertDispositionKind.SUPPRESSED,
        AlertDispositionKind.UNSUPPRESSED,
        AlertDispositionKind.SUPPRESSED,
        AlertDispositionKind.RESOLVED,
    ]
    assert [item.actor_id for item in resolved.dispositions] == [
        "operator-1",
        "operator-1",
        "operator-2",
        "operator-2",
        "operator-3",
    ]
    assert all(item.reason and item.occurred_at.tzinfo for item in resolved.dispositions)


def test_suppression_expiry_reopens_only_after_the_frozen_deadline() -> None:
    suppressed = suppress_alert(
        _alert(),
        expected_version=1,
        actor_id="operator-1",
        reason="planned_maintenance",
        occurred_at=NOW + timedelta(minutes=1),
        suppressed_until=NOW + timedelta(hours=2),
        command_key="suppress:one",
    )

    with pytest.raises(AlertConflict, match="has not expired"):
        release_expired_suppression(
            suppressed,
            expected_version=2,
            actor_id="system-alert-expiry",
            occurred_at=NOW + timedelta(hours=1),
            command_key="expiry:early",
        )

    reopened = release_expired_suppression(
        suppressed,
        expected_version=2,
        actor_id="system-alert-expiry",
        occurred_at=NOW + timedelta(hours=2),
        command_key="expiry:due",
    )

    assert reopened.status is AlertStatus.OPEN
    assert reopened.dispositions[-1].reason == "suppression_expired"
    assert reopened.dispositions[-1].actor_id == "system-alert-expiry"
    assert (
        release_expired_suppression(
            reopened,
            expected_version=2,
            actor_id="system-alert-expiry",
            occurred_at=NOW + timedelta(hours=3),
            command_key="expiry:due",
        )
        is reopened
    )


def test_disposition_commands_are_idempotent_and_version_fenced() -> None:
    acknowledged = acknowledge_alert(
        _alert(),
        expected_version=1,
        actor_id="operator-1",
        reason="triage_started",
        occurred_at=NOW + timedelta(minutes=1),
        command_key="ack:one",
    )

    replay = acknowledge_alert(
        acknowledged,
        expected_version=1,
        actor_id="operator-1",
        reason="triage_started",
        occurred_at=NOW + timedelta(minutes=10),
        command_key="ack:one",
    )

    assert replay is acknowledged
    with pytest.raises(AlertConflict, match="different input"):
        acknowledge_alert(
            acknowledged,
            expected_version=1,
            actor_id="operator-1",
            reason="different_reason",
            occurred_at=NOW + timedelta(minutes=2),
            command_key="ack:one",
        )
    with pytest.raises(AlertConflict, match="version changed"):
        suppress_alert(
            acknowledged,
            expected_version=1,
            actor_id="operator-2",
            reason="stale_concurrent_command",
            occurred_at=NOW + timedelta(minutes=2),
            suppressed_until=NOW + timedelta(days=1),
            command_key="suppress:stale",
        )


def test_invalid_transition_and_time_inputs_are_rejected() -> None:
    resolved = resolve_alert(
        _alert(),
        expected_version=1,
        actor_id="operator-1",
        reason="fixed",
        occurred_at=NOW + timedelta(minutes=1),
        command_key="resolve:one",
    )

    with pytest.raises(AlertConflict, match="cannot acknowledged"):
        acknowledge_alert(
            resolved,
            expected_version=2,
            actor_id="operator-1",
            reason="late_ack",
            occurred_at=NOW + timedelta(minutes=2),
            command_key="ack:late",
        )
    with pytest.raises(AlertRuleViolation, match="must follow"):
        suppress_alert(
            _alert(),
            expected_version=1,
            actor_id="operator-1",
            reason="bad_expiry",
            occurred_at=NOW + timedelta(minutes=1),
            suppressed_until=NOW,
            command_key="suppress:bad",
        )


def test_notification_payload_is_an_exact_non_sensitive_whitelist() -> None:
    alert = _alert()
    commands = build_notification_commands(alert, event_type="opened", created_at=NOW)

    assert {command.channel for command in commands} == set(NotificationChannel)
    for command in commands:
        payload = command.summary.payload()
        serialized = json.dumps(payload, sort_keys=True)
        assert frozenset(payload) == NOTIFICATION_SUMMARY_FIELDS
        assert command.payload_hash
        assert "provider_api_key" not in serialized
        assert "customer@example.com" not in serialized
        assert "s3://private/raw-answer.json" not in serialized
        assert command.summary.detail_link.endswith(f"/alerts/{alert.id}")


def test_notification_outbox_identity_is_stable_per_alert_version_and_channel() -> None:
    alert = _alert()
    first = build_notification_commands(
        alert,
        event_type="opened",
        created_at=NOW,
        channels=(NotificationChannel.INTERNAL_WEBHOOK,),
    )[0]
    replay = build_notification_commands(
        alert,
        event_type="opened",
        created_at=NOW + timedelta(minutes=1),
        channels=(NotificationChannel.INTERNAL_WEBHOOK,),
    )[0]
    acknowledged = acknowledge_alert(
        alert,
        expected_version=1,
        actor_id="operator-1",
        reason="triage_started",
        occurred_at=NOW + timedelta(minutes=1),
        command_key="ack:one",
    )
    next_version = build_notification_commands(
        acknowledged,
        event_type="acknowledged",
        created_at=NOW + timedelta(minutes=1),
        channels=(NotificationChannel.INTERNAL_WEBHOOK,),
    )[0]

    assert first.id == replay.id
    assert first.idempotency_key == replay.idempotency_key
    assert first.payload_hash == replay.payload_hash
    assert first.id != next_version.id
    assert first.idempotency_key != next_version.idempotency_key


def test_notification_failure_retries_the_command_without_mutating_alert_state() -> None:
    alert = _alert()
    command = build_notification_commands(
        alert,
        event_type="opened",
        created_at=NOW,
        channels=(NotificationChannel.INTERNAL_WEBHOOK,),
    )[0]
    delivery = start_notification_delivery(command, max_attempts=2)
    first_failure = record_notification_failure(
        delivery,
        attempted_at=NOW + timedelta(minutes=1),
        error_code="webhook_timeout",
        retry_at=NOW + timedelta(minutes=2),
    )
    terminal_failure = record_notification_failure(
        first_failure,
        attempted_at=NOW + timedelta(minutes=2),
        error_code="webhook_timeout",
        retry_at=NOW + timedelta(minutes=3),
    )

    assert first_failure.command_id == terminal_failure.command_id == command.id
    assert first_failure.status is NotificationDeliveryStatus.RETRY_WAIT
    assert terminal_failure.status is NotificationDeliveryStatus.FAILED
    assert alert.status is AlertStatus.OPEN
    assert alert.version == 1
    assert alert.dispositions == ()

    delivered = record_notification_success(
        start_notification_delivery(command),
        attempted_at=NOW + timedelta(minutes=1),
    )
    assert delivered.status is NotificationDeliveryStatus.DELIVERED


def _rule(
    *,
    kind: AlertRuleKind = AlertRuleKind.THRESHOLD,
    version: int = 1,
) -> AlertRuleVersion:
    return AlertRuleVersion(
        id=uuid4(),
        project_id=PROJECT_ID,
        rule_key="recommendation-share-low",
        version=version,
        kind=kind,
        severity=AlertSeverity.WARNING,
        parameters={
            "condition": {"operator": "lt", "threshold": Decimal("0.50")},
            "metric_key": "recommendation_share",
        },
        frozen_by="admin-1",
        frozen_at=NOW,
    )


def _scope(
    *,
    resource_key: str = "cluster:purchase-intent",
    dimensions: tuple[tuple[str, str], ...] = (),
) -> AlertScope:
    return AlertScope(
        project_id=PROJECT_ID,
        resource_kind="question_cluster",
        resource_key=resource_key,
        dimensions=dimensions,
    )


def _alert():
    rule = _rule()
    scope = _scope()
    snapshot = AlertTriggerSnapshot(
        values={
            "metric_key": "recommendation_share",
            "observed_value": Decimal("0.31"),
            "provider_api_key": "secret-value",
            "contact": "customer@example.com",
        },
        captured_at=NOW,
    )
    evidence = AlertEvidenceReference(
        kind="metric_snapshot",
        resource_id="metric:one",
        version="statistics-v2",
        sha256="a" * 64,
        locator="s3://private/raw-answer.json",
    )
    return open_alert(
        alert_id=ALERT_ID,
        rule_version=rule,
        scope=scope,
        trigger_snapshot=snapshot,
        evidence=(evidence,),
        opened_at=NOW,
    )
