"""Recommendation artifact key canaries and restore verification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from geo_core.model_gateway.identity import canonical_json_hash
from geo_core.recommendations.generation_artifacts import (
    RecommendationTaskArtifactRef,
    RecommendationTaskArtifactStore,
)
from geo_core.secrets import EnvelopeCipher, MasterKeyCanary, SecretConfigurationError


@dataclass(frozen=True)
class RecommendationArtifactRestoreVerification:
    verified_master_key_versions: tuple[int, ...]
    artifact_lineage_count: int
    representative_artifact_verified: bool
    representative_child_job_id: UUID | None
    representative_manifest_hash: str | None
    verification_receipt_hash: str
    empty_artifact_domain: bool


def synchronize_recommendation_artifact_key_canaries(
    connection: Any,
    *,
    cipher: EnvelopeCipher,
    clock=lambda: datetime.now(UTC),
) -> tuple[int, ...]:
    """Create/verify every configured canary and freeze one active key version."""

    now = clock()
    if now.tzinfo is None or now.utcoffset() is None:
        raise SecretConfigurationError("Recommendation artifact canary clock is invalid")
    rows = tuple(
        connection.execute(
            """SELECT master_key_version, status, algorithm,
                      canary_nonce, canary_ciphertext, retired_at
               FROM recommendation_artifact_master_key_versions
               ORDER BY master_key_version FOR UPDATE"""
        ).fetchall()
    )
    configured = cipher.master_key_versions
    non_retired = tuple(
        int(row["master_key_version"])
        for row in rows
        if row["status"] != "retired"
    )
    if any(version not in configured for version in non_retired):
        raise SecretConfigurationError(
            "Recommendation artifact keyring lacks a non-retired database key"
        )
    connection.execute(
        """UPDATE recommendation_artifact_master_key_versions
           SET status = 'decrypt_only'
           WHERE status = 'encrypt_decrypt' AND master_key_version <> %s""",
        (cipher.active_master_key_version,),
    )
    existing = {int(row["master_key_version"]): row for row in rows}
    for version in configured:
        row = existing.get(version)
        expected_status = (
            "encrypt_decrypt"
            if version == cipher.active_master_key_version
            else "decrypt_only"
        )
        if row is None:
            canary = cipher.create_canary(version)
            connection.execute(
                """INSERT INTO recommendation_artifact_master_key_versions(
                       master_key_version, status, algorithm, canary_nonce,
                       canary_ciphertext, created_at, retired_at
                   ) VALUES (%s, %s, %s, %s, %s, %s, NULL)""",
                (
                    version,
                    expected_status,
                    canary.algorithm,
                    canary.nonce,
                    canary.ciphertext,
                    now,
                ),
            )
            continue
        if row["status"] == "retired":
            raise SecretConfigurationError(
                "Recommendation artifact key version cannot be unretired"
            )
        _verify_canary(cipher, row)
        if row["status"] != expected_status:
            connection.execute(
                """UPDATE recommendation_artifact_master_key_versions
                   SET status = %s
                   WHERE master_key_version = %s AND status <> 'retired'""",
                (expected_status, version),
            )
    final = tuple(
        connection.execute(
            """SELECT master_key_version, status, algorithm,
                      canary_nonce, canary_ciphertext, retired_at
               FROM recommendation_artifact_master_key_versions
               WHERE status <> 'retired' ORDER BY master_key_version"""
        ).fetchall()
    )
    _verify_keyring_rows(cipher, final)
    return tuple(int(row["master_key_version"]) for row in final)


def verify_recommendation_artifact_restore(
    *,
    connection: Any,
    cipher: EnvelopeCipher,
    artifacts: RecommendationTaskArtifactStore,
) -> RecommendationArtifactRestoreVerification:
    """Verify key coverage and one encrypted task without exposing its content."""

    canaries = tuple(
        connection.execute(
            """SELECT master_key_version, status, algorithm,
                      canary_nonce, canary_ciphertext, retired_at
               FROM recommendation_artifact_master_key_versions
               WHERE status <> 'retired' ORDER BY master_key_version"""
        ).fetchall()
    )
    _verify_keyring_rows(cipher, canaries)
    count_row = connection.execute(
        """SELECT count(*) AS count
           FROM recommendation_model_tasks AS task
           JOIN recommendation_model_call_lineage AS lineage
             ON lineage.project_id = task.project_id
            AND lineage.child_job_id = task.child_job_id
           WHERE task.task_artifact_status = 'active'
             AND task.task_artifact_expires_at > clock_timestamp()
             AND lineage.task_artifact_status = 'active'
             AND lineage.task_artifact_expires_at > clock_timestamp()"""
    ).fetchone()
    count = int(count_row["count"])
    representative = connection.execute(
        """SELECT task.project_id, task.parent_job_id, task.child_job_id,
                  task.parent_input_hash, task.task_artifact_uri,
                  task.task_artifact_manifest_hash,
                  task.task_artifact_payload_uri, task.task_payload_hash,
                  task.task_artifact_content_hash, task.task_artifact_byte_size
           FROM recommendation_model_tasks AS task
           JOIN recommendation_model_call_lineage AS lineage
             ON lineage.project_id = task.project_id
            AND lineage.child_job_id = task.child_job_id
           WHERE task.task_artifact_status = 'active'
             AND task.task_artifact_expires_at > clock_timestamp()
             AND lineage.task_artifact_status = 'active'
             AND lineage.task_artifact_expires_at > clock_timestamp()
           ORDER BY task.created_at, task.project_id, task.child_job_id LIMIT 1"""
    ).fetchone()
    child_job_id: UUID | None = None
    manifest_hash: str | None = None
    verified = False
    if representative is not None:
        child_job_id = representative["child_job_id"]
        if not isinstance(child_job_id, UUID):
            raise SecretConfigurationError(
                "Recommendation restore representative Job ID is invalid"
            )
        manifest_hash = str(representative["task_artifact_manifest_hash"])
        task = artifacts.load(
            RecommendationTaskArtifactRef(
                uri=str(representative["task_artifact_uri"]),
                manifest_hash=manifest_hash,
                payload_uri=str(representative["task_artifact_payload_uri"]),
                payload_hash=str(representative["task_payload_hash"]),
                content_hash=str(representative["task_artifact_content_hash"]),
                byte_size=int(representative["task_artifact_byte_size"]),
            ),
            project_id=representative["project_id"],
            child_job_id=child_job_id,
            expected_parent_input_hash=str(representative["parent_input_hash"]),
        )
        if task.parent_job_id != representative["parent_job_id"]:
            raise SecretConfigurationError(
                "Recommendation restore representative parent lineage changed"
            )
        verified = True
    if count > 0 and not verified:
        raise SecretConfigurationError(
            "Recommendation artifact restore has no verified representative"
        )
    empty = count == 0
    receipt_hash = canonical_json_hash(
        {
            "schema_version": 1,
            "verified_master_key_versions": tuple(
                int(row["master_key_version"]) for row in canaries
            ),
            "active_master_key_version": cipher.active_master_key_version,
            "artifact_lineage_count": count,
            "representative_artifact_verified": verified,
            "representative_child_job_id": child_job_id,
            "representative_manifest_hash": manifest_hash,
            "empty_artifact_domain": empty,
        }
    )
    return RecommendationArtifactRestoreVerification(
        verified_master_key_versions=tuple(
            int(row["master_key_version"]) for row in canaries
        ),
        artifact_lineage_count=count,
        representative_artifact_verified=verified,
        representative_child_job_id=child_job_id,
        representative_manifest_hash=manifest_hash,
        verification_receipt_hash=receipt_hash,
        empty_artifact_domain=empty,
    )


def _verify_keyring_rows(cipher: EnvelopeCipher, rows: tuple[Any, ...]) -> None:
    versions = tuple(int(row["master_key_version"]) for row in rows)
    if versions != cipher.master_key_versions:
        raise SecretConfigurationError(
            "Recommendation artifact canaries do not cover the configured keyring"
        )
    active = tuple(
        int(row["master_key_version"])
        for row in rows
        if row["status"] == "encrypt_decrypt"
    )
    if active != (cipher.active_master_key_version,):
        raise SecretConfigurationError(
            "Recommendation artifact active key differs from its canary"
        )
    for row in rows:
        _verify_canary(cipher, row)


def _verify_canary(cipher: EnvelopeCipher, row: Any) -> None:
    if row["algorithm"] != "AES-256-GCM" or row["retired_at"] is not None:
        raise SecretConfigurationError("Recommendation artifact canary shape is invalid")
    cipher.verify_canary(
        MasterKeyCanary(
            master_key_version=int(row["master_key_version"]),
            algorithm=str(row["algorithm"]),
            nonce=bytes(row["canary_nonce"]),
            ciphertext=bytes(row["canary_ciphertext"]),
        )
    )


__all__ = [
    "RecommendationArtifactRestoreVerification",
    "synchronize_recommendation_artifact_key_canaries",
    "verify_recommendation_artifact_restore",
]
