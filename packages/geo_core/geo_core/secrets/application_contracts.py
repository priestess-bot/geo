"""Protected Secret Store commands and keyed idempotency fingerprints."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import hmac
import json
from typing import ClassVar, Never
from uuid import UUID

from .errors import (
    SecretConfigurationError,
    SecretContractError,
    SecretSerializationRejected,
)
from .models import SecretValue, SecretVersionHandle
from .ports import SecretOperation, SecretPrincipal


class _ProtectedCommand:
    __secret_bearing__: ClassVar[bool] = True

    def __repr__(self) -> str:
        return f"{type(self).__name__}([REDACTED COMMAND])"

    def __reduce__(self) -> Never:
        raise SecretSerializationRejected("Secret Store commands cannot be serialized")


@dataclass(frozen=True, kw_only=True, repr=False)
class CreateSecretCommand(_ProtectedCommand):
    principal: SecretPrincipal
    reference_id: UUID
    purpose: str
    value: SecretValue
    idempotency_key: str
    expected_version: int = 0


@dataclass(frozen=True, kw_only=True, repr=False)
class VerifySecretCommand(_ProtectedCommand):
    principal: SecretPrincipal
    handle: SecretVersionHandle
    idempotency_key: str
    expected_version: int


@dataclass(frozen=True, kw_only=True, repr=False)
class StageSecretRotationCommand(_ProtectedCommand):
    principal: SecretPrincipal
    reference_id: UUID
    purpose: str
    value: SecretValue
    idempotency_key: str
    expected_version: int


@dataclass(frozen=True, kw_only=True, repr=False)
class ActivateSecretVersionCommand(_ProtectedCommand):
    principal: SecretPrincipal
    handle: SecretVersionHandle
    idempotency_key: str
    expected_version: int


@dataclass(frozen=True, kw_only=True, repr=False)
class RevokeSecretVersionCommand(_ProtectedCommand):
    principal: SecretPrincipal
    handle: SecretVersionHandle
    idempotency_key: str
    expected_version: int


@dataclass(frozen=True, kw_only=True, repr=False)
class ResolveSecretCommand(_ProtectedCommand):
    principal: SecretPrincipal
    handle: SecretVersionHandle
    idempotency_key: str


class SecretRequestHasher:
    """Keyed fingerprints prevent plaintext secrets and raw idempotency keys at rest."""

    __secret_bearing__ = True
    __slots__ = ("__key",)

    def __init__(self, key: bytes) -> None:
        copied = bytes(key)
        if len(copied) != 32:
            raise SecretConfigurationError("Secret Store request hash key must be 256 bits")
        self.__key = copied

    def __repr__(self) -> str:
        return "SecretRequestHasher([REDACTED])"

    def __reduce__(self) -> Never:
        raise SecretSerializationRejected("Secret Store request hashers cannot be serialized")

    def idempotency_key_hash(self, value: str) -> str:
        if (
            not isinstance(value, str)
            or not 8 <= len(value) <= 256
            or any(character.isspace() or ord(character) < 32 for character in value)
        ):
            raise SecretContractError("Idempotency-Key format is invalid")
        return hmac.new(
            self.__key,
            b"geo-secret-idempotency-key-v1\0" + value.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def request_hash(
        self,
        *,
        operation: SecretOperation,
        metadata: Mapping[str, object],
        value: SecretValue | None = None,
    ) -> str:
        encoded = json.dumps(
            {"operation": operation.value, "metadata": metadata},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        digest = hmac.new(
            self.__key,
            b"geo-secret-command-request-v1\0" + encoded,
            hashlib.sha256,
        )
        if value is not None:
            digest.update(b"\0secret-value\0")
            digest.update(value.reveal_bytes())
        return digest.hexdigest()
