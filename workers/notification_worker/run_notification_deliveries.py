from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import unquote, urlparse

import httpx

from geo_core.email_delivery import (
    DEFAULT_RUNTIME_EMAIL_SMTP_ENV_PREFIX,
    runtime_smtp_config_from_env,
    send_runtime_email_message,
)
from geo_core.models import RuntimeNotificationDeliveryStatusInput
from geo_core.repository import PostgresEvidenceRepository
from geo_core.runtime import (
    build_repository_from_env,
    close_repository_connection,
    validate_runtime_schema_compatibility,
)
from geo_core.webhook_signing import (
    RUNTIME_NOTIFICATION_WEBHOOK_DELIVERY_ID_HEADER,
    RUNTIME_NOTIFICATION_WEBHOOK_NOTIFICATION_ID_HEADER,
    RUNTIME_NOTIFICATION_WEBHOOK_PAYLOAD_HASH_HEADER,
    runtime_notification_webhook_payload_hash,
    sign_runtime_notification_webhook,
)


WORKER_ID = "notification-worker"
DEFAULT_SIGNING_SECRET_ENV = "GEO_NOTIFICATION_WEBHOOK_SIGNING_SECRET"
DEFAULT_SIGNING_SECRET_KEY_ID = "primary"
DEFAULT_SECONDARY_SIGNING_SECRET_ENV = "GEO_NOTIFICATION_WEBHOOK_SIGNING_SECRET_PREVIOUS"
DEFAULT_SMTP_ENV_PREFIX = DEFAULT_RUNTIME_EMAIL_SMTP_ENV_PREFIX


class NotificationDeliveryRepository(Protocol):
    def claim_next_runtime_notification_delivery(
        self,
        *,
        updated_by: str = WORKER_ID,
        lease_seconds: int = 300,
    ) -> object | None:
        ...

    def update_runtime_notification_delivery_status(
        self,
        update: RuntimeNotificationDeliveryStatusInput,
    ) -> object:
        ...


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _failed_status(*, attempt_count: int, max_attempts: int) -> str:
    return "dead_letter" if attempt_count >= max_attempts else "queued"


def _next_attempt_at(*, attempt_count: int, max_attempts: int, retry_backoff_seconds: int) -> datetime | None:
    if attempt_count >= max_attempts:
        return None
    delay = retry_backoff_seconds * max(1, attempt_count)
    return datetime.now(UTC) + timedelta(seconds=delay)


def _subscription_metadata(delivery_record: object) -> dict[str, Any]:
    subscription = getattr(delivery_record, "subscription", None)
    if not isinstance(subscription, dict):
        return {}
    metadata = subscription.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _delivery_channel(delivery: dict[str, Any]) -> str:
    return str(delivery.get("channel") or "webhook").strip().lower() or "webhook"


def _delivery_body_payload(*, channel: str, payload: dict[str, Any]) -> dict[str, Any]:
    if channel == "slack":
        slack_payload = payload.get("slack")
        if isinstance(slack_payload, dict):
            return slack_payload
    if channel == "email":
        email_payload = payload.get("email")
        if isinstance(email_payload, dict):
            return email_payload
    return payload


def _email_recipients_from_endpoint(endpoint_url: str) -> list[str]:
    parsed = urlparse(endpoint_url)
    if parsed.scheme != "mailto":
        return []
    return [
        unquote(recipient.strip())
        for recipient in parsed.path.split(",")
        if recipient and recipient.strip()
    ]


def _smtp_config(env_prefix: str | None = DEFAULT_SMTP_ENV_PREFIX) -> dict[str, Any]:
    return runtime_smtp_config_from_env(env_prefix)


def _send_email_delivery(
    *,
    endpoint_url: str,
    payload: dict[str, Any],
    smtp_env_prefix: str | None,
    email_sender: Any | None = None,
) -> tuple[int, bytes]:
    recipients = payload.get("to") if isinstance(payload.get("to"), list) else []
    recipient_addresses = [str(recipient).strip() for recipient in recipients if str(recipient).strip()]
    if not recipient_addresses:
        recipient_addresses = _email_recipients_from_endpoint(endpoint_url)
    headers = payload.get("headers") if isinstance(payload.get("headers"), dict) else {}
    result = send_runtime_email_message(
        recipients=tuple(recipient_addresses),
        subject=str(payload.get("subject") or "GEO runtime notification"),
        text=str(payload.get("text") or "GEO runtime notification"),
        headers={str(key): str(value) for key, value in headers.items()},
        smtp_env_prefix=smtp_env_prefix,
        email_sender=email_sender,
    )
    return result.response_status, result.response_body


def _webhook_signing_secret(
    *,
    subscription_metadata: dict[str, Any],
    default_signing_secret_env: str | None,
) -> tuple[str | None, str | None, str | None]:
    configured_env = str(
        subscription_metadata.get("signing_secret_env")
        or subscription_metadata.get("webhook_signing_secret_env")
        or ""
    ).strip()
    configured_key_id = str(
        subscription_metadata.get("signing_secret_key_id")
        or subscription_metadata.get("webhook_signing_secret_key_id")
        or ""
    ).strip()
    if configured_env:
        secret = os.environ.get(configured_env)
        if not secret:
            raise RuntimeError(f"webhook signing secret env {configured_env} is not configured")
        return secret, configured_env, configured_key_id or configured_env
    fallback_env = (default_signing_secret_env or "").strip()
    if fallback_env:
        secret = os.environ.get(fallback_env)
        if secret:
            return secret, fallback_env, configured_key_id or DEFAULT_SIGNING_SECRET_KEY_ID
    return None, None, None


def _apply_webhook_signature_headers(
    *,
    headers: dict[str, str],
    secret: str,
    key_id: str | None,
    delivery_id: str,
    notification_id: str,
    payload_hash: str,
) -> dict[str, str]:
    return {
        **headers,
        **sign_runtime_notification_webhook(
            secret=secret,
            delivery_id=delivery_id,
            notification_id=notification_id,
            payload_hash=payload_hash,
            key_id=key_id,
        ),
    }


def process_next_notification_delivery(
    *,
    repository: NotificationDeliveryRepository,
    updated_by: str = WORKER_ID,
    max_attempts: int = 3,
    retry_backoff_seconds: int = 120,
    lease_seconds: int = 300,
    timeout_seconds: float = 5.0,
    default_signing_secret_env: str | None = DEFAULT_SIGNING_SECRET_ENV,
    requester: Any | None = None,
    email_sender: Any | None = None,
    smtp_env_prefix: str | None = DEFAULT_SMTP_ENV_PREFIX,
) -> dict[str, Any]:
    max_attempts = max(1, int(max_attempts))
    retry_backoff_seconds = max(0, int(retry_backoff_seconds))
    lease_seconds = max(1, int(lease_seconds))
    timeout_seconds = max(0.1, float(timeout_seconds))
    delivery_record = repository.claim_next_runtime_notification_delivery(
        updated_by=updated_by,
        lease_seconds=lease_seconds,
    )
    if delivery_record is None:
        return {
            "processed": False,
            "status": "idle",
            "reason": "no queued notification deliveries",
        }

    delivery = dict(getattr(delivery_record, "delivery"))
    delivery_id = str(delivery["id"])
    project_id = str(delivery["project_id"])
    attempt_count = int(delivery.get("attempt_count") or 0)
    delivery_max_attempts = max(max_attempts, int(delivery.get("max_attempts") or max_attempts))
    endpoint_url = str(delivery["endpoint_url"])
    payload = delivery.get("payload") if isinstance(delivery.get("payload"), dict) else {}
    channel = _delivery_channel(delivery)
    outbound_payload = _delivery_body_payload(channel=channel, payload=payload)
    body = _canonical_json_bytes(outbound_payload)
    body_hash = runtime_notification_webhook_payload_hash(body)
    headers = {"content-type": "application/json"}
    if channel == "webhook":
        headers.update(
            {
                RUNTIME_NOTIFICATION_WEBHOOK_DELIVERY_ID_HEADER: delivery_id,
                RUNTIME_NOTIFICATION_WEBHOOK_NOTIFICATION_ID_HEADER: str(delivery["notification_id"]),
                RUNTIME_NOTIFICATION_WEBHOOK_PAYLOAD_HASH_HEADER: body_hash,
            }
        )
    signed = False
    signing_secret_env: str | None = None
    signing_secret_key_id: str | None = None

    try:
        if channel == "webhook":
            signing_secret, signing_secret_env, signing_secret_key_id = _webhook_signing_secret(
                subscription_metadata=_subscription_metadata(delivery_record),
                default_signing_secret_env=default_signing_secret_env,
            )
            if signing_secret:
                headers = _apply_webhook_signature_headers(
                    headers=headers,
                    secret=signing_secret,
                    key_id=signing_secret_key_id,
                    delivery_id=delivery_id,
                    notification_id=str(delivery["notification_id"]),
                    payload_hash=body_hash,
                )
                signed = True
        if channel == "email":
            response_status, response_body = _send_email_delivery(
                endpoint_url=endpoint_url,
                payload=outbound_payload,
                smtp_env_prefix=smtp_env_prefix,
                email_sender=email_sender,
            )
        elif requester is None:
            response = httpx.post(endpoint_url, content=body, headers=headers, timeout=timeout_seconds)
            response_status = response.status_code
            response_body = response.content[:4096]
        else:
            response_status, response_body = requester("POST", endpoint_url, headers, body, timeout_seconds)
        response_body_hash = runtime_notification_webhook_payload_hash(response_body or b"")
        if 200 <= int(response_status) < 300:
            repository.update_runtime_notification_delivery_status(
                RuntimeNotificationDeliveryStatusInput(
                    delivery_id=delivery_id,
                    status="delivered",
                    updated_by=updated_by,
                    response_status=int(response_status),
                    response_body_hash=response_body_hash,
                    reason="runtime notification delivery delivered",
                )
            )
            return {
                "processed": True,
                "status": "delivered",
                "delivery_id": delivery_id,
                "project_id": project_id,
                "attempt_count": attempt_count,
                "max_attempts": delivery_max_attempts,
                "response_status": int(response_status),
                "payload_hash": body_hash,
                "signed": signed,
                "signing_secret_env": signing_secret_env if signed else None,
                "signing_secret_key_id": signing_secret_key_id if signed else None,
                "channel": channel,
            }
        failed_status = _failed_status(attempt_count=attempt_count, max_attempts=delivery_max_attempts)
        next_attempt_at = _next_attempt_at(
            attempt_count=attempt_count,
            max_attempts=delivery_max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
        )
        repository.update_runtime_notification_delivery_status(
            RuntimeNotificationDeliveryStatusInput(
                delivery_id=delivery_id,
                status=failed_status,
                updated_by=updated_by,
                response_status=int(response_status),
                response_body_hash=response_body_hash,
                error_message=f"Delivery returned HTTP {response_status}",
                next_attempt_at=next_attempt_at,
                reason="runtime notification delivery failed",
            )
        )
        return {
            "processed": True,
            "status": failed_status,
            "delivery_id": delivery_id,
            "project_id": project_id,
            "attempt_count": attempt_count,
            "max_attempts": delivery_max_attempts,
            "response_status": int(response_status),
            "next_attempt_at": next_attempt_at.isoformat() if next_attempt_at else None,
            "payload_hash": body_hash,
            "signed": signed,
            "signing_secret_env": signing_secret_env if signed else None,
            "signing_secret_key_id": signing_secret_key_id if signed else None,
            "channel": channel,
        }
    except Exception as exc:
        failed_status = _failed_status(attempt_count=attempt_count, max_attempts=delivery_max_attempts)
        next_attempt_at = _next_attempt_at(
            attempt_count=attempt_count,
            max_attempts=delivery_max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
        )
        repository.update_runtime_notification_delivery_status(
            RuntimeNotificationDeliveryStatusInput(
                delivery_id=delivery_id,
                status=failed_status,
                updated_by=updated_by,
                error_message=str(exc),
                next_attempt_at=next_attempt_at,
                reason="runtime notification delivery raised exception",
            )
        )
        return {
            "processed": True,
            "status": failed_status,
            "delivery_id": delivery_id,
            "project_id": project_id,
            "attempt_count": attempt_count,
            "max_attempts": delivery_max_attempts,
            "next_attempt_at": next_attempt_at.isoformat() if next_attempt_at else None,
            "error_message": str(exc),
            "payload_hash": body_hash,
            "signed": signed,
            "signing_secret_env": signing_secret_env if signed else None,
            "signing_secret_key_id": signing_secret_key_id if signed else None,
            "channel": channel,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process queued GEO runtime notification deliveries")
    parser.add_argument("--max-deliveries", type=int, default=1, help="Maximum queued deliveries to process before exiting.")
    parser.add_argument("--worker-id", default=WORKER_ID, help="Actor id used in notification delivery audit events.")
    parser.add_argument("--max-attempts", type=int, default=3, help="Dead-letter a delivery after this many attempts.")
    parser.add_argument("--retry-backoff-seconds", type=int, default=120, help="Base delay before retrying failed deliveries.")
    parser.add_argument("--lease-seconds", type=int, default=300, help="Delivery lease duration before reclaim.")
    parser.add_argument("--timeout-seconds", type=float, default=5.0, help="Webhook HTTP timeout in seconds.")
    parser.add_argument(
        "--default-signing-secret-env",
        default=DEFAULT_SIGNING_SECRET_ENV,
        help="Optional default env var containing the outbound webhook HMAC secret.",
    )
    parser.add_argument(
        "--secondary-signing-secret-env",
        default=DEFAULT_SECONDARY_SIGNING_SECRET_ENV,
        help="Optional previous env var name documented for receiver-side dual-secret rotation.",
    )
    parser.add_argument(
        "--smtp-env-prefix",
        default=DEFAULT_SMTP_ENV_PREFIX,
        help="Env var prefix for email delivery SMTP settings.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    validate_runtime_schema_compatibility()
    max_deliveries = max(1, args.max_deliveries)
    repository: PostgresEvidenceRepository | None = None
    results: list[dict[str, Any]] = []
    try:
        repository = build_repository_from_env()
        for _ in range(max_deliveries):
            result = process_next_notification_delivery(
                repository=repository,
                updated_by=args.worker_id,
                max_attempts=args.max_attempts,
                retry_backoff_seconds=args.retry_backoff_seconds,
                lease_seconds=args.lease_seconds,
                timeout_seconds=args.timeout_seconds,
                default_signing_secret_env=args.default_signing_secret_env,
                smtp_env_prefix=args.smtp_env_prefix,
            )
            results.append(result)
            if result["status"] == "idle":
                break
    finally:
        if repository is not None:
            close_repository_connection(repository)
    print(
        json.dumps(
            {
                "worker": WORKER_ID,
                "processed_count": len(results),
                "signature_rotation": {
                    "active_secret_env": args.default_signing_secret_env,
                    "previous_secret_env": args.secondary_signing_secret_env,
                    "secret_material_logged": False,
                },
                "results": results,
            },
            default=str,
        )
    )


if __name__ == "__main__":
    main()
