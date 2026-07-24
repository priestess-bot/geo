"""Immutable, persistence-neutral Secret Store contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import hmac
import re
from typing import Mapping, Never
from uuid import UUID

from .errors import SecretContractError, SecretSerializationRejected


ENVELOPE_ALGORITHM = "AES-256-GCM"
KEYRING_FORMAT = "geo-master-keyring-v1"
REDACTED = "[REDACTED]"
_PURPOSE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")


def require_uuid(value: UUID, label: str) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise SecretContractError(f"{label} must be a non-zero UUID")


def require_aware_datetime(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SecretContractError(f"{label} must include a timezone")


def require_positive_int(value: int, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise SecretContractError(f"{label} must be positive")


def require_purpose(value: str) -> None:
    if not isinstance(value, str) or _PURPOSE.fullmatch(value) is None:
        raise SecretContractError("secret purpose must be a stable lowercase identifier")


class SecretValue:
    """Short-lived plaintext with redacted display and denied serialization.

    Python cannot guarantee erasure of every allocator copy. Callers should keep
    this object local to a connection operation and discard it immediately.
    """

    __slots__ = ("__value",)

    def __init__(self, value: bytes | bytearray | memoryview | str) -> None:
        encoded = value.encode("utf-8") if isinstance(value, str) else bytes(value)
        if not encoded:
            raise SecretContractError("secret value must not be empty")
        self.__value = encoded

    def __repr__(self) -> str:
        return "SecretValue([REDACTED])"

    def __str__(self) -> str:
        return REDACTED

    def __reduce__(self) -> Never:
        raise SecretSerializationRejected("secret values cannot be serialized")

    def reveal_bytes(self) -> bytes:
        """Return a transient copy for the immediate provider call only."""

        return bytes(self.__value)

    def reveal_text(self, *, encoding: str = "utf-8") -> str:
        try:
            return self.__value.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            raise SecretContractError("secret value is not valid requested text") from None

    def matches(self, candidate: bytes | str) -> bool:
        encoded = candidate.encode("utf-8") if isinstance(candidate, str) else candidate
        return hmac.compare_digest(self.__value, encoded)


@dataclass(frozen=True, kw_only=True)
class SecretReference:
    id: UUID
    project_id: UUID
    purpose: str
    created_at: datetime

    def __post_init__(self) -> None:
        require_uuid(self.id, "secret reference ID")
        require_uuid(self.project_id, "secret project ID")
        require_purpose(self.purpose)
        require_aware_datetime(self.created_at, "secret reference creation time")


@dataclass(frozen=True, kw_only=True)
class SecretVersionHandle:
    """The only Secret Store value allowed in Job/outbox payloads."""

    reference_id: UUID
    project_id: UUID
    purpose: str
    version: int

    def __post_init__(self) -> None:
        require_uuid(self.reference_id, "secret reference ID")
        require_uuid(self.project_id, "secret project ID")
        require_purpose(self.purpose)
        require_positive_int(self.version, "secret version")

    def as_job_payload(self) -> Mapping[str, str | int]:
        return {
            "secret_reference_id": str(self.reference_id),
            "secret_project_id": str(self.project_id),
            "secret_purpose": self.purpose,
            "secret_version": self.version,
        }


@dataclass(frozen=True, kw_only=True, repr=False)
class EncryptedSecretVersion:
    """An immutable envelope suitable for a database ciphertext row."""

    handle: SecretVersionHandle
    ciphertext: bytes
    data_nonce: bytes
    wrapped_data_key: bytes
    wrap_nonce: bytes
    master_key_version: int
    created_at: datetime
    algorithm: str = ENVELOPE_ALGORITHM

    def __post_init__(self) -> None:
        if self.algorithm != ENVELOPE_ALGORITHM:
            raise SecretContractError("unsupported secret envelope algorithm")
        require_positive_int(self.master_key_version, "master key version")
        if len(self.data_nonce) != 12 or len(self.wrap_nonce) != 12:
            raise SecretContractError("AES-GCM nonce must be 12 bytes")
        if len(self.ciphertext) < 17 or len(self.wrapped_data_key) != 48:
            raise SecretContractError("secret envelope has invalid ciphertext lengths")
        require_aware_datetime(self.created_at, "secret version creation time")

    def __repr__(self) -> str:
        return (
            "EncryptedSecretVersion("
            f"reference_id={self.handle.reference_id!r}, version={self.handle.version}, "
            f"master_key_version={self.master_key_version}, algorithm={self.algorithm!r})"
        )

    def __reduce__(self) -> Never:
        raise SecretSerializationRejected("encrypted secret envelopes cannot be serialized")


class SecretVersionStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REVOKED = "revoked"


class SecretAuditAction(StrEnum):
    REFERENCE_CREATED = "reference_created"
    VERSION_STAGED = "version_staged"
    VERSION_VERIFIED = "version_verified"
    VERSION_ACTIVATED = "version_activated"
    VERSION_RESOLVED = "version_resolved"
    VERSION_REVOKED = "version_revoked"
    VERSION_REWRAPPED = "version_rewrapped"


@dataclass(frozen=True, kw_only=True)
class SecretAuditEvent:
    id: UUID
    reference_id: UUID
    project_id: UUID
    purpose: str
    version: int
    action: SecretAuditAction
    actor_id: UUID
    occurred_at: datetime
    master_key_version: int

    def __post_init__(self) -> None:
        require_uuid(self.id, "secret audit event ID")
        require_uuid(self.reference_id, "secret audit reference ID")
        require_uuid(self.project_id, "secret audit project ID")
        require_uuid(self.actor_id, "secret audit actor ID")
        require_purpose(self.purpose)
        require_aware_datetime(self.occurred_at, "secret audit time")
        require_positive_int(self.version, "secret audit version")
        require_positive_int(self.master_key_version, "secret audit master key version")


@dataclass(frozen=True, kw_only=True, repr=False)
class MasterKeyCanary:
    master_key_version: int
    nonce: bytes
    ciphertext: bytes
    algorithm: str = ENVELOPE_ALGORITHM

    def __post_init__(self) -> None:
        require_positive_int(self.master_key_version, "canary master key version")
        if self.algorithm != ENVELOPE_ALGORITHM:
            raise SecretContractError("unsupported canary algorithm")
        if len(self.nonce) != 12 or len(self.ciphertext) < 17:
            raise SecretContractError("master key canary has invalid ciphertext lengths")

    def __repr__(self) -> str:
        return (
            "MasterKeyCanary("
            f"master_key_version={self.master_key_version}, algorithm={self.algorithm!r})"
        )


@dataclass(frozen=True, kw_only=True)
class SecretVerificationResult:
    handle: SecretVersionHandle
    verified_at: datetime
    master_key_version: int
    valid: bool = True

    def __post_init__(self) -> None:
        require_aware_datetime(self.verified_at, "secret verification time")
        require_positive_int(self.master_key_version, "verified master key version")
