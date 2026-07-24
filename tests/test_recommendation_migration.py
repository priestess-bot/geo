from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0032_recommendation_workflows.py"
UP = ROOT / "infra/db/alembic/sql/0032_recommendation_workflows.sql"
DOWN = ROOT / "infra/db/alembic/sql/0032_recommendation_workflows.down.sql"


def test_recommendation_revision_extends_the_single_chain() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0032_recommendation_workflows"' in source
    assert 'down_revision = "0031_workflow_c_stats_alerts"' in source
    assert UP.is_file() and DOWN.is_file()
    assert "driver_connection" in source and "cursor.execute" in source


def test_recommendation_schema_freezes_evidence_approval_drafts_and_artifacts() -> None:
    source = UP.read_text(encoding="utf-8")
    for table in (
        "service_identities",
        "workflow_c_job_specs",
        "recommendation_workflow_versions",
        "recommendation_evidence_bindings",
        "recommendation_approvals",
        "recommendation_reviews",
        "recommendation_command_receipts",
        "recommendation_drafts",
        "recommendation_generation_specs",
        "recommendation_generation_results",
        "recommendation_generation_command_receipts",
        "recommendation_model_tasks",
        "recommendation_model_call_lineage",
        "recommendation_artifact_master_key_versions",
        "recommendation_artifact_deletion_intents",
    ):
        assert f"CREATE TABLE {table}" in source
    for contract in (
        "hard_blocker",
        "insufficient_evidence",
        "blocked_source_stale",
        "blocked_source_expired",
        "geo_block_recommendation_drafts_on_stale",
        "geo_resolve_recommendation_evidence",
        "output_schema_hash",
        "application_output_schema_hash",
        "crypto_erased",
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
        "geo_current_project_ids()",
        "FROM PUBLIC, geo_app, geo_worker, geo_readonly",
    ):
        assert contract in source


def test_recommendation_service_identity_evidence_and_artifact_scheduler_are_fenced() -> None:
    source = UP.read_text(encoding="utf-8")
    down = DOWN.read_text(encoding="utf-8")
    for contract in (
        "geo_provision_service_identity",
        "geo_require_active_service_identity",
        "geo_workflow_c_job_spec_payload_is_safe",
        "geo_assert_workflow_c_job_spec_immutable",
        "'sampling.provider_execute'",
        "'workflow_c.alert.notify'",
        "spec_payload -> 'schema_version' = '1'::jsonb",
        "spec_payload ->> 'kind' = kind",
        "connector-attribution-policy-v1",
        "connector_attribution_excluded_from_this_phase",
        "'valid', false",
        "'available', false",
        "geo_schedule_recommendation_artifact_maintenance",
        "recommendation-artifact-maintenance:wake:",
        "geo_enqueue_recommendation_artifact_maintenance(uuid, timestamptz)",
        "geo_claim_recommendation_artifact_deletion(uuid, text, timestamptz, integer, integer)",
        "recommendation_artifact_maintenance_scheduler",
    ):
        assert contract in source
    assert "GRANT EXECUTE ON FUNCTION\n    geo_provision_service_identity" not in source
    for contract in (
        "DROP TABLE recommendation_generation_command_receipts",
        "DROP TABLE workflow_c_job_specs",
        "DROP TABLE service_identities",
        "DROP FUNCTION geo_workflow_c_job_spec_payload_is_safe(jsonb)",
        "DROP FUNCTION geo_schedule_recommendation_artifact_maintenance",
    ):
        assert contract in down


def test_recommendation_evidence_resolver_freezes_all_producer_kinds_and_scope() -> None:
    source = UP.read_text(encoding="utf-8")
    for contract in (
        "IF NOT p_project_id = ANY(geo_current_project_ids())",
        "WHEN 'observation' THEN",
        "WHEN 'metric_comparison' THEN",
        "WHEN 'fact' THEN",
        "WHEN 'rule' THEN",
        "WHEN 'prompt_release' THEN",
        "WHEN 'model_call' THEN",
        "WHEN 'content' THEN",
        "WHEN 'question' THEN",
        "WHEN 'surface' THEN",
        "WHEN 'attribution' THEN",
        "'connector_attribution_excluded_from_this_phase'",
        "'available', false",
        "'valid', false",
    ):
        assert contract in source


def test_recommendation_downgrade_refuses_to_discard_evidence_or_key_history() -> None:
    source = DOWN.read_text(encoding="utf-8")
    assert "cannot downgrade: Recommendation data exists" in source
    for table in (
        "recommendation_workflow_versions",
        "recommendation_evidence_bindings",
        "recommendation_generation_specs",
        "recommendation_model_tasks",
        "recommendation_model_call_lineage",
        "recommendation_artifact_master_key_versions",
        "recommendation_artifact_deletion_intents",
    ):
        assert f"EXISTS (SELECT 1 FROM {table})" in source
