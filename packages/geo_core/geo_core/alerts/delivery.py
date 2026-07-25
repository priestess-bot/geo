"""Fail-closed delivery adapters for alert notification outbox commands."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.message import EmailMessage
import hashlib
import hmac
import ipaddress
import json
from pathlib import Path
import smtplib
from types import TracebackType
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from geo_core.alerts.domain import AlertRuleViolation, _require_aware
from geo_core.alerts.notifications import (
    NotificationChannel,
    NotificationDelivery,
    NotificationDeliveryStatus,
    NotificationOutboxCommand,
    record_notification_failure,
    record_notification_success,
)
from geo_core.secrets.models import SecretValue


class NotificationDeliveryError(RuntimeError):
    """A sanitized external delivery failure safe to persist."""

    def __init__(
        self,
        code: str,
        *,
        retryable: bool,
        retry_after: timedelta | None = None,
    ) -> None:
        if not code or len(code) > 64 or not code.replace("_", "").isalnum():
            raise AlertRuleViolation("notification failure code is invalid")
        if retry_after is not None and (not retryable or retry_after <= timedelta(0)):
            raise AlertRuleViolation("notification retry delay is invalid")
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.retry_after = retry_after


class NotificationTransport(Protocol):
    def deliver(self, command: NotificationOutboxCommand, *, attempted_at: datetime) -> None: ...


@dataclass(frozen=True)
class NotificationDispatchResult:
    delivery: NotificationDelivery
    delivered: bool


class NotificationDispatcher:
    """Dispatch one already-claimed command without mutating its owning alert."""

    def __init__(
        self,
        transports: Mapping[NotificationChannel, NotificationTransport],
        *,
        retry_delays: tuple[timedelta, ...] = (
            timedelta(seconds=30),
            timedelta(minutes=2),
            timedelta(minutes=10),
        ),
    ) -> None:
        self._transports = dict(transports)
        if not retry_delays or any(delay <= timedelta(0) for delay in retry_delays):
            raise AlertRuleViolation("notification retry schedule is invalid")
        self._retry_delays = retry_delays

    def dispatch(
        self,
        command: NotificationOutboxCommand,
        delivery: NotificationDelivery,
        *,
        attempted_at: datetime,
    ) -> NotificationDispatchResult:
        _require_aware(attempted_at, "notification delivery attempt time")
        if delivery.command_id != command.id:
            raise AlertRuleViolation("notification delivery belongs to another command")
        if delivery.status not in {
            NotificationDeliveryStatus.PENDING,
            NotificationDeliveryStatus.RETRY_WAIT,
        }:
            raise AlertRuleViolation("terminal notification delivery cannot be dispatched")
        if delivery.retry_at is not None and attempted_at < delivery.retry_at:
            raise AlertRuleViolation("notification retry is not due")
        transport = self._transports.get(command.channel)
        if transport is None:
            updated = record_notification_failure(
                delivery,
                attempted_at=attempted_at,
                error_code="channel_unconfigured",
                retry_at=None,
            )
            return NotificationDispatchResult(updated, False)
        try:
            transport.deliver(command, attempted_at=attempted_at)
        except NotificationDeliveryError as error:
            retry_at = None
            if error.retryable and delivery.attempt_count + 1 < delivery.max_attempts:
                delay = error.retry_after or self._retry_delay(delivery.attempt_count)
                retry_at = attempted_at + delay
            updated = record_notification_failure(
                delivery,
                attempted_at=attempted_at,
                error_code=error.code,
                retry_at=retry_at,
            )
            return NotificationDispatchResult(updated, False)
        updated = record_notification_success(delivery, attempted_at=attempted_at)
        return NotificationDispatchResult(updated, True)

    def _retry_delay(self, attempt_count: int) -> timedelta:
        return self._retry_delays[min(attempt_count, len(self._retry_delays) - 1)]


class AdminInboxWriter(Protocol):
    def put(
        self,
        *,
        command_id: str,
        idempotency_key: str,
        project_id: str,
        payload: Mapping[str, object],
    ) -> None: ...


class AdminInboxTransport:
    def __init__(self, writer: AdminInboxWriter) -> None:
        self._writer = writer

    def deliver(self, command: NotificationOutboxCommand, *, attempted_at: datetime) -> None:
        _require_aware(attempted_at, "Admin inbox delivery time")
        try:
            self._writer.put(
                command_id=str(command.id),
                idempotency_key=command.idempotency_key,
                project_id=str(command.project_id),
                payload=command.summary.payload(),
            )
        except Exception as error:
            raise NotificationDeliveryError("inbox_unavailable", retryable=True) from error


@dataclass(frozen=True)
class LocalSmtpConfig:
    host: str
    port: int
    sender: str
    recipients: tuple[str, ...]
    timeout_seconds: float = 10.0
    allowed_internal_hosts: frozenset[str] = frozenset({"alert-smtp-relay"})

    def __post_init__(self) -> None:
        _require_local_smtp_host(self.host, self.allowed_internal_hosts)
        if not 1 <= self.port <= 65535:
            raise AlertRuleViolation("local SMTP port is invalid")
        if not self.recipients:
            raise AlertRuleViolation("local SMTP recipients cannot be empty")
        for address in (self.sender, *self.recipients):
            _require_email_address(address)
        if not 0 < self.timeout_seconds <= 60:
            raise AlertRuleViolation("local SMTP timeout is invalid")


class SmtpClient(Protocol):
    def send_message(self, message: EmailMessage) -> object: ...


class SmtpClientContext(Protocol):
    def __enter__(self) -> SmtpClient: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


class LocalSmtpTransport:
    def __init__(
        self,
        config: LocalSmtpConfig,
        *,
        client_factory: Callable[[str, int, float], SmtpClientContext] | None = None,
    ) -> None:
        self._config = config
        self._client_factory = client_factory or _smtp_client

    def deliver(self, command: NotificationOutboxCommand, *, attempted_at: datetime) -> None:
        _require_aware(attempted_at, "SMTP delivery time")
        message = _email_message(command, config=self._config)
        try:
            with self._client_factory(
                self._config.host,
                self._config.port,
                self._config.timeout_seconds,
            ) as client:
                refused = client.send_message(message)
                if isinstance(refused, Mapping) and refused:
                    retryable = any(_smtp_code(value) in range(400, 500) for value in refused.values())
                    raise NotificationDeliveryError(
                        "smtp_recipients_refused",
                        retryable=retryable,
                    )
        except NotificationDeliveryError:
            raise
        except smtplib.SMTPResponseException as error:
            raise NotificationDeliveryError(
                "smtp_rejected",
                retryable=400 <= error.smtp_code < 500,
            ) from error
        except (TimeoutError, OSError, smtplib.SMTPException) as error:
            raise NotificationDeliveryError("smtp_unavailable", retryable=True) from error


@dataclass(frozen=True, repr=False)
class InternalWebhookConfig:
    endpoint: str
    allowed_hosts: frozenset[str]
    signing_secret: SecretValue
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        parsed = urlsplit(self.endpoint)
        host = (parsed.hostname or "").lower()
        allowed = frozenset(value.strip().lower() for value in self.allowed_hosts if value.strip())
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise AlertRuleViolation("internal webhook endpoint is invalid")
        if host not in allowed:
            raise AlertRuleViolation("internal webhook host is not allowlisted")
        if not isinstance(self.signing_secret, SecretValue):
            raise AlertRuleViolation("internal webhook signing secret must be secret-backed")
        if not 0 < self.timeout_seconds <= 60:
            raise AlertRuleViolation("internal webhook timeout is invalid")
        object.__setattr__(self, "allowed_hosts", allowed)


@dataclass(frozen=True)
class WebhookResponse:
    status_code: int
    headers: Mapping[str, str]


class WebhookClient(Protocol):
    def post(
        self,
        url: str,
        *,
        content: bytes,
        headers: Mapping[str, str],
        timeout_seconds: float,
        follow_redirects: bool,
    ) -> WebhookResponse: ...


class HttpxWebhookClient:
    """One-shot client that cannot inherit host proxy settings or follow redirects."""

    def __init__(self, *, ca_file: str | Path | None = None) -> None:
        if ca_file is None or not str(ca_file).strip():
            self._verify: bool | str = True
            return
        path = Path(ca_file)
        if path.is_symlink() or not path.is_file():
            raise AlertRuleViolation("internal webhook CA file is invalid")
        self._verify = str(path)

    def post(
        self,
        url: str,
        *,
        content: bytes,
        headers: Mapping[str, str],
        timeout_seconds: float,
        follow_redirects: bool,
    ) -> WebhookResponse:
        if follow_redirects:
            raise AlertRuleViolation("internal webhook redirects must remain disabled")
        try:
            with httpx.Client(
                trust_env=False,
                follow_redirects=False,
                timeout=timeout_seconds,
                verify=self._verify,
            ) as client:
                response = client.post(url, content=content, headers=headers)
        except httpx.TimeoutException as error:
            raise TimeoutError("internal webhook timed out") from error
        except httpx.TransportError as error:
            raise OSError("internal webhook transport failed") from error
        return WebhookResponse(response.status_code, dict(response.headers))


class InternalWebhookTransport:
    def __init__(self, config: InternalWebhookConfig, client: WebhookClient) -> None:
        self._config = config
        self._client = client

    def deliver(self, command: NotificationOutboxCommand, *, attempted_at: datetime) -> None:
        _require_aware(attempted_at, "Webhook delivery time")
        body = _canonical_json(command.summary.payload())
        timestamp = str(int(attempted_at.timestamp()))
        signature = _webhook_signature(
            secret=self._config.signing_secret,
            timestamp=timestamp,
            command_id=str(command.id),
            body=body,
        )
        headers = {
            "Content-Type": "application/json",
            "X-GEO-Webhook-ID": str(command.id),
            "X-GEO-Webhook-Timestamp": timestamp,
            "X-GEO-Webhook-Signature": f"v1={signature}",
            "Idempotency-Key": command.idempotency_key,
        }
        try:
            response = self._client.post(
                self._config.endpoint,
                content=body,
                headers=headers,
                timeout_seconds=self._config.timeout_seconds,
                follow_redirects=False,
            )
        except (TimeoutError, OSError) as error:
            raise NotificationDeliveryError("webhook_unavailable", retryable=True) from error
        status = response.status_code
        if 200 <= status < 300:
            return
        retry_after = _retry_after(response.headers) if status in {408, 425, 429} else None
        if status in {408, 409, 425, 429} or 500 <= status < 600:
            raise NotificationDeliveryError(
                "webhook_retryable",
                retryable=True,
                retry_after=retry_after,
            )
        raise NotificationDeliveryError("webhook_rejected", retryable=False)


def _email_message(command: NotificationOutboxCommand, *, config: LocalSmtpConfig) -> EmailMessage:
    summary = command.summary
    message = EmailMessage()
    message["From"] = config.sender
    message["To"] = ", ".join(config.recipients)
    message["Subject"] = f"[GEO {summary.severity.value.upper()}] {summary.rule_key}"
    message["Message-ID"] = f"<{command.id}@geo.local>"
    message.set_content(
        "\n".join(
            (
                f"Event: {summary.event_type}",
                f"Status: {summary.status.value}",
                f"Rule: {summary.rule_key} v{summary.rule_version}",
                f"Occurred: {summary.occurred_at.isoformat()}",
                f"Details: {summary.detail_link}",
            )
        )
    )
    return message


def _webhook_signature(
    *, secret: SecretValue, timestamp: str, command_id: str, body: bytes
) -> str:
    signed = b".".join((timestamp.encode("ascii"), command_id.encode("ascii"), body))
    return hmac.new(secret.reveal_bytes(), signed, hashlib.sha256).hexdigest()


def _canonical_json(value: Mapping[str, object]) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def _retry_after(headers: Mapping[str, str]) -> timedelta | None:
    raw = next(
        (value for name, value in headers.items() if name.lower() == "retry-after"),
        None,
    )
    if raw is None or not raw.isdigit():
        return None
    seconds = int(raw)
    if not 1 <= seconds <= 3600:
        return None
    return timedelta(seconds=seconds)


def _require_local_smtp_host(host: str, allowed_internal_hosts: frozenset[str]) -> None:
    normalized = host.strip().lower()
    allowed = frozenset(item.strip().lower() for item in allowed_internal_hosts if item.strip())
    if normalized == "localhost" or normalized in allowed:
        return
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        raise AlertRuleViolation("local SMTP host is not the fixed relay or loopback") from None
    if not address.is_loopback:
        raise AlertRuleViolation("local SMTP host is not the fixed relay or loopback")


def _require_email_address(value: str) -> None:
    if (
        not value
        or len(value) > 254
        or "\r" in value
        or "\n" in value
        or value.count("@") != 1
        or any(character.isspace() for character in value)
    ):
        raise AlertRuleViolation("notification email address is invalid")


def _smtp_code(value: object) -> int:
    if isinstance(value, tuple) and value and isinstance(value[0], int):
        return value[0]
    return 500


def _smtp_client(host: str, port: int, timeout: float) -> SmtpClientContext:
    return smtplib.SMTP(host=host, port=port, timeout=timeout)
