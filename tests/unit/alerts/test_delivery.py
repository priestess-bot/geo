from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
import hashlib
import hmac
from typing import Mapping
from uuid import UUID

import pytest

from geo_core.alerts.delivery import (
    AdminInboxTransport,
    InternalWebhookConfig,
    InternalWebhookTransport,
    LocalSmtpConfig,
    LocalSmtpTransport,
    NotificationDispatcher,
    WebhookResponse,
)
from geo_core.alerts.domain import (
    AlertRuleKind,
    AlertRuleViolation,
    AlertSeverity,
    AlertStatus,
)
from geo_core.alerts.notifications import (
    NotificationChannel,
    NotificationOutboxCommand,
    NotificationSummary,
    notification_idempotency_key,
    start_notification_delivery,
)
from geo_core.secrets.models import SecretValue


NOW = datetime(2026, 7, 23, 9, 30, tzinfo=UTC)


def _command(channel: NotificationChannel) -> NotificationOutboxCommand:
    alert_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    project_id = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    summary = NotificationSummary(
        alert_id=alert_id,
        project_id=project_id,
        rule_key="completion_ratio",
        rule_version=2,
        rule_kind=AlertRuleKind.COMPLETION_FRESHNESS,
        severity=AlertSeverity.WARNING,
        status=AlertStatus.OPEN,
        event_type="opened",
        occurred_at=NOW,
        detail_link=f"/admin/projects/{project_id}/alerts/{alert_id}",
    )
    key = notification_idempotency_key(
        alert_id=alert_id,
        alert_version=1,
        event_type="opened",
        channel=channel,
    )
    from geo_core.alerts.notifications import ALERT_NOTIFICATION_NAMESPACE
    from uuid import uuid5

    return NotificationOutboxCommand(
        id=uuid5(ALERT_NOTIFICATION_NAMESPACE, key),
        project_id=project_id,
        alert_id=alert_id,
        alert_version=1,
        channel=channel,
        topic=f"alerts.notify.{channel.value}",
        summary=summary,
        idempotency_key=key,
        created_at=NOW,
        payload_hash=_hash(summary.payload()),
    )


class _Inbox:
    def __init__(self) -> None:
        self.payload: Mapping[str, object] | None = None

    def put(self, **values: object) -> None:
        self.payload = values["payload"]  # type: ignore[assignment]


def test_admin_inbox_dispatch_is_idempotently_addressed_and_whitelisted() -> None:
    command = _command(NotificationChannel.ADMIN_INBOX)
    inbox = _Inbox()
    dispatcher = NotificationDispatcher(
        {NotificationChannel.ADMIN_INBOX: AdminInboxTransport(inbox)}
    )

    result = dispatcher.dispatch(
        command,
        start_notification_delivery(command),
        attempted_at=NOW,
    )

    assert result.delivered is True
    assert result.delivery.status.value == "delivered"
    assert inbox.payload == command.summary.payload()


class _Smtp:
    def __init__(self, result: object | None = None) -> None:
        self.message: EmailMessage | None = None
        self.result = {} if result is None else result

    def __enter__(self) -> _Smtp:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def send_message(self, message: EmailMessage) -> object:
        self.message = message
        return self.result


def test_local_smtp_sends_only_sanitized_summary() -> None:
    smtp = _Smtp()
    transport = LocalSmtpTransport(
        LocalSmtpConfig(
            host="127.0.0.1",
            port=2525,
            sender="geo-alerts@example.test",
            recipients=("ops@example.test",),
        ),
        client_factory=lambda *_: smtp,
    )
    transport.deliver(_command(NotificationChannel.LOCAL_SMTP), attempted_at=NOW)

    assert smtp.message is not None
    content = smtp.message.get_content()
    assert "completion_ratio" in content
    assert "payload" not in content
    assert "secret" not in content.lower()


def test_local_smtp_accepts_only_the_fixed_backend_relay_name() -> None:
    config = LocalSmtpConfig(
        host="alert-smtp-relay",
        port=8025,
        sender="geo@example.test",
        recipients=("ops@example.test",),
    )

    assert config.host == "alert-smtp-relay"


@pytest.mark.parametrize("host", ["smtp.internal", "10.0.0.2", "8.8.8.8"])
def test_local_smtp_rejects_non_loopback_hosts(host: str) -> None:
    with pytest.raises(AlertRuleViolation, match="loopback"):
        LocalSmtpConfig(
            host=host,
            port=25,
            sender="geo@example.test",
            recipients=("ops@example.test",),
        )


def test_local_smtp_recipient_refusal_is_sanitized_and_terminal() -> None:
    command = _command(NotificationChannel.LOCAL_SMTP)
    smtp = _Smtp({"ops@example.test": (550, b"mailbox unavailable")})
    transport = LocalSmtpTransport(
        LocalSmtpConfig(
            host="localhost",
            port=25,
            sender="geo@example.test",
            recipients=("ops@example.test",),
        ),
        client_factory=lambda *_: smtp,
    )
    result = NotificationDispatcher({NotificationChannel.LOCAL_SMTP: transport}).dispatch(
        command,
        start_notification_delivery(command),
        attempted_at=NOW,
    )

    assert result.delivery.status.value == "failed"
    assert result.delivery.error_code == "smtp_recipients_refused"


class _Webhook:
    def __init__(self, statuses: list[int], *, retry_after: str | None = None) -> None:
        self.statuses = statuses
        self.retry_after = retry_after
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, **values: object) -> WebhookResponse:
        self.calls.append({"url": url, **values})
        headers = {"Retry-After": self.retry_after} if self.retry_after else {}
        return WebhookResponse(self.statuses.pop(0), headers)


def _webhook_transport(client: _Webhook) -> InternalWebhookTransport:
    return InternalWebhookTransport(
        InternalWebhookConfig(
            endpoint="https://alerts.intranet.test/hooks/geo",
            allowed_hosts=frozenset({"alerts.intranet.test"}),
            signing_secret=SecretValue("signing-key"),
        ),
        client,
    )


def test_webhook_configuration_rejects_plain_http_even_for_an_allowlisted_host() -> None:
    with pytest.raises(AlertRuleViolation, match="endpoint"):
        InternalWebhookConfig(
            endpoint="http://alerts.intranet.test/hooks/geo",
            allowed_hosts=frozenset({"alerts.intranet.test"}),
            signing_secret=SecretValue("signing-key"),
        )


def test_webhook_is_canonical_signed_and_never_follows_redirects() -> None:
    command = _command(NotificationChannel.INTERNAL_WEBHOOK)
    client = _Webhook([204])
    transport = _webhook_transport(client)

    transport.deliver(command, attempted_at=NOW)

    call = client.calls[0]
    body = call["content"]
    headers = call["headers"]
    assert isinstance(body, bytes)
    assert isinstance(headers, dict)
    assert call["follow_redirects"] is False
    signed = b".".join(
        (
            str(int(NOW.timestamp())).encode(),
            str(command.id).encode(),
            body,
        )
    )
    expected = hmac.new(b"signing-key", signed, hashlib.sha256).hexdigest()
    assert headers["X-GEO-Webhook-Signature"] == f"v1={expected}"
    assert b"secret" not in body.lower()


def test_webhook_429_uses_bounded_retry_after_then_succeeds() -> None:
    command = _command(NotificationChannel.INTERNAL_WEBHOOK)
    client = _Webhook([429, 200], retry_after="90")
    dispatcher = NotificationDispatcher(
        {NotificationChannel.INTERNAL_WEBHOOK: _webhook_transport(client)}
    )

    failed = dispatcher.dispatch(
        command,
        start_notification_delivery(command),
        attempted_at=NOW,
    )
    assert failed.delivered is False
    assert failed.delivery.retry_at == NOW + timedelta(seconds=90)

    succeeded = dispatcher.dispatch(
        command,
        failed.delivery,
        attempted_at=NOW + timedelta(seconds=90),
    )
    assert succeeded.delivered is True
    assert succeeded.delivery.attempt_count == 2


def test_webhook_reject_and_unconfigured_channel_are_terminal() -> None:
    command = _command(NotificationChannel.INTERNAL_WEBHOOK)
    rejected = NotificationDispatcher(
        {NotificationChannel.INTERNAL_WEBHOOK: _webhook_transport(_Webhook([400]))}
    ).dispatch(command, start_notification_delivery(command), attempted_at=NOW)
    assert rejected.delivery.status.value == "failed"
    assert rejected.delivery.error_code == "webhook_rejected"

    missing = NotificationDispatcher({}).dispatch(
        command,
        start_notification_delivery(command),
        attempted_at=NOW,
    )
    assert missing.delivery.status.value == "failed"
    assert missing.delivery.error_code == "channel_unconfigured"


def test_webhook_configuration_rejects_host_escape_and_url_credentials() -> None:
    with pytest.raises(AlertRuleViolation, match="allowlisted"):
        InternalWebhookConfig(
            endpoint="https://public.example/hooks",
            allowed_hosts=frozenset({"alerts.intranet.test"}),
            signing_secret=SecretValue("key"),
        )
    with pytest.raises(AlertRuleViolation, match="invalid"):
        InternalWebhookConfig(
            endpoint="https://user:pass@alerts.intranet.test/hooks",
            allowed_hosts=frozenset({"alerts.intranet.test"}),
            signing_secret=SecretValue("key"),
        )


def _hash(payload: Mapping[str, object]) -> str:
    encoded = json_bytes(payload)
    return hashlib.sha256(encoded).hexdigest()


def json_bytes(payload: Mapping[str, object]) -> bytes:
    import json

    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
