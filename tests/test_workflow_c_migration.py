from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0031_workflow_c_stats_alerts.py"
UP = ROOT / "infra/db/alembic/sql/0031_workflow_c_stats_alerts.sql"
DOWN = ROOT / "infra/db/alembic/sql/0031_workflow_c_stats_alerts.down.sql"
FOLLOW_UP_UP = ROOT / "infra/db/alembic/sql/0032_recommendation_workflows.sql"
FOLLOW_UP_DOWN = ROOT / "infra/db/alembic/sql/0032_recommendation_workflows.down.sql"
ARTIFACT_ENCRYPTION_MIGRATION = (
    ROOT / "infra/db/alembic/versions/0046_workflow_c_artifact_encryption.py"
)
ARTIFACT_ENCRYPTION_UP = ROOT / "infra/db/alembic/sql/0046_wfc_artifact_encryption.sql"
ARTIFACT_ENCRYPTION_DOWN = ROOT / "infra/db/alembic/sql/0046_wfc_artifact_encryption.down.sql"
MANUAL_IMPORT_CONTROL_MIGRATION = (
    ROOT / "infra/db/alembic/versions/0047_sampling_manual_import_control.py"
)
MANUAL_IMPORT_CONTROL_UP = ROOT / "infra/db/alembic/sql/0047_sampling_manual_import.sql"
MANUAL_IMPORT_CONTROL_DOWN = ROOT / "infra/db/alembic/sql/0047_sampling_manual_import.down.sql"
WFC_RETENTION_LOCK_MIGRATION = ROOT / "infra/db/alembic/versions/0050_wfc_retention_lock.py"
WFC_RETENTION_LOCK_UP = ROOT / "infra/db/alembic/sql/0050_wfc_retention_lock.sql"
WFC_RETENTION_LOCK_DOWN = ROOT / "infra/db/alembic/sql/0050_wfc_retention_lock.down.sql"
PROVIDER_EXECUTION_INPUT_MIGRATION = (
    ROOT / "infra/db/alembic/versions/0052_provider_execution_input.py"
)
PROVIDER_EXECUTION_INPUT_UP = ROOT / "infra/db/alembic/sql/0052_provider_execution_input.sql"
PROVIDER_EXECUTION_INPUT_DOWN = ROOT / "infra/db/alembic/sql/0052_provider_execution_input.down.sql"
PROVIDER_EXECUTION_ENFORCEMENT_MIGRATION = (
    ROOT / "infra/db/alembic/versions/0053_provider_execution_enforcement.py"
)
PROVIDER_EXECUTION_ENFORCEMENT_UP = ROOT / "infra/db/alembic/sql/0053_provider_exec_enforce.sql"
PROVIDER_EXECUTION_ENFORCEMENT_DOWN = (
    ROOT / "infra/db/alembic/sql/0053_provider_exec_enforce.down.sql"
)
PROVIDER_ATTEMPT_SCHEDULE_MIGRATION = (
    ROOT / "infra/db/alembic/versions/0054_provider_attempt_schedule.py"
)
PROVIDER_ATTEMPT_SCHEDULE_UP = ROOT / "infra/db/alembic/sql/0054_provider_attempt_schedule.sql"
PROVIDER_ATTEMPT_SCHEDULE_DOWN = (
    ROOT / "infra/db/alembic/sql/0054_provider_attempt_schedule.down.sql"
)
PROVIDER_BULK_ENQUEUE_MIGRATION = ROOT / "infra/db/alembic/versions/0055_provider_bulk_enqueue.py"
PROVIDER_BULK_ENQUEUE_UP = ROOT / "infra/db/alembic/sql/0055_provider_bulk_enqueue.sql"
PROVIDER_BULK_ENQUEUE_DOWN = ROOT / "infra/db/alembic/sql/0055_provider_bulk_enqueue.down.sql"
SAMPLING_CANCEL_RESULT_LINEAGE_MIGRATION = (
    ROOT / "infra/db/alembic/versions/0056_sampling_cancel_result_lineage.py"
)
SAMPLING_CANCEL_RESULT_LINEAGE_UP = ROOT / "infra/db/alembic/sql/0056_sampling_cancel_lineage.sql"
SAMPLING_CANCEL_RESULT_LINEAGE_DOWN = (
    ROOT / "infra/db/alembic/sql/0056_sampling_cancel_lineage.down.sql"
)
PROVIDER_EXECUTION_RETIREMENT_MIGRATION = (
    ROOT / "infra/db/alembic/versions/0057_provider_execution_retirement.py"
)
PROVIDER_EXECUTION_RETIREMENT_UP = ROOT / "infra/db/alembic/sql/0057_provider_exec_retirement.sql"
PROVIDER_EXECUTION_RETIREMENT_DOWN = (
    ROOT / "infra/db/alembic/sql/0057_provider_exec_retirement.down.sql"
)
WORKFLOW_C_SPEC_SENSITIVE_MIGRATION = (
    ROOT / "infra/db/alembic/versions/0058_workflow_c_spec_sensitive_fields.py"
)
WORKFLOW_C_SPEC_SENSITIVE_UP = ROOT / "infra/db/alembic/sql/0058_wfc_spec_sensitive.sql"
WORKFLOW_C_SPEC_SENSITIVE_DOWN = ROOT / "infra/db/alembic/sql/0058_wfc_spec_sensitive.down.sql"
ANALYSIS_PROJECT_SCOPE_MIGRATION = (
    ROOT / "infra/db/alembic/versions/0059_analysis_projection_project_scope.py"
)
ANALYSIS_PROJECT_SCOPE_UP = ROOT / "infra/db/alembic/sql/0059_analysis_project_scope.sql"
ANALYSIS_PROJECT_SCOPE_DOWN = ROOT / "infra/db/alembic/sql/0059_analysis_project_scope.down.sql"
METRIC_RPC_AGGREGATE_FIX_MIGRATION = (
    ROOT / "infra/db/alembic/versions/0060_metric_rpc_aggregate_fix.py"
)
METRIC_RPC_AGGREGATE_FIX_UP = ROOT / "infra/db/alembic/sql/0060_metric_rpc_aggregate_fix.sql"
METRIC_RPC_AGGREGATE_FIX_DOWN = ROOT / "infra/db/alembic/sql/0060_metric_rpc_aggregate_fix.down.sql"
METRIC_CHILD_RECONCILE_MIGRATION = ROOT / "infra/db/alembic/versions/0061_metric_child_reconcile.py"
METRIC_CHILD_RECONCILE_UP = ROOT / "infra/db/alembic/sql/0061_metric_child_reconcile.sql"
METRIC_CHILD_RECONCILE_DOWN = ROOT / "infra/db/alembic/sql/0061_metric_child_reconcile.down.sql"
METRIC_JUDGE_AGREEMENT_MIGRATION = ROOT / "infra/db/alembic/versions/0062_metric_judge_agreement.py"
METRIC_JUDGE_AGREEMENT_UP = ROOT / "infra/db/alembic/sql/0062_metric_judge_agreement.sql"
METRIC_JUDGE_AGREEMENT_DOWN = ROOT / "infra/db/alembic/sql/0062_metric_judge_agreement.down.sql"
ARTIFACT_WRITE_FAILURE_GRANT_MIGRATION = (
    ROOT / "infra/db/alembic/versions/0063_wfc_artifact_write_grant.py"
)
ARTIFACT_WRITE_FAILURE_GRANT_UP = ROOT / "infra/db/alembic/sql/0063_wfc_artifact_write_grant.sql"
ARTIFACT_WRITE_FAILURE_GRANT_DOWN = (
    ROOT / "infra/db/alembic/sql/0063_wfc_artifact_write_grant.down.sql"
)
ARTIFACT_HOLD_EXPIRY_MIGRATION = ROOT / "infra/db/alembic/versions/0064_wfc_artifact_hold_expiry.py"
ARTIFACT_HOLD_EXPIRY_UP = ROOT / "infra/db/alembic/sql/0064_wfc_artifact_hold_expiry.sql"
ARTIFACT_HOLD_EXPIRY_DOWN = ROOT / "infra/db/alembic/sql/0064_wfc_artifact_hold_expiry.down.sql"
METRIC_OUTPUT_PROJECTION_MIGRATION = (
    ROOT / "infra/db/alembic/versions/0065_metric_output_projection.py"
)
METRIC_OUTPUT_PROJECTION_UP = ROOT / "infra/db/alembic/sql/0065_metric_output_projection.sql"
METRIC_OUTPUT_PROJECTION_DOWN = ROOT / "infra/db/alembic/sql/0065_metric_output_projection.down.sql"
METRIC_ARBITER_ADMISSION_MIGRATION = (
    ROOT / "infra/db/alembic/versions/0067_metric_arbiter_admission.py"
)
METRIC_ARBITER_ADMISSION_UP = ROOT / "infra/db/alembic/sql/0067_metric_arbiter_admission.sql"
METRIC_ARBITER_ADMISSION_DOWN = ROOT / "infra/db/alembic/sql/0067_metric_arbiter_admission.down.sql"
METRIC_PARENT_PROGRESS_MIGRATION = ROOT / "infra/db/alembic/versions/0068_metric_parent_progress.py"
METRIC_PARENT_PROGRESS_UP = ROOT / "infra/db/alembic/sql/0068_metric_parent_progress.sql"
METRIC_PARENT_PROGRESS_DOWN = ROOT / "infra/db/alembic/sql/0068_metric_parent_progress.down.sql"
SEMANTIC_SNAPSHOT_PERSISTENCE_MIGRATION = (
    ROOT / "infra/db/alembic/versions/0069_metric_snapshot_rpc.py"
)
SEMANTIC_SNAPSHOT_PERSISTENCE_UP = ROOT / "infra/db/alembic/sql/0069_metric_snapshot_rpc.sql"
SEMANTIC_SNAPSHOT_PERSISTENCE_DOWN = ROOT / "infra/db/alembic/sql/0069_metric_snapshot_rpc.down.sql"
ANALYSIS_PROJECTION_PERSISTENCE_MIGRATION = (
    ROOT / "infra/db/alembic/versions/0070_analysis_projection_rpc.py"
)
ANALYSIS_PROJECTION_PERSISTENCE_UP = ROOT / "infra/db/alembic/sql/0070_analysis_projection_rpc.sql"
ANALYSIS_PROJECTION_PERSISTENCE_DOWN = (
    ROOT / "infra/db/alembic/sql/0070_analysis_projection_rpc.down.sql"
)


def test_workflow_c_revision_is_linear_and_has_reversible_sql_files() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0031_workflow_c_stats_alerts"' in source
    assert 'down_revision = "0030_synthetic_lab"' in source
    assert UP.is_file() and DOWN.is_file()
    assert "driver_connection" in source
    assert "cursor.execute" in source


def test_analytical_projection_hashes_are_project_scoped_at_the_database_boundary() -> None:
    migration = ANALYSIS_PROJECT_SCOPE_MIGRATION.read_text(encoding="utf-8")
    source = ANALYSIS_PROJECT_SCOPE_UP.read_text(encoding="utf-8")
    down = ANALYSIS_PROJECT_SCOPE_DOWN.read_text(encoding="utf-8")
    persistence = (
        ROOT / "packages/geo_core/geo_core/workflow_c_analysis_persistence.py"
    ).read_text(encoding="utf-8")
    projection_rpc = ANALYSIS_PROJECTION_PERSISTENCE_UP.read_text(encoding="utf-8")

    assert 'revision = "0059_analysis_project_scope"' in migration
    assert 'down_revision = "0058_wfc_spec_sensitive"' in migration
    for contract in (
        "PRIMARY KEY (project_id, snapshot_hash)",
        "PRIMARY KEY (project_id, snapshot_hash, metric_key)",
        "PRIMARY KEY (project_id, family_hash)",
        "PRIMARY KEY (project_id, family_hash, comparison_id)",
        "PRIMARY KEY (project_id, report_hash)",
        "family.project_id = result.project_id",
        "geo_resolve_recommendation_evidence_pre_0059",
    ):
        assert contract in source
    for contract in (
        "ON CONFLICT (project_id, family_hash)",
        "ON CONFLICT (project_id, report_hash)",
        "WHERE project_id = %s AND snapshot_hash = %s",
        "WHERE project_id = %s AND family_hash = %s",
        "WHERE project_id = %s AND report_hash = %s",
    ):
        assert contract in persistence or contract in projection_rpc
    assert "geo_persist_workflow_c_semantic_metric_snapshot" in persistence
    assert "Project-scoped analytical hash identities exist" in down


def test_metric_child_terminal_rpcs_qualify_their_aggregate_version_updates() -> None:
    migration = METRIC_RPC_AGGREGATE_FIX_MIGRATION.read_text(encoding="utf-8")
    source = METRIC_RPC_AGGREGATE_FIX_UP.read_text(encoding="utf-8")
    down = METRIC_RPC_AGGREGATE_FIX_DOWN.read_text(encoding="utf-8")

    assert 'revision = "0060_metric_rpc_aggregate_fix"' in migration
    assert 'down_revision = "0059_analysis_project_scope"' in migration
    assert (
        source.count("aggregate_version = workflow_c_metric_judge_batches.aggregate_version + 1")
        == 2
    )
    assert "pg_get_functiondef" in source
    assert "metric completion RPC does not match" in source
    assert "metric failure RPC does not match" in source
    assert down.count("aggregate_version = aggregate_version + 1") == 2


def test_metric_child_durable_reconciliation_closes_retry_failure_and_cancel_paths() -> None:
    migration = METRIC_CHILD_RECONCILE_MIGRATION.read_text(encoding="utf-8")
    source = METRIC_CHILD_RECONCILE_UP.read_text(encoding="utf-8")
    down = METRIC_CHILD_RECONCILE_DOWN.read_text(encoding="utf-8")

    assert 'revision = "0061_metric_child_reconcile"' in migration
    assert 'down_revision = "0060_metric_rpc_aggregate_fix"' in migration
    for contract in (
        "geo_reconcile_workflow_c_metric_child_durable_status",
        "workflow_c_metric_child_durable_status",
        "'retry_wait', 'failed', 'dead_lettered', 'cancelled'",
        "Metric retry Durable Job conflicts with terminal child",
        "workflow_c_metric_judge_batches.aggregate_version + 1",
        "sibling_job.status IN ('queued', 'retry_wait')",
        "sibling_job.status IN ('running', 'finalizing')",
        "SET row_security = off",
    ):
        assert contract in source
    assert "DROP TRIGGER workflow_c_metric_child_durable_status" in down
    assert "DROP FUNCTION geo_reconcile_workflow_c_metric_child_durable_status" in down


def test_metric_judge_agreement_completes_a_batch_without_an_arbiter() -> None:
    migration = METRIC_JUDGE_AGREEMENT_MIGRATION.read_text(encoding="utf-8")
    source = METRIC_JUDGE_AGREEMENT_UP.read_text(encoding="utf-8")
    down = METRIC_JUDGE_AGREEMENT_DOWN.read_text(encoding="utf-8")

    assert 'revision = "0062_metric_judge_agreement"' in migration
    assert 'down_revision = "0061_metric_child_reconcile"' in migration
    for contract in (
        "CREATE OR REPLACE FUNCTION geo_complete_workflow_c_metric_child",
        "SET row_security = off",
        "judge_count >= 2 AND judge_output_count = 1",
        "selected_candidate_id = agreed_candidate_id",
        "ORDER BY judge.evaluator_id, judge.candidate_id",
        "workflow_c_metric_judge_batches.aggregate_version + 1",
    ):
        assert contract in source
    assert "CREATE OR REPLACE FUNCTION geo_complete_workflow_c_metric_child" in down
    assert "selected_candidate_id = agreed_candidate_id" not in down


def test_restricted_artifact_writer_can_enqueue_only_failed_stage_cleanup() -> None:
    migration = ARTIFACT_WRITE_FAILURE_GRANT_MIGRATION.read_text(encoding="utf-8")
    source = ARTIFACT_WRITE_FAILURE_GRANT_UP.read_text(encoding="utf-8")
    down = ARTIFACT_WRITE_FAILURE_GRANT_DOWN.read_text(encoding="utf-8")

    assert 'revision = "0063_wfc_artifact_write_grant"' in migration
    assert 'down_revision = "0062_metric_judge_agreement"' in migration
    function = "geo_enqueue_workflow_c_artifact_write_failure(uuid, uuid)"
    assert "FROM workflow_c_manual_artifacts AS artifact_row" in source
    assert "artifact_row.artifact_id = p_artifact_id" in source
    assert "FROM workflow_c_artifact_deletion_queue AS queued_row" in source
    assert f"GRANT EXECUTE ON FUNCTION {function}" in source
    assert "TO geo_app" in source
    assert "GRANT EXECUTE ON FUNCTION geo_schedule_workflow_c_artifact_maintenance" not in source
    assert f"REVOKE EXECUTE ON FUNCTION {function}" in down
    assert "FROM geo_app" in down
    assert "SELECT * INTO STRICT artifact FROM workflow_c_manual_artifacts" in down


def test_artifact_legal_holds_are_bounded_reapproved_and_expire_into_retention() -> None:
    migration = ARTIFACT_HOLD_EXPIRY_MIGRATION.read_text(encoding="utf-8")
    source = ARTIFACT_HOLD_EXPIRY_UP.read_text(encoding="utf-8")
    down = ARTIFACT_HOLD_EXPIRY_DOWN.read_text(encoding="utf-8")

    assert 'revision = "0064_wfc_artifact_hold_expiry"' in migration
    assert 'down_revision = "0063_wfc_artifact_write_grant"' in migration
    for contract in (
        "legal_hold_until",
        "hold_policy_version",
        "'apply', 'extend', 'release'",
        "INTERVAL '90 days'",
        "geo_expire_workflow_c_artifact_holds",
        "hold_extended",
        "hold_period_elapsed",
        "PERFORM geo_expire_workflow_c_artifact_holds(p_now, p_limit)",
        "REVOKE INSERT ON workflow_c_artifact_hold_requests FROM geo_app",
    ):
        assert contract in source
    assert "active Workflow C legal holds require manual release and reapproval" in source
    assert "legacy_0064_bounded_hold" in down
    assert "DROP FUNCTION geo_expire_workflow_c_artifact_holds" in down


def test_metric_child_output_projection_is_hash_bound_and_immutable() -> None:
    migration = METRIC_OUTPUT_PROJECTION_MIGRATION.read_text(encoding="utf-8")
    source = METRIC_OUTPUT_PROJECTION_UP.read_text(encoding="utf-8")
    down = METRIC_OUTPUT_PROJECTION_DOWN.read_text(encoding="utf-8")

    assert 'revision = "0065_metric_output_projection"' in migration
    assert 'down_revision = "0064_wfc_artifact_hold_expiry"' in migration
    for contract in (
        "workflow_c_metric_child_output_projections",
        "output_projection jsonb",
        "workflow_c_metric_child_output_projections_change_guard",
        "geo_jsonb_canonical_text(p_output_projection)",
        "metric output projection does not match its hash",
        "output projection is immutable",
        "uuid, uuid, uuid, integer, text, text, uuid, text, uuid, text, jsonb",
    ):
        assert contract in source
    assert "DROP FUNCTION geo_complete_workflow_c_metric_child" in down
    assert "DROP TABLE workflow_c_metric_child_output_projections" in down


def test_metric_arbiter_admission_requires_complete_disagreeing_judge_lineage() -> None:
    migration = METRIC_ARBITER_ADMISSION_MIGRATION.read_text(encoding="utf-8")
    source = METRIC_ARBITER_ADMISSION_UP.read_text(encoding="utf-8")
    down = METRIC_ARBITER_ADMISSION_DOWN.read_text(encoding="utf-8")

    assert 'revision = "0067_metric_arbiter_admission"' in migration
    assert 'down_revision = "0066_metric_parent_admission"' in migration
    for contract in (
        "geo_admit_workflow_c_metric_arbiter_child",
        "SET row_security = off",
        "workflow_c_metric_child_output_projections",
        "judge_output_count < 2",
        "judge_projection_count <> judge_count",
        "arbiter_child_job_id IS NOT NULL",
        "workflow_c.metric_arbiter",
        "workflow_c_metric_judge_batches.aggregate_version + 1",
        "task_hash' <> child_task_hash",
        "GRANT EXECUTE",
        "TO geo_worker",
    ):
        assert contract in source
    assert "REVOKE ALL ON FUNCTION geo_admit_workflow_c_metric_arbiter_child" in source
    assert "DROP FUNCTION geo_admit_workflow_c_metric_arbiter_child" in down


def test_workflow_c_schema_freezes_sampling_metric_alert_and_artifact_lineage() -> None:
    source = UP.read_text(encoding="utf-8")
    for table in (
        "workflow_c_sampling_admission_policies",
        "workflow_c_sampling_suites",
        "workflow_c_sampling_runs",
        "workflow_c_sampling_tasks",
        "workflow_c_sampling_attempts",
        "workflow_c_sampling_observations",
        "workflow_c_sampling_manual_imports",
        "workflow_c_semantic_metric_snapshots",
        "workflow_c_metric_judge_batches",
        "workflow_c_metric_model_children",
        "workflow_c_comparison_families",
        "workflow_c_comparison_results",
        "workflow_c_drift_reports",
        "workflow_c_monitoring_report_snapshots",
        "workflow_c_alert_rule_versions",
        "workflow_c_alerts",
        "workflow_c_alert_notifications",
        "workflow_c_artifact_master_key_versions",
        "workflow_c_artifact_deks",
        "workflow_c_manual_artifacts",
        "workflow_c_artifact_deletion_queue",
        "workflow_c_artifact_hold_requests",
        "workflow_c_artifact_lifecycle_events",
    ):
        assert f"CREATE TABLE {table}" in source
    for contract in (
        "portable_output_schema_hash",
        "application_output_schema_hash",
        "UNIQUE (project_id, parent_job_id, observation_id, ordinal)",
        "UNIQUE (project_id, batch_id, role, ordinal)",
        "inconclusive",
        "insufficient_evidence",
        "geo_claim_workflow_c_artifact_deletion",
        "geo_record_workflow_c_artifact_deletion_attempt",
        "geo_request_workflow_c_artifact_hold",
        "geo_decide_workflow_c_artifact_hold",
        "crypto_erased",
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
        "geo_current_project_ids()",
        "FROM PUBLIC, geo_app, geo_worker, geo_readonly",
    ):
        assert contract in source


def test_workflow_c_artifact_maintenance_is_seeded_per_project_before_delete_claims() -> None:
    source = UP.read_text(encoding="utf-8")

    assert "geo_seed_workflow_c_artifact_maintenance(timestamptz, integer, integer)" in source
    assert "geo_schedule_workflow_c_artifact_maintenance(uuid, timestamptz)" in source
    assert "geo_claim_workflow_c_artifact_deletion(uuid, text, timestamptz, integer)" in source
    assert (
        "geo_crypto_erase_workflow_c_artifact_deletion(uuid, uuid, integer, timestamptz)" in source
    )
    assert "PERFORM * FROM geo_enqueue_workflow_c_artifact_maintenance(" in source
    assert "candidate.project_id, p_now, p_staged_grace_seconds" in source
    assert (
        "PERFORM 1 FROM geo_schedule_workflow_c_artifact_maintenance(p_project_id, queued_at)"
        in source
    )
    assert "WHERE queued.project_id = p_project_id AND (" in source
    assert "workflow-c-artifact-maintenance:wake:" in source
    assert "workflow_c_maintenance_scheduler" in source


def test_workflow_c_alert_channel_contract_is_compatible_at_current_head() -> None:
    head = ROOT / "infra/db/alembic/sql/0032_recommendation_workflows.sql"
    down = ROOT / "infra/db/alembic/sql/0032_recommendation_workflows.down.sql"
    source = head.read_text(encoding="utf-8")

    assert "channel IN ('admin_inbox', 'local_smtp', 'internal_webhook')" in source
    assert "WHEN 'smtp' THEN 'local_smtp'" in source
    assert "WHEN 'webhook' THEN 'internal_webhook'" in source
    assert "ADD COLUMN last_attempt_at timestamptz" in source
    assert "workflow_c_alert_notifications_pending_attempt_check" in source
    assert "workflow_c_alert_notifications_terminal_attempt_check" in source
    assert "workflow_c_alert_notifications_retry_after_attempt_check" in source
    assert "reconcile non-pending notification rows first" in source
    assert "GRANT UPDATE (\n    status, attempt_count, last_attempt_at, next_attempt_at," in source
    assert "WHEN 'local_smtp' THEN 'smtp'" in down.read_text(encoding="utf-8")
    assert "cannot downgrade: alert attempt provenance exists" in down.read_text(encoding="utf-8")
    assert "REVOKE UPDATE ON workflow_c_alert_notifications FROM geo_worker" in down.read_text(
        encoding="utf-8"
    )


def test_workflow_c_downgrade_refuses_to_discard_operational_evidence() -> None:
    source = DOWN.read_text(encoding="utf-8")
    assert "cannot downgrade: Workflow C data exists" in source
    for table in (
        "workflow_c_sampling_attempts",
        "workflow_c_semantic_metric_snapshots",
        "workflow_c_metric_model_children",
        "workflow_c_alerts",
        "workflow_c_manual_artifacts",
        "workflow_c_artifact_deletion_queue",
        "workflow_c_artifact_lifecycle_events",
    ):
        assert f"EXISTS (SELECT 1 FROM {table})" in source


def test_workflow_c_job_specs_bind_the_producer_to_one_frozen_durable_input() -> None:
    source = FOLLOW_UP_UP.read_text(encoding="utf-8")
    down = FOLLOW_UP_DOWN.read_text(encoding="utf-8")

    assert "CREATE TABLE workflow_c_job_specs" in source
    assert "FOREIGN KEY (job_id, project_id) REFERENCES durable_jobs" in source
    assert "durable.kind <> NEW.kind OR durable.input_hash <> NEW.spec_hash" in source
    assert "Workflow C Job spec is immutable" in source
    assert "workflow_c_job_spec_immutable_guard" in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "GRANT INSERT ON workflow_c_job_specs" in source
    assert "TO geo_app" in source
    assert "DROP TABLE workflow_c_job_specs" in down
    assert "EXISTS (SELECT 1 FROM workflow_c_job_specs)" in down


def test_workflow_c_notification_channel_values_match_the_worker_contract() -> None:
    source = FOLLOW_UP_UP.read_text(encoding="utf-8")
    down = FOLLOW_UP_DOWN.read_text(encoding="utf-8")

    assert "local_smtp" in source
    assert "internal_webhook" in source
    assert "smtp" in source and "webhook" in source
    assert "local_smtp" in down
    assert "internal_webhook" in down


def test_workflow_c_manual_artifact_encryption_migration_matches_the_writer_contract() -> None:
    migration = ARTIFACT_ENCRYPTION_MIGRATION.read_text(encoding="utf-8")
    source = ARTIFACT_ENCRYPTION_UP.read_text(encoding="utf-8")
    down = ARTIFACT_ENCRYPTION_DOWN.read_text(encoding="utf-8")

    assert 'revision = "0046_wfc_artifact_encryption"' in migration
    assert 'down_revision = "0045_sampling_terminal_reconcile"' in migration
    assert "AES-256-GCM/independent-DEK/v1" in source
    assert "automatic_structured_redaction" in source
    assert "operator_attested_pre_redacted_pending_dual_review" in source
    assert "CREATE FUNCTION geo_activate_workflow_c_manual_artifact" in source
    assert "SECURITY DEFINER" in source
    assert "geo_current_project_ids()" in source
    assert "GRANT EXECUTE ON FUNCTION geo_activate_workflow_c_manual_artifact" in source
    assert "cannot downgrade: current Workflow C artifact lineage exists" in down


def test_provider_execution_input_is_immutable_and_bound_before_provider_enqueue() -> None:
    migration = PROVIDER_EXECUTION_INPUT_MIGRATION.read_text(encoding="utf-8")
    source = PROVIDER_EXECUTION_INPUT_UP.read_text(encoding="utf-8")
    down = PROVIDER_EXECUTION_INPUT_DOWN.read_text(encoding="utf-8")

    assert 'revision = "0052_provider_execution_input"' in migration
    assert 'down_revision = "0051_synthetic_parent_scope"' in migration
    assert "CREATE TABLE workflow_c_sampling_provider_execution_inputs" in source
    assert "geo_register_workflow_c_provider_execution_input" in source
    assert "geo_bind_workflow_c_sampling_provider_execution_input" in source
    assert "BEFORE INSERT ON workflow_c_sampling_suites" in source
    assert "Provider execution input is immutable once registered" in source
    assert "Provider execution input questions differ from the frozen Suite input" in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "GRANT EXECUTE ON FUNCTION" in source
    assert "TO geo_app" in source
    assert "cannot downgrade Provider execution input while data exists" in down


def test_provider_execution_binding_is_enforced_at_suite_and_attempt_write_boundaries() -> None:
    migration = PROVIDER_EXECUTION_ENFORCEMENT_MIGRATION.read_text(encoding="utf-8")
    source = PROVIDER_EXECUTION_ENFORCEMENT_UP.read_text(encoding="utf-8")
    down = PROVIDER_EXECUTION_ENFORCEMENT_DOWN.read_text(encoding="utf-8")

    assert 'revision = "0053_provider_exec_enforce"' in migration
    assert 'down_revision = "0052_provider_execution_input"' in migration
    assert "geo_require_workflow_c_sampling_provider_execution_input" in source
    assert "geo_verify_workflow_c_provider_execution_attempt" in source
    assert "Provider Sampling Suite has no frozen execution input" in source
    assert "Provider Sampling Attempt differs from its frozen execution input" in source
    assert "BEFORE INSERT ON workflow_c_sampling_suites" in source
    assert "BEFORE INSERT ON workflow_c_sampling_attempts" in source
    assert (
        "DROP TRIGGER IF EXISTS workflow_c_sampling_attempt_verify_provider_execution_input" in down
    )


def test_provider_attempt_schedule_is_durable_and_old_unscheduled_rpc_is_not_app_callable() -> None:
    migration = PROVIDER_ATTEMPT_SCHEDULE_MIGRATION.read_text(encoding="utf-8")
    source = PROVIDER_ATTEMPT_SCHEDULE_UP.read_text(encoding="utf-8")
    down = PROVIDER_ATTEMPT_SCHEDULE_DOWN.read_text(encoding="utf-8")

    assert 'revision = "0054_provider_attempt_schedule"' in migration
    assert 'down_revision = "0053_provider_exec_enforce"' in migration
    assert "geo_schedule_workflow_c_provider_sampling_attempt" in source
    assert "p_requested_not_before timestamptz" in source
    assert "SET next_run_at = scheduled_at" in source
    assert "idempotency schedule changed" in source
    assert ") FROM geo_app;" in source
    assert "GRANT EXECUTE ON FUNCTION geo_schedule_workflow_c_provider_sampling_attempt" in source
    assert "DROP FUNCTION IF EXISTS geo_schedule_workflow_c_provider_sampling_attempt" in down


def test_provider_bulk_enqueue_is_one_atomic_replayable_database_command() -> None:
    migration = PROVIDER_BULK_ENQUEUE_MIGRATION.read_text(encoding="utf-8")
    source = PROVIDER_BULK_ENQUEUE_UP.read_text(encoding="utf-8")
    down = PROVIDER_BULK_ENQUEUE_DOWN.read_text(encoding="utf-8")

    assert 'revision = "0055_provider_bulk_enqueue"' in migration
    assert 'down_revision = "0054_provider_attempt_schedule"' in migration
    assert "geo_enqueue_ready_workflow_c_provider_sampling_attempts" in source
    assert "SECURITY DEFINER" in source and "SET row_security = off" in source
    assert "ORDER BY task_key" in source and "FOR UPDATE" in source
    assert "geo_schedule_workflow_c_provider_sampling_attempt" in source
    assert "bulk Sampling items differ from the ready Task slice" in source
    assert "sampling.provider_attempt.bulk_enqueue" in source
    assert "jsonb_set(existing.result_payload, '{replayed}', 'true'::jsonb, false)" in source
    assert (
        "REVOKE ALL ON FUNCTION geo_enqueue_ready_workflow_c_provider_sampling_attempts" in source
    )
    assert (
        "GRANT EXECUTE ON FUNCTION geo_enqueue_ready_workflow_c_provider_sampling_attempts"
        in source
    )
    assert "DROP FUNCTION IF EXISTS geo_enqueue_ready_workflow_c_provider_sampling_attempts" in down


def test_sampling_run_cancellation_replay_persists_exact_attempt_lineage() -> None:
    migration = SAMPLING_CANCEL_RESULT_LINEAGE_MIGRATION.read_text(encoding="utf-8")
    source = SAMPLING_CANCEL_RESULT_LINEAGE_UP.read_text(encoding="utf-8")
    down = SAMPLING_CANCEL_RESULT_LINEAGE_DOWN.read_text(encoding="utf-8")

    assert 'revision = "0056_sampling_cancel_lineage"' in migration
    assert 'down_revision = "0055_provider_bulk_enqueue"' in migration
    assert "geo_cancel_workflow_c_sampling_run_v2" in source
    assert "pg_advisory_xact_lock" in source
    assert "FOR UPDATE OF attempt, task, durable" in source
    assert "'attempt_ids', to_jsonb(targeted_attempt_ids)" in source
    assert "replay lacks immutable Attempt lineage" in source
    assert "GRANT EXECUTE ON FUNCTION geo_cancel_workflow_c_sampling_run_v2" in source
    assert "DROP FUNCTION geo_cancel_workflow_c_sampling_run_v2" in down


def test_provider_execution_input_retirement_preserves_frozen_suite_lineage() -> None:
    migration = PROVIDER_EXECUTION_RETIREMENT_MIGRATION.read_text(encoding="utf-8")
    source = PROVIDER_EXECUTION_RETIREMENT_UP.read_text(encoding="utf-8")
    down = PROVIDER_EXECUTION_RETIREMENT_DOWN.read_text(encoding="utf-8")

    assert 'revision = "0057_provider_exec_retirement"' in migration
    assert 'down_revision = "0056_sampling_cancel_lineage"' in migration
    assert len("0057_provider_exec_retirement") <= 32
    assert "aggregate_version integer NOT NULL DEFAULT 1" in source
    assert "geo_retire_workflow_c_provider_execution_input" in source
    assert "SECURITY DEFINER" in source and "SET row_security = off" in source
    assert "Provider execution input retirement idempotency key was reused" in source
    assert "status IN ('approved', 'retired')" in source
    assert "New Suite binding stays restricted to `approved`" in source
    assert "GRANT EXECUTE ON FUNCTION geo_retire_workflow_c_provider_execution_input" in source
    assert "cannot downgrade: Provider execution input retirement evidence exists" in down
    assert "status = 'approved'" in down


def test_workflow_c_job_spec_rejects_expanded_sensitive_keys_at_the_database_boundary() -> None:
    migration = WORKFLOW_C_SPEC_SENSITIVE_MIGRATION.read_text(encoding="utf-8")
    source = WORKFLOW_C_SPEC_SENSITIVE_UP.read_text(encoding="utf-8")
    down = WORKFLOW_C_SPEC_SENSITIVE_DOWN.read_text(encoding="utf-8")

    assert 'revision = "0058_wfc_spec_sensitive"' in migration
    assert 'down_revision = "0057_provider_exec_retirement"' in migration
    assert len("0058_wfc_spec_sensitive") <= 32
    assert "CREATE OR REPLACE FUNCTION geo_workflow_c_job_spec_payload_is_safe" in source
    assert "replace(lower(btrim(child_key)), '-', '_')" in source
    assert "ELSE\n            NULL;" in source
    for field_name in (
        "'api_key'",
        "'access_token'",
        "'client_secret'",
        "'cookie'",
        "'proxy_url'",
        "'session_token'",
        "'storage_state'",
    ):
        assert field_name in source
    assert "secret_reference_id" not in source
    assert "predecessor Workflow C credential-like key set" in down


def test_workflow_c_manual_import_control_defers_attempt_until_approved_review() -> None:
    migration = MANUAL_IMPORT_CONTROL_MIGRATION.read_text(encoding="utf-8")
    source = MANUAL_IMPORT_CONTROL_UP.read_text(encoding="utf-8")
    down = MANUAL_IMPORT_CONTROL_DOWN.read_text(encoding="utf-8")

    assert 'revision = "0047_sampling_manual_import"' in migration
    assert 'down_revision = "0046_wfc_artifact_encryption"' in migration
    assert "DROP CONSTRAINT workflow_c_sampling_manual_imports_attempt_id_project_id_fkey" in source
    assert "CREATE FUNCTION geo_submit_workflow_c_manual_sampling_evidence" in source
    assert "CREATE FUNCTION geo_review_workflow_c_manual_sampling_evidence" in source
    assert "geo_activate_workflow_c_manual_artifact" in source
    assert "geo_enqueue_workflow_c_job_spec" in source
    assert "sampling.manual_import" in source
    assert "sampling.manual_import.submit" in source
    assert "sampling.manual_import.review" in source
    assert "Maker-checker review" in source
    assert "REVOKE INSERT, UPDATE, DELETE ON workflow_c_sampling_manual_imports" in source
    assert "cannot downgrade Manual Sampling import control after evidence exists" in down


def test_workflow_c_retention_scheduler_serializes_first_wake_per_project() -> None:
    migration = WFC_RETENTION_LOCK_MIGRATION.read_text(encoding="utf-8")
    source = WFC_RETENTION_LOCK_UP.read_text(encoding="utf-8")
    down = WFC_RETENTION_LOCK_DOWN.read_text(encoding="utf-8")

    assert 'revision = "0050_wfc_retention_lock"' in migration
    assert 'down_revision = "0049_synthetic_retention_lock"' in migration
    assert len("0050_wfc_retention_lock") <= 32
    assert "pg_advisory_xact_lock" in source
    assert "workflow-c-artifact-maintenance:' || p_project_id::text" in source
    assert "pg_advisory_xact_lock" not in down


def test_workflow_c_worker_only_alert_metric_and_admin_inbox_contracts_are_symmetric() -> None:
    source = FOLLOW_UP_UP.read_text(encoding="utf-8")
    down = FOLLOW_UP_DOWN.read_text(encoding="utf-8")

    for contract in (
        "CREATE TABLE workflow_c_alert_evaluations",
        "jsonb_typeof(payload->'evidence') = 'array'",
        "CREATE TABLE workflow_c_admin_inbox_notifications",
        "workflow_c_admin_inbox_notification_immutable_guard",
        "CREATE FUNCTION geo_enqueue_workflow_c_alert_evaluation",
        "CREATE FUNCTION geo_complete_workflow_c_alert_evaluation",
        "CREATE FUNCTION geo_complete_workflow_c_metric_child",
        "CREATE FUNCTION geo_fail_workflow_c_metric_child",
        "Workflow C metric arbiter candidates are incomplete or inconsistent",
        "count(DISTINCT output_hash)",
        "GRANT SELECT, INSERT ON workflow_c_admin_inbox_notifications TO geo_worker",
    ):
        assert contract in source

    assert (
        "'connector_failure'"
        not in source.split("ALTER TABLE workflow_c_alert_rule_versions", maxsplit=1)[1].split(
            "CREATE TABLE workflow_c_admin_inbox_notifications", maxsplit=1
        )[0]
    )
    for contract in (
        "DROP FUNCTION geo_complete_workflow_c_alert_evaluation",
        "DROP FUNCTION geo_complete_workflow_c_metric_child",
        "DROP FUNCTION geo_fail_workflow_c_metric_child",
        "DROP TABLE workflow_c_admin_inbox_notifications",
        "'connector_failure'",
    ):
        assert contract in down


def test_metric_parent_progress_readers_are_fenced_worker_only_minimal_projections() -> None:
    migration = METRIC_PARENT_PROGRESS_MIGRATION.read_text(encoding="utf-8")
    source = METRIC_PARENT_PROGRESS_UP.read_text(encoding="utf-8")
    down = METRIC_PARENT_PROGRESS_DOWN.read_text(encoding="utf-8")

    assert 'revision = "0068_metric_parent_progress"' in migration
    assert 'down_revision = "0067_metric_arbiter_admission"' in migration
    for function_name in (
        "geo_read_workflow_c_metric_parent_batches",
        "geo_read_workflow_c_metric_parent_judges",
    ):
        assert f"CREATE FUNCTION {function_name}" in source
        assert "SECURITY DEFINER" in source and "SET row_security = off" in source
        assert f"GRANT EXECUTE ON FUNCTION {function_name}" in source
        assert f"DROP FUNCTION {function_name}" in down
    assert source.count("parent_job.lease_token IS DISTINCT FROM p_lease_token") == 2
    assert source.count("parent_job.fencing_generation <> p_fencing_generation") == 2
    assert source.count("parent_spec.spec_hash <> p_parent_input_hash") == 2
    assert "task_ciphertext" not in source
    assert "raw model output" in source


def test_semantic_metric_snapshots_use_a_fenced_worker_write_rpc() -> None:
    migration = SEMANTIC_SNAPSHOT_PERSISTENCE_MIGRATION.read_text(encoding="utf-8")
    source = SEMANTIC_SNAPSHOT_PERSISTENCE_UP.read_text(encoding="utf-8")
    down = SEMANTIC_SNAPSHOT_PERSISTENCE_DOWN.read_text(encoding="utf-8")
    persistence = (
        ROOT / "packages/geo_core/geo_core/workflow_c_analysis_persistence.py"
    ).read_text(encoding="utf-8")

    assert 'revision = "0069_metric_snapshot_rpc"' in migration
    assert 'down_revision = "0068_metric_parent_progress"' in migration
    for contract in (
        "geo_persist_workflow_c_semantic_metric_snapshot",
        "SECURITY DEFINER",
        "SET row_security = off",
        "parent_job.fencing_generation <> p_fencing_generation",
        "parent_job.input_hash <> parent_spec.spec_hash",
        "geo_jsonb_canonical_text(p_snapshot_payload - 'computed_at')",
        "snapshot results do not match result rows",
        "ON CONFLICT (project_id, snapshot_hash)",
        "ON CONFLICT (project_id, snapshot_hash, metric_key)",
        "REVOKE INSERT, UPDATE, DELETE ON workflow_c_semantic_metric_snapshots",
        "TO geo_worker",
    ):
        assert contract in source
    assert "SELECT geo_persist_workflow_c_semantic_metric_snapshot(" in persistence
    for lease_field in (
        "lease.job_id",
        "lease.lease_token",
        "lease.fencing_generation",
    ):
        assert lease_field in persistence
    assert "INSERT INTO workflow_c_semantic_metric_snapshots" not in persistence
    assert "INSERT INTO workflow_c_semantic_metric_results" not in persistence
    assert "DROP FUNCTION geo_persist_workflow_c_semantic_metric_snapshot" in down


def test_comparison_and_drift_projections_use_fenced_worker_write_rpcs() -> None:
    migration = ANALYSIS_PROJECTION_PERSISTENCE_MIGRATION.read_text(encoding="utf-8")
    source = ANALYSIS_PROJECTION_PERSISTENCE_UP.read_text(encoding="utf-8")
    down = ANALYSIS_PROJECTION_PERSISTENCE_DOWN.read_text(encoding="utf-8")
    persistence = (
        ROOT / "packages/geo_core/geo_core/workflow_c_analysis_persistence.py"
    ).read_text(encoding="utf-8")

    assert 'revision = "0070_analysis_projection_rpc"' in migration
    assert 'down_revision = "0069_metric_snapshot_rpc"' in migration
    for function_name, kind in (
        ("geo_persist_workflow_c_comparison_family", "workflow_c.analysis.comparison"),
        ("geo_persist_workflow_c_drift_report", "workflow_c.analysis.drift"),
    ):
        assert f"CREATE FUNCTION {function_name}" in source
        assert "SECURITY DEFINER" in source and "SET row_security = off" in source
        assert f"parent_job.kind <> '{kind}'" in source
        assert "parent_job.fencing_generation <> p_fencing_generation" in source
        assert "parent_job.input_hash <> parent_spec.spec_hash" in source
        assert f"GRANT EXECUTE ON FUNCTION {function_name}" in source
        assert f"DROP FUNCTION {function_name}" in down
    assert "geo_workflow_c_python_canonical_text(p_family_payload)" in source
    assert "geo_workflow_c_python_canonical_text(p_report_payload)" in source
    assert 'ORDER BY item.key COLLATE "C"' in source
    assert "REVOKE INSERT, UPDATE, DELETE ON workflow_c_comparison_families" in source
    assert "SELECT geo_persist_workflow_c_comparison_family(" in persistence
    assert "SELECT geo_persist_workflow_c_drift_report(" in persistence
    assert "INSERT INTO workflow_c_comparison_families" not in persistence
    assert "INSERT INTO workflow_c_comparison_results" not in persistence
    assert "INSERT INTO workflow_c_drift_reports" not in persistence
