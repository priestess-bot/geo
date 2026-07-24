"""Notification summary whitelist, deterministic outbox identity and delivery state."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid5

from geo_core.alerts.domain import (
    Alert,
    AlertConflict,
    AlertRuleKind,
    AlertRuleViolation,
    AlertSeverity,
    AlertStatus,
    _bounded_key,
    _canonical_hash,
    _require_aware,
)


ALERT_NOTIFICATION_NAMESPACE = UUID("32ef8551-a61f-5acd-b47d-cd866fab8971")
NOTIFICATION_SUMMARY_FIELDS = frozenset(
    {
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
    }
)


class NotificationChannel(StrEnum):
    ADMIN_INBOX = "admin_inbox"
    LOCAL_SMTP = "local_smtp"
    INTERNAL_WEBHOOK = "internal_webhook"


DEFAULT_NOTIFICATION_CHANNELS = (
    NotificationChannel.ADMIN_INBOX,
    NotificationChannel.LOCAL_SMTP,
    NotificationChannel.INTERNAL_WEBHOOK,
)


class NotificationDeliveryStatus(StrEnum):
    PENDING = "pending"
    RETRY_WAIT = "retry_wait"
    DELIVERED = "delivered"
    FAILED = "failed"


@dataclass(frozen=True)
class NotificationSummary:
    alert_id: UUID
    project_id: UUID
    rule_key: str
    rule_version: int
    rule_kind: AlertRuleKind
    severity: AlertSeverity
    status: AlertStatus
    event_type: str
    occurred_at: datetime
    detail_link: str

    def __post_init__(self) -> None:
        try:
            rule_kind = AlertRuleKind(self.rule_kind)
            severity = AlertSeverity(self.severity)
            status = AlertStatus(self.status)
        except ValueError as error:
            raise AlertRuleViolation("notification summary enum value is unsupported") from error
        event_type = _bounded_key(self.event_type, "alert notification event type")
        _require_aware(self.occurred_at, "alert notification event time")
        expected_link = f"/admin/projects/{self.project_id}/alerts/{self.alert_id}"
        if self.detail_link != expected_link:
            raise AlertRuleViolation("alert notification detail link is not canonical")
        object.__setattr__(self, "rule_kind", rule_kind)
        object.__setattr__(self, "severity", severity)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "event_type", event_type)

    def payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "alert_id": str(self.alert_id),
            "project_id": str(self.project_id),
            "rule_key": self.rule_key,
            "rule_version": self.rule_version,
            "rule_kind": self.rule_kind.value,
            "severity": self.severity.value,
            "status": self.status.value,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at.isoformat(),
            "detail_link": self.detail_link,
        }
        if frozenset(payload) != NOTIFICATION_SUMMARY_FIELDS:
            raise AlertRuleViolation("alert notification summary whitelist changed unexpectedly")
        return payload


@dataclass(frozen=True)
class NotificationOutboxCommand:
    id: UUID
    project_id: UUID
    alert_id: UUID
    alert_version: int
    channel: NotificationChannel
    topic: str
    summary: NotificationSummary
    idempotency_key: str
    created_at: datetime
    payload_hash: str

    def __post_init__(self) -> None:
        try:
            channel = NotificationChannel(self.channel)
        except ValueError as error:
            raise AlertRuleViolation("notification channel is unsupported") from error
        _require_aware(self.created_at, "notification command creation time")
        expected_topic = f"alerts.notify.{channel.value}"
        expected_key = notification_idempotency_key(
            alert_id=self.alert_id,
            alert_version=self.alert_version,
            event_type=self.summary.event_type,
            channel=channel,
        )
        if self.topic != expected_topic or self.idempotency_key != expected_key:
            raise AlertRuleViolation("notification command routing identity is inconsistent")
        if self.id != uuid5(ALERT_NOTIFICATION_NAMESPACE, expected_key):
            raise AlertRuleViolation("notification command id is not deterministic")
        if self.summary.alert_id != self.alert_id or self.summary.project_id != self.project_id:
            raise AlertRuleViolation("notification summary belongs to another alert")
        if self.summary.rule_version < 1 or self.alert_version < 1:
            raise AlertRuleViolation("notification versions must be positive")
        if self.payload_hash != _canonical_hash(self.summary.payload()):
            raise AlertRuleViolation("notification payload hash is inconsistent")
        object.__setattr__(self, "channel", channel)


@dataclass(frozen=True)
class NotificationDelivery:
    command_id: UUID
    status: NotificationDeliveryStatus = NotificationDeliveryStatus.PENDING
    attempt_count: int = 0
    max_attempts: int = 3
    last_attempt_at: datetime | None = None
    retry_at: datetime | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        try:
            status = NotificationDeliveryStatus(self.status)
        except ValueError as error:
            raise AlertRuleViolation("notification delivery status is unsupported") from error
        if self.max_attempts < 1 or not 0 <= self.attempt_count <= self.max_attempts:
            raise AlertRuleViolation("notification delivery attempt budget is inconsistent")
        if self.last_attempt_at is not None:
            _require_aware(self.last_attempt_at, "notification delivery attempt time")
        if self.retry_at is not None:
            _require_aware(self.retry_at, "notification delivery retry time")
            if self.last_attempt_at is None or self.retry_at <= self.last_attempt_at:
                raise AlertRuleViolation("notification retry must follow its failed attempt")
        if status is NotificationDeliveryStatus.PENDING and self.attempt_count != 0:
            raise AlertRuleViolation("a pending notification cannot have attempts")
        if status is not NotificationDeliveryStatus.PENDING and self.attempt_count < 1:
            raise AlertRuleViolation("a started notification requires at least one attempt")
        if status is NotificationDeliveryStatus.RETRY_WAIT:
            if self.retry_at is None or self.error_code is None:
                raise AlertRuleViolation("a retrying notification requires retry and error details")
        elif self.retry_at is not None:
            raise AlertRuleViolation("only a retrying notification can retain retry time")
        if status is NotificationDeliveryStatus.DELIVERED and self.error_code is not None:
            raise AlertRuleViolation("a delivered notification cannot retain an error")
        if status is NotificationDeliveryStatus.FAILED and self.error_code is None:
            raise AlertRuleViolation("a failed notification requires an error code")
        object.__setattr__(self, "status", status)


def build_notification_commands(
    alert: Alert,
    *,
    event_type: str,
    created_at: datetime,
    channels: Sequence[NotificationChannel] = DEFAULT_NOTIFICATION_CHANNELS,
) -> tuple[NotificationOutboxCommand, ...]:
    _require_aware(created_at, "notification command creation time")
    event = _bounded_key(event_type, "alert notification event type")
    normalized_channels = tuple(sorted({NotificationChannel(item) for item in channels}, key=str))
    if not normalized_channels:
        raise AlertRuleViolation("at least one notification channel is required")
    summary = NotificationSummary(
        alert_id=alert.id,
        project_id=alert.project_id,
        rule_key=alert.rule_version.rule_key,
        rule_version=alert.rule_version.version,
        rule_kind=alert.rule_version.kind,
        severity=alert.severity,
        status=alert.status,
        event_type=event,
        occurred_at=alert.updated_at,
        detail_link=f"/admin/projects/{alert.project_id}/alerts/{alert.id}",
    )
    commands: list[NotificationOutboxCommand] = []
    for channel in normalized_channels:
        key = notification_idempotency_key(
            alert_id=alert.id,
            alert_version=alert.version,
            event_type=event,
            channel=channel,
        )
        commands.append(
            NotificationOutboxCommand(
                id=uuid5(ALERT_NOTIFICATION_NAMESPACE, key),
                project_id=alert.project_id,
                alert_id=alert.id,
                alert_version=alert.version,
                channel=channel,
                topic=f"alerts.notify.{channel.value}",
                summary=summary,
                idempotency_key=key,
                created_at=created_at,
                payload_hash=_canonical_hash(summary.payload()),
            )
        )
    return tuple(commands)


def notification_idempotency_key(
    *,
    alert_id: UUID,
    alert_version: int,
    event_type: str,
    channel: NotificationChannel,
) -> str:
    if alert_version < 1:
        raise AlertRuleViolation("notification alert version must be positive")
    event = _bounded_key(event_type, "alert notification event type")
    normalized_channel = NotificationChannel(channel)
    return f"alert-notification:{alert_id}:v{alert_version}:{event}:{normalized_channel.value}"


def start_notification_delivery(
    command: NotificationOutboxCommand, *, max_attempts: int = 3
) -> NotificationDelivery:
    return NotificationDelivery(command_id=command.id, max_attempts=max_attempts)


def record_notification_failure(
    delivery: NotificationDelivery,
    *,
    attempted_at: datetime,
    error_code: str,
    retry_at: datetime | None,
) -> NotificationDelivery:
    if delivery.status not in {
        NotificationDeliveryStatus.PENDING,
        NotificationDeliveryStatus.RETRY_WAIT,
    }:
        raise AlertConflict("notification delivery is already terminal")
    _require_aware(attempted_at, "notification delivery attempt time")
    error = _bounded_key(error_code, "notification delivery error code")
    attempts = delivery.attempt_count + 1
    retryable = retry_at is not None and attempts < delivery.max_attempts
    if retry_at is not None:
        _require_aware(retry_at, "notification delivery retry time")
        if retry_at <= attempted_at:
            raise AlertRuleViolation("notification retry must follow its failed attempt")
    return replace(
        delivery,
        status=(
            NotificationDeliveryStatus.RETRY_WAIT
            if retryable
            else NotificationDeliveryStatus.FAILED
        ),
        attempt_count=attempts,
        last_attempt_at=attempted_at,
        retry_at=retry_at if retryable else None,
        error_code=error,
    )


def record_notification_success(
    delivery: NotificationDelivery, *, attempted_at: datetime
) -> NotificationDelivery:
    if delivery.status not in {
        NotificationDeliveryStatus.PENDING,
        NotificationDeliveryStatus.RETRY_WAIT,
    }:
        raise AlertConflict("notification delivery is already terminal")
    _require_aware(attempted_at, "notification delivery attempt time")
    return replace(
        delivery,
        status=NotificationDeliveryStatus.DELIVERED,
        attempt_count=delivery.attempt_count + 1,
        last_attempt_at=attempted_at,
        retry_at=None,
        error_code=None,
    )
