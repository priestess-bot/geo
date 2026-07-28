from __future__ import annotations

from io import BytesIO
import hashlib
import json
from pathlib import Path
import tarfile

import pytest

from scripts.alembic_sql_ledger import build_ledger
from scripts.backup_envelope import BackupSecurityError
from scripts.verify_minio_backup import MinioBackupError, verify_minio_tar
from scripts.write_backup_restore_receipt import validate_restore_receipt, write_receipt


OBJECTS = {
    "buckets/geo-artifacts/reports/one.json": b'{"one":1}\n',
    "buckets/geo-restricted-recommendation-artifacts/recommendations/task.bin": (
        b"encrypted-recommendation-task"
    ),
    "buckets/geo-restricted-workflow-c-artifacts/workflow-c/manual/two.bin": (
        b"\x00\x01\x02"
    ),
}
BUCKET_COUNTS = {
    "geo-artifacts": 1,
    "geo-restricted-recommendation-artifacts": 1,
    "geo-restricted-workflow-c-artifacts": 1,
    "geo-synthetic-style-derived": 0,
    "geo-synthetic-style-raw": 0,
}
RELATION_HASHES = {
    "evidence_items": "1" * 64,
    "monitoring_reports": "2" * 64,
    "project_memberships": "3" * 64,
    "projects": "4" * 64,
}
ROOT = Path(__file__).resolve().parents[3]
MIGRATION_LEDGER = build_ledger(
    ROOT / "infra" / "db" / "alembic" / "sql",
    head_revision="0028_secret_store",
)
DATABASE_LEDGER_ROWS = [
    {
        "downgrade_sha256": entry["downgrade_sha256"],
        "revision": entry["revision"],
        "upgrade_sha256": entry["upgrade_sha256"],
    }
    for entry in MIGRATION_LEDGER["entries"]
]
DRIFTED_DATABASE_LEDGER_ROWS = json.loads(json.dumps(DATABASE_LEDGER_ROWS))
DRIFTED_DATABASE_LEDGER_ROWS[0]["upgrade_sha256"] = "e" * 64


def _database_ledger(rows: list[dict[str, str]]) -> dict[str, object]:
    payload = {"entries": rows, "head_revision": "0028_secret_store"}
    return {
        **payload,
        "ledger_sha256": hashlib.sha256(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("ascii")
        ).hexdigest(),
        "schema_version": "geo-database-alembic-checksum-ledger-v1",
    }
PROVIDER_SOURCE = {
    "active_dek_count": 1,
    "master_key_version_count": 1,
    "recoverable_artifact_count": 1,
    "representative_probe_target_count": 1,
}
SYNTHETIC_SOURCE = {
    "active_dek_count": 1,
    "master_key_version_count": 1,
    "nondeleted_artifact_count": 2,
    "restricted_probe_target_count": 1,
    "tier_key_artifact_count": 1,
    "tier_probe_target_count": 1,
}
RECOMMENDATION_SOURCE = {
    "artifact_lineage_count": 1,
    "master_key_version_count": 1,
    "representative_probe_target_count": 1,
    "source_verification_receipt_hash": "8" * 64,
}
WORKFLOW_C_SOURCE = {
    "active_dek_count": 1,
    "master_key_version_count": 1,
    "recoverable_artifact_count": 1,
    "representative_probe_target_count": 1,
    "source_verification_receipt_hash": "7" * 64,
}
ACL_RLS_CANARY = {
    "project_id": "c6b21c00-0000-0000-0000-000000000001",
    "role_grants_restored": True,
    "rls_scoped_visibility_verified": True,
    "roles": {
        "geo_restore_canary_app": {
            "bypass_rls": False,
            "can_create_role": False,
            "can_login": False,
            "empty_scope_hidden": True,
            "inherits_roles": False,
            "is_superuser": False,
            "member_of_expected_group": True,
            "scoped_project_visible": True,
            "worker_outbox_execute": False,
        },
        "geo_restore_canary_readonly": {
            "bypass_rls": False,
            "can_create_role": False,
            "can_login": False,
            "empty_scope_hidden": True,
            "inherits_roles": False,
            "is_superuser": False,
            "member_of_expected_group": True,
            "scoped_project_visible": True,
            "worker_outbox_execute": False,
        },
        "geo_restore_canary_worker": {
            "bypass_rls": False,
            "can_create_role": False,
            "can_login": False,
            "empty_scope_hidden": True,
            "inherits_roles": False,
            "is_superuser": False,
            "member_of_expected_group": True,
            "scoped_project_visible": True,
            "worker_outbox_execute": True,
        },
    },
    "schema_version": "geo-restore-acl-rls-canary-v1",
    "unscoped_visibility_denied": True,
    "worker_dispatch_privilege_isolated": True,
}
BUSINESS_RELATIONS = {
    "model_gateway_call_attempts",
    "model_gateway_job_admissions",
    "model_gateway_runtime_manifests",
    "model_gateway_runtime_options",
    "model_gateway_terminal_events",
    "prompt_program_bindings",
    "prompt_program_releases",
    "prompt_programs",
    "synthetic_lab_aggregate_versions",
    "synthetic_lab_artifact_governance_decisions",
    "synthetic_lab_execution_results",
    "synthetic_lab_execution_tasks",
    "synthetic_lab_manual_import_manifests",
    "synthetic_lab_terminal_results",
}


def _business_consistency() -> dict[str, object]:
    empty_hash = hashlib.sha256(b"").hexdigest()
    return {
        "invariant_violations": {},
        "migration_revision": "0028_secret_store",
        "schema_version": "geo-non-b-business-consistency-v1",
        "tables": {
            relation: {
                "aggregate_sha256": empty_hash,
                "scopes": {},
                "total_count": 0,
            }
            for relation in BUSINESS_RELATIONS
        },
    }


def test_minio_tar_verifies_every_object_and_count(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    destination = _secure_directory(tmp_path / "restored")

    result = verify_minio_tar(
        archive,
        destination,
        expected_object_count=3,
        expected_bucket_object_counts=BUCKET_COUNTS,
    )

    assert result == {
        "bucket_object_counts": BUCKET_COUNTS,
        "object_count": 3,
        "per_object_sha256_verified": True,
    }
    for name, content in OBJECTS.items():
        assert (destination / name).read_bytes() == content


def test_minio_tar_rejects_checksum_count_and_non_regular_members(tmp_path: Path) -> None:
    archive = _archive(tmp_path, corrupt_inventory=True)
    with pytest.raises(MinioBackupError):
        verify_minio_tar(
            archive,
            _secure_directory(tmp_path / "bad-hash"),
            expected_object_count=3,
            expected_bucket_object_counts=BUCKET_COUNTS,
        )

    archive = _archive(tmp_path, name="count.tar")
    with pytest.raises(MinioBackupError):
        verify_minio_tar(
            archive,
            _secure_directory(tmp_path / "bad-count"),
            expected_object_count=4,
            expected_bucket_object_counts={**BUCKET_COUNTS, "geo-artifacts": 2},
        )

    archive = _archive(tmp_path, name="link.tar", add_symlink=True)
    with pytest.raises(MinioBackupError):
        verify_minio_tar(
            archive,
            _secure_directory(tmp_path / "bad-link"),
            expected_object_count=3,
            expected_bucket_object_counts=BUCKET_COUNTS,
        )


def test_minio_tar_rejects_path_traversal_without_writing_outside_destination(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "traversal.tar"
    with tarfile.open(archive, "w") as bundle:
        member = tarfile.TarInfo("../outside.txt")
        member.size = 7
        bundle.addfile(member, BytesIO(b"outside"))
    archive.chmod(0o600)
    destination = _secure_directory(tmp_path / "destination")

    with pytest.raises(MinioBackupError):
        verify_minio_tar(
            archive,
            destination,
            expected_object_count=0,
            expected_bucket_object_counts={
                "geo-artifacts": 0,
                "geo-restricted-recommendation-artifacts": 0,
                "geo-restricted-workflow-c-artifacts": 0,
                "geo-synthetic-style-derived": 0,
                "geo-synthetic-style-raw": 0,
            },
        )

    assert not (tmp_path / "outside.txt").exists()


def test_restore_receipt_requires_real_secret_probe_and_matching_source_counts(
    tmp_path: Path,
) -> None:
    evidence = _secure_directory(tmp_path / "evidence")
    output = _secure_directory(tmp_path / "receipts") / "receipt.json"
    manifest = _write_json(
        evidence / "manifest.json",
        {
            "backup_id": "backup-1",
            "source": {
                "minio": {
                    "bucket_object_counts": BUCKET_COUNTS,
                    "object_count": 3,
                },
                "postgres": {
                    "alembic_sql_checksum_ledger": MIGRATION_LEDGER,
                    "database_checksum_ledger": _database_ledger(
                        DRIFTED_DATABASE_LEDGER_ROWS
                    ),
                    "critical_relation_counts": {
                        "evidence_items": 7,
                        "monitoring_reports": 5,
                        "project_memberships": 4,
                    },
                    "critical_relation_hashes": RELATION_HASHES,
                    "migration_revision": "0028_secret_store",
                    "non_b_business_consistency": _business_consistency(),
                    "project_count": 3,
                    "table_count": 44,
                },
                "provider_artifacts": PROVIDER_SOURCE,
                "recommendation_artifacts": RECOMMENDATION_SOURCE,
                "secret_store": {
                    "master_key_version_count": 2,
                    "representative_probe_target_count": 2,
                },
                "synthetic_artifacts": SYNTHETIC_SOURCE,
                "workflow_c_artifacts": WORKFLOW_C_SOURCE,
            },
        },
    )
    probe = _write_json(
        evidence / "probe.json",
        _application_probe(representative_secrets=2, secret_versions=[1, 2]),
    )
    minio = _write_json(
        evidence / "minio.json",
        {
            "bucket_object_counts": BUCKET_COUNTS,
            "object_count": 3,
            "per_object_sha256_verified": True,
        },
    )
    acl_rls = _write_json(evidence / "acl-rls.json", ACL_RLS_CANARY)

    receipt = write_receipt(
        verified_manifest=manifest,
        application_key_probe=probe,
        acl_rls_canary=acl_rls,
        minio_verification=minio,
        output=output,
        restored_project_count=3,
        restored_table_count=44,
        restored_migration_revision="0028_secret_store",
        restored_alembic_sql_checksum_ledger=MIGRATION_LEDGER,
        restored_database_checksum_ledger_rows=DRIFTED_DATABASE_LEDGER_ROWS,
        restored_critical_relation_counts={
            "evidence_items": 7,
            "monitoring_reports": 5,
            "project_memberships": 4,
        },
        restored_critical_relation_hashes=RELATION_HASHES,
        restored_non_b_business_consistency=_business_consistency(),
    )

    assert receipt["secret_store"] == {
        "frozen_handle_audit_count": 1,
        "frozen_handle_receipt_count": 1,
        "frozen_handle_runtime_verified": True,
        "representative_secret_count": 2,
        "representative_secret_target_count": 2,
        "verified_key_versions": [1, 2],
    }
    assert receipt["recommendation_artifacts"] == {
        "artifact_lineage_count": 1,
        "representative_artifact_verified": True,
        "verification_receipt_hash": "8" * 64,
        "verified_master_key_versions": [1],
    }
    assert receipt["workflow_c_artifacts"] == {
        "active_dek_count": 1,
        "recoverable_artifact_count": 1,
        "representative_artifact_verified": True,
        "verification_receipt_hash": "7" * 64,
        "verified_master_key_versions": [1],
    }
    assert receipt["restore_copy_removed"] is True
    assert receipt["plaintext_staging_removed"] is True
    assert receipt["postgres"]["source_critical_relation_hashes"] == RELATION_HASHES
    assert receipt["postgres"]["restored_critical_relation_hashes"] == RELATION_HASHES
    assert receipt["postgres"]["critical_relation_hashes_verified"] is True
    assert receipt["postgres"]["database_checksum_ledger"] == {
        "entry_count": len(DRIFTED_DATABASE_LEDGER_ROWS),
        "ledger_sha256": hashlib.sha256(
            json.dumps(
                {
                    "entries": DRIFTED_DATABASE_LEDGER_ROWS,
                    "head_revision": "0028_secret_store",
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode("ascii")
        ).hexdigest(),
        "verified_against_manifest": True,
    }
    assert receipt["postgres"]["non_b_business_consistency"] == {
        "exact_match_verified": True,
        "invariant_check_count": 0,
        "manifest_sha256": hashlib.sha256(
            json.dumps(
                _business_consistency(), separators=(",", ":"), sort_keys=True
            ).encode("ascii")
        ).hexdigest(),
        "project_scope_count": 0,
        "relation_count": len(BUSINESS_RELATIONS),
        "schema_version": "geo-non-b-business-consistency-v1",
    }
    assert output.stat().st_mode & 0o777 == 0o600
    validated = validate_restore_receipt(
        output,
        expected_backup_id="backup-1",
        expected_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
        expected_migration_revision="0028_secret_store",
        expected_ledger_sha256=MIGRATION_LEDGER["ledger_sha256"],
        expected_database_ledger_sha256=receipt["postgres"][
            "database_checksum_ledger"
        ]["ledger_sha256"],
        expected_project_count=3,
    )
    assert validated == receipt

    mismatched_database_ledger = json.loads(json.dumps(DRIFTED_DATABASE_LEDGER_ROWS))
    mismatched_database_ledger[0]["upgrade_sha256"] = "f" * 64
    with pytest.raises(BackupSecurityError):
        write_receipt(
            verified_manifest=manifest,
            application_key_probe=probe,
            acl_rls_canary=acl_rls,
            minio_verification=minio,
            output=output.with_name("database-ledger-mismatch.json"),
            restored_project_count=3,
            restored_table_count=44,
            restored_migration_revision="0028_secret_store",
            restored_alembic_sql_checksum_ledger=MIGRATION_LEDGER,
            restored_database_checksum_ledger_rows=mismatched_database_ledger,
            restored_critical_relation_counts={
                "evidence_items": 7,
                "monitoring_reports": 5,
                "project_memberships": 4,
            },
            restored_critical_relation_hashes=RELATION_HASHES,
            restored_non_b_business_consistency=_business_consistency(),
        )

    _write_json(
        probe,
        _application_probe(representative_secrets=0, secret_versions=[1, 2]),
    )
    with pytest.raises(BackupSecurityError):
        write_receipt(
            verified_manifest=manifest,
            application_key_probe=probe,
            acl_rls_canary=acl_rls,
            minio_verification=minio,
            output=output.with_name("must-not-exist.json"),
            restored_project_count=3,
            restored_table_count=44,
            restored_migration_revision="0028_secret_store",
            restored_alembic_sql_checksum_ledger=MIGRATION_LEDGER,
            restored_database_checksum_ledger_rows=DRIFTED_DATABASE_LEDGER_ROWS,
            restored_critical_relation_counts={
                "evidence_items": 7,
                "monitoring_reports": 5,
                "project_memberships": 4,
            },
            restored_critical_relation_hashes=RELATION_HASHES,
            restored_non_b_business_consistency=_business_consistency(),
        )

    mismatched_business = _business_consistency()
    business_tables = mismatched_business["tables"]
    assert isinstance(business_tables, dict)
    row_hash = "a" * 64
    business_tables["prompt_programs"] = {
        "aggregate_sha256": hashlib.sha256(
            f"__global__:1:{row_hash}".encode("ascii")
        ).hexdigest(),
        "scopes": {"__global__": {"row_count": 1, "rows_sha256": row_hash}},
        "total_count": 1,
    }
    with pytest.raises(BackupSecurityError):
        write_receipt(
            verified_manifest=manifest,
            application_key_probe=probe,
            acl_rls_canary=acl_rls,
            minio_verification=minio,
            output=output.with_name("business-consistency-mismatch.json"),
            restored_project_count=3,
            restored_table_count=44,
            restored_migration_revision="0028_secret_store",
            restored_alembic_sql_checksum_ledger=MIGRATION_LEDGER,
            restored_database_checksum_ledger_rows=DRIFTED_DATABASE_LEDGER_ROWS,
            restored_critical_relation_counts={
                "evidence_items": 7,
                "monitoring_reports": 5,
                "project_memberships": 4,
            },
            restored_critical_relation_hashes=RELATION_HASHES,
            restored_non_b_business_consistency=mismatched_business,
        )

    mismatched_hashes = {**RELATION_HASHES, "projects": "f" * 64}
    with pytest.raises(BackupSecurityError):
        write_receipt(
            verified_manifest=manifest,
            application_key_probe=_write_json(
                probe,
                _application_probe(representative_secrets=2, secret_versions=[1, 2]),
            ),
            acl_rls_canary=acl_rls,
            minio_verification=minio,
            output=output.with_name("hash-mismatch.json"),
            restored_project_count=3,
            restored_table_count=44,
            restored_migration_revision="0028_secret_store",
            restored_alembic_sql_checksum_ledger=MIGRATION_LEDGER,
            restored_database_checksum_ledger_rows=DRIFTED_DATABASE_LEDGER_ROWS,
            restored_critical_relation_counts={
                "evidence_items": 7,
                "monitoring_reports": 5,
                "project_memberships": 4,
            },
            restored_critical_relation_hashes=mismatched_hashes,
            restored_non_b_business_consistency=_business_consistency(),
        )


def test_restore_receipt_records_zero_representative_secrets_without_false_pass(
    tmp_path: Path,
) -> None:
    evidence = _secure_directory(tmp_path / "evidence")
    manifest = _write_json(
        evidence / "manifest.json",
        {
            "backup_id": "empty-secret-store",
            "source": {
                "minio": {
                    "bucket_object_counts": {
                        "geo-artifacts": 0,
                        "geo-restricted-recommendation-artifacts": 0,
                        "geo-restricted-workflow-c-artifacts": 0,
                        "geo-synthetic-style-derived": 0,
                        "geo-synthetic-style-raw": 0,
                    },
                    "object_count": 0,
                },
                "postgres": {
                    "alembic_sql_checksum_ledger": MIGRATION_LEDGER,
                    "critical_relation_counts": {
                        "evidence_items": 0,
                        "monitoring_reports": 0,
                        "project_memberships": 0,
                    },
                    "critical_relation_hashes": RELATION_HASHES,
                    "migration_revision": "0028_secret_store",
                    "non_b_business_consistency": _business_consistency(),
                    "project_count": 0,
                    "table_count": 40,
                },
                "provider_artifacts": PROVIDER_SOURCE,
                "recommendation_artifacts": RECOMMENDATION_SOURCE,
                "secret_store": {
                    "master_key_version_count": 1,
                    "representative_probe_target_count": 0,
                },
                "synthetic_artifacts": SYNTHETIC_SOURCE,
                "workflow_c_artifacts": WORKFLOW_C_SOURCE,
            },
        },
    )
    probe = _write_json(
        evidence / "probe.json",
        _application_probe(representative_secrets=0, secret_versions=[1]),
    )
    minio = _write_json(
        evidence / "minio.json",
        {
            "bucket_object_counts": {
                "geo-artifacts": 0,
                "geo-restricted-recommendation-artifacts": 0,
                "geo-restricted-workflow-c-artifacts": 0,
                "geo-synthetic-style-derived": 0,
                "geo-synthetic-style-raw": 0,
            },
            "object_count": 0,
            "per_object_sha256_verified": True,
        },
    )
    acl_rls = _write_json(evidence / "acl-rls.json", ACL_RLS_CANARY)
    output = _secure_directory(tmp_path / "receipts") / "receipt.json"

    receipt = write_receipt(
        verified_manifest=manifest,
        application_key_probe=probe,
        acl_rls_canary=acl_rls,
        minio_verification=minio,
        output=output,
        restored_project_count=0,
        restored_table_count=40,
        restored_migration_revision="0028_secret_store",
        restored_alembic_sql_checksum_ledger=MIGRATION_LEDGER,
        restored_database_checksum_ledger_rows=DATABASE_LEDGER_ROWS,
        restored_critical_relation_counts={
            "evidence_items": 0,
            "monitoring_reports": 0,
            "project_memberships": 0,
        },
        restored_critical_relation_hashes=RELATION_HASHES,
        restored_non_b_business_consistency=_business_consistency(),
    )

    assert receipt["secret_store"]["representative_secret_count"] == 0
    assert receipt["secret_store"]["representative_secret_target_count"] == 0


def test_restore_receipt_accepts_empty_recommendation_and_workflow_c_domains(
    tmp_path: Path,
) -> None:
    evidence = _secure_directory(tmp_path / "evidence")
    output = _secure_directory(tmp_path / "receipts") / "receipt.json"
    manifest = _write_json(
        evidence / "manifest.json",
        {
            "backup_id": "empty-restricted-artifact-domains",
            "source": {
                "minio": {"bucket_object_counts": BUCKET_COUNTS, "object_count": 3},
                "postgres": {
                    "alembic_sql_checksum_ledger": MIGRATION_LEDGER,
                    "critical_relation_counts": {
                        "evidence_items": 7,
                        "monitoring_reports": 5,
                        "project_memberships": 4,
                    },
                    "critical_relation_hashes": RELATION_HASHES,
                    "migration_revision": "0028_secret_store",
                    "non_b_business_consistency": _business_consistency(),
                    "project_count": 3,
                    "table_count": 44,
                },
                "provider_artifacts": PROVIDER_SOURCE,
                "recommendation_artifacts": {
                    **RECOMMENDATION_SOURCE,
                    "artifact_lineage_count": 0,
                    "representative_probe_target_count": 0,
                },
                "secret_store": {
                    "master_key_version_count": 2,
                    "representative_probe_target_count": 2,
                },
                "synthetic_artifacts": SYNTHETIC_SOURCE,
                "workflow_c_artifacts": {
                    **WORKFLOW_C_SOURCE,
                    "active_dek_count": 0,
                    "recoverable_artifact_count": 0,
                    "representative_probe_target_count": 0,
                },
            },
        },
    )
    probe = _application_probe(representative_secrets=2, secret_versions=[1, 2])
    probe["recommendation_artifacts"] = {
        "artifact_lineage_count": 0,
        "empty_artifact_domain": True,
        "representative_artifact_verified": False,
        "verification_receipt_hash": "8" * 64,
        "verified_master_key_versions": [1],
    }
    probe["workflow_c_artifacts"] = {
        "active_dek_count": 0,
        "empty_artifact_domain": True,
        "recoverable_artifact_count": 0,
        "representative_artifact_verified": False,
        "verification_receipt_hash": "7" * 64,
        "verified_master_key_versions": [1],
    }
    receipt = write_receipt(
        verified_manifest=manifest,
        application_key_probe=_write_json(evidence / "probe.json", probe),
        acl_rls_canary=_write_json(evidence / "acl-rls.json", ACL_RLS_CANARY),
        minio_verification=_write_json(
            evidence / "minio.json",
            {
                "bucket_object_counts": BUCKET_COUNTS,
                "object_count": 3,
                "per_object_sha256_verified": True,
            },
        ),
        output=output,
        restored_project_count=3,
        restored_table_count=44,
        restored_migration_revision="0028_secret_store",
        restored_alembic_sql_checksum_ledger=MIGRATION_LEDGER,
        restored_database_checksum_ledger_rows=DATABASE_LEDGER_ROWS,
        restored_critical_relation_counts={
            "evidence_items": 7,
            "monitoring_reports": 5,
            "project_memberships": 4,
        },
        restored_critical_relation_hashes=RELATION_HASHES,
        restored_non_b_business_consistency=_business_consistency(),
    )

    assert receipt["recommendation_artifacts"]["artifact_lineage_count"] == 0
    assert receipt["recommendation_artifacts"]["representative_artifact_verified"] is False
    assert receipt["workflow_c_artifacts"]["active_dek_count"] == 0
    assert receipt["workflow_c_artifacts"]["representative_artifact_verified"] is False


def _application_probe(
    *, representative_secrets: int, secret_versions: list[int]
) -> dict[str, object]:
    return {
        "provider_artifacts": {
            "active_dek_count": 1,
            "empty_artifact_domain": False,
            "recoverable_artifact_count": 1,
            "representative_artifact_verified": True,
            "verification_receipt_hash": "9" * 64,
            "verified_master_key_versions": [1],
        },
        "recommendation_artifacts": {
            "artifact_lineage_count": 1,
            "empty_artifact_domain": False,
            "representative_artifact_verified": True,
            "verification_receipt_hash": "8" * 64,
            "verified_master_key_versions": [1],
        },
        "schema_version": "geo-application-key-recovery-probe-v3",
        "secret_store": {
            "frozen_handle_audit_count": 1,
            "frozen_handle_receipt_count": 1,
            "frozen_handle_runtime_verified": True,
            "representative_secret_count": representative_secrets,
            "verified_key_versions": secret_versions,
        },
        "synthetic_artifacts": {
            "active_dek_count": 1,
            "empty_artifact_domain": False,
            "nondeleted_artifact_count": 2,
            "restricted_representative_verified": True,
            "tier_key_artifact_count": 1,
            "tier_representative_verified": True,
            "verified_master_key_versions": ["1"],
        },
        "workflow_c_artifacts": {
            "active_dek_count": 1,
            "empty_artifact_domain": False,
            "recoverable_artifact_count": 1,
            "representative_artifact_verified": True,
            "verification_receipt_hash": "7" * 64,
            "verified_master_key_versions": [1],
        },
    }


def _archive(
    tmp_path: Path,
    *,
    name: str = "minio.tar",
    corrupt_inventory: bool = False,
    add_symlink: bool = False,
) -> Path:
    archive = tmp_path / name
    inventory = []
    with tarfile.open(archive, "w") as bundle:
        for object_name, content in OBJECTS.items():
            member = tarfile.TarInfo(object_name)
            member.size = len(content)
            bundle.addfile(member, BytesIO(content))
            digest = hashlib.sha256(content).hexdigest()
            if corrupt_inventory and not inventory:
                digest = "0" * 64
            inventory.append(f"{digest}  {object_name}\n")
        inventory_bytes = "".join(inventory).encode("ascii")
        member = tarfile.TarInfo("objects.sha256")
        member.size = len(inventory_bytes)
        bundle.addfile(member, BytesIO(inventory_bytes))
        if add_symlink:
            link = tarfile.TarInfo("objects/unsafe-link")
            link.type = tarfile.SYMTYPE
            link.linkname = "/etc/passwd"
            bundle.addfile(link)
    archive.chmod(0o600)
    return archive


def _write_json(path: Path, value: object) -> Path:
    path.write_text(
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="ascii",
    )
    path.chmod(0o600)
    return path


def _secure_directory(path: Path) -> Path:
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path
