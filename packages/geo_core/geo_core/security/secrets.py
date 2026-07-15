from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


CONNECTOR_SECRET_MASTER_KEY_ENV = "GEO_CONNECTOR_SECRET_MASTER_KEY"
CONNECTOR_SECRET_ENCRYPTION_VERSION = "connector_secret_fernet_v1"
REDACTED_VALUE = "[redacted]"
SECRET_FIELD_HINTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "client_secret",
    "cookie",
    "credential",
    "invite_token",
    "password",
    "provider_key",
    "raw_secret",
    "secret",
    "session",
    "token",
)


class SecretStoreError(ValueError):
    pass


@dataclass(frozen=True)
class EncryptedSecret:
    secret_ref: str
    encrypted_secret: str
    encryption_version: str
    key_hint: str
    secret_hash: str
    masked_value: str


def _master_key_bytes(master_key: str | None = None) -> bytes:
    value = (master_key if master_key is not None else os.getenv(CONNECTOR_SECRET_MASTER_KEY_ENV, "")).strip()
    if not value:
        raise SecretStoreError(f"{CONNECTOR_SECRET_MASTER_KEY_ENV} is required for connector secret storage")
    return hashlib.sha256(value.encode("utf-8")).digest()


def _fernet_for_key(key: bytes) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(key))


def _secret_ref(*, project_id: str, provider: str, purpose: str, secret_hash: str, key: bytes) -> str:
    payload = "|".join((project_id.strip(), provider.strip().lower(), purpose.strip().lower(), secret_hash))
    digest = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"connector-secret:{digest[:32]}"


def mask_secret(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return ""
    if len(normalized) <= 8:
        return f"{normalized[0]}***{normalized[-1]}"
    return f"{normalized[:4]}...{normalized[-4:]}"


def encrypt_connector_secret(
    *,
    project_id: str,
    provider: str,
    purpose: str,
    raw_secret: str,
    master_key: str | None = None,
) -> EncryptedSecret:
    normalized_secret = raw_secret.strip()
    if not normalized_secret:
        raise SecretStoreError("raw_secret is required")
    key = _master_key_bytes(master_key)
    plaintext = normalized_secret.encode("utf-8")
    envelope = {
        "v": CONNECTOR_SECRET_ENCRYPTION_VERSION,
        "token": _fernet_for_key(key).encrypt(plaintext).decode("ascii"),
    }
    secret_hash = hashlib.sha256(plaintext).hexdigest()
    key_hint = hashlib.sha256(key).hexdigest()[:12]
    return EncryptedSecret(
        secret_ref=_secret_ref(
            project_id=project_id,
            provider=provider,
            purpose=purpose,
            secret_hash=secret_hash,
            key=key,
        ),
        encrypted_secret=json.dumps(envelope, sort_keys=True, separators=(",", ":")),
        encryption_version=CONNECTOR_SECRET_ENCRYPTION_VERSION,
        key_hint=key_hint,
        secret_hash=secret_hash,
        masked_value=mask_secret(normalized_secret),
    )


def decrypt_connector_secret(*, encrypted_secret: str, master_key: str | None = None) -> str:
    key = _master_key_bytes(master_key)
    try:
        envelope = json.loads(encrypted_secret)
        if envelope.get("v") != CONNECTOR_SECRET_ENCRYPTION_VERSION:
            raise SecretStoreError("unsupported connector secret encryption version")
        token = str(envelope["token"]).encode("ascii")
    except (KeyError, TypeError, ValueError) as exc:
        raise SecretStoreError("encrypted connector secret envelope is invalid") from exc
    try:
        return _fernet_for_key(key).decrypt(token).decode("utf-8")
    except InvalidToken as exc:
        raise SecretStoreError("encrypted connector secret token is invalid") from exc


def is_secret_field_name(name: str) -> bool:
    normalized = name.strip().lower().replace("-", "_")
    if normalized in {"completion_tokens", "llm_tokens", "prompt_tokens", "total_tokens"}:
        return False
    return any(hint in normalized for hint in SECRET_FIELD_HINTS)


def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: REDACTED_VALUE if is_secret_field_name(str(key)) else redact_secrets(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(item) for item in value)
    return value


def redact_secret_text(value: bytes | str, *, content_type: str | None = None) -> bytes | str:
    is_bytes = isinstance(value, bytes)
    text = value.decode("utf-8", errors="replace") if is_bytes else value
    if "json" in (content_type or "").lower():
        try:
            payload = json.loads(text)
        except ValueError:
            pass
        else:
            redacted = json.dumps(redact_secrets(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            return redacted.encode("utf-8") if is_bytes else redacted
    redacted_text = re_redact_secret_assignments(text)
    return redacted_text.encode("utf-8") if is_bytes else redacted_text


def re_redact_secret_assignments(text: str) -> str:
    import re

    field_pattern = r"(api[_-]?key|authorization|bearer|client[_-]?secret|cookie|invite[_-]?token|password|provider[_-]?key|raw[_-]?secret|secret|session[_-]?token|token)"
    redacted = re.sub(
        rf"(?i)({field_pattern}\s*[:=]\s*)([^,\s&]+)",
        lambda match: f"{match.group(1)}{REDACTED_VALUE}",
        text,
    )
    provider_key_prefixes = (
        "s" + "k-",
        "p" + "plx-",
        "geo" + "-invite-",
        "ai" + "za",
    )
    provider_key_pattern = "|".join(
        f"{re.escape(prefix)}[a-z0-9._-]+" for prefix in provider_key_prefixes
    )
    return re.sub(
        rf"(?i)\b({provider_key_pattern})\b",
        REDACTED_VALUE,
        redacted,
    )
