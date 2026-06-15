from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


SENDGRID_EVENT_WEBHOOK_SIGNATURE_HEADER = "x-twilio-email-event-webhook-signature"
SENDGRID_EVENT_WEBHOOK_TIMESTAMP_HEADER = "x-twilio-email-event-webhook-timestamp"
POSTMARK_WEBHOOK_AUTHORIZATION_HEADER = "authorization"


@dataclass(frozen=True)
class RuntimeNotificationEmailProviderSignatureVerification:
    provider: str
    valid: bool
    status: str
    method: str
    reason: str
    payload_hash: str
    checked_signature_count: int = 0
    age_seconds: int | None = None

    def metadata(self) -> dict[str, object]:
        metadata: dict[str, object] = {
            "provider_native_signature_status": self.status,
            "provider_native_signature_method": self.method,
            "provider_native_signature_reason": self.reason,
            "provider_native_signature_checked_count": self.checked_signature_count,
            "provider_native_signature_payload_hash": self.payload_hash,
        }
        if self.age_seconds is not None:
            metadata["provider_native_signature_age_seconds"] = self.age_seconds
        return metadata


def verify_runtime_notification_email_provider_signature(
    *,
    provider: str,
    headers: Mapping[str, str],
    body: bytes,
    payload: Any | None = None,
    sendgrid_public_key: str = "",
    mailgun_signing_key: str = "",
    postmark_basic_username: str = "",
    postmark_basic_password: str = "",
    tolerance_seconds: int = 300,
    now: datetime | None = None,
) -> RuntimeNotificationEmailProviderSignatureVerification:
    normalized_provider = provider.strip().lower()
    normalized_headers = {str(key).lower(): str(value) for key, value in headers.items()}
    payload_hash = hashlib.sha256(body).hexdigest()
    if normalized_provider == "sendgrid":
        return _verify_sendgrid_signature(
            headers=normalized_headers,
            body=body,
            public_key=sendgrid_public_key,
            payload_hash=payload_hash,
            tolerance_seconds=tolerance_seconds,
            now=now,
        )
    if normalized_provider == "mailgun":
        return _verify_mailgun_signature(
            payload=payload,
            signing_key=mailgun_signing_key,
            payload_hash=payload_hash,
            tolerance_seconds=tolerance_seconds,
            now=now,
        )
    if normalized_provider == "postmark":
        return _verify_postmark_basic_auth(
            headers=normalized_headers,
            username=postmark_basic_username,
            password=postmark_basic_password,
            payload_hash=payload_hash,
        )
    return RuntimeNotificationEmailProviderSignatureVerification(
        provider=normalized_provider,
        valid=False,
        status="unsupported",
        method="unsupported",
        reason="unsupported_provider",
        payload_hash=payload_hash,
    )


def _verify_sendgrid_signature(
    *,
    headers: Mapping[str, str],
    body: bytes,
    public_key: str,
    payload_hash: str,
    tolerance_seconds: int,
    now: datetime | None,
) -> RuntimeNotificationEmailProviderSignatureVerification:
    method = "sendgrid_ecdsa_sha256"
    key_text = public_key.strip()
    if not key_text:
        return _not_configured(provider="sendgrid", method=method, payload_hash=payload_hash)
    signature = headers.get(SENDGRID_EVENT_WEBHOOK_SIGNATURE_HEADER, "").strip()
    timestamp = headers.get(SENDGRID_EVENT_WEBHOOK_TIMESTAMP_HEADER, "").strip()
    if not signature or not timestamp:
        return _invalid(
            provider="sendgrid",
            method=method,
            reason="missing_signature_headers",
            payload_hash=payload_hash,
            checked_signature_count=1,
        )
    age = _timestamp_age_seconds(timestamp, now=now)
    if age is None:
        return _invalid(
            provider="sendgrid",
            method=method,
            reason="invalid_timestamp",
            payload_hash=payload_hash,
            checked_signature_count=1,
        )
    if tolerance_seconds > 0 and abs(age) > tolerance_seconds:
        return _invalid(
            provider="sendgrid",
            method=method,
            reason="timestamp_outside_tolerance",
            payload_hash=payload_hash,
            checked_signature_count=1,
            age_seconds=age,
        )
    try:
        public_key_obj = _load_sendgrid_public_key(key_text)
        signature_bytes = base64.b64decode(signature)
        public_key_obj.verify(signature_bytes, timestamp.encode("utf-8") + body, ec.ECDSA(hashes.SHA256()))
    except (ValueError, TypeError, InvalidSignature):
        return _invalid(
            provider="sendgrid",
            method=method,
            reason="signature_mismatch",
            payload_hash=payload_hash,
            checked_signature_count=1,
            age_seconds=age,
        )
    return _verified(
        provider="sendgrid",
        method=method,
        payload_hash=payload_hash,
        checked_signature_count=1,
        age_seconds=age,
    )


def _verify_mailgun_signature(
    *,
    payload: Any | None,
    signing_key: str,
    payload_hash: str,
    tolerance_seconds: int,
    now: datetime | None,
) -> RuntimeNotificationEmailProviderSignatureVerification:
    method = "mailgun_hmac_sha256"
    key_text = signing_key.strip()
    if not key_text:
        return _not_configured(provider="mailgun", method=method, payload_hash=payload_hash)
    signature_payload = _mailgun_signature_payload(payload)
    timestamp = _clean_text(signature_payload.get("timestamp"))
    token = _clean_text(signature_payload.get("token"))
    signature = _clean_text(signature_payload.get("signature"))
    if not timestamp or not token or not signature:
        return _invalid(
            provider="mailgun",
            method=method,
            reason="missing_signature_fields",
            payload_hash=payload_hash,
            checked_signature_count=1,
        )
    age = _timestamp_age_seconds(timestamp, now=now)
    if age is None:
        return _invalid(
            provider="mailgun",
            method=method,
            reason="invalid_timestamp",
            payload_hash=payload_hash,
            checked_signature_count=1,
        )
    if tolerance_seconds > 0 and abs(age) > tolerance_seconds:
        return _invalid(
            provider="mailgun",
            method=method,
            reason="timestamp_outside_tolerance",
            payload_hash=payload_hash,
            checked_signature_count=1,
            age_seconds=age,
        )
    expected = hmac.new(key_text.encode("utf-8"), f"{timestamp}{token}".encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return _invalid(
            provider="mailgun",
            method=method,
            reason="signature_mismatch",
            payload_hash=payload_hash,
            checked_signature_count=1,
            age_seconds=age,
        )
    return _verified(
        provider="mailgun",
        method=method,
        payload_hash=payload_hash,
        checked_signature_count=1,
        age_seconds=age,
    )


def _verify_postmark_basic_auth(
    *,
    headers: Mapping[str, str],
    username: str,
    password: str,
    payload_hash: str,
) -> RuntimeNotificationEmailProviderSignatureVerification:
    method = "postmark_basic_auth"
    if not username.strip() and not password.strip():
        return _not_configured(provider="postmark", method=method, payload_hash=payload_hash)
    if not username.strip() or not password.strip():
        return _invalid(
            provider="postmark",
            method=method,
            reason="config_incomplete",
            payload_hash=payload_hash,
            checked_signature_count=1,
        )
    header = headers.get(POSTMARK_WEBHOOK_AUTHORIZATION_HEADER, "").strip()
    if not header.lower().startswith("basic "):
        return _invalid(
            provider="postmark",
            method=method,
            reason="missing_basic_auth",
            payload_hash=payload_hash,
            checked_signature_count=1,
        )
    try:
        decoded = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return _invalid(
            provider="postmark",
            method=method,
            reason="invalid_basic_auth",
            payload_hash=payload_hash,
            checked_signature_count=1,
        )
    expected = f"{username}:{password}"
    if not hmac.compare_digest(decoded, expected):
        return _invalid(
            provider="postmark",
            method=method,
            reason="basic_auth_mismatch",
            payload_hash=payload_hash,
            checked_signature_count=1,
        )
    return _verified(
        provider="postmark",
        method=method,
        payload_hash=payload_hash,
        checked_signature_count=1,
    )


def _load_sendgrid_public_key(key_text: str) -> ec.EllipticCurvePublicKey:
    key_bytes = key_text.encode("utf-8")
    if "BEGIN PUBLIC KEY" in key_text:
        loaded = serialization.load_pem_public_key(key_bytes)
    else:
        loaded = serialization.load_der_public_key(base64.b64decode(key_text))
    if not isinstance(loaded, ec.EllipticCurvePublicKey):
        raise ValueError("sendgrid public key must be an ECDSA public key")
    return loaded


def _mailgun_signature_payload(payload: Any | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    signature = payload.get("signature")
    if isinstance(signature, dict):
        return signature
    return payload


def _timestamp_age_seconds(value: str, *, now: datetime | None) -> int | None:
    try:
        timestamp = int(float(value))
    except ValueError:
        return None
    current = int((now or datetime.now(UTC)).timestamp())
    return current - timestamp


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\r", "\n").split()).strip()


def _not_configured(
    *,
    provider: str,
    method: str,
    payload_hash: str,
) -> RuntimeNotificationEmailProviderSignatureVerification:
    return RuntimeNotificationEmailProviderSignatureVerification(
        provider=provider,
        valid=True,
        status="not_configured",
        method=method,
        reason="provider_native_signature_not_configured",
        payload_hash=payload_hash,
    )


def _verified(
    *,
    provider: str,
    method: str,
    payload_hash: str,
    checked_signature_count: int,
    age_seconds: int | None = None,
) -> RuntimeNotificationEmailProviderSignatureVerification:
    return RuntimeNotificationEmailProviderSignatureVerification(
        provider=provider,
        valid=True,
        status="verified",
        method=method,
        reason="signature_verified",
        payload_hash=payload_hash,
        checked_signature_count=checked_signature_count,
        age_seconds=age_seconds,
    )


def _invalid(
    *,
    provider: str,
    method: str,
    reason: str,
    payload_hash: str,
    checked_signature_count: int,
    age_seconds: int | None = None,
) -> RuntimeNotificationEmailProviderSignatureVerification:
    return RuntimeNotificationEmailProviderSignatureVerification(
        provider=provider,
        valid=False,
        status="invalid",
        method=method,
        reason=reason,
        payload_hash=payload_hash,
        checked_signature_count=checked_signature_count,
        age_seconds=age_seconds,
    )
