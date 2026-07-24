"""Authenticated master-key escrow snapshot creation and recovery."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
import hashlib
import hmac
import os
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .crypto import EnvelopeCipher, MasterKeyring
from .errors import (
    SecretConfigurationError,
    SecretContractError,
    SecretSnapshotIntegrityError,
    SecretStoreError,
)
from .models import require_aware_datetime, require_uuid
from .recovery_contracts import (
    DEFAULT_REPRESENTATIVE_KINDS,
    KEYRING_COMMIT_FORMAT,
    KEYRING_PAYLOAD_FORMAT,
    KEYRING_SNAPSHOT_FORMAT,
    AuthenticatedKeyringSnapshot,
    KeyringRestoreResult,
    KeyringSnapshotManifest,
    RecoveryEscrowKey,
    RepresentativeCanaryDescriptor,
    RepresentativeSecretCanary,
    RepresentativeSecretProbe,
    _require_kind,
    create_representative_secret_canary,
)
from .recovery_serialization import (
    decode_keyring_payload,
    encode_keyring_payload,
    parse_snapshot_manifest,
    snapshot_commit_bytes,
    verify_snapshot_commit,
)


_NONCE_BYTES = 12


class KeyringSnapshotCodec:
    """Seal and restore independently stored, authenticated keyring snapshots."""

    def __init__(
        self,
        *,
        required_representative_kinds: Iterable[str] = DEFAULT_REPRESENTATIVE_KINDS,
        random_bytes: Callable[[int], bytes] = os.urandom,
    ) -> None:
        required = tuple(sorted(set(required_representative_kinds)))
        if not required:
            raise SecretConfigurationError("representative canary kinds are required")
        try:
            for kind in required:
                _require_kind(kind)
        except SecretContractError:
            raise SecretConfigurationError("representative canary kinds are invalid")
        self._required_kinds = required
        self._random_bytes = random_bytes

    def seal(
        self,
        *,
        keyring: MasterKeyring,
        escrow_key: RecoveryEscrowKey | None,
        representative_canaries: Iterable[RepresentativeSecretCanary],
        snapshot_id: UUID,
        created_at: datetime,
        data_backup_reference: str,
    ) -> AuthenticatedKeyringSnapshot:
        if escrow_key is None:
            raise SecretConfigurationError("recovery escrow key is required")
        require_uuid(snapshot_id, "keyring snapshot ID")
        require_aware_datetime(created_at, "keyring snapshot creation time")
        escrow_material = escrow_key._key_material()
        if keyring._contains_material(escrow_material):
            raise SecretConfigurationError(
                "recovery escrow key must be independent from application master keys"
            )

        representatives = _ordered_representatives(representative_canaries)
        self._require_representative_coverage(representatives)
        cipher = EnvelopeCipher(keyring)
        for canary in representatives:
            canary.verify(cipher)
        master_canaries = cipher.create_all_canaries()
        cipher.verify_canary_set(master_canaries)

        payload = encode_keyring_payload(
            keyring=keyring,
            master_canaries=master_canaries,
            representative_canaries=representatives,
        )
        nonce = self._random_exact(_NONCE_BYTES)
        descriptors = tuple(canary.descriptor for canary in representatives)
        provisional = KeyringSnapshotManifest(
            snapshot_id=snapshot_id,
            created_at=created_at,
            escrow_key_id=escrow_key.id,
            data_backup_reference=data_backup_reference,
            active_key_version=keyring.active_version,
            key_versions=keyring.versions,
            canary_versions=keyring.versions,
            representative_canaries=descriptors,
            nonce=nonce,
            ciphertext_size=len(payload) + 16,
            ciphertext_sha256="0" * 64,
        )
        ciphertext = AESGCM(escrow_material).encrypt(
            nonce,
            payload,
            provisional.authenticated_bytes(),
        )
        manifest = KeyringSnapshotManifest(
            snapshot_id=snapshot_id,
            created_at=created_at,
            escrow_key_id=escrow_key.id,
            data_backup_reference=data_backup_reference,
            active_key_version=keyring.active_version,
            key_versions=keyring.versions,
            canary_versions=keyring.versions,
            representative_canaries=descriptors,
            nonce=nonce,
            ciphertext_size=len(ciphertext),
            ciphertext_sha256=hashlib.sha256(ciphertext).hexdigest(),
        )
        return AuthenticatedKeyringSnapshot(manifest=manifest, ciphertext=ciphertext)

    def restore(
        self,
        *,
        snapshot: AuthenticatedKeyringSnapshot,
        escrow_key: RecoveryEscrowKey | None,
    ) -> KeyringRestoreResult:
        if escrow_key is None:
            raise SecretConfigurationError("recovery escrow key is required")
        manifest = snapshot.manifest
        if not hmac.compare_digest(manifest.escrow_key_id, escrow_key.id):
            raise SecretSnapshotIntegrityError("keyring snapshot escrow key does not match")
        try:
            payload = AESGCM(escrow_key._key_material()).decrypt(
                manifest.nonce,
                snapshot.ciphertext,
                manifest.authenticated_bytes(),
            )
        except InvalidTag:
            raise SecretSnapshotIntegrityError(
                "keyring snapshot authentication failed"
            ) from None

        try:
            keyring, master_canaries, representatives = decode_keyring_payload(payload)
            if keyring._contains_material(escrow_key._key_material()):
                raise SecretSnapshotIntegrityError("keyring and escrow key separation failed")
            if (
                keyring.active_version != manifest.active_key_version
                or keyring.versions != manifest.key_versions
                or tuple(canary.master_key_version for canary in master_canaries)
                != manifest.canary_versions
                or tuple(canary.descriptor for canary in representatives)
                != manifest.representative_canaries
            ):
                raise SecretSnapshotIntegrityError("keyring snapshot manifest does not match payload")
            cipher = EnvelopeCipher(keyring)
            cipher.verify_canary_set(master_canaries, required_versions=manifest.key_versions)
            self._require_representative_coverage(representatives)
            for canary in representatives:
                canary.verify(cipher)
        except (SecretStoreError, SecretContractError):
            raise SecretSnapshotIntegrityError("keyring snapshot recovery checks failed") from None

        return KeyringRestoreResult(
            keyring=keyring,
            snapshot_id=manifest.snapshot_id,
            manifest_sha256=manifest.manifest_sha256,
            verified_key_versions=keyring.versions,
            verified_representative_kinds=tuple(sorted({item.kind for item in representatives})),
            data_backup_reference=manifest.data_backup_reference,
        )

    def _require_representative_coverage(
        self,
        canaries: tuple[RepresentativeSecretCanary, ...],
    ) -> None:
        kinds = {item.kind for item in canaries}
        if not set(self._required_kinds).issubset(kinds):
            raise SecretConfigurationError("representative secret canary coverage is incomplete")

    def _random_exact(self, length: int) -> bytes:
        value = self._random_bytes(length)
        if len(value) != length:
            raise SecretConfigurationError("secure random source returned an invalid length")
        return bytes(value)


def _ordered_representatives(
    values: Iterable[RepresentativeSecretCanary],
) -> tuple[RepresentativeSecretCanary, ...]:
    ordered = tuple(sorted(values, key=lambda item: (item.kind, str(item.id))))
    keys = tuple((item.kind, item.id) for item in ordered)
    if not ordered or len(keys) != len(set(keys)):
        raise SecretConfigurationError("representative secret canaries must be unique")
    return ordered


def verify_representative_secret_probes(
    *,
    keyring: MasterKeyring,
    probes: Iterable[RepresentativeSecretProbe],
    required_kinds: Iterable[str] = DEFAULT_REPRESENTATIVE_KINDS,
) -> tuple[str, ...]:
    """Run post-data-restore probes while returning only non-sensitive classifications."""

    try:
        required = tuple(sorted(set(required_kinds)))
        for kind in required:
            _require_kind(kind)
        candidates = tuple(probes)
        for probe in candidates:
            require_uuid(probe.id, "representative secret probe ID")
            _require_kind(probe.kind)
        ordered = tuple(sorted(candidates, key=lambda item: (item.kind, str(item.id))))
        identities = tuple((item.kind, item.id) for item in ordered)
    except Exception:
        raise SecretConfigurationError("representative secret probes are invalid") from None
    if not required or not ordered or len(identities) != len(set(identities)):
        raise SecretConfigurationError("representative secret probes are invalid")
    kinds = {item.kind for item in ordered}
    if not set(required).issubset(kinds):
        raise SecretConfigurationError("representative secret probe coverage is incomplete")
    cipher = EnvelopeCipher(keyring)
    try:
        for probe in ordered:
            probe.verify(cipher)
    except Exception:
        raise SecretSnapshotIntegrityError("representative secret probe verification failed") from None
    return tuple(sorted(kinds))


__all__ = [
    "DEFAULT_REPRESENTATIVE_KINDS",
    "KEYRING_COMMIT_FORMAT",
    "KEYRING_PAYLOAD_FORMAT",
    "KEYRING_SNAPSHOT_FORMAT",
    "AuthenticatedKeyringSnapshot",
    "KeyringRestoreResult",
    "KeyringSnapshotCodec",
    "KeyringSnapshotManifest",
    "RecoveryEscrowKey",
    "RepresentativeCanaryDescriptor",
    "RepresentativeSecretCanary",
    "RepresentativeSecretProbe",
    "create_representative_secret_canary",
    "parse_snapshot_manifest",
    "snapshot_commit_bytes",
    "verify_snapshot_commit",
    "verify_representative_secret_probes",
]
