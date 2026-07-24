"""PostgreSQL key, lineage and restore controls for Workflow C artifacts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from typing import Any
from uuid import UUID

import psycopg

from geo_core.model_gateway.identity import canonical_json_hash
from geo_core.project_scope import set_project_scope
from geo_core.sampling.contracts import SamplingRuleViolation
from geo_core.sampling.manual_artifact_governance import wipe_bytearray
from geo_core.sampling.manual_artifact_storage import (
    WorkflowCManualArtifactObjectStore,
    WorkflowCManualArtifactRecord,
    decrypt_workflow_c_artifact_payload,
    workflow_c_artifact_associated_data,
)
from geo_core.secrets import (
    EncryptedSecretVersion,
    EnvelopeCipher,
    MasterKeyCanary,
    SecretConfigurationError,
    SecretReference,
    SecretValue,
    SecretVersionHandle,
)


WORKFLOW_C_ARTIFACT_KEYRING_ENV = "GEO_WORKFLOW_C_ARTIFACT_KEYRING_FILE"
_DEK_PURPOSE = "workflow_c.manual_artifact_dek"


class PostgresWorkflowCArtifactKeyVault:
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
                synchronize_workflow_c_artifact_master_keys(connection, cipher)

    def __repr__(self) -> str:
        return "PostgresWorkflowCArtifactKeyVault([REDACTED])"

    def store_wrapped_key(
        self, *, project_id: UUID, artifact_id: UUID, key_material: bytearray
    ) -> UUID:
        if len(key_material) != 32:
            raise SamplingRuleViolation("Workflow C artifact DEK must be 256 bits")
        created_at = self._clock()
        _require_aware(created_at)
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
                    """INSERT INTO workflow_c_artifact_deks(
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
            raise SamplingRuleViolation(
                "Workflow C artifact DEK could not be durably wrapped"
            ) from exc
        return artifact_id

    def destroy_wrapped_key(self, *, project_id: UUID, key_reference: UUID) -> None:
        try:
            with self._connect() as connection:
                set_project_scope(connection, project_id)
                connection.execute(
                    """UPDATE workflow_c_artifact_deks
                       SET status = 'destroyed', ciphertext = NULL, data_nonce = NULL,
                           wrapped_data_key = NULL, wrap_nonce = NULL,
                           destroyed_at = clock_timestamp()
                       WHERE project_id = %s AND key_ref = %s AND status = 'active'""",
                    (project_id, key_reference),
                )
        except psycopg.Error as exc:
            raise SamplingRuleViolation("Workflow C artifact DEK could not be destroyed") from exc


class PostgresWorkflowCManualArtifactRepository:
    def __init__(self, *, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def stage(self, record: WorkflowCManualArtifactRecord) -> None:
        try:
            with self._connect() as connection:
                set_project_scope(connection, record.project_id)
                connection.execute(
                    """INSERT INTO workflow_c_manual_artifacts(
                           artifact_id, project_id, run_id, task_id,
                           capture_session_id, evidence_kind, source_content_type,
                           persisted_content_type, source_content_hash,
                           redacted_content_hash, object_uri, object_hash,
                           manifest_uri, manifest_hash, governance_policy_hash,
                           redactor_version_hash, scanner_version_hash,
                           pii_finding_count, secret_finding_count,
                           redaction_assurance, classification, audience,
                           export_allowed, raw_retained, retention_days, expires_at,
                           legal_hold, status, key_ref, encryption_algorithm,
                           stored_byte_size, created_at
                       ) VALUES (
                           %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, 'staged', %s, %s, %s, %s
                       )""",
                    (
                        record.artifact_id,
                        record.project_id,
                        record.run_id,
                        record.task_id,
                        record.capture_session_id,
                        record.evidence_kind,
                        record.source_content_type,
                        record.persisted_content_type,
                        record.source_content_hash,
                        record.redacted_content_hash,
                        record.object_uri,
                        record.object_hash,
                        record.manifest_uri,
                        record.manifest_hash,
                        record.governance_policy_hash,
                        record.redactor_version_hash,
                        record.scanner_version_hash,
                        record.pii_finding_count,
                        record.secret_finding_count,
                        record.redaction_assurance,
                        record.classification,
                        record.audience,
                        record.export_allowed,
                        record.raw_retained,
                        record.retention_days,
                        record.expires_at,
                        record.legal_hold,
                        record.key_reference,
                        record.encryption_algorithm,
                        record.stored_byte_size,
                        record.created_at,
                    ),
                )
        except psycopg.Error as exc:
            raise SamplingRuleViolation(
                "Workflow C manual artifact lineage could not be staged"
            ) from exc

    def activate(self, *, project_id: UUID, artifact_id: UUID) -> None:
        try:
            with self._connect() as connection:
                set_project_scope(connection, project_id)
                row = connection.execute(
                    """SELECT * FROM geo_activate_workflow_c_manual_artifact(
                           %s, %s
                       )""",
                    (project_id, artifact_id),
                ).fetchone()
                if row is None or row["artifact_id"] != artifact_id or row["status"] != "active":
                    raise SamplingRuleViolation(
                        "Workflow C manual artifact stage cannot be activated"
                    )
        except SamplingRuleViolation:
            raise
        except psycopg.Error as exc:
            raise SamplingRuleViolation("Workflow C manual artifact activation failed") from exc

    def queue_failed_stage_cleanup(self, *, project_id: UUID, artifact_id: UUID) -> None:
        try:
            with self._connect() as connection:
                set_project_scope(connection, project_id)
                row = connection.execute(
                    "SELECT * FROM geo_enqueue_workflow_c_artifact_write_failure(%s, %s)",
                    (project_id, artifact_id),
                ).fetchone()
                if row is None or row["artifact_id"] != artifact_id:
                    raise SamplingRuleViolation("Workflow C failed stage cleanup was not queued")
        except psycopg.Error as exc:
            raise SamplingRuleViolation(
                "Workflow C artifact failed stage cleanup could not be queued"
            ) from exc


@dataclass(frozen=True)
class WorkflowCArtifactRestoreVerification:
    verified_master_key_versions: tuple[int, ...]
    active_dek_count: int
    recoverable_artifact_count: int
    representative_artifact_verified: bool
    representative_artifact_id: UUID | None
    representative_manifest_hash: str | None
    verification_receipt_hash: str
    empty_artifact_domain: bool


def synchronize_workflow_c_artifact_master_keys(
    connection: Any,
    cipher: EnvelopeCipher,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> tuple[int, ...]:
    rows = tuple(
        connection.execute(
            """SELECT master_key_version, status, algorithm,
                      canary_nonce, canary_ciphertext, retired_at
               FROM workflow_c_artifact_master_key_versions
               ORDER BY master_key_version FOR UPDATE"""
        ).fetchall()
    )
    configured = set(cipher.master_key_versions)
    required = {int(row["master_key_version"]) for row in rows if row["status"] != "retired"}
    if required - configured:
        raise SecretConfigurationError(
            "Workflow C artifact keyring lacks a non-retired database key"
        )
    _verify_canary_rows(cipher, rows, configured)
    existing = {int(row["master_key_version"]) for row in rows}
    missing = configured - existing
    active = cipher.active_master_key_version
    if rows and missing not in (set(), {active}):
        raise SecretConfigurationError(
            "Workflow C artifact keyring history cannot be registered out of order"
        )
    if rows and missing == {active} and active <= max(existing):
        raise SecretConfigurationError("Workflow C artifact active key version must increase")
    now = clock()
    _require_aware(now)
    connection.execute(
        """UPDATE workflow_c_artifact_master_key_versions
           SET status = 'decrypt_only'
           WHERE status = 'encrypt_decrypt' AND master_key_version <> %s""",
        (active,),
    )
    for version in sorted(missing):
        canary = cipher.create_canary(version)
        connection.execute(
            """INSERT INTO workflow_c_artifact_master_key_versions(
                   master_key_version, status, algorithm, canary_nonce,
                   canary_ciphertext, created_at, retired_at
               ) VALUES (%s, %s, %s, %s, %s, %s, NULL)""",
            (
                version,
                "encrypt_decrypt" if version == active else "decrypt_only",
                canary.algorithm,
                canary.nonce,
                canary.ciphertext,
                now,
            ),
        )
    final = tuple(
        connection.execute(
            """SELECT master_key_version, status, algorithm,
                      canary_nonce, canary_ciphertext, retired_at
               FROM workflow_c_artifact_master_key_versions
               WHERE status <> 'retired' ORDER BY master_key_version"""
        ).fetchall()
    )
    if {int(row["master_key_version"]) for row in final} != configured:
        raise SecretConfigurationError("Workflow C artifact canary set does not cover the keyring")
    _verify_canary_rows(cipher, final, configured)
    active_rows = tuple(
        int(row["master_key_version"]) for row in final if row["status"] == "encrypt_decrypt"
    )
    if active_rows != (active,):
        raise SecretConfigurationError("Workflow C artifact active key differs from its canary")
    return tuple(sorted(configured))


def decrypt_workflow_c_artifact_dek(cipher: EnvelopeCipher, row: Mapping[str, Any]) -> bytearray:
    project_id = row["project_id"]
    artifact_id = row["artifact_id"]
    created_at = row["dek_created_at"] if "dek_created_at" in row else row["created_at"]
    if not isinstance(project_id, UUID) or not isinstance(artifact_id, UUID):
        raise SamplingRuleViolation("Workflow C artifact DEK identity is invalid")
    if not isinstance(created_at, datetime):
        raise SamplingRuleViolation("Workflow C artifact DEK time is invalid")
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
        algorithm=str(row["dek_algorithm"] if "dek_algorithm" in row else row["algorithm"]),
        created_at=created_at,
    )
    material = bytearray(cipher.decrypt(envelope).reveal_bytes())
    if len(material) != 32:
        wipe_bytearray(material)
        raise SamplingRuleViolation("Workflow C artifact DEK plaintext is invalid")
    return material


def verify_workflow_c_artifact_keyring_canaries(
    connection: Any, cipher: EnvelopeCipher
) -> tuple[int, ...]:
    rows = tuple(
        connection.execute(
            """SELECT master_key_version, status, algorithm,
                      canary_nonce, canary_ciphertext, retired_at
               FROM workflow_c_artifact_master_key_versions
               WHERE status <> 'retired' ORDER BY master_key_version"""
        ).fetchall()
    )
    return verify_workflow_c_artifact_keyring_canary_rows(cipher, rows)


def verify_workflow_c_artifact_keyring_canary_rows(
    cipher: EnvelopeCipher, rows: tuple[Mapping[str, Any], ...]
) -> tuple[int, ...]:
    """Verify non-retired canaries supplied by a restricted database reader.

    The Internal API must validate its Docker-Secret keyring before it encrypts
    governed evidence, but must not receive direct table access to global
    master-key metadata.  A constrained database RPC supplies these rows.
    """

    versions = tuple(int(row["master_key_version"]) for row in rows)
    if versions != cipher.master_key_versions:
        raise SecretConfigurationError(
            "Workflow C artifact keyring does not match non-retired canaries"
        )
    _verify_canary_rows(cipher, rows, set(versions))
    active_versions = tuple(
        int(row["master_key_version"]) for row in rows if row["status"] == "encrypt_decrypt"
    )
    if active_versions != (cipher.active_master_key_version,):
        raise SecretConfigurationError("Workflow C artifact active key differs from its canary")
    return versions


def verify_workflow_c_artifact_restore(
    *,
    connection: Any,
    cipher: EnvelopeCipher,
    object_store: WorkflowCManualArtifactObjectStore,
) -> WorkflowCArtifactRestoreVerification:
    versions = verify_workflow_c_artifact_keyring_canaries(connection, cipher)
    counts = connection.execute(
        """SELECT
               (SELECT count(*) FROM workflow_c_artifact_deks
                WHERE status = 'active') AS active_dek_count,
               (SELECT count(*)
                  FROM workflow_c_manual_artifacts artifact
                  JOIN workflow_c_artifact_deks dek
                    ON dek.key_ref = artifact.key_ref
                   AND dek.project_id = artifact.project_id
                   AND dek.artifact_id = artifact.artifact_id
                 WHERE artifact.status = 'active' AND dek.status = 'active'
               ) AS recoverable_artifact_count"""
    ).fetchone()
    active_deks = int(counts["active_dek_count"])
    recoverable = int(counts["recoverable_artifact_count"])
    if active_deks != recoverable:
        raise SamplingRuleViolation("Workflow C artifact restore found orphaned active key lineage")
    representative = connection.execute(
        """SELECT artifact.*,
                  dek.ciphertext, dek.data_nonce, dek.wrapped_data_key,
                  dek.wrap_nonce, dek.master_key_version,
                  dek.algorithm AS dek_algorithm, dek.created_at AS dek_created_at
             FROM workflow_c_manual_artifacts artifact
             JOIN workflow_c_artifact_deks dek
               ON dek.key_ref = artifact.key_ref
              AND dek.project_id = artifact.project_id
              AND dek.artifact_id = artifact.artifact_id
            WHERE artifact.status = 'active' AND dek.status = 'active'
            ORDER BY artifact.activated_at, artifact.artifact_id LIMIT 1"""
    ).fetchone()
    artifact_id: UUID | None = None
    manifest_hash: str | None = None
    verified = False
    if representative is not None:
        artifact_id = representative["artifact_id"]
        if not isinstance(artifact_id, UUID):
            raise SamplingRuleViolation(
                "Workflow C artifact restore representative identity is invalid"
            )
        manifest_hash = str(representative["manifest_hash"])
        manifest = object_store.get_s3_uri(
            uri=str(representative["manifest_uri"]),
            expected_hash=manifest_hash,
        )
        payload = object_store.get_s3_uri(
            uri=str(representative["object_uri"]),
            expected_hash=str(representative["object_hash"]),
        )
        validate_workflow_c_artifact_manifest(representative, manifest.content)
        key_material = bytearray()
        plaintext = bytearray()
        try:
            key_material = decrypt_workflow_c_artifact_dek(cipher, representative)
            plaintext = decrypt_workflow_c_artifact_payload(
                encrypted_payload=payload.content,
                key_material=key_material,
                associated_data=workflow_c_artifact_associated_data(
                    project_id=representative["project_id"],
                    artifact_id=artifact_id,
                    persisted_content_hash=str(representative["redacted_content_hash"]),
                    governance_policy_hash=str(representative["governance_policy_hash"]),
                ),
            )
            if hashlib.sha256(plaintext).hexdigest() != representative["redacted_content_hash"]:
                raise SamplingRuleViolation("Workflow C restored artifact content hash changed")
            verified = True
        finally:
            wipe_bytearray(key_material)
            wipe_bytearray(plaintext)
    if recoverable > 0 and not verified:
        raise SamplingRuleViolation("Workflow C artifact restore has no verified representative")
    empty = active_deks == 0 and recoverable == 0
    receipt_hash = canonical_json_hash(
        {
            "schema_version": 1,
            "verified_master_key_versions": versions,
            "active_dek_count": active_deks,
            "recoverable_artifact_count": recoverable,
            "representative_artifact_verified": verified,
            "representative_artifact_id": artifact_id,
            "representative_manifest_hash": manifest_hash,
            "empty_artifact_domain": empty,
        }
    )
    return WorkflowCArtifactRestoreVerification(
        verified_master_key_versions=versions,
        active_dek_count=active_deks,
        recoverable_artifact_count=recoverable,
        representative_artifact_verified=verified,
        representative_artifact_id=artifact_id,
        representative_manifest_hash=manifest_hash,
        verification_receipt_hash=receipt_hash,
        empty_artifact_domain=empty,
    )


def validate_workflow_c_artifact_manifest(row: Mapping[str, Any], content: bytes) -> None:
    if hashlib.sha256(content).hexdigest() != row["manifest_hash"]:
        raise SamplingRuleViolation("Workflow C artifact manifest hash changed")
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SamplingRuleViolation("Workflow C artifact manifest is invalid") from None
    if not isinstance(value, dict):
        raise SamplingRuleViolation("Workflow C artifact manifest shape is invalid")
    expected = {
        "artifact_id": str(row["artifact_id"]),
        "project_id": str(row["project_id"]),
        "persisted_content_hash": str(row["redacted_content_hash"]),
        "stored_object_hash": str(row["object_hash"]),
        "raw_retained": False,
        "export_allowed": False,
        "audience": "admin_only",
        "classification": "restricted_manual_evidence",
    }
    if any(value.get(key) != item for key, item in expected.items()):
        raise SamplingRuleViolation("Workflow C artifact manifest lineage changed")


def _verify_canary_rows(
    cipher: EnvelopeCipher,
    rows: tuple[Mapping[str, Any], ...],
    configured: set[int],
) -> None:
    for row in rows:
        version = int(row["master_key_version"])
        if version not in configured:
            continue
        if row["algorithm"] != "AES-256-GCM" or row["retired_at"] is not None:
            raise SecretConfigurationError("Workflow C artifact canary shape is invalid")
        cipher.verify_canary(
            MasterKeyCanary(
                master_key_version=version,
                algorithm=str(row["algorithm"]),
                nonce=bytes(row["canary_nonce"]),
                ciphertext=bytes(row["canary_ciphertext"]),
            )
        )


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SamplingRuleViolation("Workflow C artifact time must be timezone-aware")


__all__ = [
    "PostgresWorkflowCArtifactKeyVault",
    "PostgresWorkflowCManualArtifactRepository",
    "WORKFLOW_C_ARTIFACT_KEYRING_ENV",
    "WorkflowCArtifactRestoreVerification",
    "decrypt_workflow_c_artifact_dek",
    "synchronize_workflow_c_artifact_master_keys",
    "validate_workflow_c_artifact_manifest",
    "verify_workflow_c_artifact_restore",
    "verify_workflow_c_artifact_keyring_canary_rows",
    "verify_workflow_c_artifact_keyring_canaries",
]
