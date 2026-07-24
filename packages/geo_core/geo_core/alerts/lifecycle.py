"""Pure, version-fenced alert lifecycle transitions."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from uuid import UUID

from geo_core.alerts.domain import (
    Alert,
    AlertConflict,
    AlertDisposition,
    AlertDispositionKind,
    AlertEvidenceReference,
    AlertRuleVersion,
    AlertRuleViolation,
    AlertScope,
    AlertStatus,
    AlertTriggerSnapshot,
    _bounded_key,
    _bounded_text,
    _disposition_command_hash,
    _require_aware,
    alert_dedupe_key,
)


def open_alert(
    *,
    alert_id: UUID,
    rule_version: AlertRuleVersion,
    scope: AlertScope,
    trigger_snapshot: AlertTriggerSnapshot,
    evidence: Sequence[AlertEvidenceReference],
    opened_at: datetime,
) -> Alert:
    _require_aware(opened_at, "alert opened time")
    if trigger_snapshot.captured_at > opened_at:
        raise AlertRuleViolation("alert trigger cannot be captured after alert opening")
    return Alert(
        id=alert_id,
        project_id=scope.project_id,
        rule_version=rule_version,
        scope=scope,
        trigger_snapshot=trigger_snapshot,
        evidence=tuple(evidence),
        severity=rule_version.severity,
        dedupe_key=alert_dedupe_key(rule_version, scope),
        status=AlertStatus.OPEN,
        opened_at=opened_at,
        updated_at=opened_at,
    )


def acknowledge_alert(
    alert: Alert,
    *,
    expected_version: int,
    actor_id: str,
    reason: str,
    occurred_at: datetime,
    command_key: str,
) -> Alert:
    return _transition_alert(
        alert,
        expected_version=expected_version,
        allowed_from=frozenset({AlertStatus.OPEN}),
        to_status=AlertStatus.ACKNOWLEDGED,
        disposition=AlertDispositionKind.ACKNOWLEDGED,
        actor_id=actor_id,
        reason=reason,
        occurred_at=occurred_at,
        command_key=command_key,
    )


def suppress_alert(
    alert: Alert,
    *,
    expected_version: int,
    actor_id: str,
    reason: str,
    occurred_at: datetime,
    suppressed_until: datetime,
    command_key: str,
) -> Alert:
    return _transition_alert(
        alert,
        expected_version=expected_version,
        allowed_from=frozenset({AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED}),
        to_status=AlertStatus.SUPPRESSED,
        disposition=AlertDispositionKind.SUPPRESSED,
        actor_id=actor_id,
        reason=reason,
        occurred_at=occurred_at,
        command_key=command_key,
        suppressed_until=suppressed_until,
    )


def release_suppression(
    alert: Alert,
    *,
    expected_version: int,
    actor_id: str,
    reason: str,
    occurred_at: datetime,
    command_key: str,
) -> Alert:
    return _transition_alert(
        alert,
        expected_version=expected_version,
        allowed_from=frozenset({AlertStatus.SUPPRESSED}),
        to_status=AlertStatus.OPEN,
        disposition=AlertDispositionKind.UNSUPPRESSED,
        actor_id=actor_id,
        reason=reason,
        occurred_at=occurred_at,
        command_key=command_key,
    )


def release_expired_suppression(
    alert: Alert,
    *,
    expected_version: int,
    actor_id: str,
    occurred_at: datetime,
    command_key: str,
) -> Alert:
    replay = _replay_disposition_command(
        alert,
        disposition=AlertDispositionKind.UNSUPPRESSED,
        actor_id=actor_id,
        reason="suppression_expired",
        command_key=command_key,
    )
    if replay is not None:
        return replay
    if alert.status is not AlertStatus.SUPPRESSED or alert.suppressed_until is None:
        raise AlertConflict("only a suppressed alert can expire suppression")
    if occurred_at < alert.suppressed_until:
        raise AlertConflict("alert suppression has not expired")
    return release_suppression(
        alert,
        expected_version=expected_version,
        actor_id=actor_id,
        reason="suppression_expired",
        occurred_at=occurred_at,
        command_key=command_key,
    )


def resolve_alert(
    alert: Alert,
    *,
    expected_version: int,
    actor_id: str,
    reason: str,
    occurred_at: datetime,
    command_key: str,
) -> Alert:
    return _transition_alert(
        alert,
        expected_version=expected_version,
        allowed_from=frozenset(
            {AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED, AlertStatus.SUPPRESSED}
        ),
        to_status=AlertStatus.RESOLVED,
        disposition=AlertDispositionKind.RESOLVED,
        actor_id=actor_id,
        reason=reason,
        occurred_at=occurred_at,
        command_key=command_key,
    )


def _transition_alert(
    alert: Alert,
    *,
    expected_version: int,
    allowed_from: frozenset[AlertStatus],
    to_status: AlertStatus,
    disposition: AlertDispositionKind,
    actor_id: str,
    reason: str,
    occurred_at: datetime,
    command_key: str,
    suppressed_until: datetime | None = None,
) -> Alert:
    actor = _bounded_text(actor_id, "alert disposition actor")
    normalized_reason = _bounded_text(reason, "alert disposition reason", maximum=1000)
    key = _bounded_key(command_key, "alert disposition command key")
    _require_aware(occurred_at, "alert disposition time")
    if suppressed_until is not None:
        _require_aware(suppressed_until, "alert suppression expiry")
    replay = _replay_disposition_command(
        alert,
        disposition=disposition,
        actor_id=actor,
        reason=normalized_reason,
        command_key=key,
        suppressed_until=suppressed_until,
    )
    if replay is not None:
        return replay
    if alert.version != expected_version:
        raise AlertConflict("alert version changed before disposition")
    if alert.status not in allowed_from:
        raise AlertConflict(f"cannot {disposition.value} an alert from {alert.status.value}")
    if occurred_at < alert.updated_at:
        raise AlertRuleViolation("alert disposition cannot predate current state")
    next_version = alert.version + 1
    record = AlertDisposition(
        disposition=disposition,
        from_status=alert.status,
        to_status=to_status,
        actor_id=actor,
        occurred_at=occurred_at,
        reason=normalized_reason,
        command_key=key,
        resulting_version=next_version,
        suppressed_until=suppressed_until,
    )
    return replace(
        alert,
        status=to_status,
        updated_at=occurred_at,
        version=next_version,
        dispositions=(*alert.dispositions, record),
        suppressed_until=suppressed_until if to_status is AlertStatus.SUPPRESSED else None,
        suppression_reason=(
            normalized_reason if to_status is AlertStatus.SUPPRESSED else None
        ),
    )


def _replay_disposition_command(
    alert: Alert,
    *,
    disposition: AlertDispositionKind,
    actor_id: str,
    reason: str,
    command_key: str,
    suppressed_until: datetime | None = None,
) -> Alert | None:
    actor = _bounded_text(actor_id, "alert disposition actor")
    normalized_reason = _bounded_text(reason, "alert disposition reason", maximum=1000)
    key = _bounded_key(command_key, "alert disposition command key")
    command_hash = _disposition_command_hash(
        disposition=disposition,
        actor_id=actor,
        reason=normalized_reason,
        suppressed_until=suppressed_until,
    )
    for existing in alert.dispositions:
        if existing.command_key != key:
            continue
        if existing.command_hash != command_hash:
            raise AlertConflict("alert disposition command key was reused with different input")
        return alert
    return None
