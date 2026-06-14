from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_TOKEN_VERSION = "runtime_notification_email_preference_token_hmac_sha256_v1"
RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_UNSUBSCRIBE_ACTION = "unsubscribe"


@dataclass(frozen=True)
class RuntimeNotificationEmailPreferenceTokenClaims:
    action: str
    project_id: str
    delivery_id: str
    notification_id: str
    subscription_id: str
    recipient_hash: str
    issued_at: int
    expires_at: int
    version: str = RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_TOKEN_VERSION


@dataclass(frozen=True)
class RuntimeNotificationEmailPreferenceTokenVerification:
    valid: bool
    reason: str
    token_hash: str
    claims: RuntimeNotificationEmailPreferenceTokenClaims | None = None


def runtime_notification_email_preference_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _base64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _canonical_claims_payload(claims: RuntimeNotificationEmailPreferenceTokenClaims) -> bytes:
    return json.dumps(claims.__dict__, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _claims_from_payload(payload: dict[str, Any]) -> RuntimeNotificationEmailPreferenceTokenClaims:
    return RuntimeNotificationEmailPreferenceTokenClaims(
        version=str(payload.get("version") or ""),
        action=str(payload.get("action") or ""),
        project_id=str(payload.get("project_id") or ""),
        delivery_id=str(payload.get("delivery_id") or ""),
        notification_id=str(payload.get("notification_id") or ""),
        subscription_id=str(payload.get("subscription_id") or ""),
        recipient_hash=str(payload.get("recipient_hash") or ""),
        issued_at=int(payload.get("issued_at") or 0),
        expires_at=int(payload.get("expires_at") or 0),
    )


def sign_runtime_notification_email_preference_token(
    *,
    secret: str,
    action: str = RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_UNSUBSCRIBE_ACTION,
    project_id: str,
    delivery_id: str,
    notification_id: str,
    subscription_id: str,
    recipient_hash: str,
    ttl_seconds: int = 2_592_000,
    now: datetime | None = None,
) -> str:
    if not secret:
        raise ValueError("email preference token secret is required")
    issued_at_datetime = now or datetime.now(UTC)
    issued_at = int(issued_at_datetime.timestamp())
    expires_at = int((issued_at_datetime + timedelta(seconds=max(1, int(ttl_seconds)))).timestamp())
    claims = RuntimeNotificationEmailPreferenceTokenClaims(
        action=action.strip().lower() or RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_UNSUBSCRIBE_ACTION,
        project_id=project_id.strip(),
        delivery_id=delivery_id.strip(),
        notification_id=notification_id.strip(),
        subscription_id=subscription_id.strip(),
        recipient_hash=recipient_hash.strip().lower(),
        issued_at=issued_at,
        expires_at=expires_at,
    )
    encoded_payload = _base64url_encode(_canonical_claims_payload(claims))
    signature = hmac.new(secret.encode("utf-8"), encoded_payload.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{encoded_payload}.{signature}"


def verify_runtime_notification_email_preference_token(
    *,
    secret: str,
    token: str,
    action: str = RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_UNSUBSCRIBE_ACTION,
    now: datetime | None = None,
) -> RuntimeNotificationEmailPreferenceTokenVerification:
    normalized_token = token.strip()
    token_hash = runtime_notification_email_preference_token_hash(normalized_token)
    if not secret:
        return RuntimeNotificationEmailPreferenceTokenVerification(valid=False, reason="missing_secret", token_hash=token_hash)
    parts = normalized_token.split(".")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return RuntimeNotificationEmailPreferenceTokenVerification(valid=False, reason="invalid_token_format", token_hash=token_hash)
    encoded_payload, signature = parts
    try:
        encoded_payload_bytes = encoded_payload.encode("ascii")
    except UnicodeEncodeError:
        return RuntimeNotificationEmailPreferenceTokenVerification(
            valid=False,
            reason="invalid_token_format",
            token_hash=token_hash,
        )
    expected_signature = hmac.new(secret.encode("utf-8"), encoded_payload_bytes, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        return RuntimeNotificationEmailPreferenceTokenVerification(valid=False, reason="signature_mismatch", token_hash=token_hash)
    try:
        payload = json.loads(_base64url_decode(encoded_payload).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        claims = _claims_from_payload(payload)
    except Exception:
        return RuntimeNotificationEmailPreferenceTokenVerification(valid=False, reason="invalid_payload", token_hash=token_hash)
    if claims.version != RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_TOKEN_VERSION:
        return RuntimeNotificationEmailPreferenceTokenVerification(valid=False, reason="unsupported_token_version", token_hash=token_hash)
    if claims.action != (action.strip().lower() or RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_UNSUBSCRIBE_ACTION):
        return RuntimeNotificationEmailPreferenceTokenVerification(valid=False, reason="action_mismatch", token_hash=token_hash)
    if len(claims.recipient_hash) != 64 or any(char not in "0123456789abcdef" for char in claims.recipient_hash):
        return RuntimeNotificationEmailPreferenceTokenVerification(valid=False, reason="invalid_recipient_hash", token_hash=token_hash)
    if claims.expires_at < int((now or datetime.now(UTC)).timestamp()):
        return RuntimeNotificationEmailPreferenceTokenVerification(
            valid=False,
            reason="token_expired",
            token_hash=token_hash,
            claims=claims,
        )
    return RuntimeNotificationEmailPreferenceTokenVerification(
        valid=True,
        reason="ok",
        token_hash=token_hash,
        claims=claims,
    )
