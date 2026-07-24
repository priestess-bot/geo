"""Fail-closed production composition for Workflow C notification transports."""

from __future__ import annotations

import os

from geo_core.alerts import (
    AdminInboxTransport,
    HttpxWebhookClient,
    InternalWebhookConfig,
    InternalWebhookTransport,
    LocalSmtpConfig,
    LocalSmtpTransport,
    NotificationChannel,
    NotificationDispatcher,
)
from geo_core.alerts.delivery import AdminInboxWriter
from geo_core.secrets import SecretValue
from geo_worker.config import bounded_int_setting, secret_setting


def build_workflow_c_notification_dispatcher(
    *, inbox_writer: AdminInboxWriter
) -> NotificationDispatcher:
    smtp_host = os.getenv("GEO_ALERT_SMTP_HOST", "").strip().lower()
    if smtp_host != "alert-smtp-relay":
        raise RuntimeError("GEO_ALERT_SMTP_HOST must be the fixed alert-smtp-relay service")
    sender = _required("GEO_ALERT_SMTP_SENDER")
    recipients = _csv("GEO_ALERT_SMTP_RECIPIENTS")
    webhook_endpoint = _required("GEO_ALERT_WEBHOOK_ENDPOINT")
    webhook_hosts = frozenset(_csv("GEO_ALERT_WEBHOOK_ALLOWED_HOSTS"))
    webhook_secret = SecretValue(secret_setting("GEO_ALERT_WEBHOOK_SIGNING_SECRET"))
    return NotificationDispatcher(
        {
            NotificationChannel.ADMIN_INBOX: AdminInboxTransport(inbox_writer),
            NotificationChannel.LOCAL_SMTP: LocalSmtpTransport(
                LocalSmtpConfig(
                    host=smtp_host,
                    port=bounded_int_setting(
                        "GEO_ALERT_SMTP_PORT", 8025, minimum=1, maximum=65_535
                    ),
                    sender=sender,
                    recipients=tuple(recipients),
                )
            ),
            NotificationChannel.INTERNAL_WEBHOOK: InternalWebhookTransport(
                InternalWebhookConfig(
                    endpoint=webhook_endpoint,
                    allowed_hosts=webhook_hosts,
                    signing_secret=webhook_secret,
                ),
                HttpxWebhookClient(),
            ),
        }
    )


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _csv(name: str) -> tuple[str, ...]:
    values = tuple(item.strip() for item in _required(name).split(",") if item.strip())
    if not values or len(set(values)) != len(values):
        raise RuntimeError(f"{name} must be a unique non-empty list")
    return values


__all__ = ["build_workflow_c_notification_dispatcher"]
