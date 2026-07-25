import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]


def test_production_backup_streams_both_sources_into_authenticated_envelopes() -> None:
    source = (ROOT / "scripts" / "backup_geo_data.sh").read_text(encoding="utf-8")

    assert "set -Eeuo pipefail" in source
    assert "umask 077" in source
    assert "trap cleanup EXIT" in source
    assert "trap 'exit 130' INT" in source
    assert "trap 'exit 143' TERM" in source
    assert "postgres.sql.gz.enc" in source
    assert "minio.tar.enc" in source
    assert source.count("backup_envelope.py\" encrypt") == 2
    assert "backup_manifest.py\" create" in source
    assert "backup_manifest.py\" verify" in source
    assert "pg_export_snapshot()" in source
    assert '--snapshot="$1"' in source
    assert "--no-privileges" not in source
    assert "frozen Secret Store restore canary is unavailable" in source
    assert "geo_require_active_service_identity" in source
    assert "secret_command_receipts" in source
    assert "secret_audit_events" in source
    assert "GEO_RESTORE_TMPFS_ROOT" in source
    assert "verification staging must be a 0700 tmpfs directory" in source
    assert '| tee "$verification_staging/minio.tar"' in source
    assert "--object-root /backup-source-objects" in source
    assert "--recommendation-object-root /backup-source-recommendation-objects" in source
    assert "--workflow-c-object-root /backup-source-workflow-c-objects" in source
    assert "--synthetic-raw-object-root /backup-source-synthetic-style-raw-objects" in source
    assert "--synthetic-derived-object-root /backup-source-synthetic-style-derived-objects" in source
    object_capture_at = source.index('| tee "$verification_staging/minio.tar"')
    exact_source_probe_at = source.index("--object-root /backup-source-objects")
    snapshot_close_at = source.index("close_consistent_snapshot", exact_source_probe_at)
    assert object_capture_at < exact_source_probe_at < snapshot_close_at
    assert "critical-relation-hashes-json" in source
    assert source.count("alembic_sql_ledger.py\" create") == 2
    assert "Alembic SQL changed during backup" in source
    assert "alembic-sql-checksum-ledger-json" in source
    assert source.count("relation_hash_at_snapshot") >= 5
    assert source.index("backup_manifest.py\" create") < source.index(
        'mv -T -- "$staging" "$final"'
    )
    assert "flock -n" in source
    assert "postgres.sql.gz\"" not in source
    assert "SHA256SUMS" not in source


def test_backup_object_store_uses_tmpfs_tar_inventory_and_never_recurses_backups() -> None:
    source = (ROOT / "infra" / "backup" / "backup-object-store.sh").read_text(
        encoding="utf-8"
    )
    compose = (ROOT / "infra" / "compose.prod.yml").read_text(encoding="utf-8")

    assert "set -o pipefail" in source
    assert "umask 077" in source
    assert "trap cleanup EXIT" in source
    assert "trap 'exit 130' INT" in source
    assert "/plaintext-staging" in source
    assert "objects.sha256" in source
    assert "tar -C" in source
    assert '"geo/$reports_bucket"' in source
    assert '"geo/$recommendation_bucket"' in source
    assert '"geo/$workflow_c_bucket"' in source
    assert "geo-restricted-recommendation-artifacts" in source
    assert "geo-synthetic-style-raw" in source
    assert "geo-synthetic-style-derived" in source
    assert "geo-restricted-workflow-c-artifacts" in source
    assert "geo/geo-backups" not in source
    assert "/plaintext-staging:size=" in compose
    assert "mode=0700" in compose


def test_workflow_c_object_store_principals_are_functionally_separated() -> None:
    source = (ROOT / "infra" / "minio" / "bootstrap.sh").read_text(
        encoding="utf-8"
    )
    writer_policy = source.split(
        "cat > /tmp/geo-minio-bootstrap/workflow-c-writer-policy.json <<EOF", 1
    )[1].split("EOF", 1)[0]

    assert "workflow-c-reader-policy.json" in source
    assert "workflow-c-deleter-policy.json" in source
    assert "DeleteObject" not in writer_policy
    assert "Workflow C writer unexpectedly deleted an object" in source
    assert "Workflow C reader unexpectedly deleted an object" in source
    assert "Workflow C deleter unexpectedly wrote an object" in source
    assert "Workflow C deleter unexpectedly accessed the application bucket" in source
    assert 'mc rm "workflow-c-deleter/$workflow_c_bucket/$workflow_c_readiness_key"' in source
    assert '"workflow_c_reader_delete_denied":true' in source
    assert '"workflow_c_writer_delete_denied":true' in source
    assert '"workflow_c_deleter_delete_verified":true' in source
    assert '"workflow_c_deleter_put_denied":true' in source


def test_minio_bootstrap_uses_hash_comparison_available_in_the_mc_image() -> None:
    source = (ROOT / "infra" / "minio" / "bootstrap.sh").read_text(
        encoding="utf-8"
    )

    assert "files_match_sha256()" in source
    assert "cmp -s" not in source
    assert source.count("files_match_sha256 /tmp/geo-minio-bootstrap/") == 2
    assert "umask 077" in source


def test_minio_bootstrap_proves_delete_only_principals_without_granting_reads() -> None:
    source = (ROOT / "infra" / "minio" / "bootstrap.sh").read_text(
        encoding="utf-8"
    )

    assert "mc rm --recursive --force --versions" in source
    assert (
        '"recommendation-deleter/$recommendation_bucket/'
        'recommendations/model-tasks/bootstrap/"' in source
    )
    assert (
        '"synthetic-artifact-deleter/$synthetic_raw_bucket/'
        'synthetic-raw/bootstrap/"' in source
    )
    assert "Recommendation artifact deleter unexpectedly read an object" in source
    assert "Synthetic artifact deleter unexpectedly read a raw object" in source


def test_restore_verifies_commit_before_decrypt_and_removes_plaintext_and_database() -> None:
    source = (ROOT / "scripts" / "restore_geo_backup_smoke.sh").read_text(
        encoding="utf-8"
    )

    verify_at = source.index('backup_manifest.py\" verify')
    postgres_decrypt_at = source.index("--artifact postgres")
    minio_decrypt_at = source.index("--artifact minio")
    assert verify_at < postgres_decrypt_at < minio_decrypt_at
    assert "set -Eeuo pipefail" in source
    assert "check_postgres_fk_integrity.sql" in source
    assert "restore-smoke-application-key-probe" in source
    assert "application-key-probe.json" in source
    assert "--application-key-probe" in source
    assert "bootstrap_restore_acl_roles" in source
    assert "geo_restore_canary_app" in source
    assert "SET LOCAL ROLE $canary_role" in source
    assert "SET LOCAL ROLE $canary_group" in source
    assert "SET LOCAL geo.project_ids" in source
    assert "pg_has_role('$canary_role', '$canary_group', 'member')" in source
    assert "write_restore_acl_rls_canary.py" in source
    assert "--acl-rls-canary" in source
    assert "minio-restored/buckets/geo-artifacts:/restore-objects:ro" in source
    assert (
        "minio-restored/buckets/geo-restricted-recommendation-artifacts:"
        "/restore-recommendation-objects:ro"
    ) in source
    assert (
        "minio-restored/buckets/geo-restricted-workflow-c-artifacts:"
        "/restore-workflow-c-objects:ro"
    ) in source
    assert (
        "minio-restored/buckets/geo-synthetic-style-raw:"
        "/restore-synthetic-style-raw-objects:ro"
    ) in source
    assert (
        "minio-restored/buckets/geo-synthetic-style-derived:"
        "/restore-synthetic-style-derived-objects:ro"
    ) in source
    assert "verify_minio_backup.py" in source
    assert 'rm -rf -- "$restore_staging/minio.tar"' in source
    assert "remove_restore_copy" in source
    assert "write_backup_restore_receipt.py" in source
    assert "GEO_RESTORE_TMPFS_ROOT" in source
    assert "stat -f -c '%T'" in source
    assert '!= "tmpfs"' in source
    assert 'mktemp -d "$restore_tmpfs_root/' in source
    assert '${TMPDIR:-/tmp}' not in source
    assert "restored-critical-relation-hashes-json" in source
    assert "alembic_sql_ledger.py\" verify" in source
    assert "restored-alembic-sql-checksum-ledger-json" in source
    assert "remaining_restore_containers" in source
    assert "flock -n" in source
    receipt_write_at = source.index("write_backup_restore_receipt.py")
    staging_remove_at = source.index('rm -rf -- "$restore_staging"', receipt_write_at)
    final_receipt_at = source.index("from scripts.backup_envelope import atomic_write")
    assert receipt_write_at < staging_remove_at < final_receipt_at


def test_make_targets_require_preflight_and_accept_directory_alias() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "backup: production-preflight" in makefile
    assert "restore-smoke: production-preflight" in makefile
    assert "BACKUP_DIR" in makefile
    assert "legacy BACKUP_FILE pointing to a directory" in makefile


def test_development_smoke_persists_only_encrypted_bundle_and_truthful_receipt() -> None:
    source = (ROOT / "scripts" / "backup_restore_development_smoke.sh").read_text(
        encoding="utf-8"
    )

    assert "set -Eeuo pipefail" in source
    assert "GEO_DEVELOPMENT_RESTORE_TMPFS_ROOT" in source
    assert "GEO_DEVELOPMENT_RESTORE_COMPOSE_PROJECT" in source
    assert 'docker compose --project-name "$compose_project"' in source
    assert "restore Compose project name is invalid" in source
    assert "compose_published_port()" in source
    assert 'compose_published_port postgres 5432' in source
    assert 'compose_published_port minio 9000' in source
    assert 'GEO_DATABASE_URL="postgresql://geo_installer:geo_installer_dev@127.0.0.1:${postgres_host_port}/$source_database"' in source
    assert 'GEO_MINIO_HOST_PORT:-9000' not in source
    assert "--no-privileges" not in source
    assert "GEO_DEVELOPMENT_BACKUP_SOURCE_DATABASE" in source
    assert "GEO_DEVELOPMENT_BACKUP_SOURCE_BUCKET" in source
    assert "GEO_DEVELOPMENT_SECRET_STORE_MASTER_KEYRING_FILE" in source
    assert "GEO_DEVELOPMENT_PROVIDER_ARTIFACT_KEYRING_FILE" in source
    assert "GEO_DEVELOPMENT_SYNTHETIC_ARTIFACT_KEYRING_FILE" in source
    assert "GEO_DEVELOPMENT_RECOMMENDATION_ARTIFACT_KEYRING_FILE" in source
    assert "GEO_DEVELOPMENT_WORKFLOW_C_ARTIFACT_KEYRING_FILE" in source
    assert "GEO_DEVELOPMENT_RECOMMENDATION_BACKUP_SOURCE_BUCKET" in source
    assert "GEO_DEVELOPMENT_WORKFLOW_C_BACKUP_SOURCE_BUCKET" in source
    assert "GEO_DEVELOPMENT_SYNTHETIC_RAW_BACKUP_SOURCE_BUCKET" in source
    assert "GEO_DEVELOPMENT_SYNTHETIC_DERIVED_BACKUP_SOURCE_BUCKET" in source
    assert 'GEO_DEVELOPMENT_BACKUP_SOURCE_DATABASE:-}' in source
    assert 'GEO_DEVELOPMENT_BACKUP_SOURCE_BUCKET:-}' in source
    assert "stat -f -c '%T'" in source
    assert '(cd "$plaintext_root/minio-source" && find buckets' in source
    assert source.count('run --rm -T --no-deps') == 3
    assert source.count('--user "$(id -u):$(id -g)"') == 3
    assert source.count('MC_CONFIG_DIR=/tmp/mc-config') == 3
    assert "/primary:ro" in source
    assert "/recommendation:ro" in source
    assert "/workflow-c:ro" in source
    assert "/synthetic-raw:ro" in source
    assert "/synthetic-derived:ro" in source
    assert "docker cp" not in source
    assert source.count("backup_envelope.py\" encrypt") == 2
    assert "critical-relation-hashes-json" in source
    assert source.count("alembic_sql_ledger.py\" create") == 2
    assert "Alembic SQL changed during backup" in source
    assert "alembic_sql_ledger.py\" verify" in source
    assert "geo_worker.backup_restore_probe" in source
    assert "--recommendation-object-root" in source
    assert "--synthetic-raw-object-root" in source
    assert "--synthetic-derived-object-root" in source
    assert 'assert_probe_rejected "wrong Secret Store key"' in source
    assert 'assert_probe_rejected "wrong Provider artifact key"' in source
    assert 'assert_probe_rejected "wrong Synthetic artifact key"' in source
    assert 'assert_probe_rejected "missing Provider artifact keyring"' in source
    assert 'assert_probe_rejected "wrong Recommendation artifact key"' in source
    assert 'assert_probe_rejected "missing Recommendation artifact keyring"' in source
    assert 'assert_probe_rejected "wrong Workflow C artifact key"' in source
    assert 'assert_probe_rejected "missing Workflow C artifact keyring"' in source
    assert "production_equivalent_restore_receipt" in source
    assert "write_restore_acl_rls_canary.py" in source
    assert "--acl-rls-canary" in source
    assert "SET LOCAL ROLE $canary_role" in source
    assert "SET LOCAL ROLE $canary_group" in source
    assert "SET LOCAL geo.project_ids" in source
    assert "pg_has_role('$canary_role', '$canary_group', 'member')" in source
    assert "remove_restore_copies" in source
    assert source.rindex("remove_restore_copies") < source.index(
        '"ephemeral_backup_key_destroyed": True'
    )
    assert 'rm -rf -- "$plaintext_root" "$secret_root"' in source
    assert 'if [[ "$smoke_completed" != "1" ]]' in source
    assert 'rm -rf -- "$output"' in source
    assert "postgres.sql.gz\"" not in source
    assert "SHA256SUMS" not in source


def test_development_smoke_refuses_implicit_live_sources(tmp_path: Path) -> None:
    environment = os.environ.copy()
    for field in (
        "GEO_DEVELOPMENT_BACKUP_SOURCE_DATABASE",
        "GEO_DEVELOPMENT_BACKUP_SOURCE_BUCKET",
        "GEO_DEVELOPMENT_SECRET_STORE_MASTER_KEYRING_FILE",
        "GEO_DEVELOPMENT_PROVIDER_ARTIFACT_KEYRING_FILE",
        "GEO_DEVELOPMENT_SYNTHETIC_ARTIFACT_KEYRING_FILE",
        "GEO_DEVELOPMENT_RECOMMENDATION_ARTIFACT_KEYRING_FILE",
        "GEO_DEVELOPMENT_WORKFLOW_C_ARTIFACT_KEYRING_FILE",
        "GEO_DEVELOPMENT_WORKFLOW_C_BACKUP_SOURCE_BUCKET",
    ):
        environment.pop(field, None)
    output = tmp_path / "must-not-exist"

    completed = subprocess.run(
        [str(ROOT / "scripts" / "backup_restore_development_smoke.sh"), str(output)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "isolated source, Secret Store HMAC, and frozen resolve canary are required" in (
        completed.stderr
    )
    assert not output.exists()


def test_authenticated_restore_gate_uses_dynamic_head_and_cleans_isolated_sources() -> None:
    source = (ROOT / "scripts" / "run_authenticated_restore_gate.sh").read_text(
        encoding="utf-8"
    )
    seed = (ROOT / "scripts" / "backup_restore_gate_seed.py").read_text(
        encoding="utf-8"
    )
    prompt_seed = (
        ROOT / "scripts" / "backup_restore_gate_seed_secret_prompt.py"
    ).read_text(encoding="utf-8")

    assert "set -Eeuo pipefail" in source
    assert 'compose_project="geo-restore-gate-${nonce}"' in source
    assert 'docker compose --project-name "$compose_project"' in source
    assert 'export GEO_POSTGRES_HOST_PORT="127.0.0.1:0"' in source
    assert 'export GEO_MINIO_HOST_PORT="127.0.0.1:0"' in source
    assert 'export GEO_MINIO_CONSOLE_HOST_PORT="127.0.0.1:0"' in source
    assert 'down --volumes --remove-orphans' in source
    assert "backup_restore_gate_seed.py head" in source
    assert "--expected-head \"$head_revision\"" in source
    assert "CREATE DATABASE $source_database" in source
    assert "DROP DATABASE $source_database WITH (FORCE)" in source
    assert "GATE_BUCKETS=$source_bucket $recommendation_source_bucket" in source
    assert "geo-synthetic-style-raw" in source
    assert "geo-synthetic-style-derived" in source
    assert "--synthetic-raw-object-store-bucket" in source
    assert "--synthetic-derived-object-store-bucket" in source
    assert "--recommendation-object-store-bucket" in source
    assert "--workflow-c-object-store-bucket" in source
    assert "GEO_DEVELOPMENT_SYNTHETIC_RAW_BACKUP_SOURCE_BUCKET" in source
    assert "GEO_DEVELOPMENT_SYNTHETIC_DERIVED_BACKUP_SOURCE_BUCKET" in source
    assert "if mc stat \"gate/$bucket\"" in source
    assert "mc rb \"gate/$bucket\"" in source
    assert "geo-restore-gate-keys" in source
    assert "stat -f -c '%T'" in source
    assert "backup_restore_development_smoke.sh" in source
    assert 'GEO_DEVELOPMENT_RESTORE_COMPOSE_PROJECT="$compose_project"' in source
    assert "scan_backup_plaintext_artifacts.py" in source
    assert "wrong_provider_key_rejected" not in source
    assert "all(receipt[\"negative_key_tests\"].values())" in source
    assert "verified_key_versions\"] == [1, 2]" in source
    assert "verified_master_key_versions\"] == [\"1\", \"2\"]" in source
    assert '"artifact_lineage_count"] == 1' in source
    assert '"recoverable_artifact_count"] == 1' in source
    assert '"representative_artifact_verified"] is True' in source
    assert "0030_synthetic_lab" not in source
    assert "0030_synthetic_lab" not in seed
    assert "_RestoreGatePromptEvidenceVerifier" in prompt_seed
    assert "test_evidence_verifier=verifier" in prompt_seed
    assert "restore Gate Prompt evidence changed" in prompt_seed
    assert 'GEO_RESTORE_GATE_DEBUG' in seed
    assert 'constraint={constraint or \'-\'}' in seed
    assert 'str(error)' not in seed
    synthetic_seed = (
        ROOT / "scripts" / "backup_restore_gate_seed_synthetic.py"
    ).read_text(encoding="utf-8")
    assert "StyleCollectionExecutionApplication" in synthetic_seed
    assert "create_authorization_record" in synthetic_seed
    assert "StyleCollectionTask" in synthetic_seed
    assert "session_replication_role" not in synthetic_seed
    assert "INSERT INTO synthetic_lab_raw_artifacts" not in synthetic_seed
