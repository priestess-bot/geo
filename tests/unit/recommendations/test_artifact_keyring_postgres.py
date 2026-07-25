from __future__ import annotations

from datetime import UTC, datetime

import pytest

from geo_core.recommendations.artifact_keyring_postgres import (
    synchronize_recommendation_artifact_key_canaries,
    verify_recommendation_artifact_restore,
)
from geo_core.recommendations.generation_artifacts import (
    EncryptedRecommendationTaskArtifactStore,
)
from geo_core.secrets import (
    EnvelopeCipher,
    MasterKeyring,
    SecretConfigurationError,
    SecretDecryptionError,
)

from .test_generation_artifacts import _Objects, _task


class _Cursor:
    def __init__(self, *, rows=(), row=None) -> None:
        self.rows = rows
        self.row = row

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.row


class _Connection:
    def __init__(self, canaries, *, representative=None) -> None:
        self.canaries = canaries
        self.representative = representative

    def execute(self, query, params=None):
        del params
        if "recommendation_artifact_master_key_versions" in query:
            return _Cursor(rows=self.canaries)
        if "count(*) AS count" in query:
            return _Cursor(row={"count": 1 if self.representative else 0})
        if "JOIN recommendation_model_call_lineage AS lineage" in query:
            return _Cursor(row=self.representative)
        raise AssertionError(query)


def test_restore_query_reads_encrypted_task_metadata_from_task_table() -> None:
    source = verify_recommendation_artifact_restore.__code__.co_consts
    queries = tuple(value for value in source if isinstance(value, str))
    restore_query = next(
        query
        for query in queries
        if "task.task_artifact_manifest_hash" in query
    )

    assert "FROM recommendation_model_tasks AS task" in restore_query
    assert "JOIN recommendation_model_call_lineage AS lineage" in restore_query
    assert "lineage.task_artifact_manifest_hash" not in restore_query


class _CanaryConnection:
    def __init__(self, rows=()) -> None:
        self.rows = {
            int(row["master_key_version"]): dict(row)
            for row in rows
        }

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        if normalized == "SELECT pg_advisory_xact_lock(185613921, 1)":
            return _Cursor()
        if normalized.startswith("SELECT master_key_version"):
            rows = tuple(
                dict(self.rows[version])
                for version in sorted(self.rows)
                if "WHERE status <> 'retired'" not in normalized
                or self.rows[version]["status"] != "retired"
            )
            return _Cursor(rows=rows)
        if normalized.startswith("UPDATE recommendation_artifact_master_key_versions SET status = 'decrypt_only'"):
            active = int(params[0])
            for row in self.rows.values():
                if row["status"] == "encrypt_decrypt" and row["master_key_version"] != active:
                    row["status"] = "decrypt_only"
            return _Cursor()
        if normalized.startswith("INSERT INTO recommendation_artifact_master_key_versions"):
            version, status, algorithm, nonce, ciphertext, created_at = params
            self.rows[int(version)] = {
                "master_key_version": int(version),
                "status": status,
                "algorithm": algorithm,
                "canary_nonce": nonce,
                "canary_ciphertext": ciphertext,
                "created_at": created_at,
                "retired_at": None,
            }
            return _Cursor()
        if normalized.startswith("UPDATE recommendation_artifact_master_key_versions SET status = %s"):
            status, version = params
            if self.rows[int(version)]["status"] != "retired":
                self.rows[int(version)]["status"] = status
            return _Cursor()
        raise AssertionError(normalized)


def test_canary_sync_registers_history_and_rotates_the_only_active_version() -> None:
    first = _cipher(b"r" * 32)
    connection = _CanaryConnection()

    assert synchronize_recommendation_artifact_key_canaries(
        connection,
        cipher=first,
    ) == (1,)
    assert connection.rows[1]["status"] == "encrypt_decrypt"

    rotated = EnvelopeCipher(
        MasterKeyring(keys={1: b"r" * 32, 2: b"R" * 32}, active_version=2)
    )
    assert synchronize_recommendation_artifact_key_canaries(
        connection,
        cipher=rotated,
    ) == (1, 2)
    assert connection.rows[1]["status"] == "decrypt_only"
    assert connection.rows[2]["status"] == "encrypt_decrypt"


def test_canary_sync_rejects_missing_required_history_and_retired_key_reuse() -> None:
    original = _cipher(b"r" * 32)
    canary = original.create_canary(1)
    row = {
        "master_key_version": 1,
        "status": "encrypt_decrypt",
        "algorithm": canary.algorithm,
        "canary_nonce": canary.nonce,
        "canary_ciphertext": canary.ciphertext,
        "retired_at": None,
    }

    with pytest.raises(SecretConfigurationError, match="lacks a non-retired database key"):
        synchronize_recommendation_artifact_key_canaries(
            _CanaryConnection((row,)),
            cipher=EnvelopeCipher(
                MasterKeyring(keys={2: b"R" * 32}, active_version=2)
            ),
        )

    retired = {**row, "status": "retired", "retired_at": datetime.now(UTC)}
    with pytest.raises(SecretConfigurationError, match="cannot be unretired"):
        synchronize_recommendation_artifact_key_canaries(
            _CanaryConnection((retired,)),
            cipher=original,
        )


def test_restore_verifies_all_key_canaries_and_one_typed_encrypted_task() -> None:
    cipher = _cipher(b"r" * 32)
    objects = _Objects()
    artifacts = EncryptedRecommendationTaskArtifactStore(
        object_store=objects,
        cipher=cipher,
        clock=lambda: datetime(2026, 7, 23, 12, 0, tzinfo=UTC),
    )
    task = _task()
    reference = artifacts.put(task)
    canary = cipher.create_canary(1)
    connection = _Connection(
        (
            {
                "master_key_version": 1,
                "status": "encrypt_decrypt",
                "algorithm": canary.algorithm,
                "canary_nonce": canary.nonce,
                "canary_ciphertext": canary.ciphertext,
                "retired_at": None,
            },
        ),
        representative={
            "project_id": task.project_id,
            "parent_job_id": task.parent_job_id,
            "child_job_id": task.child_job_id,
            "parent_input_hash": task.parent_input_hash,
            "task_artifact_uri": reference.uri,
            "task_artifact_manifest_hash": reference.manifest_hash,
            "task_artifact_payload_uri": reference.payload_uri,
            "task_payload_hash": reference.payload_hash,
            "task_artifact_content_hash": reference.content_hash,
            "task_artifact_byte_size": reference.byte_size,
        },
    )

    result = verify_recommendation_artifact_restore(
        connection=connection,
        cipher=cipher,
        artifacts=artifacts,
    )

    assert result.verified_master_key_versions == (1,)
    assert result.artifact_lineage_count == 1
    assert result.representative_artifact_verified is True
    assert result.representative_child_job_id == task.child_job_id
    assert result.empty_artifact_domain is False
    assert len(result.verification_receipt_hash) == 64
    assert "Approved summary" not in repr(result)


def test_restore_fails_with_wrong_key_and_accepts_canary_covered_empty_domain() -> None:
    original = _cipher(b"r" * 32)
    canary = original.create_canary(1)
    canary_rows = (
        {
            "master_key_version": 1,
            "status": "encrypt_decrypt",
            "algorithm": canary.algorithm,
            "canary_nonce": canary.nonce,
            "canary_ciphertext": canary.ciphertext,
            "retired_at": None,
        },
    )
    objects = _Objects()
    wrong = _cipher(b"w" * 32)

    with pytest.raises(SecretDecryptionError):
        verify_recommendation_artifact_restore(
            connection=_Connection(canary_rows),
            cipher=wrong,
            artifacts=EncryptedRecommendationTaskArtifactStore(
                object_store=objects,
                cipher=wrong,
            ),
        )

    empty = verify_recommendation_artifact_restore(
        connection=_Connection(canary_rows),
        cipher=original,
        artifacts=EncryptedRecommendationTaskArtifactStore(
            object_store=objects,
            cipher=original,
        ),
    )
    assert empty.empty_artifact_domain is True
    assert empty.representative_artifact_verified is False


def _cipher(key: bytes) -> EnvelopeCipher:
    return EnvelopeCipher(
        MasterKeyring(keys={1: key}, active_version=1),
        random_bytes=lambda size: bytes(range(1, size + 1)),
    )
