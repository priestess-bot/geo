"""PostgreSQL canaries and independent-DEK wrapping for Synthetic artifacts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import os
from threading import RLock
from typing import Any, cast
from uuid import UUID, uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from geo_core.synthetic_lab.artifact_keyring import (
    ArtifactKeyringConfigurationError,
    SyntheticArtifactKeyring,
)
from geo_core.synthetic_lab.raw_artifact_storage_contracts import (
    ArtifactDekVaultPort,
    RawArtifactStorageError,
)
from geo_core.synthetic_lab.raw_artifact_crypto import (
    decrypt_independent_dek_artifact,
    decrypt_project_tier_artifact,
)
from geo_core.synthetic_lab.raw_artifact_governance import ArtifactStorageTier
from geo_core.synthetic_lab.raw_artifact_storage import artifact_encryption_aad


_CANARY_PREFIX = b"geo-synthetic-artifact-key-canary-v1\0"
_WRAP_SALT = b"geo-synthetic-artifact-dek-wrap-v1\0"
_WRAP_ALGORITHM = "AES-256-GCM/synthetic-artifact-KEK/v1"


@dataclass(frozen=True, kw_only=True, repr=False)
class PendingWrappedDek:
    key_ref: str
    project_id: UUID
    artifact_id: UUID
    fencing_generation: int
    wrapped_dek: bytes
    wrap_nonce: bytes
    master_key_version: str
    algorithm: str
    created_at: datetime


@dataclass(frozen=True, kw_only=True)
class ArtifactRecoveryVerification:
    non_retired_master_key_count: int
    verified_master_key_canary_count: int
    verified_master_key_versions: tuple[str, ...]
    active_dek_count: int
    nondeleted_artifact_count: int
    tier_key_artifact_count: int
    restricted_representative_verified: bool
    tier_representative_verified: bool
    empty_artifact_domain: bool


class PostgresArtifactDekVault(ArtifactDekVaultPort):
    """Keep wrapped envelopes pending until artifact metadata commits atomically."""

    def __init__(self, keyring: SyntheticArtifactKeyring) -> None:
        self._keyring = keyring
        self._pending: dict[str, PendingWrappedDek] = {}
        self._lock = RLock()

    def store_wrapped_key(
        self,
        *,
        project_id: UUID,
        artifact_id: UUID,
        fencing_generation: int,
        key_material: bytearray,
    ) -> str:
        if fencing_generation < 1 or len(key_material) != 32:
            raise RawArtifactStorageError("artifact DEK wrapping input is invalid")
        key_ref = f"synthetic-dek-v1:{uuid4()}"
        version = self._keyring.active_version
        nonce = os.urandom(12)
        wrapping_key = _wrapping_key(self._keyring, version, project_id)
        try:
            wrapped = AESGCM(wrapping_key).encrypt(
                nonce,
                bytes(key_material),
                _dek_aad(project_id, artifact_id, fencing_generation, key_ref, version),
            )
        finally:
            wrapping_key = b""
        pending = PendingWrappedDek(
            key_ref=key_ref,
            project_id=project_id,
            artifact_id=artifact_id,
            fencing_generation=fencing_generation,
            wrapped_dek=wrapped,
            wrap_nonce=nonce,
            master_key_version=version,
            algorithm=_WRAP_ALGORITHM,
            created_at=datetime.now(UTC),
        )
        with self._lock:
            self._pending[key_ref] = pending
        return key_ref

    def pending_for(
        self,
        *,
        key_ref: str,
        project_id: UUID,
        artifact_id: UUID,
        fencing_generation: int,
    ) -> PendingWrappedDek:
        with self._lock:
            pending = self._pending.get(key_ref)
        if pending is None or (
            pending.project_id,
            pending.artifact_id,
            pending.fencing_generation,
        ) != (project_id, artifact_id, fencing_generation):
            raise RawArtifactStorageError("pending artifact DEK ownership changed")
        return pending

    def mark_committed(self, key_ref: str) -> None:
        with self._lock:
            if self._pending.pop(key_ref, None) is None:
                raise RawArtifactStorageError("committed artifact DEK was not pending")

    def destroy_wrapped_key(self, key_ref: str) -> None:
        with self._lock:
            if self._pending.pop(key_ref, None) is not None:
                return
        raise RawArtifactStorageError(
            "persisted artifact DEKs may be destroyed only by the fenced deletion worker"
        )

    def unwrap(
        self,
        *,
        key_ref: str,
        project_id: UUID,
        artifact_id: UUID,
        fencing_generation: int,
        wrapped_dek: bytes,
        wrap_nonce: bytes,
        master_key_version: str,
    ) -> bytes:
        wrapping_key = _wrapping_key(self._keyring, master_key_version, project_id)
        try:
            value = AESGCM(wrapping_key).decrypt(
                wrap_nonce,
                wrapped_dek,
                _dek_aad(
                    project_id,
                    artifact_id,
                    fencing_generation,
                    key_ref,
                    master_key_version,
                ),
            )
        except InvalidTag as error:
            raise RawArtifactStorageError("artifact DEK envelope authentication failed") from error
        finally:
            wrapping_key = b""
        if len(value) != 32:
            raise RawArtifactStorageError("unwrapped artifact DEK has invalid length")
        return value


def synchronize_artifact_master_key_canaries(
    connection_factory: Callable[[], Any],
    keyring: SyntheticArtifactKeyring,
) -> None:
    connection = connection_factory()
    try:
        rows = {
            str(row[0]): {
                "status": str(row[1]),
                "algorithm": str(row[2]),
                "nonce": bytes(row[3]),
                "ciphertext": bytes(row[4]),
            }
            for row in connection.execute(
                """SELECT master_key_version, status, algorithm,
                          canary_nonce, canary_ciphertext
                   FROM synthetic_lab_artifact_master_key_versions
                   ORDER BY master_key_version::bigint"""
            ).fetchall()
        }
        _verify_registered_canaries(rows, keyring)
        missing = [version for version in _ordered_versions(keyring) if version not in rows]
        if rows and any(version != keyring.active_version for version in missing):
            raise ArtifactKeyringConfigurationError(
                "historical artifact keys cannot be inserted after database activation"
            )
        for version in missing:
            nonce = os.urandom(12)
            ciphertext = AESGCM(keyring.keys[version]).encrypt(
                nonce,
                _canary_plaintext(version),
                _canary_aad(version),
            )
            status = "encrypt_decrypt" if version == keyring.active_version else "decrypt_only"
            connection.execute(
                "SELECT geo_sync_synthetic_artifact_master_key_version(%s, %s, %s, %s, %s, %s)",
                (version, status, "AES-256-GCM", nonce, ciphertext, datetime.now(UTC)),
            )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def verify_synthetic_artifact_recovery(
    connection_factory: Callable[[], Any],
    keyring: SyntheticArtifactKeyring,
    *,
    object_reader: Callable[[str, str], bytes] | None,
) -> ArtifactRecoveryVerification:
    """Authenticate restored keys and representative ciphertext without returning secrets."""

    connection = connection_factory()
    try:
        rows = {
            str(row[0]): {
                "status": str(row[1]),
                "algorithm": str(row[2]),
                "nonce": bytes(row[3]),
                "ciphertext": bytes(row[4]),
            }
            for row in connection.execute(
                """SELECT master_key_version, status, algorithm,
                          canary_nonce, canary_ciphertext
                   FROM synthetic_lab_artifact_master_key_versions
                   ORDER BY master_key_version::bigint"""
            ).fetchall()
        }
        _verify_registered_canaries(rows, keyring)
        active_versions = [
            version for version, row in rows.items() if row["status"] == "encrypt_decrypt"
        ]
        if active_versions != [keyring.active_version]:
            raise ArtifactKeyringConfigurationError(
                "restored Synthetic artifact active key does not match the keyring"
            )
        counts = connection.execute(
            """SELECT
                   (SELECT count(*) FROM synthetic_lab_artifact_master_key_versions
                    WHERE status <> 'retired'),
                   (SELECT count(*) FROM synthetic_lab_artifact_deks WHERE status = 'active'),
                   (SELECT count(*) FROM synthetic_lab_raw_artifacts
                    WHERE lifecycle_state <> 'deleted'),
                   (SELECT count(*) FROM synthetic_lab_raw_artifacts
                    WHERE lifecycle_state <> 'deleted'
                      AND storage_tier <> 'restricted_independent_dek')"""
        ).fetchone()
        if counts is None:
            raise RawArtifactStorageError("Synthetic artifact recovery counts are unavailable")
        non_retired, active_deks, nondeleted, tier_count = map(int, counts)
        restricted = _representative_restricted_row(connection)
        tier = _representative_tier_row(connection)
        if nondeleted and object_reader is None:
            raise RawArtifactStorageError(
                "artifact object reader is required for non-empty recovery verification"
            )
        restricted_verified = (
            _verify_restricted_artifact(restricted, keyring, object_reader)
            if restricted is not None and object_reader is not None
            else False
        )
        tier_verified = (
            _verify_tier_artifact(tier, keyring, object_reader)
            if tier is not None and object_reader is not None
            else False
        )
        if active_deks and not restricted_verified:
            raise RawArtifactStorageError(
                "restored active artifact DEK has no verified representative"
            )
        if tier_count and not tier_verified:
            raise RawArtifactStorageError(
                "restored tier-key artifacts have no verified representative"
            )
        connection.rollback()
        verified_versions = tuple(
            sorted(
                (version for version, row in rows.items() if row["status"] != "retired"),
                key=int,
            )
        )
        return ArtifactRecoveryVerification(
            non_retired_master_key_count=non_retired,
            verified_master_key_canary_count=len(verified_versions),
            verified_master_key_versions=verified_versions,
            active_dek_count=active_deks,
            nondeleted_artifact_count=nondeleted,
            tier_key_artifact_count=tier_count,
            restricted_representative_verified=restricted_verified,
            tier_representative_verified=tier_verified,
            empty_artifact_domain=nondeleted == 0,
        )
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _representative_restricted_row(connection: Any) -> Mapping[str, Any] | None:
    cursor = connection.execute(
        """SELECT artifact.project_id, artifact.artifact_id, artifact.job_id,
                  artifact.fencing_generation, artifact.persisted_content_hash,
                  artifact.stored_object_hash, artifact.payload_uri,
                  artifact.captured_at, dek.key_ref, dek.wrapped_dek, dek.wrap_nonce,
                  dek.master_key_version
           FROM synthetic_lab_raw_artifacts AS artifact
           JOIN synthetic_lab_artifact_deks AS dek
             ON dek.project_id = artifact.project_id
            AND dek.artifact_id = artifact.artifact_id
            AND dek.fencing_generation = artifact.fencing_generation
           WHERE artifact.lifecycle_state <> 'deleted' AND dek.status = 'active'
           ORDER BY artifact.created_at DESC LIMIT 1"""
    )
    return _row_mapping(cursor)


def _representative_tier_row(connection: Any) -> Mapping[str, Any] | None:
    cursor = connection.execute(
        """SELECT project_id, artifact_id, job_id, fencing_generation,
                  persisted_content_hash, stored_object_hash, payload_uri,
                  captured_at, storage_tier, tier_key_version
           FROM synthetic_lab_raw_artifacts
           WHERE lifecycle_state <> 'deleted'
             AND storage_tier <> 'restricted_independent_dek'
           ORDER BY created_at DESC LIMIT 1"""
    )
    return _row_mapping(cursor)


def _verify_restricted_artifact(
    row: Mapping[str, Any],
    keyring: SyntheticArtifactKeyring,
    object_reader: Callable[[str, str], bytes],
) -> bool:
    vault = PostgresArtifactDekVault(keyring)
    data_key = vault.unwrap(
        key_ref=row["key_ref"],
        project_id=row["project_id"],
        artifact_id=row["artifact_id"],
        fencing_generation=row["fencing_generation"],
        wrapped_dek=bytes(cast(Any, row["wrapped_dek"])),
        wrap_nonce=bytes(cast(Any, row["wrap_nonce"])),
        master_key_version=row["master_key_version"],
    )
    payload = object_reader(row["payload_uri"], row["stored_object_hash"])
    _verify_stored_hash(payload, row["stored_object_hash"])
    plaintext = decrypt_independent_dek_artifact(
        payload=payload,
        data_key=data_key,
        associated_data=_artifact_aad(row),
    )
    return _content_verified(plaintext, row["persisted_content_hash"])


def _verify_tier_artifact(
    row: Mapping[str, Any],
    keyring: SyntheticArtifactKeyring,
    object_reader: Callable[[str, str], bytes],
) -> bool:
    _version, secret = keyring.resolve_version(
        project_id=row["project_id"],
        storage_tier=ArtifactStorageTier(row["storage_tier"]),
        version=row["tier_key_version"],
    )
    payload = object_reader(row["payload_uri"], row["stored_object_hash"])
    _verify_stored_hash(payload, row["stored_object_hash"])
    plaintext = decrypt_project_tier_artifact(
        payload=payload,
        tier_key=secret.reveal_bytes(),
        associated_data=_artifact_aad(row),
    )
    return _content_verified(plaintext, row["persisted_content_hash"])


def _artifact_aad(row: Mapping[str, Any]) -> bytes:
    return artifact_encryption_aad(
        project_id=row["project_id"],
        artifact_id=row["artifact_id"],
        job_id=row["job_id"],
        content_hash=row["persisted_content_hash"],
        captured_at=row["captured_at"],
    )


def _verify_stored_hash(payload: bytes, expected: str) -> None:
    if hashlib.sha256(payload).hexdigest() != expected:
        raise RawArtifactStorageError("restored artifact object hash changed")


def _content_verified(plaintext: bytes, expected: str) -> bool:
    if hashlib.sha256(plaintext).hexdigest() != expected:
        raise RawArtifactStorageError("restored artifact plaintext hash changed")
    return True


def _row_mapping(cursor: Any) -> Mapping[str, Any] | None:
    row = cursor.fetchone()
    if row is None:
        return None
    if isinstance(row, Mapping):
        return dict(row)
    names = [column.name for column in cursor.description]
    return dict(zip(names, row, strict=True))


def _verify_registered_canaries(
    rows: Mapping[str, Mapping[str, object]],
    keyring: SyntheticArtifactKeyring,
) -> None:
    usable = {
        version for version, row in rows.items() if row["status"] != "retired"
    }
    missing_local = usable - set(keyring.keys)
    if missing_local:
        raise ArtifactKeyringConfigurationError(
            "database requires unavailable Synthetic artifact key versions"
        )
    for version in set(rows).intersection(keyring.keys):
        row = rows[version]
        if row["algorithm"] != "AES-256-GCM":
            raise ArtifactKeyringConfigurationError("artifact key canary algorithm changed")
        try:
            plaintext = AESGCM(keyring.keys[version]).decrypt(
                bytes(cast(Any, row["nonce"])),
                bytes(cast(Any, row["ciphertext"])),
                _canary_aad(version),
            )
        except InvalidTag as error:
            raise ArtifactKeyringConfigurationError(
                "Synthetic artifact key canary authentication failed"
            ) from error
        if plaintext != _canary_plaintext(version):
            raise ArtifactKeyringConfigurationError("Synthetic artifact key canary changed")
    active = [version for version, row in rows.items() if row["status"] == "encrypt_decrypt"]
    if active and active != [keyring.active_version] and keyring.active_version in rows:
        raise ArtifactKeyringConfigurationError(
            "configured Synthetic artifact active key does not match database"
        )


def _wrapping_key(
    keyring: SyntheticArtifactKeyring,
    version: str,
    project_id: UUID,
) -> bytes:
    try:
        root = keyring.keys[version]
    except KeyError as error:
        raise ArtifactKeyringConfigurationError(
            "artifact DEK master key version is unavailable"
        ) from error
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_WRAP_SALT,
        info=project_id.bytes,
    ).derive(root)


def _dek_aad(
    project_id: UUID,
    artifact_id: UUID,
    fencing_generation: int,
    key_ref: str,
    version: str,
) -> bytes:
    return b"\0".join(
        (
            b"geo-synthetic-artifact-dek-v1",
            str(project_id).encode("ascii"),
            str(artifact_id).encode("ascii"),
            str(fencing_generation).encode("ascii"),
            key_ref.encode("ascii"),
            version.encode("ascii"),
        )
    )


def _canary_plaintext(version: str) -> bytes:
    return _CANARY_PREFIX + version.encode("ascii")


def _canary_aad(version: str) -> bytes:
    return b"geo-synthetic-artifact-key-canary-aad-v1\0" + version.encode("ascii")


def _ordered_versions(keyring: SyntheticArtifactKeyring) -> list[str]:
    return sorted(keyring.keys, key=int)


__all__ = [
    "ArtifactRecoveryVerification",
    "PendingWrappedDek",
    "PostgresArtifactDekVault",
    "synchronize_artifact_master_key_canaries",
    "verify_synthetic_artifact_recovery",
]
