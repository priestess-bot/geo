from __future__ import annotations

import hashlib
import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any


DEFAULT_RUNTIME_EMAIL_SMTP_ENV_PREFIX = "GEO_NOTIFICATION_SMTP"
RUNTIME_NOTIFICATION_EMAIL_TEMPLATE_VERSION = "runtime_notification_email_template_v2"
RUNTIME_NOTIFICATION_EMAIL_TEMPLATE = """{title}

{message}

Type: {notification_type}
Severity: {severity}
Threshold: {threshold}
Target: {target_type}
{target_line}Notification ID: {notification_id}
Project ID: {project_id}
Subscription ID: {subscription_id}{control_footer}"""
PROJECT_MEMBER_INVITATION_EMAIL_TEMPLATE_VERSION = "project_member_invitation_email_template_v2"
PROJECT_MEMBER_INVITATION_EMAIL_TEMPLATE = """{custom_message}

Role: {role}
Invitation ID: {invitation_id}
Expires at: {expires_at}

Open the invitation page:
{accept_url}

Enter this one-time code on that page:
{one_time_code}

This code should not be forwarded or shared."""


@dataclass(frozen=True)
class RuntimeEmailDeliveryResult:
    response_status: int
    response_body: bytes
    response_body_hash: str
    recipients: tuple[str, ...]
    smtp_host: str
    smtp_port: int
    from_address: str


@dataclass(frozen=True)
class RuntimeEmailTemplateRenderResult:
    subject: str
    text: str
    template_version: str
    template_hash: str
    subject_hash: str
    body_hash: str


def runtime_email_body_hash(body: bytes | str | None) -> str:
    if body is None:
        raw = b""
    elif isinstance(body, bytes):
        raw = body
    else:
        raw = body.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def render_project_member_invitation_email(
    *,
    role: str,
    invitation_id: str,
    expires_at: str,
    accept_url: str,
    one_time_code: str,
    subject: str | None = None,
    message: str | None = None,
) -> RuntimeEmailTemplateRenderResult:
    rendered_subject = (subject or "").strip() or "GEO project invitation"
    custom_message = (message or "").strip() or "You have been invited to join a GEO project."
    text = PROJECT_MEMBER_INVITATION_EMAIL_TEMPLATE.format(
        custom_message=custom_message,
        role=role,
        invitation_id=invitation_id,
        expires_at=expires_at,
        accept_url=accept_url,
        one_time_code=one_time_code,
    )
    return RuntimeEmailTemplateRenderResult(
        subject=rendered_subject,
        text=text,
        template_version=PROJECT_MEMBER_INVITATION_EMAIL_TEMPLATE_VERSION,
        template_hash=runtime_email_body_hash(PROJECT_MEMBER_INVITATION_EMAIL_TEMPLATE),
        subject_hash=runtime_email_body_hash(rendered_subject),
        body_hash=runtime_email_body_hash(text),
    )


def render_runtime_notification_email(
    *,
    notification_id: str,
    project_id: str,
    subscription_id: str,
    notification_type: str,
    severity: str,
    threshold: str,
    target_type: str,
    target_id: str | None = None,
    title: str | None = None,
    message: str | None = None,
    unsubscribe_url: str | None = None,
    preferences_url: str | None = None,
) -> RuntimeEmailTemplateRenderResult:
    rendered_title = (title or "").strip() or "GEO runtime notification"
    rendered_message = (message or "").strip() or "A GEO runtime notification was generated."
    rendered_severity = (severity or "info").strip().lower() or "info"
    rendered_notification_type = (notification_type or "runtime_notification").strip() or "runtime_notification"
    rendered_threshold = (threshold or "info").strip().lower() or "info"
    rendered_target_type = (target_type or "target").strip() or "target"
    rendered_target_id = (target_id or "").strip()
    rendered_unsubscribe_url = (unsubscribe_url or "").strip()
    rendered_preferences_url = (preferences_url or "").strip()
    rendered_subject = f"[GEO {rendered_severity.upper()}] {rendered_title}"
    target_line = f"Target ID: {rendered_target_id}\n" if rendered_target_id else ""
    control_lines: list[str] = []
    if rendered_unsubscribe_url:
        control_lines.append(f"Unsubscribe: {rendered_unsubscribe_url}")
    if rendered_preferences_url:
        control_lines.append(f"Preferences: {rendered_preferences_url}")
    control_footer = "\n\nNotification controls:\n" + "\n".join(control_lines) if control_lines else ""
    text = RUNTIME_NOTIFICATION_EMAIL_TEMPLATE.format(
        title=rendered_title,
        message=rendered_message,
        notification_type=rendered_notification_type,
        severity=rendered_severity,
        threshold=rendered_threshold,
        target_type=rendered_target_type,
        target_line=target_line,
        notification_id=notification_id,
        project_id=project_id,
        subscription_id=subscription_id,
        control_footer=control_footer,
    )
    return RuntimeEmailTemplateRenderResult(
        subject=rendered_subject,
        text=text,
        template_version=RUNTIME_NOTIFICATION_EMAIL_TEMPLATE_VERSION,
        template_hash=runtime_email_body_hash(RUNTIME_NOTIFICATION_EMAIL_TEMPLATE),
        subject_hash=runtime_email_body_hash(rendered_subject),
        body_hash=runtime_email_body_hash(text),
    )


def runtime_smtp_config_from_env(env_prefix: str | None = DEFAULT_RUNTIME_EMAIL_SMTP_ENV_PREFIX) -> dict[str, Any]:
    prefix = (env_prefix or DEFAULT_RUNTIME_EMAIL_SMTP_ENV_PREFIX).strip() or DEFAULT_RUNTIME_EMAIL_SMTP_ENV_PREFIX
    host = os.environ.get(f"{prefix}_HOST", "").strip()
    if not host:
        raise RuntimeError(f"{prefix}_HOST is not configured")
    try:
        port = int(os.environ.get(f"{prefix}_PORT", "587"))
    except ValueError as exc:
        raise RuntimeError(f"{prefix}_PORT must be an integer") from exc
    use_tls = os.environ.get(f"{prefix}_TLS", "1").strip().lower() not in {"0", "false", "no"}
    username = os.environ.get(f"{prefix}_USERNAME", "").strip() or None
    password = os.environ.get(f"{prefix}_PASSWORD", "")
    from_address = os.environ.get(f"{prefix}_FROM", "").strip() or username
    if not from_address:
        raise RuntimeError(f"{prefix}_FROM or {prefix}_USERNAME is required")
    try:
        timeout = float(os.environ.get(f"{prefix}_TIMEOUT_SECONDS", "10"))
    except ValueError as exc:
        raise RuntimeError(f"{prefix}_TIMEOUT_SECONDS must be numeric") from exc
    return {
        "host": host,
        "port": port,
        "use_tls": use_tls,
        "username": username,
        "password": password,
        "from_address": from_address,
        "timeout": timeout,
    }


def send_runtime_email_message(
    *,
    recipients: tuple[str, ...] | list[str],
    subject: str,
    text: str,
    headers: dict[str, str] | None = None,
    smtp_env_prefix: str | None = DEFAULT_RUNTIME_EMAIL_SMTP_ENV_PREFIX,
    email_sender: Any | None = None,
) -> RuntimeEmailDeliveryResult:
    recipient_addresses = tuple(str(recipient).strip() for recipient in recipients if str(recipient).strip())
    if not recipient_addresses:
        raise RuntimeError("email delivery requires at least one recipient")
    config = runtime_smtp_config_from_env(smtp_env_prefix)
    message = EmailMessage()
    message["From"] = str(config["from_address"])
    message["To"] = ", ".join(recipient_addresses)
    message["Subject"] = subject.strip() or "GEO runtime email"
    for header_name, header_value in (headers or {}).items():
        header = str(header_name).strip()
        cleaned_value = " ".join(str(header_value).replace("\r", "\n").split())
        if header and cleaned_value and header.lower() not in {"from", "to", "subject"}:
            message[header] = cleaned_value
    message.set_content(text)
    if email_sender is not None:
        response_status, response_body = email_sender(config, message, list(recipient_addresses))
    else:
        with smtplib.SMTP(str(config["host"]), int(config["port"]), timeout=float(config["timeout"])) as smtp:
            if config["use_tls"]:
                smtp.starttls()
            if config["username"]:
                smtp.login(str(config["username"]), str(config["password"]))
            smtp.send_message(message)
        response_status, response_body = 250, b"sent"
    response_body_bytes = response_body if isinstance(response_body, bytes) else str(response_body).encode("utf-8")
    return RuntimeEmailDeliveryResult(
        response_status=int(response_status),
        response_body=response_body_bytes,
        response_body_hash=runtime_email_body_hash(response_body_bytes),
        recipients=recipient_addresses,
        smtp_host=str(config["host"]),
        smtp_port=int(config["port"]),
        from_address=str(config["from_address"]),
    )
