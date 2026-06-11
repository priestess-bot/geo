from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Mapping


RUNTIME_NOTIFICATION_WEBHOOK_SIGNATURE_VERSION = "runtime_notification_webhook_hmac_sha256_v1"
RUNTIME_NOTIFICATION_WEBHOOK_SIGNATURE_INPUT = "timestamp.delivery_id.notification_id.payload_sha256"
RUNTIME_NOTIFICATION_WEBHOOK_SIGNATURE_HEADER = "x-geno-signature"
RUNTIME_NOTIFICATION_WEBHOOK_SIGNATURE_TIMESTAMP_HEADER = "x-geno-signature-timestamp"
RUNTIME_NOTIFICATION_WEBHOOK_SIGNATURE_VERSION_HEADER = "x-geno-signature-version"
RUNTIME_NOTIFICATION_WEBHOOK_SIGNATURE_INPUT_HEADER = "x-geno-signature-input"
RUNTIME_NOTIFICATION_WEBHOOK_PAYLOAD_HASH_HEADER = "x-geno-payload-sha256"
RUNTIME_NOTIFICATION_WEBHOOK_DELIVERY_ID_HEADER = "x-geno-delivery-id"
RUNTIME_NOTIFICATION_WEBHOOK_NOTIFICATION_ID_HEADER = "x-geno-notification-id"


@dataclass(frozen=True)
class RuntimeNotificationWebhookSignatureVerification:
    valid: bool
    reason: str
    payload_hash: str | None = None
    expected_signature: str | None = None
    signature_timestamp: int | None = None
    age_seconds: int | None = None


def runtime_notification_webhook_payload_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def runtime_notification_webhook_signature_input(
    *,
    timestamp: str,
    delivery_id: str,
    notification_id: str,
    payload_hash: str,
) -> str:
    return f"{timestamp}.{delivery_id}.{notification_id}.{payload_hash}"


def sign_runtime_notification_webhook(
    *,
    secret: str,
    delivery_id: str,
    notification_id: str,
    payload_hash: str,
    now: datetime | None = None,
) -> dict[str, str]:
    timestamp = str(int((now or datetime.now(UTC)).timestamp()))
    signature_input = runtime_notification_webhook_signature_input(
        timestamp=timestamp,
        delivery_id=delivery_id,
        notification_id=notification_id,
        payload_hash=payload_hash,
    )
    signature = hmac.new(secret.encode("utf-8"), signature_input.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        RUNTIME_NOTIFICATION_WEBHOOK_SIGNATURE_HEADER: f"sha256={signature}",
        RUNTIME_NOTIFICATION_WEBHOOK_SIGNATURE_TIMESTAMP_HEADER: timestamp,
        RUNTIME_NOTIFICATION_WEBHOOK_SIGNATURE_VERSION_HEADER: RUNTIME_NOTIFICATION_WEBHOOK_SIGNATURE_VERSION,
        RUNTIME_NOTIFICATION_WEBHOOK_SIGNATURE_INPUT_HEADER: RUNTIME_NOTIFICATION_WEBHOOK_SIGNATURE_INPUT,
    }


def verify_runtime_notification_webhook_signature(
    *,
    headers: Mapping[str, str],
    body: bytes,
    secret: str,
    tolerance_seconds: int = 300,
    now: datetime | None = None,
) -> RuntimeNotificationWebhookSignatureVerification:
    normalized_headers = {str(key).lower(): str(value) for key, value in headers.items()}
    if not secret:
        return RuntimeNotificationWebhookSignatureVerification(valid=False, reason="missing_secret")

    signature = normalized_headers.get(RUNTIME_NOTIFICATION_WEBHOOK_SIGNATURE_HEADER)
    timestamp = normalized_headers.get(RUNTIME_NOTIFICATION_WEBHOOK_SIGNATURE_TIMESTAMP_HEADER)
    version = normalized_headers.get(RUNTIME_NOTIFICATION_WEBHOOK_SIGNATURE_VERSION_HEADER)
    signature_input_name = normalized_headers.get(RUNTIME_NOTIFICATION_WEBHOOK_SIGNATURE_INPUT_HEADER)
    delivery_id = normalized_headers.get(RUNTIME_NOTIFICATION_WEBHOOK_DELIVERY_ID_HEADER)
    notification_id = normalized_headers.get(RUNTIME_NOTIFICATION_WEBHOOK_NOTIFICATION_ID_HEADER)
    payload_hash = normalized_headers.get(RUNTIME_NOTIFICATION_WEBHOOK_PAYLOAD_HASH_HEADER)
    missing = [
        name
        for name, value in (
            (RUNTIME_NOTIFICATION_WEBHOOK_SIGNATURE_HEADER, signature),
            (RUNTIME_NOTIFICATION_WEBHOOK_SIGNATURE_TIMESTAMP_HEADER, timestamp),
            (RUNTIME_NOTIFICATION_WEBHOOK_SIGNATURE_VERSION_HEADER, version),
            (RUNTIME_NOTIFICATION_WEBHOOK_SIGNATURE_INPUT_HEADER, signature_input_name),
            (RUNTIME_NOTIFICATION_WEBHOOK_DELIVERY_ID_HEADER, delivery_id),
            (RUNTIME_NOTIFICATION_WEBHOOK_NOTIFICATION_ID_HEADER, notification_id),
            (RUNTIME_NOTIFICATION_WEBHOOK_PAYLOAD_HASH_HEADER, payload_hash),
        )
        if not value
    ]
    if missing:
        return RuntimeNotificationWebhookSignatureVerification(
            valid=False,
            reason=f"missing_header:{','.join(missing)}",
        )
    if version != RUNTIME_NOTIFICATION_WEBHOOK_SIGNATURE_VERSION:
        return RuntimeNotificationWebhookSignatureVerification(valid=False, reason="unsupported_signature_version")
    if signature_input_name != RUNTIME_NOTIFICATION_WEBHOOK_SIGNATURE_INPUT:
        return RuntimeNotificationWebhookSignatureVerification(valid=False, reason="unsupported_signature_input")
    if not signature or not signature.startswith("sha256="):
        return RuntimeNotificationWebhookSignatureVerification(valid=False, reason="invalid_signature_format")

    try:
        timestamp_int = int(timestamp or "")
    except ValueError:
        return RuntimeNotificationWebhookSignatureVerification(valid=False, reason="invalid_timestamp")

    current_timestamp = int((now or datetime.now(UTC)).timestamp())
    age_seconds = current_timestamp - timestamp_int
    if abs(age_seconds) > max(0, int(tolerance_seconds)):
        return RuntimeNotificationWebhookSignatureVerification(
            valid=False,
            reason="timestamp_outside_tolerance",
            signature_timestamp=timestamp_int,
            age_seconds=age_seconds,
        )

    actual_payload_hash = runtime_notification_webhook_payload_hash(body)
    if payload_hash != actual_payload_hash:
        return RuntimeNotificationWebhookSignatureVerification(
            valid=False,
            reason="payload_hash_mismatch",
            payload_hash=actual_payload_hash,
            signature_timestamp=timestamp_int,
            age_seconds=age_seconds,
        )

    expected_signature = sign_runtime_notification_webhook(
        secret=secret,
        delivery_id=delivery_id or "",
        notification_id=notification_id or "",
        payload_hash=actual_payload_hash,
        now=datetime.fromtimestamp(timestamp_int, UTC),
    )[RUNTIME_NOTIFICATION_WEBHOOK_SIGNATURE_HEADER]
    if not hmac.compare_digest(signature, expected_signature):
        return RuntimeNotificationWebhookSignatureVerification(
            valid=False,
            reason="signature_mismatch",
            payload_hash=actual_payload_hash,
            expected_signature=expected_signature,
            signature_timestamp=timestamp_int,
            age_seconds=age_seconds,
        )
    return RuntimeNotificationWebhookSignatureVerification(
        valid=True,
        reason="ok",
        payload_hash=actual_payload_hash,
        expected_signature=expected_signature,
        signature_timestamp=timestamp_int,
        age_seconds=age_seconds,
    )
