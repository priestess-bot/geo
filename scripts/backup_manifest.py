"""Signed manifest and commit protocol for encrypted GEO backup sets."""

from __future__ import annotations

import argparse
import base64
from collections.abc import Mapping
from datetime import UTC, datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import BinaryIO

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.alembic_sql_ledger import validate_ledger  # noqa: E402
from scripts.backup_envelope import (  # noqa: E402
    ALGORITHM,
    BackupKeyring,
    BackupSecurityError,
    atomic_write,
    canonical_json,
    decrypt_authenticated_to_stream,
    derive_manifest_signing_key,
    inspect_envelope,
    load_backup_keyring,
    read_canonical_json,
)
from scripts.non_b_business_consistency import (  # noqa: E402
    validate_business_consistency_manifest,
)


MANIFEST_SCHEMA = "geo-authenticated-backup-manifest-v5"
SIGNATURE_SCHEMA = "geo-backup-manifest-signature-v1"
COMMIT_SCHEMA = "geo-backup-commit-v1"
ARTIFACT_FILES = {
    "postgres": "postgres.sql.gz.enc",
    "minio": "minio.tar.enc",
}
CONTROL_FILES = frozenset({"manifest.json", "manifest.sig", "COMMITTED"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
CRITICAL_RELATIONS = frozenset(
    {"evidence_items", "monitoring_reports", "project_memberships"}
)
HASHED_RELATIONS = frozenset(
    {"evidence_items", "monitoring_reports", "project_memberships", "projects"}
)
MINIO_SOURCE_BUCKETS = frozenset(
    {
        "geo-artifacts",
        "geo-restricted-recommendation-artifacts",
        "geo-restricted-workflow-c-artifacts",
        "geo-synthetic-style-derived",
        "geo-synthetic-style-raw",
    }
)


def create_backup_set_manifest(
    backup_directory: Path,
    *,
    keyring: BackupKeyring,
    backup_id: str,
    created_at: str,
    migration_revision: str,
    alembic_sql_checksum_ledger: object,
    postgres_project_count: int,
    postgres_table_count: int,
    critical_relation_counts: Mapping[str, int],
    critical_relation_hashes: Mapping[str, str],
    non_b_business_consistency: object,
    minio_object_count: int,
    minio_bucket_object_counts: Mapping[str, int],
    secret_key_version_count: int,
    secret_version_count: int,
    representative_probe_target_count: int,
    provider_artifact_key_version_count: int,
    provider_active_dek_count: int,
    provider_recoverable_artifact_count: int,
    provider_representative_probe_target_count: int,
    synthetic_artifact_key_version_count: int,
    synthetic_active_dek_count: int,
    synthetic_nondeleted_artifact_count: int,
    synthetic_tier_key_artifact_count: int,
    synthetic_restricted_probe_target_count: int,
    synthetic_tier_probe_target_count: int,
    recommendation_artifact_key_version_count: int,
    recommendation_artifact_lineage_count: int,
    recommendation_representative_probe_target_count: int,
    recommendation_source_verification_receipt_hash: str,
    workflow_c_artifact_key_version_count: int,
    workflow_c_active_dek_count: int,
    workflow_c_recoverable_artifact_count: int,
    workflow_c_representative_probe_target_count: int,
    workflow_c_source_verification_receipt_hash: str,
) -> dict[str, object]:
    _require_secure_directory(backup_directory)
    canonical_created_at = _timestamp(created_at)
    if _REVISION.fullmatch(migration_revision) is None:
        raise BackupSecurityError("backup migration revision is invalid")
    counts = {
        "postgres project": postgres_project_count,
        "postgres table": postgres_table_count,
        "MinIO object": minio_object_count,
        "Secret Store key version": secret_key_version_count,
        "Secret Store encrypted version": secret_version_count,
        "representative secret probe target": representative_probe_target_count,
        "Provider artifact key version": provider_artifact_key_version_count,
        "Provider active DEK": provider_active_dek_count,
        "Provider recoverable artifact": provider_recoverable_artifact_count,
        "Provider representative probe target": (
            provider_representative_probe_target_count
        ),
        "Synthetic artifact key version": synthetic_artifact_key_version_count,
        "Synthetic active DEK": synthetic_active_dek_count,
        "Synthetic nondeleted artifact": synthetic_nondeleted_artifact_count,
        "Synthetic tier-key artifact": synthetic_tier_key_artifact_count,
        "Synthetic restricted probe target": synthetic_restricted_probe_target_count,
        "Synthetic tier probe target": synthetic_tier_probe_target_count,
        "Recommendation artifact key version": (
            recommendation_artifact_key_version_count
        ),
        "Recommendation artifact lineage": recommendation_artifact_lineage_count,
        "Recommendation representative probe target": (
            recommendation_representative_probe_target_count
        ),
        "Workflow C artifact key version": workflow_c_artifact_key_version_count,
        "Workflow C active DEK": workflow_c_active_dek_count,
        "Workflow C recoverable artifact": workflow_c_recoverable_artifact_count,
        "Workflow C representative probe target": (
            workflow_c_representative_probe_target_count
        ),
    }
    for label, value in counts.items():
        _nonnegative_int(value, label)
    if postgres_table_count < 1:
        raise BackupSecurityError("postgres table count must be positive")
    if secret_key_version_count < 1:
        raise BackupSecurityError("Secret Store key version count must be positive")
    if (
        (secret_version_count == 0 and representative_probe_target_count != 0)
        or (
            secret_version_count > 0
            and not 1
            <= representative_probe_target_count
            <= min(secret_version_count, secret_key_version_count)
        )
    ):
        raise BackupSecurityError("representative secret probe target is inconsistent")
    _validate_provider_artifact_source(
        master_key_version_count=provider_artifact_key_version_count,
        active_dek_count=provider_active_dek_count,
        recoverable_artifact_count=provider_recoverable_artifact_count,
        representative_probe_target_count=provider_representative_probe_target_count,
    )
    _validate_synthetic_artifact_source(
        master_key_version_count=synthetic_artifact_key_version_count,
        active_dek_count=synthetic_active_dek_count,
        nondeleted_artifact_count=synthetic_nondeleted_artifact_count,
        tier_key_artifact_count=synthetic_tier_key_artifact_count,
        restricted_probe_target_count=synthetic_restricted_probe_target_count,
        tier_probe_target_count=synthetic_tier_probe_target_count,
    )
    _validate_recommendation_artifact_source(
        master_key_version_count=recommendation_artifact_key_version_count,
        artifact_lineage_count=recommendation_artifact_lineage_count,
        representative_probe_target_count=(
            recommendation_representative_probe_target_count
        ),
        source_verification_receipt_hash=(
            recommendation_source_verification_receipt_hash
        ),
    )
    _validate_workflow_c_artifact_source(
        master_key_version_count=workflow_c_artifact_key_version_count,
        active_dek_count=workflow_c_active_dek_count,
        recoverable_artifact_count=workflow_c_recoverable_artifact_count,
        representative_probe_target_count=(
            workflow_c_representative_probe_target_count
        ),
        source_verification_receipt_hash=workflow_c_source_verification_receipt_hash,
    )
    relation_counts = _critical_relation_counts(critical_relation_counts)
    relation_hashes = _critical_relation_hashes(critical_relation_hashes)
    bucket_object_counts = _minio_bucket_object_counts(minio_bucket_object_counts)
    if sum(bucket_object_counts.values()) != minio_object_count:
        raise BackupSecurityError("MinIO bucket counts do not match total object count")
    migration_ledger = validate_ledger(alembic_sql_checksum_ledger)
    if migration_ledger["head_revision"] != migration_revision:
        raise BackupSecurityError("backup migration ledger does not match the database")
    business_consistency = validate_business_consistency_manifest(
        non_b_business_consistency,
        expected_revision=migration_revision,
    )

    artifacts: dict[str, object] = {}
    key_versions: set[int] = set()
    for artifact, filename in ARTIFACT_FILES.items():
        path = backup_directory / filename
        metadata = inspect_envelope(path)
        if metadata.backup_id != backup_id or metadata.artifact != artifact:
            raise BackupSecurityError("backup artifact scope is inconsistent")
        key_versions.add(metadata.key_version)
        artifacts[artifact] = {
            "artifact": artifact,
            "encrypted_sha256": metadata.encrypted_sha256,
            "encrypted_size": metadata.encrypted_size,
            "key_version": metadata.key_version,
            "path": filename,
        }
    if len(key_versions) != 1:
        raise BackupSecurityError("backup artifacts use different key versions")
    key_version = key_versions.pop()
    if key_version != keyring.active_version:
        raise BackupSecurityError("backup artifacts do not use the active backup key")

    manifest: dict[str, object] = {
        "algorithm": ALGORITHM,
        "artifacts": artifacts,
        "backup_id": backup_id,
        "created_at": canonical_created_at,
        "key_version": key_version,
        "schema_version": MANIFEST_SCHEMA,
        "source": {
            "minio": {
                "bucket_object_counts": bucket_object_counts,
                "object_count": minio_object_count,
            },
            "postgres": {
                "alembic_sql_checksum_ledger": migration_ledger,
                "migration_revision": migration_revision,
                "project_count": postgres_project_count,
                "table_count": postgres_table_count,
                "critical_relation_counts": relation_counts,
                "critical_relation_hashes": relation_hashes,
                "non_b_business_consistency": business_consistency,
            },
            "secret_store": {
                "encrypted_secret_version_count": secret_version_count,
                "master_key_version_count": secret_key_version_count,
                "representative_probe_target_count": representative_probe_target_count,
            },
            "provider_artifacts": {
                "active_dek_count": provider_active_dek_count,
                "master_key_version_count": provider_artifact_key_version_count,
                "recoverable_artifact_count": provider_recoverable_artifact_count,
                "representative_probe_target_count": (
                    provider_representative_probe_target_count
                ),
            },
            "recommendation_artifacts": {
                "artifact_lineage_count": recommendation_artifact_lineage_count,
                "master_key_version_count": (
                    recommendation_artifact_key_version_count
                ),
                "representative_probe_target_count": (
                    recommendation_representative_probe_target_count
                ),
                "source_verification_receipt_hash": (
                    recommendation_source_verification_receipt_hash
                ),
            },
            "synthetic_artifacts": {
                "active_dek_count": synthetic_active_dek_count,
                "master_key_version_count": synthetic_artifact_key_version_count,
                "nondeleted_artifact_count": synthetic_nondeleted_artifact_count,
                "restricted_probe_target_count": (
                    synthetic_restricted_probe_target_count
                ),
                "tier_key_artifact_count": synthetic_tier_key_artifact_count,
                "tier_probe_target_count": synthetic_tier_probe_target_count,
            },
            "workflow_c_artifacts": {
                "active_dek_count": workflow_c_active_dek_count,
                "master_key_version_count": workflow_c_artifact_key_version_count,
                "recoverable_artifact_count": workflow_c_recoverable_artifact_count,
                "representative_probe_target_count": (
                    workflow_c_representative_probe_target_count
                ),
                "source_verification_receipt_hash": (
                    workflow_c_source_verification_receipt_hash
                ),
            },
        },
    }
    manifest_bytes = canonical_json(manifest) + b"\n"
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    signature = hmac.new(
        derive_manifest_signing_key(keyring, key_version),
        manifest_bytes,
        hashlib.sha256,
    ).digest()
    signature_document = {
        "algorithm": "HMAC-SHA-256",
        "key_version": key_version,
        "manifest_sha256": manifest_hash,
        "schema_version": SIGNATURE_SCHEMA,
        "signature": base64.b64encode(signature).decode("ascii"),
    }
    signature_bytes = canonical_json(signature_document) + b"\n"
    commit = {
        "backup_id": backup_id,
        "manifest_sha256": manifest_hash,
        "schema_version": COMMIT_SCHEMA,
        "signature_sha256": hashlib.sha256(signature_bytes).hexdigest(),
    }
    atomic_write(backup_directory / "manifest.json", manifest_bytes)
    atomic_write(backup_directory / "manifest.sig", signature_bytes)
    atomic_write(backup_directory / "COMMITTED", canonical_json(commit) + b"\n")
    return manifest


def verify_backup_set(
    backup_directory: Path,
    *,
    keyring: BackupKeyring,
) -> dict[str, object]:
    _require_secure_directory(backup_directory)
    expected_names = set(ARTIFACT_FILES.values()) | set(CONTROL_FILES)
    try:
        names = {item.name for item in backup_directory.iterdir()}
    except OSError:
        raise BackupSecurityError("backup directory cannot be enumerated") from None
    if names != expected_names:
        raise BackupSecurityError("backup set is incomplete or contains unexpected files")

    commit = read_canonical_json(backup_directory / "COMMITTED", label="backup commit")
    signature = read_canonical_json(
        backup_directory / "manifest.sig", label="backup manifest signature"
    )
    manifest_path = backup_directory / "manifest.json"
    manifest = read_canonical_json(manifest_path, label="backup manifest")
    _require_exact_fields(
        commit,
        {"backup_id", "manifest_sha256", "schema_version", "signature_sha256"},
        "backup commit",
    )
    _require_exact_fields(
        signature,
        {"algorithm", "key_version", "manifest_sha256", "schema_version", "signature"},
        "backup manifest signature",
    )
    _require_exact_fields(
        manifest,
        {
            "algorithm", "artifacts", "backup_id", "created_at", "key_version",
            "schema_version", "source",
        },
        "backup manifest",
    )
    if commit["schema_version"] != COMMIT_SCHEMA:
        raise BackupSecurityError("backup commit format is unsupported")
    if signature["schema_version"] != SIGNATURE_SCHEMA:
        raise BackupSecurityError("backup signature format is unsupported")
    if manifest["schema_version"] != MANIFEST_SCHEMA or manifest["algorithm"] != ALGORITHM:
        raise BackupSecurityError("backup manifest format is unsupported")

    manifest_bytes = manifest_path.read_bytes()
    signature_bytes = (backup_directory / "manifest.sig").read_bytes()
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    signature_hash = hashlib.sha256(signature_bytes).hexdigest()
    backup_id = _string(manifest.get("backup_id"), "backup ID")
    key_version = _positive_int(manifest.get("key_version"), "backup key version")
    if (
        commit.get("backup_id") != backup_id
        or commit.get("manifest_sha256") != manifest_hash
        or commit.get("signature_sha256") != signature_hash
        or signature.get("manifest_sha256") != manifest_hash
        or signature.get("key_version") != key_version
        or signature.get("algorithm") != "HMAC-SHA-256"
    ):
        raise BackupSecurityError("backup commit or signature lineage is invalid")
    supplied_signature = _signature_bytes(signature.get("signature"))
    expected_signature = hmac.new(
        derive_manifest_signing_key(keyring, key_version),
        manifest_bytes,
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(supplied_signature, expected_signature):
        raise BackupSecurityError("backup manifest authentication failed")
    _verify_manifest_shape(manifest)

    artifacts = manifest["artifacts"]
    assert isinstance(artifacts, dict)
    for artifact, filename in ARTIFACT_FILES.items():
        entry = artifacts[artifact]
        assert isinstance(entry, dict)
        path = backup_directory / filename
        metadata = inspect_envelope(path)
        if (
            entry.get("artifact") != artifact
            or entry.get("path") != filename
            or entry.get("key_version") != metadata.key_version
            or entry.get("encrypted_sha256") != metadata.encrypted_sha256
            or entry.get("encrypted_size") != metadata.encrypted_size
            or metadata.backup_id != backup_id
            or metadata.artifact != artifact
        ):
            raise BackupSecurityError("backup artifact does not match manifest")
    return manifest


def decrypt_backup_artifact(
    backup_directory: Path,
    artifact: str,
    destination: BinaryIO,
    *,
    keyring: BackupKeyring,
    staging_directory: Path,
) -> None:
    if artifact not in ARTIFACT_FILES:
        raise BackupSecurityError("backup artifact is unsupported")
    manifest = verify_backup_set(backup_directory, keyring=keyring)
    artifacts = manifest["artifacts"]
    assert isinstance(artifacts, dict)
    artifact_metadata = artifacts[artifact]
    assert isinstance(artifact_metadata, dict)
    decrypt_authenticated_to_stream(
        backup_directory / ARTIFACT_FILES[artifact],
        destination,
        keyring=keyring,
        expected_backup_id=_string(manifest["backup_id"], "backup ID"),
        expected_artifact=artifact,
        staging_directory=staging_directory,
        expected_encrypted_sha256=_string(
            artifact_metadata["encrypted_sha256"], "artifact checksum"
        ),
        expected_encrypted_size=_positive_int(
            artifact_metadata["encrypted_size"], "artifact size"
        ),
    )


def _verify_manifest_shape(manifest: dict[str, object]) -> None:
    _timestamp(_string(manifest.get("created_at"), "backup creation time"))
    source = manifest.get("source")
    artifacts = manifest.get("artifacts")
    if not isinstance(source, dict) or set(source) != {
        "minio",
        "postgres",
        "provider_artifacts",
        "recommendation_artifacts",
        "secret_store",
        "synthetic_artifacts",
        "workflow_c_artifacts",
    }:
        raise BackupSecurityError("backup source manifest is invalid")
    if not isinstance(artifacts, dict) or set(artifacts) != set(ARTIFACT_FILES):
        raise BackupSecurityError("backup artifact manifest is invalid")
    expected_sources = {
        "minio": {"bucket_object_counts", "object_count"},
        "postgres": {
            "alembic_sql_checksum_ledger",
            "critical_relation_counts",
            "critical_relation_hashes",
            "migration_revision",
            "non_b_business_consistency",
            "project_count",
            "table_count",
        },
        "secret_store": {
            "encrypted_secret_version_count",
            "master_key_version_count",
            "representative_probe_target_count",
        },
        "provider_artifacts": {
            "active_dek_count",
            "master_key_version_count",
            "recoverable_artifact_count",
            "representative_probe_target_count",
        },
        "recommendation_artifacts": {
            "artifact_lineage_count",
            "master_key_version_count",
            "representative_probe_target_count",
            "source_verification_receipt_hash",
        },
        "synthetic_artifacts": {
            "active_dek_count",
            "master_key_version_count",
            "nondeleted_artifact_count",
            "restricted_probe_target_count",
            "tier_key_artifact_count",
            "tier_probe_target_count",
        },
        "workflow_c_artifacts": {
            "active_dek_count",
            "master_key_version_count",
            "recoverable_artifact_count",
            "representative_probe_target_count",
            "source_verification_receipt_hash",
        },
    }
    for name, fields in expected_sources.items():
        entry = source[name]
        if not isinstance(entry, dict) or set(entry) != fields:
            raise BackupSecurityError("backup source manifest is invalid")
        for field, value in entry.items():
            if field not in {
                "alembic_sql_checksum_ledger",
                "critical_relation_counts",
                "critical_relation_hashes",
                "migration_revision",
                "non_b_business_consistency",
                "source_verification_receipt_hash",
                "bucket_object_counts",
            }:
                _nonnegative_int(value, f"{name} {field}")
    postgres = source["postgres"]
    minio_source = source["minio"]
    secret_store = source["secret_store"]
    provider_artifacts = source["provider_artifacts"]
    recommendation_artifacts = source["recommendation_artifacts"]
    synthetic_artifacts = source["synthetic_artifacts"]
    workflow_c_artifacts = source["workflow_c_artifacts"]
    assert (
        isinstance(postgres, dict)
        and isinstance(minio_source, dict)
        and isinstance(secret_store, dict)
        and isinstance(provider_artifacts, dict)
        and isinstance(recommendation_artifacts, dict)
        and isinstance(synthetic_artifacts, dict)
        and isinstance(workflow_c_artifacts, dict)
    )
    migration = _string(postgres["migration_revision"], "migration revision")
    if _REVISION.fullmatch(migration) is None or postgres["table_count"] < 1:
        raise BackupSecurityError("postgres source manifest is invalid")
    migration_ledger = validate_ledger(postgres["alembic_sql_checksum_ledger"])
    if migration_ledger["head_revision"] != migration:
        raise BackupSecurityError("postgres migration ledger does not match revision")
    relation_counts = postgres["critical_relation_counts"]
    if not isinstance(relation_counts, dict):
        raise BackupSecurityError("postgres critical relation counts are invalid")
    _critical_relation_counts(relation_counts)
    relation_hashes = postgres["critical_relation_hashes"]
    if not isinstance(relation_hashes, dict):
        raise BackupSecurityError("postgres critical relation hashes are invalid")
    _critical_relation_hashes(relation_hashes)
    validate_business_consistency_manifest(
        postgres["non_b_business_consistency"],
        expected_revision=migration,
    )
    bucket_object_counts = _minio_bucket_object_counts(
        minio_source["bucket_object_counts"]
    )
    if sum(bucket_object_counts.values()) != minio_source["object_count"]:
        raise BackupSecurityError("MinIO source bucket counts are inconsistent")
    secret_count = secret_store["encrypted_secret_version_count"]
    if secret_store["master_key_version_count"] < 1:
        raise BackupSecurityError("Secret Store key canary coverage is empty")
    probe_count = secret_store["representative_probe_target_count"]
    if (
        (secret_count == 0 and probe_count != 0)
        or (
            secret_count > 0
            and not (
                1
                <= probe_count
                <= min(secret_count, secret_store["master_key_version_count"])
            )
        )
    ):
        raise BackupSecurityError("representative probe target is inconsistent")
    _validate_provider_artifact_source(
        master_key_version_count=provider_artifacts["master_key_version_count"],
        active_dek_count=provider_artifacts["active_dek_count"],
        recoverable_artifact_count=provider_artifacts["recoverable_artifact_count"],
        representative_probe_target_count=provider_artifacts[
            "representative_probe_target_count"
        ],
    )
    _validate_synthetic_artifact_source(
        master_key_version_count=synthetic_artifacts["master_key_version_count"],
        active_dek_count=synthetic_artifacts["active_dek_count"],
        nondeleted_artifact_count=synthetic_artifacts["nondeleted_artifact_count"],
        tier_key_artifact_count=synthetic_artifacts["tier_key_artifact_count"],
        restricted_probe_target_count=synthetic_artifacts[
            "restricted_probe_target_count"
        ],
        tier_probe_target_count=synthetic_artifacts["tier_probe_target_count"],
    )
    _validate_recommendation_artifact_source(
        master_key_version_count=recommendation_artifacts[
            "master_key_version_count"
        ],
        artifact_lineage_count=recommendation_artifacts["artifact_lineage_count"],
        representative_probe_target_count=recommendation_artifacts[
            "representative_probe_target_count"
        ],
        source_verification_receipt_hash=recommendation_artifacts[
            "source_verification_receipt_hash"
        ],
    )
    _validate_workflow_c_artifact_source(
        master_key_version_count=workflow_c_artifacts["master_key_version_count"],
        active_dek_count=workflow_c_artifacts["active_dek_count"],
        recoverable_artifact_count=workflow_c_artifacts[
            "recoverable_artifact_count"
        ],
        representative_probe_target_count=workflow_c_artifacts[
            "representative_probe_target_count"
        ],
        source_verification_receipt_hash=workflow_c_artifacts[
            "source_verification_receipt_hash"
        ],
    )
    for artifact, filename in ARTIFACT_FILES.items():
        entry = artifacts[artifact]
        if not isinstance(entry, dict):
            raise BackupSecurityError("backup artifact manifest is invalid")
        _require_exact_fields(
            entry,
            {"artifact", "encrypted_sha256", "encrypted_size", "key_version", "path"},
            "backup artifact manifest",
        )
        if (
            entry["artifact"] != artifact
            or entry["path"] != filename
            or _SHA256.fullmatch(_string(entry["encrypted_sha256"], "artifact checksum")) is None
        ):
            raise BackupSecurityError("backup artifact manifest is invalid")
        _positive_int(entry["encrypted_size"], "artifact size")
        _positive_int(entry["key_version"], "artifact key version")


def _require_exact_fields(value: Mapping[str, object], fields: set[str], label: str) -> None:
    if set(value) != fields:
        raise BackupSecurityError(f"{label} structure is invalid")


def _critical_relation_counts(value: Mapping[str, object]) -> dict[str, int]:
    if set(value) != set(CRITICAL_RELATIONS):
        raise BackupSecurityError("postgres critical relation counts are invalid")
    return {
        name: _nonnegative_int(value[name], f"{name} relation count")
        for name in sorted(CRITICAL_RELATIONS)
    }


def _critical_relation_hashes(value: Mapping[str, object]) -> dict[str, str]:
    if set(value) != set(HASHED_RELATIONS):
        raise BackupSecurityError("postgres critical relation hashes are invalid")
    hashes: dict[str, str] = {}
    for name in sorted(HASHED_RELATIONS):
        digest = value[name]
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise BackupSecurityError("postgres critical relation hashes are invalid")
        hashes[name] = digest
    return hashes


def _minio_bucket_object_counts(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != set(MINIO_SOURCE_BUCKETS):
        raise BackupSecurityError("MinIO source bucket counts are invalid")
    return {
        bucket: _nonnegative_int(value[bucket], f"{bucket} object count")
        for bucket in sorted(MINIO_SOURCE_BUCKETS)
    }


def _validate_provider_artifact_source(
    *,
    master_key_version_count: object,
    active_dek_count: object,
    recoverable_artifact_count: object,
    representative_probe_target_count: object,
) -> None:
    master_keys = _positive_int(
        master_key_version_count, "Provider artifact master key version count"
    )
    active_deks = _nonnegative_int(active_dek_count, "Provider active DEK count")
    recoverable = _nonnegative_int(
        recoverable_artifact_count, "Provider recoverable artifact count"
    )
    target = _nonnegative_int(
        representative_probe_target_count, "Provider representative probe target"
    )
    if master_keys < 1 or recoverable > active_deks or target != (1 if recoverable else 0):
        raise BackupSecurityError("Provider artifact recovery source is inconsistent")


def _validate_synthetic_artifact_source(
    *,
    master_key_version_count: object,
    active_dek_count: object,
    nondeleted_artifact_count: object,
    tier_key_artifact_count: object,
    restricted_probe_target_count: object,
    tier_probe_target_count: object,
) -> None:
    master_keys = _positive_int(
        master_key_version_count, "Synthetic artifact master key version count"
    )
    active_deks = _nonnegative_int(active_dek_count, "Synthetic active DEK count")
    nondeleted = _nonnegative_int(
        nondeleted_artifact_count, "Synthetic nondeleted artifact count"
    )
    tier_artifacts = _nonnegative_int(
        tier_key_artifact_count, "Synthetic tier-key artifact count"
    )
    restricted_target = _nonnegative_int(
        restricted_probe_target_count, "Synthetic restricted probe target"
    )
    tier_target = _nonnegative_int(tier_probe_target_count, "Synthetic tier probe target")
    if (
        master_keys < 1
        or active_deks + tier_artifacts != nondeleted
        or restricted_target != (1 if active_deks else 0)
        or tier_target != (1 if tier_artifacts else 0)
    ):
        raise BackupSecurityError("Synthetic artifact recovery source is inconsistent")


def _validate_recommendation_artifact_source(
    *,
    master_key_version_count: object,
    artifact_lineage_count: object,
    representative_probe_target_count: object,
    source_verification_receipt_hash: object,
) -> None:
    master_keys = _positive_int(
        master_key_version_count, "Recommendation artifact master key version count"
    )
    lineage_count = _nonnegative_int(
        artifact_lineage_count, "Recommendation artifact lineage count"
    )
    target = _nonnegative_int(
        representative_probe_target_count,
        "Recommendation representative probe target",
    )
    if (
        master_keys < 1
        or target != (1 if lineage_count else 0)
        or not isinstance(source_verification_receipt_hash, str)
        or _SHA256.fullmatch(source_verification_receipt_hash) is None
    ):
        raise BackupSecurityError("Recommendation artifact recovery source is inconsistent")


def _validate_workflow_c_artifact_source(
    *,
    master_key_version_count: object,
    active_dek_count: object,
    recoverable_artifact_count: object,
    representative_probe_target_count: object,
    source_verification_receipt_hash: object,
) -> None:
    master_keys = _positive_int(
        master_key_version_count, "Workflow C artifact master key version count"
    )
    active_deks = _nonnegative_int(active_dek_count, "Workflow C active DEK count")
    recoverable = _nonnegative_int(
        recoverable_artifact_count, "Workflow C recoverable artifact count"
    )
    target = _nonnegative_int(
        representative_probe_target_count, "Workflow C representative probe target"
    )
    if (
        master_keys < 1
        or active_deks != recoverable
        or target != (1 if recoverable else 0)
        or not isinstance(source_verification_receipt_hash, str)
        or _SHA256.fullmatch(source_verification_receipt_hash) is None
    ):
        raise BackupSecurityError("Workflow C artifact recovery source is inconsistent")


def _relation_counts_json(value: str) -> dict[str, int]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        raise BackupSecurityError("postgres critical relation counts are invalid") from None
    if not isinstance(parsed, dict):
        raise BackupSecurityError("postgres critical relation counts are invalid")
    return _critical_relation_counts(parsed)


def _relation_hashes_json(value: str) -> dict[str, str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        raise BackupSecurityError("postgres critical relation hashes are invalid") from None
    if not isinstance(parsed, dict):
        raise BackupSecurityError("postgres critical relation hashes are invalid")
    return _critical_relation_hashes(parsed)


def _json_value(value: str, label: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        raise BackupSecurityError(f"{label} is invalid") from None


def _timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise BackupSecurityError("backup timestamp is invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BackupSecurityError("backup timestamp must include timezone")
    return parsed.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _signature_bytes(value: object) -> bytes:
    if not isinstance(value, str):
        raise BackupSecurityError("backup signature is invalid")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        raise BackupSecurityError("backup signature is invalid") from None
    if len(decoded) != 32 or base64.b64encode(decoded).decode("ascii") != value:
        raise BackupSecurityError("backup signature is invalid")
    return decoded


def _positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise BackupSecurityError(f"{label} is invalid")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise BackupSecurityError(f"{label} is invalid")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise BackupSecurityError(f"{label} is invalid")
    return value


def _require_secure_directory(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError:
        raise BackupSecurityError("backup directory is unavailable") from None
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid not in {0, os.geteuid()}
    ):
        raise BackupSecurityError("backup directory permissions are invalid")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create or verify an authenticated backup set.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--keyring", type=Path, required=True)
    create.add_argument("--backup-dir", type=Path, required=True)
    create.add_argument("--backup-id", required=True)
    create.add_argument("--created-at", required=True)
    create.add_argument("--migration-revision", required=True)
    create.add_argument("--alembic-sql-checksum-ledger-json", required=True)
    create.add_argument("--postgres-project-count", type=int, required=True)
    create.add_argument("--postgres-table-count", type=int, required=True)
    create.add_argument("--critical-relation-counts-json", required=True)
    create.add_argument("--critical-relation-hashes-json", required=True)
    create.add_argument("--non-b-business-consistency-json", required=True)
    create.add_argument("--minio-object-count", type=int, required=True)
    create.add_argument("--minio-bucket-object-counts-json", required=True)
    create.add_argument("--secret-key-version-count", type=int, required=True)
    create.add_argument("--secret-version-count", type=int, required=True)
    create.add_argument("--representative-probe-target-count", type=int, required=True)
    create.add_argument("--provider-artifact-key-version-count", type=int, required=True)
    create.add_argument("--provider-active-dek-count", type=int, required=True)
    create.add_argument("--provider-recoverable-artifact-count", type=int, required=True)
    create.add_argument("--provider-representative-probe-target-count", type=int, required=True)
    create.add_argument("--synthetic-artifact-key-version-count", type=int, required=True)
    create.add_argument("--synthetic-active-dek-count", type=int, required=True)
    create.add_argument("--synthetic-nondeleted-artifact-count", type=int, required=True)
    create.add_argument("--synthetic-tier-key-artifact-count", type=int, required=True)
    create.add_argument("--synthetic-restricted-probe-target-count", type=int, required=True)
    create.add_argument("--synthetic-tier-probe-target-count", type=int, required=True)
    create.add_argument("--recommendation-artifact-key-version-count", type=int, required=True)
    create.add_argument("--recommendation-artifact-lineage-count", type=int, required=True)
    create.add_argument(
        "--recommendation-representative-probe-target-count", type=int, required=True
    )
    create.add_argument(
        "--recommendation-source-verification-receipt-hash", required=True
    )
    create.add_argument("--workflow-c-artifact-key-version-count", type=int, required=True)
    create.add_argument("--workflow-c-active-dek-count", type=int, required=True)
    create.add_argument("--workflow-c-recoverable-artifact-count", type=int, required=True)
    create.add_argument(
        "--workflow-c-representative-probe-target-count", type=int, required=True
    )
    create.add_argument("--workflow-c-source-verification-receipt-hash", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--keyring", type=Path, required=True)
    verify.add_argument("--backup-dir", type=Path, required=True)
    decrypt = subparsers.add_parser("decrypt")
    decrypt.add_argument("--keyring", type=Path, required=True)
    decrypt.add_argument("--backup-dir", type=Path, required=True)
    decrypt.add_argument("--artifact", choices=tuple(ARTIFACT_FILES), required=True)
    decrypt.add_argument("--staging-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        keyring = load_backup_keyring(args.keyring)
        if args.command == "create":
            manifest = create_backup_set_manifest(
                args.backup_dir,
                keyring=keyring,
                backup_id=args.backup_id,
                created_at=args.created_at,
                migration_revision=args.migration_revision,
                alembic_sql_checksum_ledger=_json_value(
                    args.alembic_sql_checksum_ledger_json,
                    "Alembic SQL checksum ledger",
                ),
                postgres_project_count=args.postgres_project_count,
                postgres_table_count=args.postgres_table_count,
                critical_relation_counts=_relation_counts_json(
                    args.critical_relation_counts_json
                ),
                critical_relation_hashes=_relation_hashes_json(
                    args.critical_relation_hashes_json
                ),
                non_b_business_consistency=_json_value(
                    args.non_b_business_consistency_json,
                    "non-B business consistency manifest",
                ),
                minio_object_count=args.minio_object_count,
                minio_bucket_object_counts=_minio_bucket_object_counts(
                    _json_value(
                        args.minio_bucket_object_counts_json,
                        "MinIO bucket object counts",
                    )
                ),
                secret_key_version_count=args.secret_key_version_count,
                secret_version_count=args.secret_version_count,
                representative_probe_target_count=args.representative_probe_target_count,
                provider_artifact_key_version_count=(
                    args.provider_artifact_key_version_count
                ),
                provider_active_dek_count=args.provider_active_dek_count,
                provider_recoverable_artifact_count=(
                    args.provider_recoverable_artifact_count
                ),
                provider_representative_probe_target_count=(
                    args.provider_representative_probe_target_count
                ),
                synthetic_artifact_key_version_count=(
                    args.synthetic_artifact_key_version_count
                ),
                synthetic_active_dek_count=args.synthetic_active_dek_count,
                synthetic_nondeleted_artifact_count=(
                    args.synthetic_nondeleted_artifact_count
                ),
                synthetic_tier_key_artifact_count=(
                    args.synthetic_tier_key_artifact_count
                ),
                synthetic_restricted_probe_target_count=(
                    args.synthetic_restricted_probe_target_count
                ),
                synthetic_tier_probe_target_count=(
                    args.synthetic_tier_probe_target_count
                ),
                recommendation_artifact_key_version_count=(
                    args.recommendation_artifact_key_version_count
                ),
                recommendation_artifact_lineage_count=(
                    args.recommendation_artifact_lineage_count
                ),
                recommendation_representative_probe_target_count=(
                    args.recommendation_representative_probe_target_count
                ),
                recommendation_source_verification_receipt_hash=(
                    args.recommendation_source_verification_receipt_hash
                ),
                workflow_c_artifact_key_version_count=(
                    args.workflow_c_artifact_key_version_count
                ),
                workflow_c_active_dek_count=args.workflow_c_active_dek_count,
                workflow_c_recoverable_artifact_count=(
                    args.workflow_c_recoverable_artifact_count
                ),
                workflow_c_representative_probe_target_count=(
                    args.workflow_c_representative_probe_target_count
                ),
                workflow_c_source_verification_receipt_hash=(
                    args.workflow_c_source_verification_receipt_hash
                ),
            )
            print(canonical_json(manifest).decode("ascii"))
        elif args.command == "verify":
            manifest = verify_backup_set(args.backup_dir, keyring=keyring)
            print(canonical_json(manifest).decode("ascii"))
        else:
            decrypt_backup_artifact(
                args.backup_dir,
                args.artifact,
                sys.stdout.buffer,
                keyring=keyring,
                staging_directory=args.staging_dir,
            )
        return 0
    except (BackupSecurityError, OSError):
        print("backup security error: backup set verification failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
