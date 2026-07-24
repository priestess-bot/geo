from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0028_secret_store.py"
UP = ROOT / "infra/db/alembic/sql/0028_secret_store.sql"
DOWN = ROOT / "infra/db/alembic/sql/0028_secret_store.down.sql"


def test_secret_store_revision_is_the_single_linear_head() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0028_secret_store"' in source
    assert 'down_revision = "0027_prompt_programs"' in source
    assert UP.is_file() and DOWN.is_file()


def test_secret_store_schema_is_encrypted_scoped_and_audited() -> None:
    source = UP.read_text(encoding="utf-8")
    for table in (
        "secret_master_key_versions",
        "secret_references",
        "secret_versions",
        "secret_command_receipts",
        "secret_audit_events",
    ):
        assert f"CREATE TABLE {table}" in source
    for field in (
        "ciphertext bytea",
        "data_nonce bytea",
        "wrapped_data_key bytea",
        "wrap_nonce bytea",
        "master_key_version integer",
        "algorithm text",
        "idempotency_key_hash text",
        "request_hash text",
        "aggregate_version integer",
        "current_version integer",
        "envelope_fingerprint text",
    ):
        assert field in source
    assert "plaintext" not in source.lower()
    assert "secret_value" not in source.lower()
    assert "'rewrap'" in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "geo_current_project_ids()" in source
    assert "FROM PUBLIC, geo_app, geo_worker, geo_readonly" in source
    select_grants = source.split("GRANT SELECT ON")[1:]
    assert all(
        "geo_readonly" not in grant.split(";", 1)[0] for grant in select_grants
    )


def test_secret_store_schema_enforces_lifecycle_rotation_and_rewrap() -> None:
    source = UP.read_text(encoding="utf-8")
    for contract in (
        "secret_versions_one_active",
        "secret_versions_one_pending",
        "secret_versions_creator_approval_separation",
        "geo_assert_secret_reference_change()",
        "geo_assert_secret_version_insert()",
        "geo_assert_secret_version_change()",
        "geo_assert_secret_current_version()",
        "geo_assert_secret_rewrap_audit()",
        "Secret Store rewrap requires matching receipt and audit lineage",
        "old_key_status <> 'decrypt_only'",
        "new_key_status <> 'encrypt_decrypt'",
        "OLD.verified_by IS NOT NULL",
        "NEW.verified_by = OLD.verified_by",
        "NEW.activated_by = OLD.activated_by",
        "NEW.revoked_by IS NOT NULL",
        "Secret Store master key is still referenced by ciphertext",
    ):
        assert contract in source
    assert "GRANT INSERT, UPDATE ON secret_master_key_versions" not in source
    assert "SECURITY DEFINER" in source
    assert "SET search_path = pg_catalog, public" in source


def test_secret_store_schema_has_composite_lineage_and_fk_indexes() -> None:
    source = UP.read_text(encoding="utf-8")
    for constraint in (
        "secret_versions_reference_fkey",
        "secret_references_current_fkey",
        "secret_command_receipts_version_fkey",
        "secret_audit_events_version_fkey",
    ):
        section = source.split(f"CONSTRAINT {constraint}", 1)[1]
        assert "project_id" in section.split(")", 1)[0]
    for index in (
        "secret_references_project_created_idx",
        "secret_versions_scope_fkey_idx",
        "secret_versions_project_key_idx",
        "secret_versions_master_key_idx",
        "secret_command_receipts_version_fkey_idx",
        "secret_audit_events_project_time_idx",
        "secret_audit_events_version_fkey_idx",
        "secret_audit_events_actor_idx",
        "secret_audit_events_master_key_idx",
    ):
        assert f"CREATE INDEX {index}" in source


def test_secret_store_downgrade_refuses_to_discard_any_key_or_history() -> None:
    source = DOWN.read_text(encoding="utf-8")
    assert "cannot downgrade: Secret Store data exists" in source
    for table in (
        "secret_audit_events",
        "secret_command_receipts",
        "secret_versions",
        "secret_references",
        "secret_master_key_versions",
    ):
        assert f"EXISTS (SELECT 1 FROM {table})" in source
