"""Immutable contracts for authenticated keyring escrow and recovery."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import hmac
import json
import re
from typing import Never, Protocol
from uuid import UUID

from .crypto import EnvelopeCipher, MasterKeyring
from .errors import (
    SecretConfigurationError,
    SecretContractError,
    SecretSerializationRejected,
    SecretSnapshotIntegrityError,
)
from .models import (
    ENVELOPE_ALGORITHM,
    EncryptedSecretVersion,
    SecretReference,
    SecretValue,
    require_aware_datetime,
    require_positive_int,
    require_uuid,
)


KEYRING_SNAPSHOT_FORMAT = "geo-keyring-snapshot-v1"
KEYRING_PAYLOAD_FORMAT = "geo-keyring-snapshot-payload-v1"
KEYRING_COMMIT_FORMAT = "geo-keyring-snapshot-commit-v1"
KEYRING_STORAGE_DOMAIN = "independent-keyring-escrow"
DEFAULT_REPRESENTATIVE_KINDS = ("connector", "provider", "egress")
_ESCROW_KEY_BYTES = 32
_NONCE_BYTES = 12
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}$")
_KIND = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


class RecoveryEscrowKey:
    """A separately controlled key used only to encrypt keyring snapshots."""

    __slots__ = ("__id", "__material")

    def __init__(self, *, id: str, material: bytes) -> None:
        _require_identifier(id, "recovery escrow key ID")
        copied = bytes(material)
        if len(copied) != _ESCROW_KEY_BYTES:
            raise SecretConfigurationError("recovery escrow keys must be 256 bits")
        self.__id = id
        self.__material = copied

    @property
    def id(self) -> str:
        return self.__id

    def __repr__(self) -> str:
        return f"RecoveryEscrowKey(id={self.id!r})"

    def __reduce__(self) -> Never:
        raise SecretSerializationRejected("recovery escrow keys cannot be serialized")

    def _key_material(self) -> bytes:
        return bytes(self.__material)


@dataclass(frozen=True, kw_only=True)
class RepresentativeCanaryDescriptor:
    id: UUID
    kind: str
    master_key_version: int

    def __post_init__(self) -> None:
        require_uuid(self.id, "representative secret canary ID")
        _require_kind(self.kind)
        require_positive_int(self.master_key_version, "representative canary master key version")


@dataclass(frozen=True, kw_only=True, repr=False)
class RepresentativeSecretCanary:
    """A non-business envelope proving the full Secret Store decrypt path."""

    id: UUID
    kind: str
    envelope: EncryptedSecretVersion

    def __post_init__(self) -> None:
        require_uuid(self.id, "representative secret canary ID")
        _require_kind(self.kind)
        if self.envelope.handle.reference_id != self.id:
            raise SecretContractError("representative canary identity does not match its envelope")

    @property
    def descriptor(self) -> RepresentativeCanaryDescriptor:
        return RepresentativeCanaryDescriptor(
            id=self.id,
            kind=self.kind,
            master_key_version=self.envelope.master_key_version,
        )

    def __repr__(self) -> str:
        return (
            "RepresentativeSecretCanary("
            f"id={self.id!r}, kind={self.kind!r}, "
            f"master_key_version={self.envelope.master_key_version})"
        )

    def __reduce__(self) -> Never:
        raise SecretSerializationRejected("representative secret canaries cannot be serialized")

    def verify(self, cipher: EnvelopeCipher) -> None:
        try:
            value = cipher.decrypt(self.envelope)
        except Exception:
            raise SecretSnapshotIntegrityError(
                "representative secret canary verification failed"
            ) from None
        if not value.matches(_representative_challenge(self.id, self.kind)):
            raise SecretSnapshotIntegrityError("representative secret canary verification failed")


class RepresentativeSecretProbe(Protocol):
    """Adapter contract for validating a restored real secret without exposing it."""

    @property
    def id(self) -> UUID: ...

    @property
    def kind(self) -> str: ...

    def verify(self, cipher: EnvelopeCipher) -> None: ...


def create_representative_secret_canary(
    *,
    cipher: EnvelopeCipher,
    canary_id: UUID,
    kind: str,
    project_id: UUID,
    purpose: str,
    created_at: datetime,
) -> RepresentativeSecretCanary:
    """Create a safe known-plaintext envelope for one integration class."""

    _require_kind(kind)
    reference = SecretReference(
        id=canary_id,
        project_id=project_id,
        purpose=purpose,
        created_at=created_at,
    )
    envelope = cipher.encrypt(
        reference=reference,
        version=1,
        value=SecretValue(_representative_challenge(canary_id, kind)),
        created_at=created_at,
    )
    return RepresentativeSecretCanary(id=canary_id, kind=kind, envelope=envelope)


@dataclass(frozen=True, kw_only=True, repr=False)
class KeyringSnapshotManifest:
    snapshot_id: UUID
    created_at: datetime
    escrow_key_id: str
    data_backup_reference: str
    active_key_version: int
    key_versions: tuple[int, ...]
    canary_versions: tuple[int, ...]
    representative_canaries: tuple[RepresentativeCanaryDescriptor, ...]
    nonce: bytes
    ciphertext_size: int
    ciphertext_sha256: str
    format: str = KEYRING_SNAPSHOT_FORMAT
    algorithm: str = ENVELOPE_ALGORITHM
    storage_domain: str = KEYRING_STORAGE_DOMAIN

    def __post_init__(self) -> None:
        require_uuid(self.snapshot_id, "keyring snapshot ID")
        require_aware_datetime(self.created_at, "keyring snapshot creation time")
        _require_identifier(self.escrow_key_id, "recovery escrow key ID")
        _require_identifier(self.data_backup_reference, "data backup reference")
        require_positive_int(self.active_key_version, "active master key version")
        _require_sorted_versions(self.key_versions, "snapshot key versions")
        _require_sorted_versions(self.canary_versions, "snapshot canary versions")
        if self.active_key_version not in self.key_versions:
            raise SecretContractError("active master key is absent from snapshot key versions")
        if self.key_versions != self.canary_versions:
            raise SecretContractError("snapshot canaries must cover every key version")
        if not self.representative_canaries:
            raise SecretContractError("representative secret canaries are required")
        descriptor_keys = tuple(
            (item.kind, str(item.id)) for item in self.representative_canaries
        )
        if descriptor_keys != tuple(sorted(set(descriptor_keys))):
            raise SecretContractError("representative secret canaries must be unique and sorted")
        if any(item.master_key_version not in self.key_versions for item in self.representative_canaries):
            raise SecretContractError("representative canary uses an unknown master key version")
        if len(self.nonce) != _NONCE_BYTES:
            raise SecretContractError("keyring snapshot nonce must be 12 bytes")
        if self.ciphertext_size < 17:
            raise SecretContractError("keyring snapshot ciphertext size is invalid")
        if _SHA256.fullmatch(self.ciphertext_sha256) is None:
            raise SecretContractError("keyring snapshot ciphertext checksum is invalid")
        if self.format != KEYRING_SNAPSHOT_FORMAT or self.algorithm != ENVELOPE_ALGORITHM:
            raise SecretContractError("keyring snapshot format or algorithm is unsupported")
        if self.storage_domain != KEYRING_STORAGE_DOMAIN:
            raise SecretContractError("keyring snapshot storage domain is invalid")

    def __repr__(self) -> str:
        return (
            "KeyringSnapshotManifest("
            f"snapshot_id={self.snapshot_id!r}, active_key_version={self.active_key_version}, "
            f"key_versions={self.key_versions!r}, ciphertext_sha256={self.ciphertext_sha256!r})"
        )

    def authenticated_bytes(self) -> bytes:
        return _canonical_json(_manifest_payload(self, include_ciphertext_checksum=False))

    def serialized_bytes(self) -> bytes:
        return _canonical_json(_manifest_payload(self, include_ciphertext_checksum=True))

    @property
    def manifest_sha256(self) -> str:
        return hashlib.sha256(self.serialized_bytes()).hexdigest()


@dataclass(frozen=True, kw_only=True, repr=False)
class AuthenticatedKeyringSnapshot:
    manifest: KeyringSnapshotManifest
    ciphertext: bytes

    def __post_init__(self) -> None:
        if len(self.ciphertext) != self.manifest.ciphertext_size:
            raise SecretSnapshotIntegrityError("keyring snapshot ciphertext size does not match")
        if not hmac.compare_digest(
            hashlib.sha256(self.ciphertext).hexdigest(),
            self.manifest.ciphertext_sha256,
        ):
            raise SecretSnapshotIntegrityError("keyring snapshot ciphertext checksum does not match")

    def __repr__(self) -> str:
        return (
            "AuthenticatedKeyringSnapshot("
            f"snapshot_id={self.manifest.snapshot_id!r}, "
            f"manifest_sha256={self.manifest.manifest_sha256!r}, "
            f"ciphertext_size={len(self.ciphertext)})"
        )

    def __reduce__(self) -> Never:
        raise SecretSerializationRejected("keyring snapshots cannot be serialized")


@dataclass(frozen=True, kw_only=True, repr=False)
class KeyringRestoreResult:
    keyring: MasterKeyring
    snapshot_id: UUID
    manifest_sha256: str
    verified_key_versions: tuple[int, ...]
    verified_representative_kinds: tuple[str, ...]
    data_backup_reference: str

    def __repr__(self) -> str:
        return (
            "KeyringRestoreResult("
            f"snapshot_id={self.snapshot_id!r}, "
            f"verified_key_versions={self.verified_key_versions!r}, "
            f"verified_representative_kinds={self.verified_representative_kinds!r})"
        )

    def __reduce__(self) -> Never:
        raise SecretSerializationRejected("restored keyring results cannot be serialized")


def _manifest_payload(
    manifest: KeyringSnapshotManifest,
    *,
    include_ciphertext_checksum: bool,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "format": manifest.format,
        "snapshot_id": str(manifest.snapshot_id),
        "created_at": _canonical_datetime(manifest.created_at),
        "algorithm": manifest.algorithm,
        "escrow_key_id": manifest.escrow_key_id,
        "storage_domain": manifest.storage_domain,
        "data_backup_reference": manifest.data_backup_reference,
        "active_key_version": manifest.active_key_version,
        "key_versions": list(manifest.key_versions),
        "canary_versions": list(manifest.canary_versions),
        "representative_canaries": [
            {
                "id": str(item.id),
                "kind": item.kind,
                "master_key_version": item.master_key_version,
            }
            for item in manifest.representative_canaries
        ],
        "nonce": _encode_base64(manifest.nonce),
        "ciphertext_size": manifest.ciphertext_size,
    }
    if include_ciphertext_checksum:
        payload["ciphertext_sha256"] = manifest.ciphertext_sha256
    return payload


def _representative_challenge(canary_id: UUID, kind: str) -> bytes:
    return f"geo-representative-secret-canary-v1:{kind}:{canary_id}".encode("ascii")


def _canonical_datetime(value: datetime) -> str:
    require_aware_datetime(value, "recovery timestamp")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _encode_base64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _require_identifier(value: str, label: str) -> None:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise SecretContractError(f"{label} must be a non-sensitive stable identifier")


def _require_kind(value: str) -> None:
    if not isinstance(value, str) or _KIND.fullmatch(value) is None:
        raise SecretContractError("representative canary kind must be a stable identifier")


def _require_sorted_versions(values: tuple[int, ...], label: str) -> None:
    for value in values:
        require_positive_int(value, label)
    if not values or values != tuple(sorted(set(values))):
        raise SecretContractError(f"{label} must be unique and sorted")
