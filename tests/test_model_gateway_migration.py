from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0029_model_gateway.py"
UP = ROOT / "infra/db/alembic/sql/0029_model_gateway.sql"
DOWN = ROOT / "infra/db/alembic/sql/0029_model_gateway.down.sql"


def test_model_gateway_revision_is_the_single_linear_head() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0029_model_gateway"' in source
    assert 'down_revision = "0028_secret_store"' in source
    assert UP.is_file() and DOWN.is_file()


def test_model_gateway_migration_uses_nonparameterized_driver_cursor() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    source = UP.read_text(encoding="utf-8")
    assert "driver_connection" in migration
    assert "cursor.execute" in migration
    assert "exec_driver_sql" not in migration
    assert "%ROWTYPE" in source


def test_model_gateway_schema_covers_releases_policy_and_audited_calls() -> None:
    source = UP.read_text(encoding="utf-8")
    for table in (
        "model_gateway_adapter_releases",
        "model_gateway_model_releases",
        "model_gateway_project_policy_versions",
        "model_gateway_runtime_manifests",
        "model_gateway_runtime_options",
        "model_gateway_job_admissions",
        "model_gateway_call_attempts",
        "model_gateway_terminal_events",
        "model_gateway_reconciliation_commands",
        "model_gateway_artifact_recovery_receipts",
        "model_gateway_artifact_master_key_versions",
        "model_gateway_artifact_bundles",
        "model_gateway_artifact_deks",
        "model_gateway_artifacts",
        "model_gateway_artifact_deletion_outbox",
        "model_gateway_artifact_tombstones",
    ):
        assert f"CREATE TABLE {table}" in source
    for contract in (
        "data_policy_hash",
        "policy_version_hash",
        "maximum_paid_calls",
        "maximum_concurrent_calls",
        "budget_version",
        "expected_budget_version",
        "lease_token",
        "fencing_generation",
        "idempotency_key_hash",
        "configured_model",
        "provider_reported_model",
        "citation_lineage_hash",
        "search_lineage_hash",
        "usage_details_hash",
        "raw_artifact_reference_hash",
        "raw_artifact_policy_hash",
        "raw_artifact_storage_decision",
        "raw_artifact_retention_days",
        "supports_structured_output_with_tools",
        "expected_capture_method",
        "provider_secret_reference_id",
        "provider_secret_version",
        "provider_secret_handle_hash",
        "admission_mode",
        "prompt_state_version",
        "prompt_test_set_hash",
        "prompt_test_case_hash",
        "runtime_manifest_id",
        "runtime_manifest_hash",
        "runtime_option_id",
        "runtime_option_hash",
        "application_output_schema_hash",
        "Provider-portable structured-output Schema hash",
    ):
        assert contract in source


def test_model_gateway_schema_forbids_bodies_credentials_and_customer_access() -> None:
    source = UP.read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in (
        "message_body",
        "prompt_body",
        "output_body",
        "response_body",
        "raw_artifact_uri",
        "credential",
        "secret_value",
    ):
        assert forbidden not in lowered
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "geo_current_project_ids()" in source
    assert "FROM PUBLIC, geo_app, geo_worker, geo_readonly" in source
    select_grants = source.split("GRANT SELECT ON")[1:]
    assert select_grants
    assert all("geo_readonly" not in grant.split(";", 1)[0] for grant in select_grants)


def test_model_gateway_schema_enforces_append_only_budget_and_exact_lineage() -> None:
    source = UP.read_text(encoding="utf-8")
    for contract in (
        "Model Gateway Adapter Releases are immutable",
        "Model Gateway Model Releases are immutable",
        "model_gateway_project_policy_versions_immutable",
        "Model Gateway call attempts are append-only",
        "Model Gateway terminal events are append-only",
        "Model Gateway budget counters do not match append-only call history",
        "Model Gateway reservation lost Job, lease, fencing, or budget CAS",
        "Model Gateway terminal writer lost Job lease or fencing ownership",
        "Model Gateway raw artifact policy lineage is invalid",
        "Model Gateway provider-reported model violates frozen Model Release",
        "model_gateway_terminal_events_reconciliation_class",
        "model_gateway_terminal_events_failed_artifact_shape",
        "paid_call_count = 1",
        "expected_capture_method",
        "Model Gateway attempt violates exact capture, model, or search release",
        "DEFERRABLE INITIALLY DEFERRED",
        "Model Gateway admission requires the current active Provider Secret handle",
        "Model Gateway admission requires a matching active Durable Job",
        "provider_secret.status NOT IN ('active', 'superseded')",
        "Model Gateway Provider Secret handle is unavailable",
        "Model Gateway admission differs from the current approved runtime option",
        "Model Gateway admission Schema hashes differ from Prompt Release",
        "Model Gateway Attempt differs from its frozen runtime option",
    ):
        assert contract in source
    assert "GRANT DELETE" not in source
    assert "GRANT UPDATE (paid_calls, reserved_calls, budget_version, next_attempt_number)" in source
    assert "GRANT UPDATE ON model_gateway_job_admissions" not in source


def test_model_gateway_artifact_keyring_and_reconciliation_are_fail_closed() -> None:
    source = UP.read_text(encoding="utf-8")
    for contract in (
        "model_gateway_artifact_master_key_versions",
        "geo_sync_model_gateway_artifact_master_key_version",
        "Provider artifact master key still wraps an active DEK",
        "key_ref = artifact_id",
        "model_gateway_artifact_deks_restore_idx",
        "model_gateway_artifact_deks_unstaged_idx",
        "geo_destroy_model_gateway_unstaged_artifact_deks",
        "invalid Model Gateway pre-stage DEK sweep input",
        "FOR UPDATE OF dek SKIP LOCKED",
        "model_gateway_reconciliation_commands_immutable",
        "model_gateway_artifact_recovery_receipts_immutable",
        "source_model_job_id uuid NOT NULL",
        "source_job.parent_job_id IS DISTINCT FROM NEW.recovery_job_id",
        "artifact.bundle_job_id <> NEW.source_model_job_id",
        "Provider artifact recovery receipt lost exact Job or artifact lineage",
        "Provider artifact recovery receipt lacks committed terminal output",
        "expected_output_hash = recovered_output_hash",
        "Model Gateway reconciliation command lineage is inconsistent",
        "admission.budget_version <> NEW.expected_budget_version + 1",
        "UNIQUE (project_id, idempotency_key_hash)",
        "UNIQUE (project_id, attempt_id)",
        "model_gateway_artifact_recovery_receipts_source_job_fkey_idx",
    ):
        assert contract in source
    assert "REFERENCES secret_master_key_versions" not in source


def test_model_gateway_runtime_catalog_is_project_scoped_and_fail_closed() -> None:
    source = UP.read_text(encoding="utf-8")
    for contract in (
        "schema_version integer NOT NULL CHECK (schema_version = 2)",
        "prepared_by uuid NOT NULL REFERENCES identities(id)",
        "CHECK (prepared_by <> approved_by)",
        "approval_evidence_reference text NOT NULL",
        "approval_evidence_sha256 text NOT NULL",
        "NEW.prepared_at > clock_timestamp() + interval '5 minutes'",
        "NEW.approved_at > clock_timestamp() + interval '5 minutes'",
        "role IN ('owner', 'admin')",
        "model_gateway_runtime_manifests_one_approved",
        "model_gateway_runtime_manifests_change_guard",
        "model_gateway_runtime_options_insert_guard",
        "model_gateway_runtime_options_immutable",
        "model_gateway_runtime_manifests_consistency_guard",
        "model_gateway_runtime_options_consistency_guard",
        "geo_register_model_gateway_runtime_manifest",
        "geo_add_model_gateway_runtime_option",
        "geo_retire_model_gateway_runtime_manifest",
        "geo_resolve_model_gateway_runtime_option",
        "runtime manifest options do not match frozen policy",
        "runtime option violates approved live dependencies",
        "manifest.status = 'approved'",
        "secret.status = 'active'",
        "microsoft_market text",
        "microsoft_language text",
        "Microsoft runtime option endpoint or Agent Reference is invalid",
    ):
        assert contract in source
    assert "GRANT INSERT ON\n    model_gateway_runtime_manifests" not in source
    assert "GRANT INSERT ON\n    model_gateway_runtime_options" not in source


def test_model_gateway_governance_evidence_location_and_retry_lease_are_frozen() -> None:
    source = UP.read_text(encoding="utf-8")
    down = DOWN.read_text(encoding="utf-8")
    for contract in (
        "capability_evidence_sha256",
        "terms_sha256",
        "capability_evidence_reference !~ '://[^/]*@'",
        "terms_reference !~ '://[^/]*@'",
        "requested_location_country",
        "requested_location_region",
        "requested_location_locale",
        "requested_location_language",
        "expected_location_control",
        "expected_location_evidence_hash",
        "effective_location_control",
        "effective_location_evidence_hash",
        "model_gateway_call_attempts_location_shape",
        "model_gateway_terminal_events_location_shape",
        "Microsoft Attempt location differs from the frozen market/language option",
        "Model Gateway success effective-location lineage is incomplete",
        "failed Model Gateway terminal cannot claim effective location",
        "geo_refresh_model_gateway_job_admission_lease",
        "Model Gateway lease refresh lost retry, lease, or fence eligibility",
        "latest.error_retryable IS NOT TRUE",
        "admission.reserved_calls <> 0",
    ):
        assert contract in source
    grant_section = source.split("GRANT EXECUTE ON FUNCTION", 2)[2]
    assert "geo_refresh_model_gateway_job_admission_lease(" in grant_section
    assert "TO geo_app, geo_worker;" in grant_section
    assert "GRANT UPDATE (job_version, lease_token, fencing_generation)" not in source
    assert "DROP FUNCTION geo_refresh_model_gateway_job_admission_lease(" in down


def test_model_gateway_invoker_triggers_do_not_lock_immutable_read_dependencies() -> None:
    source = UP.read_text(encoding="utf-8")
    admission_guard = source.split(
        "CREATE FUNCTION geo_assert_model_gateway_job_admission_insert", 1
    )[1].split("CREATE FUNCTION geo_assert_model_gateway_job_budget_change", 1)[0]
    terminal_guard = source.split(
        "CREATE FUNCTION geo_assert_model_gateway_terminal_insert", 1
    )[1].split("CREATE FUNCTION geo_assert_model_gateway_terminal_immutable", 1)[0]
    assert "FROM model_gateway_runtime_manifests" in admission_guard
    assert "FOR SHARE" not in admission_guard
    assert "FROM model_gateway_artifact_bundles" in terminal_guard
    bundle_read = terminal_guard.split("SELECT * INTO bundle", 1)[1].split(
        "bundle_found := FOUND", 1
    )[0]
    assert "FOR UPDATE" not in bundle_read


def test_model_gateway_schema_has_scoped_foreign_keys_and_indexes() -> None:
    source = UP.read_text(encoding="utf-8")
    for constraint in (
        "model_gateway_job_admissions_policy_fkey",
        "model_gateway_job_admissions_binding_fkey",
        "model_gateway_job_admissions_release_fkey",
        "model_gateway_job_admissions_state_fkey",
        "model_gateway_job_admissions_runtime_manifest_fkey",
        "model_gateway_job_admissions_runtime_option_fkey",
        "model_gateway_call_attempts_job_fkey",
        "model_gateway_call_attempts_runtime_manifest_fkey",
        "model_gateway_call_attempts_runtime_option_fkey",
        "model_gateway_call_attempts_parent_fkey",
        "model_gateway_call_attempts_policy_fkey",
        "model_gateway_terminal_events_attempt_fkey",
    ):
        section = source.split(f"CONSTRAINT {constraint}", 1)[1]
        assert "project_id" in section.split(")", 1)[0]
    for constraint in (
        "model_gateway_job_admissions_secret_fkey",
        "model_gateway_call_attempts_secret_fkey",
    ):
        assert f"CONSTRAINT {constraint}" in source
    assert "provider_secret.project_id <> NEW.project_id" in source
    for index in (
        "model_gateway_model_releases_adapter_fkey_idx",
        "model_gateway_project_policy_versions_previous_fkey_idx",
        "model_gateway_runtime_manifests_policy_fkey_idx",
        "model_gateway_runtime_options_manifest_fkey_idx",
        "model_gateway_runtime_options_adapter_fkey_idx",
        "model_gateway_runtime_options_model_fkey_idx",
        "model_gateway_runtime_options_secret_fkey_idx",
        "model_gateway_job_admissions_runtime_manifest_fkey_idx",
        "model_gateway_job_admissions_runtime_option_fkey_idx",
        "model_gateway_job_admissions_policy_fkey_idx",
        "model_gateway_job_admissions_prompt_binding_fkey_idx",
        "model_gateway_job_admissions_prompt_release_fkey_idx",
        "model_gateway_job_admissions_prompt_state_fkey_idx",
        "model_gateway_call_attempts_parent_fkey_idx",
        "model_gateway_call_attempts_runtime_manifest_fkey_idx",
        "model_gateway_call_attempts_runtime_option_fkey_idx",
        "model_gateway_call_attempts_policy_fkey_idx",
        "model_gateway_call_attempts_prompt_state_fkey_idx",
        "model_gateway_terminal_events_attempt_fkey_idx",
        "model_gateway_job_admissions_secret_fkey_idx",
        "model_gateway_call_attempts_secret_fkey_idx",
    ):
        assert f"CREATE INDEX {index}" in source


def test_model_gateway_downgrade_refuses_to_discard_any_history() -> None:
    source = DOWN.read_text(encoding="utf-8")
    assert "cannot downgrade: Model Gateway data exists" in source
    for table in (
        "model_gateway_terminal_events",
        "model_gateway_reconciliation_commands",
        "model_gateway_artifact_recovery_receipts",
        "model_gateway_artifact_master_key_versions",
        "model_gateway_artifact_deks",
        "model_gateway_call_attempts",
        "model_gateway_job_admissions",
        "model_gateway_runtime_options",
        "model_gateway_runtime_manifests",
        "model_gateway_project_policy_versions",
        "model_gateway_model_releases",
        "model_gateway_adapter_releases",
    ):
        assert f"EXISTS (SELECT 1 FROM {table})" in source
