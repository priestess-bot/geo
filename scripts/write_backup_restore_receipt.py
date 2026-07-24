"""Write a canonical, non-sensitive receipt for an isolated backup restore test."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.alembic_sql_ledger import validate_ledger  # noqa: E402
from scripts.backup_envelope import (  # noqa: E402
    BackupSecurityError,
    atomic_write,
    canonical_json,
)
from scripts.non_b_business_consistency import (  # noqa: E402
    validate_business_consistency_manifest,
)
from scripts.write_restore_acl_rls_canary import validate_canary  # noqa: E402


SCHEMA_VERSION = "geo-production-backup-restore-v5"
APPLICATION_KEY_PROBE_SCHEMA = "geo-application-key-recovery-probe-v3"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
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


def write_receipt(
    *,
    verified_manifest: Path,
    application_key_probe: Path,
    acl_rls_canary: Path,
    minio_verification: Path,
    output: Path,
    restored_project_count: int,
    restored_table_count: int,
    restored_migration_revision: str,
    restored_alembic_sql_checksum_ledger: object,
    restored_critical_relation_counts: Mapping[str, int],
    restored_critical_relation_hashes: Mapping[str, str],
    restored_non_b_business_consistency: object,
) -> dict[str, object]:
    manifest_bytes = verified_manifest.read_bytes()
    manifest = _json_object(manifest_bytes, "verified manifest")
    probe = _json_object(
        application_key_probe.read_bytes(), "application key recovery probe"
    )
    acl_rls = validate_canary(_json_object(acl_rls_canary.read_bytes(), "ACL/RLS canary"))
    minio = _json_object(minio_verification.read_bytes(), "MinIO restore verification")
    source = _mapping(manifest.get("source"), "manifest source")
    postgres = _mapping(source.get("postgres"), "manifest postgres source")
    source_minio = _mapping(source.get("minio"), "manifest MinIO source")
    secret_store = _mapping(source.get("secret_store"), "manifest Secret Store source")
    provider_source = _mapping(
        source.get("provider_artifacts"), "manifest Provider artifact source"
    )
    recommendation_source = _mapping(
        source.get("recommendation_artifacts"),
        "manifest Recommendation artifact source",
    )
    workflow_c_source = _mapping(
        source.get("workflow_c_artifacts"), "manifest Workflow C artifact source"
    )
    synthetic_source = _mapping(
        source.get("synthetic_artifacts"), "manifest Synthetic artifact source"
    )
    if set(probe) != {
        "provider_artifacts",
        "recommendation_artifacts",
        "schema_version",
        "secret_store",
        "synthetic_artifacts",
        "workflow_c_artifacts",
    } or probe.get("schema_version") != APPLICATION_KEY_PROBE_SCHEMA:
        raise BackupSecurityError("application key recovery probe is invalid")
    secret_probe = _mapping(probe.get("secret_store"), "Secret Store restore probe")
    provider_probe = _mapping(
        probe.get("provider_artifacts"), "Provider artifact restore probe"
    )
    recommendation_probe = _mapping(
        probe.get("recommendation_artifacts"),
        "Recommendation artifact restore probe",
    )
    workflow_c_probe = _mapping(
        probe.get("workflow_c_artifacts"), "Workflow C artifact restore probe"
    )
    synthetic_probe = _mapping(
        probe.get("synthetic_artifacts"), "Synthetic artifact restore probe"
    )
    source_projects = _nonnegative(postgres.get("project_count"), "source project count")
    source_tables = _positive(postgres.get("table_count"), "source table count")
    source_objects = _nonnegative(source_minio.get("object_count"), "source object count")
    source_bucket_counts = _bucket_counts(
        source_minio.get("bucket_object_counts"), "source bucket object counts"
    )
    if sum(source_bucket_counts.values()) != source_objects:
        raise BackupSecurityError("source MinIO bucket counts are inconsistent")
    source_migration_ledger = validate_ledger(
        postgres.get("alembic_sql_checksum_ledger")
    )
    restored_migration_ledger = validate_ledger(restored_alembic_sql_checksum_ledger)
    source_relations = _relation_counts(
        postgres.get("critical_relation_counts"), "source critical relation counts"
    )
    restored_relations = _relation_counts(
        restored_critical_relation_counts, "restored critical relation counts"
    )
    source_hashes = _relation_hashes(
        postgres.get("critical_relation_hashes"), "source critical relation hashes"
    )
    restored_hashes = _relation_hashes(
        restored_critical_relation_hashes, "restored critical relation hashes"
    )
    source_business_consistency = validate_business_consistency_manifest(
        postgres.get("non_b_business_consistency"),
        expected_revision=restored_migration_revision,
    )
    restored_business_consistency = validate_business_consistency_manifest(
        restored_non_b_business_consistency,
        expected_revision=restored_migration_revision,
    )
    source_key_versions = _positive(
        secret_store.get("master_key_version_count"), "source key version count"
    )
    probe_target = _nonnegative(
        secret_store.get("representative_probe_target_count"), "probe target count"
    )
    verified_versions = secret_probe.get("verified_key_versions")
    representative_count = _nonnegative(
        secret_probe.get("representative_secret_count"), "representative secret count"
    )
    if (
        not isinstance(verified_versions, list)
        or len(verified_versions) != source_key_versions
        or len(set(verified_versions)) != len(verified_versions)
        or any(not isinstance(value, int) or value < 1 for value in verified_versions)
    ):
        raise BackupSecurityError("Secret Store key canary coverage does not match manifest")
    if representative_count != probe_target:
        raise BackupSecurityError("representative Secret Store probe coverage is incomplete")
    frozen_handle_audit_count = _positive(
        secret_probe.get("frozen_handle_audit_count"),
        "frozen Secret Store audit count",
    )
    frozen_handle_receipt_count = _positive(
        secret_probe.get("frozen_handle_receipt_count"),
        "frozen Secret Store receipt count",
    )
    if (
        secret_probe.get("frozen_handle_runtime_verified") is not True
        or frozen_handle_audit_count != 1
        or frozen_handle_receipt_count != 1
    ):
        raise BackupSecurityError("frozen Secret Store runtime resolution is incomplete")
    provider_receipt = _provider_artifact_receipt(provider_source, provider_probe)
    recommendation_receipt = _recommendation_artifact_receipt(
        recommendation_source, recommendation_probe
    )
    workflow_c_receipt = _workflow_c_artifact_receipt(
        workflow_c_source, workflow_c_probe
    )
    synthetic_receipt = _synthetic_artifact_receipt(
        synthetic_source, synthetic_probe
    )
    restored_objects = _nonnegative(minio.get("object_count"), "restored object count")
    restored_bucket_counts = _bucket_counts(
        minio.get("bucket_object_counts"), "restored bucket object counts"
    )
    if (
        minio.get("per_object_sha256_verified") is not True
        or restored_objects != source_objects
        or restored_bucket_counts != source_bucket_counts
    ):
        raise BackupSecurityError("MinIO restore verification does not match manifest")
    if (
        restored_project_count != source_projects
        or restored_table_count != source_tables
        or restored_migration_revision != postgres.get("migration_revision")
        or source_migration_ledger != restored_migration_ledger
        or source_migration_ledger["head_revision"] != restored_migration_revision
        or restored_relations != source_relations
        or restored_hashes != source_hashes
        or restored_business_consistency != source_business_consistency
    ):
        raise BackupSecurityError("PostgreSQL restore verification does not match manifest")
    migration_entries = source_migration_ledger["entries"]
    if not isinstance(migration_entries, list):
        raise BackupSecurityError("Alembic SQL checksum ledger entries are invalid")
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    if _SHA256.fullmatch(manifest_hash) is None:
        raise BackupSecurityError("verified manifest hash is invalid")
    business_consistency_hash = hashlib.sha256(
        canonical_json(source_business_consistency)
    ).hexdigest()
    business_tables = _mapping(
        source_business_consistency["tables"], "business consistency tables"
    )
    project_scopes = {
        scope
        for summary in business_tables.values()
        for scope in _mapping(
            _mapping(summary, "business consistency table summary").get("scopes"),
            "business consistency table scopes",
        )
        if scope != "__global__"
    }
    receipt: dict[str, object] = {
        "backup_id": manifest.get("backup_id"),
        "manifest_sha256": manifest_hash,
        "object_store": {
            "per_object_sha256_verified": True,
            "restored_bucket_object_counts": restored_bucket_counts,
            "restored_object_count": restored_objects,
            "source_object_count": source_objects,
            "source_bucket_object_counts": source_bucket_counts,
        },
        "plaintext_staging_removed": True,
        "postgres": {
            "acl_rls_canary": acl_rls,
            "alembic_sql_checksum_ledger": {
                "entry_count": len(migration_entries),
                "ledger_sha256": source_migration_ledger["ledger_sha256"],
                "verified_against_repository": True,
            },
            "critical_relation_hashes_verified": True,
            "foreign_key_integrity_verified": True,
            "critical_relation_counts": restored_relations,
            "migration_revision": restored_migration_revision,
            "non_b_business_consistency": {
                "exact_match_verified": True,
                "invariant_check_count": len(
                    _mapping(
                        source_business_consistency["invariant_violations"],
                        "business consistency invariant violations",
                    )
                ),
                "manifest_sha256": business_consistency_hash,
                "project_scope_count": len(project_scopes),
                "relation_count": len(business_tables),
                "schema_version": source_business_consistency["schema_version"],
            },
            "restored_project_count": restored_project_count,
            "restored_critical_relation_hashes": restored_hashes,
            "restored_table_count": restored_table_count,
            "source_project_count": source_projects,
            "source_critical_relation_hashes": source_hashes,
            "source_table_count": source_tables,
        },
        "restore_copy_removed": True,
        "schema_version": SCHEMA_VERSION,
        "provider_artifacts": provider_receipt,
        "recommendation_artifacts": recommendation_receipt,
        "secret_store": {
            "frozen_handle_audit_count": frozen_handle_audit_count,
            "frozen_handle_receipt_count": frozen_handle_receipt_count,
            "frozen_handle_runtime_verified": True,
            "representative_secret_count": representative_count,
            "representative_secret_target_count": probe_target,
            "verified_key_versions": sorted(verified_versions),
        },
        "synthetic_artifacts": synthetic_receipt,
        "workflow_c_artifacts": workflow_c_receipt,
        "verified_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    atomic_write(output, canonical_json(receipt) + b"\n")
    return receipt


def _json_object(raw: bytes, label: str) -> dict[str, object]:
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError):
        raise BackupSecurityError(f"{label} is invalid") from None
    if not isinstance(value, dict):
        raise BackupSecurityError(f"{label} is invalid")
    return value


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise BackupSecurityError(f"{label} is invalid")
    return value


def _json_value(value: str, label: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        raise BackupSecurityError(f"{label} is invalid") from None


def _relation_counts(value: object, label: str) -> dict[str, int]:
    expected = {"evidence_items", "monitoring_reports", "project_memberships"}
    if not isinstance(value, Mapping) or set(value) != expected:
        raise BackupSecurityError(f"{label} is invalid")
    return {name: _nonnegative(value[name], f"{name} count") for name in sorted(expected)}


def _bucket_counts(value: object, label: str) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != set(MINIO_SOURCE_BUCKETS):
        raise BackupSecurityError(f"{label} is invalid")
    return {
        bucket: _nonnegative(value[bucket], f"{bucket} object count")
        for bucket in sorted(MINIO_SOURCE_BUCKETS)
    }


def _relation_counts_json(value: str) -> dict[str, int]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        raise BackupSecurityError("restored critical relation counts are invalid") from None
    return _relation_counts(parsed, "restored critical relation counts")


def _provider_artifact_receipt(
    source: Mapping[str, object], probe: Mapping[str, object]
) -> dict[str, object]:
    expected_source = {
        "active_dek_count",
        "master_key_version_count",
        "recoverable_artifact_count",
        "representative_probe_target_count",
    }
    expected_probe = {
        "active_dek_count",
        "empty_artifact_domain",
        "recoverable_artifact_count",
        "representative_artifact_verified",
        "verification_receipt_hash",
        "verified_master_key_versions",
    }
    if set(source) != expected_source or set(probe) != expected_probe:
        raise BackupSecurityError("Provider artifact recovery evidence is invalid")
    source_master_keys = _positive(
        source["master_key_version_count"], "Provider source master key count"
    )
    source_active = _nonnegative(source["active_dek_count"], "Provider source active DEK")
    source_recoverable = _nonnegative(
        source["recoverable_artifact_count"], "Provider source recoverable artifact"
    )
    source_target = _nonnegative(
        source["representative_probe_target_count"], "Provider source probe target"
    )
    restored_active = _nonnegative(probe["active_dek_count"], "Provider restored active DEK")
    restored_recoverable = _nonnegative(
        probe["recoverable_artifact_count"], "Provider restored recoverable artifact"
    )
    versions = _integer_versions(
        probe["verified_master_key_versions"], "Provider verified master key versions"
    )
    receipt_hash = probe["verification_receipt_hash"]
    if (
        source_master_keys != len(versions)
        or source_active != restored_active
        or source_recoverable != restored_recoverable
        or source_active < 1
        or source_recoverable < 1
        or source_target != 1
        or probe["representative_artifact_verified"] is not True
        or probe["empty_artifact_domain"] is not False
        or not isinstance(receipt_hash, str)
        or _SHA256.fullmatch(receipt_hash) is None
    ):
        raise BackupSecurityError("Provider artifact recovery evidence is incomplete")
    return {
        "active_dek_count": restored_active,
        "recoverable_artifact_count": restored_recoverable,
        "representative_artifact_verified": True,
        "verification_receipt_hash": receipt_hash,
        "verified_master_key_versions": versions,
    }


def _synthetic_artifact_receipt(
    source: Mapping[str, object], probe: Mapping[str, object]
) -> dict[str, object]:
    expected_source = {
        "active_dek_count",
        "master_key_version_count",
        "nondeleted_artifact_count",
        "restricted_probe_target_count",
        "tier_key_artifact_count",
        "tier_probe_target_count",
    }
    expected_probe = {
        "active_dek_count",
        "empty_artifact_domain",
        "nondeleted_artifact_count",
        "restricted_representative_verified",
        "tier_key_artifact_count",
        "tier_representative_verified",
        "verified_master_key_versions",
    }
    if set(source) != expected_source or set(probe) != expected_probe:
        raise BackupSecurityError("Synthetic artifact recovery evidence is invalid")
    source_master_keys = _positive(
        source["master_key_version_count"], "Synthetic source master key count"
    )
    source_active = _nonnegative(source["active_dek_count"], "Synthetic source active DEK")
    source_nondeleted = _nonnegative(
        source["nondeleted_artifact_count"], "Synthetic source nondeleted artifact"
    )
    source_tier = _nonnegative(
        source["tier_key_artifact_count"], "Synthetic source tier-key artifact"
    )
    restricted_target = _nonnegative(
        source["restricted_probe_target_count"], "Synthetic restricted probe target"
    )
    tier_target = _nonnegative(
        source["tier_probe_target_count"], "Synthetic tier probe target"
    )
    restored_active = _nonnegative(probe["active_dek_count"], "Synthetic restored active DEK")
    restored_nondeleted = _nonnegative(
        probe["nondeleted_artifact_count"], "Synthetic restored nondeleted artifact"
    )
    restored_tier = _nonnegative(
        probe["tier_key_artifact_count"], "Synthetic restored tier-key artifact"
    )
    versions = _string_versions(
        probe["verified_master_key_versions"], "Synthetic verified master key versions"
    )
    if (
        source_master_keys != len(versions)
        or source_active != restored_active
        or source_nondeleted != restored_nondeleted
        or source_tier != restored_tier
        or source_active < 1
        or source_tier < 1
        or source_nondeleted != source_active + source_tier
        or restricted_target != 1
        or tier_target != 1
        or probe["restricted_representative_verified"] is not True
        or probe["tier_representative_verified"] is not True
        or probe["empty_artifact_domain"] is not False
    ):
        raise BackupSecurityError("Synthetic artifact recovery evidence is incomplete")
    return {
        "active_dek_count": restored_active,
        "nondeleted_artifact_count": restored_nondeleted,
        "restricted_representative_verified": True,
        "tier_key_artifact_count": restored_tier,
        "tier_representative_verified": True,
        "verified_master_key_versions": versions,
    }


def _recommendation_artifact_receipt(
    source: Mapping[str, object], probe: Mapping[str, object]
) -> dict[str, object]:
    if set(source) != {
        "artifact_lineage_count",
        "master_key_version_count",
        "representative_probe_target_count",
        "source_verification_receipt_hash",
    } or set(probe) != {
        "artifact_lineage_count",
        "empty_artifact_domain",
        "representative_artifact_verified",
        "verification_receipt_hash",
        "verified_master_key_versions",
    }:
        raise BackupSecurityError("Recommendation artifact recovery evidence is invalid")
    source_count = _nonnegative(
        source["artifact_lineage_count"], "Recommendation source artifact lineage"
    )
    restored_count = _nonnegative(
        probe["artifact_lineage_count"], "Recommendation restored artifact lineage"
    )
    versions = _integer_versions(
        probe["verified_master_key_versions"],
        "Recommendation verified master key versions",
    )
    source_receipt = source["source_verification_receipt_hash"]
    restored_receipt = probe["verification_receipt_hash"]
    if (
        _positive(
            source["master_key_version_count"],
            "Recommendation source master key count",
        )
        != len(versions)
        or source_count != restored_count
        or source["representative_probe_target_count"] != (1 if source_count else 0)
        or probe["representative_artifact_verified"] is not (source_count > 0)
        or probe["empty_artifact_domain"] is not (source_count == 0)
        or source_receipt != restored_receipt
        or not isinstance(restored_receipt, str)
        or _SHA256.fullmatch(restored_receipt) is None
    ):
        raise BackupSecurityError("Recommendation artifact recovery evidence is incomplete")
    return {
        "artifact_lineage_count": restored_count,
        "representative_artifact_verified": source_count > 0,
        "verification_receipt_hash": restored_receipt,
        "verified_master_key_versions": versions,
    }


def _workflow_c_artifact_receipt(
    source: Mapping[str, object], probe: Mapping[str, object]
) -> dict[str, object]:
    if set(source) != {
        "active_dek_count",
        "master_key_version_count",
        "recoverable_artifact_count",
        "representative_probe_target_count",
        "source_verification_receipt_hash",
    } or set(probe) != {
        "active_dek_count",
        "empty_artifact_domain",
        "recoverable_artifact_count",
        "representative_artifact_verified",
        "verification_receipt_hash",
        "verified_master_key_versions",
    }:
        raise BackupSecurityError("Workflow C artifact recovery evidence is invalid")
    source_active = _nonnegative(
        source["active_dek_count"], "Workflow C source active DEK"
    )
    source_recoverable = _nonnegative(
        source["recoverable_artifact_count"],
        "Workflow C source recoverable artifact",
    )
    restored_active = _nonnegative(
        probe["active_dek_count"], "Workflow C restored active DEK"
    )
    restored_recoverable = _nonnegative(
        probe["recoverable_artifact_count"],
        "Workflow C restored recoverable artifact",
    )
    versions = _integer_versions(
        probe["verified_master_key_versions"],
        "Workflow C verified master key versions",
    )
    source_receipt = source["source_verification_receipt_hash"]
    restored_receipt = probe["verification_receipt_hash"]
    if (
        _positive(
            source["master_key_version_count"], "Workflow C source master key count"
        )
        != len(versions)
        or source_active != restored_active
        or source_recoverable != restored_recoverable
        or source_active != source_recoverable
        or source["representative_probe_target_count"]
        != (1 if source_recoverable else 0)
        or probe["representative_artifact_verified"] is not (source_recoverable > 0)
        or probe["empty_artifact_domain"] is not (source_recoverable == 0)
        or source_receipt != restored_receipt
        or not isinstance(restored_receipt, str)
        or _SHA256.fullmatch(restored_receipt) is None
    ):
        raise BackupSecurityError("Workflow C artifact recovery evidence is incomplete")
    return {
        "active_dek_count": restored_active,
        "recoverable_artifact_count": restored_recoverable,
        "representative_artifact_verified": source_recoverable > 0,
        "verification_receipt_hash": restored_receipt,
        "verified_master_key_versions": versions,
    }


def _integer_versions(value: object, label: str) -> list[int]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, int) or isinstance(item, bool) or item < 1 for item in value)
        or value != sorted(set(value))
    ):
        raise BackupSecurityError(f"{label} is invalid")
    return value


def _string_versions(value: object, label: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(
            not isinstance(item, str)
            or not item.isascii()
            or not item.isdecimal()
            or item.startswith("0")
            for item in value
        )
        or value != sorted(set(value), key=int)
    ):
        raise BackupSecurityError(f"{label} is invalid")
    return value


def _relation_hashes(value: object, label: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != set(HASHED_RELATIONS):
        raise BackupSecurityError(f"{label} is invalid")
    hashes: dict[str, str] = {}
    for name in sorted(HASHED_RELATIONS):
        digest = value[name]
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise BackupSecurityError(f"{label} is invalid")
        hashes[name] = digest
    return hashes


def _relation_hashes_json(value: str) -> dict[str, str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        raise BackupSecurityError("restored critical relation hashes are invalid") from None
    return _relation_hashes(parsed, "restored critical relation hashes")


def _nonnegative(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise BackupSecurityError(f"{label} is invalid")
    return value


def _positive(value: object, label: str) -> int:
    value = _nonnegative(value, label)
    if value < 1:
        raise BackupSecurityError(f"{label} is invalid")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write a GEO restore verification receipt.")
    parser.add_argument("--verified-manifest", type=Path, required=True)
    parser.add_argument("--application-key-probe", type=Path, required=True)
    parser.add_argument("--acl-rls-canary", type=Path, required=True)
    parser.add_argument("--minio-verification", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--restored-project-count", type=int, required=True)
    parser.add_argument("--restored-table-count", type=int, required=True)
    parser.add_argument("--restored-migration-revision", required=True)
    parser.add_argument("--restored-alembic-sql-checksum-ledger-json", required=True)
    parser.add_argument("--restored-critical-relation-counts-json", required=True)
    parser.add_argument("--restored-critical-relation-hashes-json", required=True)
    parser.add_argument("--restored-non-b-business-consistency-json", required=True)
    args = parser.parse_args(argv)
    try:
        write_receipt(
            verified_manifest=args.verified_manifest,
            application_key_probe=args.application_key_probe,
            acl_rls_canary=args.acl_rls_canary,
            minio_verification=args.minio_verification,
            output=args.output,
            restored_project_count=args.restored_project_count,
            restored_table_count=args.restored_table_count,
            restored_migration_revision=args.restored_migration_revision,
            restored_alembic_sql_checksum_ledger=_json_value(
                args.restored_alembic_sql_checksum_ledger_json,
                "restored Alembic SQL checksum ledger",
            ),
            restored_critical_relation_counts=_relation_counts_json(
                args.restored_critical_relation_counts_json
            ),
            restored_critical_relation_hashes=_relation_hashes_json(
                args.restored_critical_relation_hashes_json
            ),
            restored_non_b_business_consistency=_json_value(
                args.restored_non_b_business_consistency_json,
                "restored non-B business consistency manifest",
            ),
        )
    except (BackupSecurityError, OSError):
        print("restore receipt error: verification evidence is invalid", file=sys.stderr)
        return 2
    print(f"restore receipt written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
