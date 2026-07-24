from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0030_synthetic_lab.py"
UP = ROOT / "infra/db/alembic/sql/0030_synthetic_lab.sql"
DOWN = ROOT / "infra/db/alembic/sql/0030_synthetic_lab.down.sql"
HEAD_UP = ROOT / "infra/db/alembic/sql/0032_recommendation_workflows.sql"
HEAD_DOWN = ROOT / "infra/db/alembic/sql/0032_recommendation_workflows.down.sql"
RETENTION_RECLAIM_MIGRATION = (
    ROOT / "infra/db/alembic/versions/0048_synthetic_retention_reclaim.py"
)
RETENTION_RECLAIM_UP = ROOT / "infra/db/alembic/sql/0048_synthetic_retention_reclaim.sql"
RETENTION_RECLAIM_DOWN = (
    ROOT / "infra/db/alembic/sql/0048_synthetic_retention_reclaim.down.sql"
)


def test_synthetic_lab_revision_is_the_single_linear_head() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0030_synthetic_lab"' in source
    assert 'down_revision = "0029_model_gateway"' in source
    assert UP.is_file() and DOWN.is_file()


def test_synthetic_lab_migration_uses_nonparameterized_driver_cursor() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    source = UP.read_text(encoding="utf-8")
    assert "driver_connection" in migration
    assert "cursor.execute" in migration
    assert "exec_driver_sql" not in migration
    assert "%ROWTYPE" in source
    assert "%%ROWTYPE" not in source


def test_synthetic_lab_schema_covers_versioned_domain_and_execution_state() -> None:
    source = UP.read_text(encoding="utf-8")
    for table in (
        "synthetic_lab_command_receipts",
        "synthetic_lab_aggregate_versions",
        "synthetic_lab_authorization_versions",
        "synthetic_lab_manual_import_previews",
        "synthetic_lab_manual_import_preview_states",
        "synthetic_lab_manual_import_manifests",
        "synthetic_lab_manual_import_row_errors",
        "synthetic_lab_imported_samples",
        "synthetic_lab_imported_sample_artifacts",
        "synthetic_lab_manual_import_cleanup_outbox",
        "synthetic_lab_manual_import_cleanup_receipts",
        "synthetic_lab_artifact_governance_decisions",
        "synthetic_lab_job_metadata",
        "synthetic_lab_outbox_messages",
        "synthetic_lab_model_call_children",
        "synthetic_lab_style_collection_tasks",
        "synthetic_lab_artifact_master_key_versions",
        "synthetic_lab_raw_artifacts",
        "synthetic_lab_artifact_deks",
        "synthetic_lab_artifact_legal_holds",
        "synthetic_lab_artifact_deletion_outbox",
        "synthetic_lab_artifact_crypto_erasures",
        "synthetic_lab_artifact_tombstones",
        "synthetic_lab_style_collection_results",
        "synthetic_lab_execution_tasks",
        "synthetic_lab_execution_results",
        "synthetic_lab_terminal_results",
    ):
        assert f"CREATE TABLE {table}" in source
    for contract in (
        "enqueue_execution",
        "create_style_source",
        "create_style_profile",
        "create_review_suite",
        "create_review_case",
        "expected_job_input_hash",
        "task_payload_hash",
        "result_payload_hash",
        "lease_token",
        "fencing_generation",
        "fact_snapshot_hash",
        "profile_hash",
        "prompt_release_hash",
        "geo_enqueue_synthetic_model_call_child",
        "synthetic.model.call",
        "task_artifact_uri",
        "structured_input_hash",
        "portable_output_schema_hash",
        "application_output_schema_hash",
        "style_profile",
        "offline_answer",
        "prompt_state_version",
    ):
        assert contract in source


def test_synthetic_authorization_reassessment_is_contiguous_and_maker_checker() -> None:
    source = UP.read_text(encoding="utf-8")
    for contract in (
        "reassess_authorization",
        "previous.state IN ('assessed_no_basis', 'expired', 'revoked')",
        "previous.state = 'approved' AND previous.expires_at <= NEW.created_at",
        "NEW.state = 'not_assessed'",
        "NEW.decided_by = previous.submitted_by",
        "Synthetic Lab authorization maker-checker separation failed",
        "ORDER BY version_number DESC LIMIT 1",
        "Synthetic Lab terminal authorization is stale or inactive",
    ):
        assert contract in source


def test_synthetic_lab_reuses_durable_job_and_broker_outbox_truth() -> None:
    source = UP.read_text(encoding="utf-8")
    for contract in (
        "REFERENCES durable_jobs(id, project_id)",
        "REFERENCES broker_outbox(id, project_id)",
        "Synthetic execution task does not match its queued Durable Job",
        "Synthetic execution result lost lease, fence, or frozen runtime lineage",
        "DEFERRABLE INITIALLY DEFERRED",
    ):
        assert contract in source
    assert "CREATE TABLE synthetic_lab_jobs" not in source


def test_synthetic_model_calls_use_fenced_deterministic_child_jobs() -> None:
    source = UP.read_text(encoding="utf-8")
    for contract in (
        "UNIQUE (project_id, parent_job_id, step_key_hash)",
        "parent_lease_token",
        "parent_fencing_generation",
        "Synthetic model child enqueue lost the parent lease or fence",
        "Synthetic model child cannot start after its parent was blocked",
        "geo_block_synthetic_unstarted_model_call_children",
        "geo_wake_synthetic_parent_after_child_terminal",
        "attempt_count = 0",
        "synthetic_parent_blocked",
        "synthetic-child-terminal:",
        "child_terminal_wakeup_staged",
        "next_run_at = LEAST(parent.next_run_at, clock_timestamp())",
        "model-gateway://attempt/",
        "synthetic_lab_model_call_child_status",
        "security_invoker = true",
    ):
        assert contract in source
    assert "GRANT INSERT ON synthetic_lab_model_call_children" not in source
    assert (
        "TO geo_worker"
        in source.split("GRANT EXECUTE ON FUNCTION geo_enqueue_synthetic_model_call_child", 1)[
            1
        ].split(";", 1)[0]
    )


def test_synthetic_artifacts_are_generation_fenced_and_restorable() -> None:
    source = UP.read_text(encoding="utf-8")
    for contract in (
        "PRIMARY KEY (project_id, artifact_id, fencing_generation)",
        "synthetic_lab_raw_artifacts_one_winner",
        "generation_lease_token",
        "geo_mark_synthetic_artifact_attempt_orphaned",
        "geo_claim_synthetic_artifact_deletions",
        "Synthetic artifact writer lost lease/fence or task ownership",
        "Synthetic artifact deletion lease was fenced or held",
        "synthetic_lab_artifact_master_key_versions",
        "geo_sync_synthetic_artifact_master_key_version",
        "synthetic_lab_artifact_deks_restore_idx",
        "style_browser_worker",
    ):
        assert contract in source
    assert "REFERENCES secret_master_key_versions" not in source


def test_synthetic_artifact_deletion_erases_before_remote_object_cleanup() -> None:
    source = UP.read_text(encoding="utf-8")
    down = DOWN.read_text(encoding="utf-8")
    for contract in (
        "object_delete_pending",
        "geo_stage_due_synthetic_artifact_expirations",
        "geo_claim_synthetic_artifact_deletions(text, timestamptz, integer, integer)",
        "geo_crypto_erase_and_tombstone_synthetic_artifact",
        "geo_complete_synthetic_artifact_object_deletion",
        "geo_fail_synthetic_artifact_object_deletion",
        "geo_enqueue_synthetic_artifact_maintenance",
        "independent_dek_destroyed",
        "synthetic-artifact-maintenance:wake:",
        "synthetic_artifact_maintenance_worker",
    ):
        assert contract in source
    # The function returns project_id/job_id, so unqualified durable_jobs columns
    # would bind ambiguously on the first real scheduler invocation.
    assert "FROM durable_jobs AS existing_job" in source
    assert "existing_job.project_id = candidate.project_id" in source
    assert "UPDATE durable_jobs AS wake_job" in source
    assert "FROM durable_jobs AS prior_job" in source
    assert "p_next_attempt_at timestamptz" in source
    assert "next_attempt_at = p_next_attempt_at" in source
    assert "DROP TABLE synthetic_lab_artifact_crypto_erasures" in down
    assert "geo_crypto_erase_and_tombstone_synthetic_artifact" in down


def test_synthetic_artifact_maintenance_is_project_scoped_at_current_head() -> None:
    source = HEAD_UP.read_text(encoding="utf-8")
    down = HEAD_DOWN.read_text(encoding="utf-8")

    assert "geo_stage_due_synthetic_artifact_expirations(\n    p_project_id uuid," in source
    assert "geo_claim_synthetic_artifact_deletions(\n    p_project_id uuid," in source
    assert "NOT p_project_id = ANY(geo_current_project_ids())" in source
    assert "WHERE item.project_id = p_project_id" in source
    assert "geo_stage_synthetic_artifact_expiry(timestamptz, integer)" in source
    assert "geo_claim_synthetic_artifact_deletions(text, timestamptz, integer, integer)" in source
    assert "geo_stage_due_synthetic_artifact_expirations(uuid, timestamptz, integer)" in source
    assert (
        "geo_claim_synthetic_artifact_deletions(uuid, text, timestamptz, integer, integer)"
        in source
    )
    assert (
        "DROP FUNCTION geo_stage_due_synthetic_artifact_expirations(uuid, timestamptz, integer)"
        in down
    )
    assert (
        "GRANT EXECUTE ON FUNCTION\n    geo_stage_synthetic_artifact_expiry(timestamptz, integer)"
        in down
    )


def test_synthetic_retention_reclaim_rotates_fence_without_wall_clock_race() -> None:
    migration = RETENTION_RECLAIM_MIGRATION.read_text(encoding="utf-8")
    source = RETENTION_RECLAIM_UP.read_text(encoding="utf-8")
    down = RETENTION_RECLAIM_DOWN.read_text(encoding="utf-8")

    assert 'revision = "0048_synthetic_retention_reclaim"' in migration
    assert 'down_revision = "0047_sampling_manual_import"' in migration
    assert "CREATE OR REPLACE FUNCTION geo_assert_synthetic_artifact_outbox_change" in source
    assert "NEW.lease_token IS DISTINCT FROM OLD.lease_token" in source
    assert "NEW.lease_expires_at > OLD.lease_expires_at" in source
    assert "OLD.lease_expires_at <= clock_timestamp()" not in source
    assert "OLD.lease_expires_at <= clock_timestamp()" in down


def test_synthetic_retention_scheduler_serializes_new_job_wakes_per_project() -> None:
    migration = (
        ROOT / "infra/db/alembic/versions/0049_synthetic_retention_scheduler_lock.py"
    ).read_text(encoding="utf-8")
    source = (
        ROOT / "infra/db/alembic/sql/0049_synthetic_retention_lock.sql"
    ).read_text(encoding="utf-8")
    down = (
        ROOT / "infra/db/alembic/sql/0049_synthetic_retention_lock.down.sql"
    ).read_text(encoding="utf-8")

    assert 'revision = "0049_synthetic_retention_lock"' in migration
    assert 'down_revision = "0048_synthetic_retention_reclaim"' in migration
    assert len("0049_synthetic_retention_lock") <= 32
    assert "pg_advisory_xact_lock" in source
    assert "synthetic-artifact-maintenance:' || candidate.project_id::text" in source
    assert "ON CONFLICT ON CONSTRAINT broker_outbox_project_id_idempotency_key_key" in source
    assert "pg_advisory_xact_lock" not in down


def test_synthetic_parent_trigger_skips_unrelated_jobs_before_scope_guard() -> None:
    migration = (
        ROOT / "infra/db/alembic/versions/0051_synthetic_parent_trigger_scope.py"
    ).read_text(encoding="utf-8")
    source = (
        ROOT / "infra/db/alembic/sql/0051_synthetic_parent_scope.sql"
    ).read_text(encoding="utf-8")
    down = (
        ROOT / "infra/db/alembic/sql/0051_synthetic_parent_scope.down.sql"
    ).read_text(encoding="utf-8")

    assert 'revision = "0051_synthetic_parent_scope"' in migration
    assert 'down_revision = "0050_wfc_retention_lock"' in migration
    assert len("0051_synthetic_parent_scope") <= 32
    child_lookup = source.index("FROM synthetic_lab_model_call_children AS link")
    scope_guard = source.index("Synthetic child cancellation Project is outside caller scope")
    assert child_lookup < scope_guard
    assert "RETURN 0;" in source[:scope_guard]
    assert "RETURN 0;" not in down


def test_synthetic_manual_import_is_two_stage_encrypted_and_cleanup_fenced() -> None:
    source = UP.read_text(encoding="utf-8")
    down = DOWN.read_text(encoding="utf-8")
    for contract in (
        "geo_create_synthetic_manual_import_preview",
        "geo_finalize_synthetic_manual_import_preview",
        "Synthetic manual import maker-checker separation failed",
        "synthetic_lab_manual_import_preview_states_shape",
        "synthetic_lab_manual_import_preview_current",
        "security_invoker = true",
        "upload_object_uri",
        "upload_plaintext_hash",
        "AES-256-GCM/HKDF-project-artifact/v1",
        "/synthetic-lab/manual-import/temporary_upload/",
        "/synthetic-lab/manual-import/anonymized_sample/",
        "approved manual import lacks exact samples and encrypted artifacts",
        "terminal manual import lacks exact temporary-object cleanup lineage",
        "geo_claim_synthetic_manual_import_cleanups",
        "geo_complete_synthetic_manual_import_cleanup",
        "geo_fail_synthetic_manual_import_cleanup",
        "Synthetic manual import cleanup lease was fenced",
    ):
        assert contract in source
    assert "GRANT INSERT ON synthetic_lab_manual_import_previews" not in source
    assert "GRANT INSERT ON synthetic_lab_manual_import_preview_states" not in source
    for table in (
        "synthetic_lab_manual_import_cleanup_receipts",
        "synthetic_lab_manual_import_cleanup_outbox",
        "synthetic_lab_imported_sample_artifacts",
        "synthetic_lab_manual_import_preview_states",
        "synthetic_lab_manual_import_previews",
    ):
        assert f"DROP TABLE {table}" in down


def test_synthetic_lab_forbids_raw_bodies_credentials_and_customer_reads() -> None:
    source = UP.read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in (
        "raw_body",
        "page_body",
        "sample_text",
        "credential_value",
        "secret_value",
        "proxy_password",
    ):
        assert forbidden not in lowered
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "geo_current_project_ids()" in source
    assert "FROM PUBLIC, geo_app, geo_worker, geo_readonly" in source
    select_grants = source.split("GRANT SELECT ON")[1:]
    assert select_grants
    assert all("geo_readonly" not in grant.split(";", 1)[0] for grant in select_grants)


def test_synthetic_lab_is_immutable_and_worker_write_scope_is_private() -> None:
    source = UP.read_text(encoding="utf-8")
    assert "geo_reject_immutable_change()" in source
    assert "GRANT DELETE" not in source
    assert "GRANT INSERT ON\n    synthetic_lab_command_receipts" in source
    assert (
        "synthetic_lab_execution_results, synthetic_lab_terminal_results\nTO geo_worker" in source
    )
    assert "GRANT UPDATE ON synthetic_lab_job_metadata" not in source
    assert "GRANT UPDATE (metadata_version, updated_at) ON synthetic_lab_job_metadata" in source


def test_synthetic_lab_downgrade_refuses_to_discard_history() -> None:
    source = DOWN.read_text(encoding="utf-8")
    assert "cannot downgrade: Synthetic Lab data exists" in source
    for table in (
        "synthetic_lab_terminal_results",
        "synthetic_lab_execution_results",
        "synthetic_lab_execution_tasks",
        "synthetic_lab_model_call_children",
        "synthetic_lab_style_collection_tasks",
        "synthetic_lab_artifact_master_key_versions",
        "synthetic_lab_raw_artifacts",
        "synthetic_lab_artifact_deks",
        "synthetic_lab_artifact_deletion_outbox",
        "synthetic_lab_job_metadata",
        "synthetic_lab_authorization_versions",
        "synthetic_lab_manual_import_previews",
        "synthetic_lab_manual_import_preview_states",
        "synthetic_lab_imported_sample_artifacts",
        "synthetic_lab_manual_import_cleanup_outbox",
        "synthetic_lab_manual_import_cleanup_receipts",
        "synthetic_lab_aggregate_versions",
        "synthetic_lab_command_receipts",
    ):
        assert f"EXISTS (SELECT 1 FROM {table})" in source
