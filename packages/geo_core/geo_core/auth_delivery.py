from __future__ import annotations

import base64
import binascii
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import format_datetime
from hashlib import sha256
from pathlib import Path
from typing import Mapping


AUTH_DELIVERY_MASTER_KEY_ENV = "GEO_AUTH_DELIVERY_MASTER_KEY"
AUTH_DELIVERY_MASTER_KEY_FILE_ENV = "GEO_AUTH_DELIVERY_MASTER_KEY_FILE"
AUTH_DELIVERY_KEY_ID_ENV = "GEO_AUTH_DELIVERY_KEY_ID"
AUTH_DELIVERY_PREVIOUS_KEYS_ENV = "GEO_AUTH_DELIVERY_PREVIOUS_KEYS"
AUTH_DELIVERY_PREVIOUS_KEYS_FILE_ENV = "GEO_AUTH_DELIVERY_PREVIOUS_KEYS_FILE"
AUTH_DELIVERY_RECOVERY_TTL_SECONDS_ENV = "GEO_AUTH_DELIVERY_RECOVERY_TTL_SECONDS"
AUTH_DELIVERY_MAX_REPLAY_ENV = "GEO_AUTH_DELIVERY_MAX_REPLAY"
RUNTIME_SESSION_COOKIE_SECURE_ENV = "GEO_RUNTIME_SESSION_COOKIE_SECURE"
DEFAULT_AUTH_DELIVERY_RECOVERY_TTL_SECONDS = 600
DEFAULT_AUTH_DELIVERY_MAX_REPLAY = 5


class AuthDeliveryError(ValueError):
    pass


@dataclass(frozen=True)
class FrozenAuthDelivery:
    cookie_headers: tuple[str, ...]
    absolute_session_expires_at: datetime

    def serialize(self) -> bytes:
        expires_at = _as_utc(self.absolute_session_expires_at)
        payload = {
            "absolute_session_expires_at": expires_at.isoformat().replace("+00:00", "Z"),
            "cookie_headers": list(self.cookie_headers),
            "schema_version": "auth_delivery_v1",
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")

    @classmethod
    def deserialize(cls, value: bytes) -> "FrozenAuthDelivery":
        try:
            payload = json.loads(value.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AuthDeliveryError("auth delivery payload is invalid") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != "auth_delivery_v1":
            raise AuthDeliveryError("auth delivery payload version is invalid")
        raw_headers = payload.get("cookie_headers")
        if not isinstance(raw_headers, list) or not raw_headers:
            raise AuthDeliveryError("auth delivery cookie headers are missing")
        cookie_headers = tuple(str(item) for item in raw_headers)
        if any(not item or "\r" in item or "\n" in item for item in cookie_headers):
            raise AuthDeliveryError("auth delivery cookie header is invalid")
        try:
            expires_at = datetime.fromisoformat(str(payload["absolute_session_expires_at"]).replace("Z", "+00:00"))
        except (KeyError, ValueError) as exc:
            raise AuthDeliveryError("auth delivery expiry is invalid") from exc
        return cls(cookie_headers=cookie_headers, absolute_session_expires_at=_as_utc(expires_at))


@dataclass(frozen=True)
class EncryptedAuthDelivery:
    ciphertext: bytes
    key_id: str
    nonce: bytes


class AuthDeliveryKeyring:
    def __init__(self, *, active_key_id: str, keys: Mapping[str, bytes]) -> None:
        normalized_key_id = active_key_id.strip()
        if not normalized_key_id:
            raise AuthDeliveryError("auth delivery active key id is required")
        normalized_keys = {str(key_id).strip(): bytes(key) for key_id, key in keys.items() if str(key_id).strip()}
        if normalized_key_id not in normalized_keys:
            raise AuthDeliveryError("auth delivery active key is missing from keyring")
        for key_id, key in normalized_keys.items():
            if len(key) != 32:
                raise AuthDeliveryError(f"auth delivery key {key_id} must be 32 bytes")
        self.active_key_id = normalized_key_id
        self._keys = normalized_keys

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "AuthDeliveryKeyring":
        runtime_env = os.environ if env is None else env
        active_key_id = runtime_env.get(AUTH_DELIVERY_KEY_ID_ENV, "").strip()
        active_key_raw = _secret_value(
            runtime_env,
            raw_field=AUTH_DELIVERY_MASTER_KEY_ENV,
            file_field=AUTH_DELIVERY_MASTER_KEY_FILE_ENV,
        )
        active_key = _decode_key(active_key_raw, field=AUTH_DELIVERY_MASTER_KEY_ENV)
        keys: dict[str, bytes] = {active_key_id: active_key} if active_key_id else {}
        previous_raw = _secret_value(
            runtime_env,
            raw_field=AUTH_DELIVERY_PREVIOUS_KEYS_ENV,
            file_field=AUTH_DELIVERY_PREVIOUS_KEYS_FILE_ENV,
            required=False,
        )
        if previous_raw:
            try:
                previous = json.loads(previous_raw)
            except json.JSONDecodeError as exc:
                raise AuthDeliveryError(f"{AUTH_DELIVERY_PREVIOUS_KEYS_ENV} must be a JSON object") from exc
            if not isinstance(previous, dict):
                raise AuthDeliveryError(f"{AUTH_DELIVERY_PREVIOUS_KEYS_ENV} must be a JSON object")
            for key_id, encoded_key in previous.items():
                keys[str(key_id)] = _decode_key(str(encoded_key), field=f"{AUTH_DELIVERY_PREVIOUS_KEYS_ENV}.{key_id}")
        return cls(active_key_id=active_key_id, keys=keys)

    def encrypt(self, delivery: FrozenAuthDelivery, *, attempt_id: str) -> EncryptedAuthDelivery:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ModuleNotFoundError as exc:
            raise AuthDeliveryError("cryptography is required for auth delivery encryption") from exc
        nonce = os.urandom(12)
        aad = _aad(attempt_id=attempt_id, key_id=self.active_key_id)
        ciphertext = AESGCM(self._keys[self.active_key_id]).encrypt(nonce, delivery.serialize(), aad)
        return EncryptedAuthDelivery(ciphertext=ciphertext, key_id=self.active_key_id, nonce=nonce)

    def decrypt(
        self,
        *,
        ciphertext: bytes,
        key_id: str,
        nonce: bytes,
        attempt_id: str,
    ) -> FrozenAuthDelivery:
        key = self._keys.get(key_id)
        if key is None:
            raise AuthDeliveryError("auth delivery key is unavailable")
        try:
            from cryptography.exceptions import InvalidTag
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ModuleNotFoundError as exc:
            raise AuthDeliveryError("cryptography is required for auth delivery encryption") from exc
        try:
            plaintext = AESGCM(key).decrypt(
                bytes(nonce),
                bytes(ciphertext),
                _aad(attempt_id=attempt_id, key_id=key_id),
            )
        except InvalidTag as exc:
            raise AuthDeliveryError("auth delivery authentication failed") from exc
        return FrozenAuthDelivery.deserialize(plaintext)


def build_frozen_auth_delivery(
    *,
    session_cookie_name: str,
    session_token: str,
    csrf_cookie_name: str,
    csrf_token: str,
    session_expires_at: datetime,
    secure: bool,
    path: str = "/",
) -> FrozenAuthDelivery:
    expires_at = _as_utc(session_expires_at)
    session_cookie = serialize_set_cookie(
        name=session_cookie_name,
        value=session_token,
        expires_at=expires_at,
        max_age=None,
        secure=secure,
        http_only=True,
        same_site="lax",
        path=path,
    )
    csrf_cookie = serialize_set_cookie(
        name=csrf_cookie_name,
        value=csrf_token,
        expires_at=expires_at,
        max_age=None,
        secure=secure,
        http_only=False,
        same_site="lax",
        path=path,
    )
    return FrozenAuthDelivery(
        cookie_headers=(session_cookie, csrf_cookie),
        absolute_session_expires_at=expires_at,
    )


def serialize_set_cookie(
    *,
    name: str,
    value: str,
    expires_at: datetime,
    max_age: int | None,
    secure: bool,
    http_only: bool,
    same_site: str,
    path: str,
) -> str:
    _validate_cookie_part(name, field="cookie name")
    _validate_cookie_part(value, field="cookie value")
    if not path.startswith("/") or ";" in path or "\r" in path or "\n" in path:
        raise AuthDeliveryError("cookie path is invalid")
    same_site_value = same_site.strip().lower()
    if same_site_value not in {"lax", "strict", "none"}:
        raise AuthDeliveryError("cookie SameSite value is invalid")
    parts = [
        f"{name}={value}",
        f"Path={path}",
        f"Expires={format_datetime(_as_utc(expires_at), usegmt=True)}",
    ]
    if max_age is not None:
        parts.insert(2, f"Max-Age={max(0, int(max_age))}")
    if http_only:
        parts.append("HttpOnly")
    if secure:
        parts.append("Secure")
    parts.append(f"SameSite={same_site_value}")
    return "; ".join(parts)


def auth_delivery_recovery_ttl_seconds(env: Mapping[str, str] | None = None) -> int:
    runtime_env = os.environ if env is None else env
    return _bounded_positive_int(
        runtime_env.get(AUTH_DELIVERY_RECOVERY_TTL_SECONDS_ENV),
        default=DEFAULT_AUTH_DELIVERY_RECOVERY_TTL_SECONDS,
        minimum=60,
        maximum=3600,
        field=AUTH_DELIVERY_RECOVERY_TTL_SECONDS_ENV,
    )


def auth_delivery_max_replay(env: Mapping[str, str] | None = None) -> int:
    runtime_env = os.environ if env is None else env
    return _bounded_positive_int(
        runtime_env.get(AUTH_DELIVERY_MAX_REPLAY_ENV),
        default=DEFAULT_AUTH_DELIVERY_MAX_REPLAY,
        minimum=1,
        maximum=20,
        field=AUTH_DELIVERY_MAX_REPLAY_ENV,
    )


def auth_session_cookie_secure(env: Mapping[str, str] | None = None) -> bool:
    runtime_env = os.environ if env is None else env
    value = runtime_env.get(RUNTIME_SESSION_COOKIE_SECURE_ENV, "1").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise AuthDeliveryError(f"{RUNTIME_SESSION_COOKIE_SECURE_ENV} must be an explicit boolean")


def delivery_ciphertext_fingerprint(ciphertext: bytes) -> str:
    return sha256(bytes(ciphertext)).hexdigest()


def _decode_key(value: str, *, field: str) -> bytes:
    encoded = value.strip()
    if not encoded:
        raise AuthDeliveryError(f"{field} is required")
    unpadded = encoded.rstrip("=")
    if not unpadded or "=" in unpadded or len(encoded) - len(unpadded) > 2:
        raise AuthDeliveryError(f"{field} must be URL-safe base64")
    padding = "=" * (-len(unpadded) % 4)
    try:
        decoded = base64.b64decode(
            (unpadded + padding).encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, UnicodeEncodeError, ValueError, TypeError) as exc:
        raise AuthDeliveryError(f"{field} must be URL-safe base64") from exc
    if base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != unpadded:
        raise AuthDeliveryError(f"{field} must be canonical URL-safe base64")
    if len(decoded) != 32:
        raise AuthDeliveryError(f"{field} must decode to 32 bytes")
    return decoded


def _secret_value(
    env: Mapping[str, str],
    *,
    raw_field: str,
    file_field: str,
    required: bool = True,
) -> str:
    raw_value = env.get(raw_field, "").strip()
    file_value = env.get(file_field, "").strip()
    if raw_value and file_value:
        raise AuthDeliveryError(f"{raw_field} and {file_field} cannot both be configured")
    if raw_value:
        return raw_value
    if file_value:
        try:
            return Path(file_value).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            raise AuthDeliveryError(f"{file_field} could not be read") from exc
    if required:
        raise AuthDeliveryError(f"{raw_field} or {file_field} is required")
    return ""


def _aad(*, attempt_id: str, key_id: str) -> bytes:
    return f"auth-delivery-v1\0{attempt_id}\0{key_id}".encode("ascii")


def _validate_cookie_part(value: str, *, field: str) -> None:
    if not value or any(char in value for char in (";", "\r", "\n", "\x00")):
        raise AuthDeliveryError(f"{field} is invalid")


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def _bounded_positive_int(
    value: str | None,
    *,
    default: int,
    minimum: int,
    maximum: int,
    field: str,
) -> int:
    try:
        parsed = int((value or str(default)).strip())
    except ValueError as exc:
        raise AuthDeliveryError(f"{field} must be an integer") from exc
    if parsed < minimum or parsed > maximum:
        raise AuthDeliveryError(f"{field} must be between {minimum} and {maximum}")
    return parsed
