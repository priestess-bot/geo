"""PostgreSQL persistence for encrypted Provider artifact keys and lifecycle."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg

from geo_core.model_gateway.artifact_lifecycle import (
    ProviderArtifactDeletionLease,
    ProviderArtifactDeletionReason,
    ProviderArtifactDeletionReceipt,
    ProviderArtifactKind,
    StagedProviderArtifact,
    StagedProviderArtifactBundle,
)
from geo_core.model_gateway.provider_adapters.artifacts import ProviderArtifactError
from geo_core.project_scope import set_project_scope
from geo_core.secrets import (
    EncryptedSecretVersion,
    EnvelopeCipher,
    MasterKeyCanary,
    MasterKeyring,
    SecretConfigurationError,
    SecretReference,
    SecretValue,
    SecretVersionHandle,
    load_master_keyring_from_docker_secret,
)


PROVIDER_ARTIFACT_KEYRING_ENV = "GEO_PROVIDER_ARTIFACT_KEYRING_FILE"
_DEK_PURPOSE = "model_gateway.artifact_dek"


class PostgresProviderArtifactKeyVault:
    """Envelope-encrypt Provider artifact DEKs under an independent keyring."""

    def __init__(
        self,
        *,
        connect: Callable[[], Any],
        cipher: EnvelopeCipher,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        synchronize: bool = True,
    ) -> None:
        self._connect = connect
        self._cipher = cipher
        self._clock = clock
        if synchronize:
            with self._connect() as connection:
                synchronize_provider_artifact_master_keys(connection, cipher)

    def __repr__(self) -> str:
        return "PostgresProviderArtifactKeyVault([REDACTED])"

    def store_wrapped_key(
        self, *, project_id: UUID, artifact_id: UUID, key_material: bytearray
    ) -> str:
        if len(key_material) != 32:
            raise ProviderArtifactError("Provider artifact DEK must be 256 bits")
        created_at = self._clock()
        reference = SecretReference(
            id=artifact_id,
            project_id=project_id,
            purpose=_DEK_PURPOSE,
            created_at=created_at,
        )
        envelope = self._cipher.encrypt(
            reference=reference,
            version=1,
            value=SecretValue(key_material),
            created_at=created_at,
        )
        try:
            with self._connect() as connection:
                set_project_scope(connection, project_id)
                connection.execute(
                    """INSERT INTO model_gateway_artifact_deks(
                           key_ref, project_id, artifact_id, ciphertext, data_nonce,
                           wrapped_data_key, wrap_nonce, master_key_version,
                           algorithm, status, created_at
                       ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', %s)""",
                    (
                        artifact_id,
                        project_id,
                        artifact_id,
                        envelope.ciphertext,
                        envelope.data_nonce,
                        envelope.wrapped_data_key,
                        envelope.wrap_nonce,
                        envelope.master_key_version,
                        envelope.algorithm,
                        created_at,
                    ),
                )
        except psycopg.Error as exc:
            raise ProviderArtifactError(
                "Provider artifact DEK could not be durably wrapped"
            ) from exc
        return str(artifact_id)

    def destroy_wrapped_key(
        self, *, project_id: UUID, key_reference: str
    ) -> None:
        try:
            key_ref = UUID(key_reference)
        except ValueError:
            raise ProviderArtifactError("Provider artifact key reference is invalid") from None
        try:
            with self._connect() as connection:
                set_project_scope(connection, project_id)
                row = connection.execute(
                    """SELECT status FROM model_gateway_artifact_deks
                       WHERE project_id = %s AND key_ref = %s FOR UPDATE""",
                    (project_id, key_ref),
                ).fetchone()
                if row is None or row["status"] == "destroyed":
                    return
                connection.execute(
                    """UPDATE model_gateway_artifact_deks
                       SET status = 'destroyed', ciphertext = NULL, data_nonce = NULL,
                           wrapped_data_key = NULL, wrap_nonce = NULL,
                           destroyed_at = clock_timestamp()
                       WHERE project_id = %s AND key_ref = %s AND status = 'active'""",
                    (project_id, key_ref),
                )
        except psycopg.Error as exc:
            raise ProviderArtifactError(
                "Provider artifact DEK could not be destroyed"
            ) from exc

    def resolve_active_key(self, *, project_id: UUID, artifact_id: UUID) -> bytearray:
        try:
            with self._connect() as connection:
                set_project_scope(connection, project_id)
                row = connection.execute(
                    """SELECT * FROM model_gateway_artifact_deks
                       WHERE project_id = %s AND artifact_id = %s AND status = 'active'""",
                    (project_id, artifact_id),
                ).fetchone()
        except psycopg.Error as exc:
            raise ProviderArtifactError("Provider artifact DEK is unavailable") from exc
        if row is None:
            raise ProviderArtifactError("Provider artifact DEK is unavailable")
        return decrypt_provider_artifact_dek(self._cipher, row)


class PostgresProviderArtifactLifecycleRepository:
    def __init__(self, *, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def stage_bundle(self, bundle: StagedProviderArtifactBundle) -> None:
        try:
            with self._connect() as connection:
                set_project_scope(connection, bundle.project_id)
                existing = connection.execute(
                    """SELECT id FROM model_gateway_artifact_bundles
                       WHERE project_id = %s AND attempt_id = %s""",
                    (bundle.project_id, bundle.attempt_id),
                ).fetchone()
                if existing is not None:
                    if existing["id"] != bundle.id or not _bundle_matches(
                        connection, bundle
                    ):
                        raise ProviderArtifactError(
                            "Provider artifact Attempt already has different staged lineage"
                        )
                    return
                connection.execute(
                    """INSERT INTO model_gateway_artifact_bundles(
                           id, project_id, job_id, attempt_id, provider,
                           adapter_release_id, adapter_release_hash, data_policy_hash,
                           storage_decision, cache_decision, display_decision,
                           redistribution_decision, usage_purpose, audience,
                           retention_days, status, staged_at, expires_at
                       ) VALUES (
                           %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s, %s, %s, %s, 'staged', %s, %s
                       )""",
                    (
                        bundle.id,
                        bundle.project_id,
                        bundle.job_id,
                        bundle.attempt_id,
                        bundle.provider,
                        bundle.adapter_release_id,
                        bundle.adapter_release_hash,
                        bundle.data_policy_hash,
                        bundle.storage_decision,
                        bundle.cache_decision,
                        bundle.display_decision,
                        bundle.redistribution_decision,
                        bundle.usage_purpose,
                        bundle.usage_audience.value,
                        bundle.retention_days,
                        bundle.staged_at,
                        bundle.expires_at,
                    ),
                )
                for artifact in bundle.artifacts:
                    _insert_artifact(connection, bundle, artifact)
        except ProviderArtifactError:
            raise
        except psycopg.Error as exc:
            raise ProviderArtifactError(
                "Provider artifact bundle could not be durably staged"
            ) from exc

    def destroy_unstaged_keys(self, *, now: datetime, grace_seconds: int) -> int:
        _require_aware(now)
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT geo_destroy_model_gateway_unstaged_artifact_deks(%s, %s) AS count",
                    (now, grace_seconds),
                ).fetchone()
        except psycopg.Error as exc:
            raise ProviderArtifactError(
                "Provider artifact unattached DEK sweep failed"
            ) from exc
        return int(row["count"])

    def enqueue_expired(self, *, now: datetime, staged_grace_seconds: int) -> int:
        _require_aware(now)
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT geo_stage_model_gateway_artifact_expiry(%s, %s) AS count",
                    (now, staged_grace_seconds),
                ).fetchone()
        except psycopg.Error as exc:
            raise ProviderArtifactError("Provider artifact expiry sweep failed") from exc
        return int(row["count"])

    def claim_deletions(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
        limit: int,
    ) -> tuple[ProviderArtifactDeletionLease, ...]:
        if not worker_id.strip():
            raise ValueError("Provider artifact deletion worker ID is required")
        _require_aware(now)
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT * FROM geo_claim_model_gateway_artifact_deletions(%s, %s)",
                    (limit, lease_seconds),
                ).fetchall()
                leases = tuple(
                    _deletion_lease(connection, row, now=now, lease_seconds=lease_seconds)
                    for row in rows
                )
        except psycopg.Error as exc:
            raise ProviderArtifactError("Provider artifact deletion claim failed") from exc
        return leases

    def complete_deletion(self, receipt: ProviderArtifactDeletionReceipt) -> None:
        lease = receipt.lease
        try:
            with self._connect() as connection:
                set_project_scope(connection, lease.project_id)
                connection.execute(
                    "SELECT geo_complete_model_gateway_artifact_deletion(%s, %s, %s, %s, %s)",
                    (
                        lease.project_id,
                        lease.outbox_id,
                        lease.lease_token,
                        lease.fencing_generation,
                        receipt.deletion_receipt_hash,
                    ),
                )
        except psycopg.Error as exc:
            raise ProviderArtifactError("Provider artifact deletion was fenced") from exc

    def fail_deletion(
        self,
        lease: ProviderArtifactDeletionLease,
        *,
        now: datetime,
        error_code: str,
    ) -> None:
        _require_aware(now)
        try:
            with self._connect() as connection:
                set_project_scope(connection, lease.project_id)
                connection.execute(
                    "SELECT geo_fail_model_gateway_artifact_deletion(%s, %s, %s, %s, %s, %s)",
                    (
                        lease.project_id,
                        lease.outbox_id,
                        lease.lease_token,
                        lease.fencing_generation,
                        error_code,
                        60,
                    ),
                )
        except psycopg.Error as exc:
            raise ProviderArtifactError(
                "Provider artifact deletion failure could not be recorded"
            ) from exc


def load_provider_artifact_keyring(
    path: str | os.PathLike[str] | None = None,
) -> MasterKeyring | None:
    configured = Path(path) if path is not None else _environment_path()
    return (
        load_master_keyring_from_docker_secret(configured)
        if configured is not None
        else None
    )


def synchronize_provider_artifact_master_keys(
    connection: Any, cipher: EnvelopeCipher
) -> None:
    rows = tuple(
        connection.execute(
            """SELECT master_key_version, status, algorithm,
                      canary_nonce, canary_ciphertext
               FROM model_gateway_artifact_master_key_versions
               ORDER BY master_key_version"""
        ).fetchall()
    )
    configured = set(cipher.master_key_versions)
    required = {
        int(row["master_key_version"])
        for row in rows
        if row["status"] != "retired"
    }
    if required - configured:
        raise SecretConfigurationError(
            "Provider artifact database requires unavailable historical keys"
        )
    _verify_canary_rows(cipher, rows, configured)
    existing = {int(row["master_key_version"]) for row in rows}
    missing = configured - existing
    active = cipher.active_master_key_version
    if rows and missing not in (set(), {active}):
        raise SecretConfigurationError(
            "Provider artifact keyring history cannot be registered out of order"
        )
    if rows and missing == {active} and active <= max(existing):
        raise SecretConfigurationError(
            "Provider artifact active master key version must increase"
        )
    for version in sorted(missing):
        canary = cipher.create_canary(version)
        connection.execute(
            "SELECT geo_sync_model_gateway_artifact_master_key_version(%s, %s, %s, %s, %s, %s)",
            (
                version,
                "encrypt_decrypt" if version == active else "decrypt_only",
                canary.algorithm,
                canary.nonce,
                canary.ciphertext,
                datetime.now(UTC),
            ),
        )
    final = tuple(
        connection.execute(
            """SELECT master_key_version, status, algorithm,
                      canary_nonce, canary_ciphertext
               FROM model_gateway_artifact_master_key_versions
               ORDER BY master_key_version"""
        ).fetchall()
    )
    final_required = {
        int(row["master_key_version"])
        for row in final
        if row["status"] != "retired"
    }
    if final_required != configured:
        raise SecretConfigurationError("Provider artifact canary set is incomplete")
    _verify_canary_rows(cipher, final, configured)
    for row in final:
        version = int(row["master_key_version"])
        if version not in configured:
            continue
        expected = "encrypt_decrypt" if version == active else "decrypt_only"
        if row["status"] != expected:
            raise SecretConfigurationError(
                "Provider artifact active key status differs from keyring"
            )


def decrypt_provider_artifact_dek(
    cipher: EnvelopeCipher, row: Mapping[str, Any]
) -> bytearray:
    project_id = row["project_id"]
    artifact_id = row["artifact_id"]
    created_at = row["created_at"]
    if not isinstance(project_id, UUID) or not isinstance(artifact_id, UUID):
        raise ProviderArtifactError("Provider artifact DEK identity is invalid")
    if not isinstance(created_at, datetime):
        raise ProviderArtifactError("Provider artifact DEK time is invalid")
    envelope = EncryptedSecretVersion(
        handle=SecretVersionHandle(
            reference_id=artifact_id,
            project_id=project_id,
            purpose=_DEK_PURPOSE,
            version=1,
        ),
        ciphertext=bytes(row["ciphertext"]),
        data_nonce=bytes(row["data_nonce"]),
        wrapped_data_key=bytes(row["wrapped_data_key"]),
        wrap_nonce=bytes(row["wrap_nonce"]),
        master_key_version=int(row["master_key_version"]),
        algorithm=str(row["algorithm"]),
        created_at=created_at,
    )
    material = bytearray(cipher.decrypt(envelope).reveal_bytes())
    if len(material) != 32:
        _wipe(material)
        raise ProviderArtifactError("Provider artifact DEK plaintext is invalid")
    return material


def _insert_artifact(
    connection: Any,
    bundle: StagedProviderArtifactBundle,
    artifact: StagedProviderArtifact,
) -> None:
    connection.execute(
        """INSERT INTO model_gateway_artifacts(
               bundle_id, kind, project_id, artifact_id, manifest_uri,
               manifest_hash, content_hash, payload_uri, payload_hash,
               content_byte_size, stored_byte_size, classification,
               encryption_algorithm, key_ref, expires_at
           ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                     %s, %s, %s, %s, %s, %s)""",
        (
            bundle.id,
            artifact.kind.value,
            bundle.project_id,
            artifact.artifact_id,
            artifact.manifest_uri,
            artifact.manifest_hash,
            artifact.content_hash,
            artifact.payload_uri,
            artifact.payload_hash,
            artifact.content_byte_size,
            artifact.stored_byte_size,
            artifact.classification,
            artifact.encryption_algorithm,
            artifact.key_reference,
            artifact.expires_at,
        ),
    )


def _bundle_matches(connection: Any, bundle: StagedProviderArtifactBundle) -> bool:
    rows = connection.execute(
        """SELECT kind, artifact_id, manifest_hash, content_hash, payload_hash, key_ref
           FROM model_gateway_artifacts
           WHERE project_id = %s AND bundle_id = %s ORDER BY kind""",
        (bundle.project_id, bundle.id),
    ).fetchall()
    expected = sorted(
        (
            item.kind.value,
            item.artifact_id,
            item.manifest_hash,
            item.content_hash,
            item.payload_hash,
            item.key_reference,
        )
        for item in bundle.artifacts
    )
    actual = [
        (
            row["kind"],
            row["artifact_id"],
            row["manifest_hash"],
            row["content_hash"],
            row["payload_hash"],
            row["key_ref"],
        )
        for row in rows
    ]
    return actual == expected


def _deletion_lease(
    connection: Any,
    row: Mapping[str, Any],
    *,
    now: datetime,
    lease_seconds: int,
) -> ProviderArtifactDeletionLease:
    project_id = row["project_id"]
    bundle_id = row["bundle_id"]
    if not isinstance(project_id, UUID) or not isinstance(bundle_id, UUID):
        raise ProviderArtifactError("Provider artifact deletion identity is invalid")
    set_project_scope(connection, project_id)
    artifacts = connection.execute(
        """SELECT * FROM model_gateway_artifacts
           WHERE project_id = %s AND bundle_id = %s ORDER BY kind""",
        (project_id, bundle_id),
    ).fetchall()
    return ProviderArtifactDeletionLease(
        outbox_id=row["id"],
        bundle_id=bundle_id,
        project_id=project_id,
        reason=ProviderArtifactDeletionReason(str(row["reason"])),
        lease_token=row["lease_token"],
        fencing_generation=int(row["fencing_generation"]),
        lease_expires_at=now + timedelta(seconds=lease_seconds),
        artifacts=tuple(_artifact_from_row(item) for item in artifacts),
    )


def _artifact_from_row(row: Mapping[str, Any]) -> StagedProviderArtifact:
    return StagedProviderArtifact(
        artifact_id=row["artifact_id"],
        kind=ProviderArtifactKind(str(row["kind"])),
        manifest_uri=str(row["manifest_uri"]),
        manifest_hash=str(row["manifest_hash"]),
        content_hash=str(row["content_hash"]),
        payload_uri=str(row["payload_uri"]),
        payload_hash=str(row["payload_hash"]),
        content_byte_size=int(row["content_byte_size"]),
        stored_byte_size=int(row["stored_byte_size"]),
        classification=str(row["classification"]),
        encryption_algorithm=str(row["encryption_algorithm"]),
        key_reference=row["key_ref"],
        expires_at=row["expires_at"],
    )


def _verify_canary_rows(
    cipher: EnvelopeCipher,
    rows: tuple[Mapping[str, Any], ...],
    configured: set[int],
) -> None:
    for row in rows:
        version = int(row["master_key_version"])
        if version not in configured:
            continue
        cipher.verify_canary(
            MasterKeyCanary(
                master_key_version=version,
                algorithm=str(row["algorithm"]),
                nonce=bytes(row["canary_nonce"]),
                ciphertext=bytes(row["canary_ciphertext"]),
            )
        )


def _environment_path() -> Path | None:
    value = os.getenv(PROVIDER_ARTIFACT_KEYRING_ENV, "").strip()
    return Path(value) if value else None


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Provider artifact lifecycle time must be timezone-aware")


def _wipe(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0


__all__ = [
    "PROVIDER_ARTIFACT_KEYRING_ENV",
    "PostgresProviderArtifactKeyVault",
    "PostgresProviderArtifactLifecycleRepository",
    "decrypt_provider_artifact_dek",
    "load_provider_artifact_keyring",
    "synchronize_provider_artifact_master_keys",
]
