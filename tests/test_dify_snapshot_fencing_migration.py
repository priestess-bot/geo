from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "infra/db/alembic/versions/0097_dify_snapshot_fencing.py"
UP = ROOT / "infra/db/alembic/sql/0097_dify_snapshot_fencing.sql"
DOWN = ROOT / "infra/db/alembic/sql/0097_dify_snapshot_fencing.down.sql"
PREVIOUS = ROOT / "infra/db/alembic/sql/0096_style_recommendation_dify.sql"


def test_dify_snapshot_fencing_is_a_separate_linear_migration() -> None:
    version = VERSION.read_text(encoding="utf-8")
    previous = PREVIOUS.read_text(encoding="utf-8")
    assert 'revision = "0097_dify_snapshot_fencing"' in version
    assert 'down_revision = "0096_style_recommendation_dify"' in version
    assert "0097_dify_snapshot_fencing.sql" in version
    assert "0097_dify_snapshot_fencing.down.sql" in version
    assert "dify_workflow_release_snapshot_pins" not in previous
    assert "geo_finish_dify_business_attempt" not in previous


def test_release_pins_require_the_successful_canary_model_graph() -> None:
    source = UP.read_text(encoding="utf-8")
    assert "CREATE TABLE dify_workflow_release_snapshot_pins" in source
    assert "attempt_row.status <> 'succeeded'" in source
    assert "attempt_row.published_snapshot_id IS DISTINCT FROM" in source
    assert "node->>'model_provider'" in source
    assert "node->>'model_name'" in source
    assert "active Dify release lacks a successful canary published snapshot" in source
    assert "'migration_backfill'" in source
    assert "ambiguous legacy Dify release still has a non-terminal task or attempt" in source
    assert "count(DISTINCT attempt.published_snapshot_id) > 1" in source
    assert "a non-terminal frozen Dify task lacks a successful-canary snapshot pin" in source
    assert "dify_workflow_binding_snapshot_pin_guard" in source
    assert "geo_assert_recommendation_model_task_change" in source
    assert "Recommendation Dify task differs from the active pinned Workflow Release" in source
    assert "Recommendation Prompt purpose is bound to Dify" in source
    assert "'dify-binding:' || NEW.project_id::text || ':' || NEW.prompt_purpose" in source


def test_only_pre_upgrade_v3_recommendation_parents_keep_native_execution() -> None:
    source = UP.read_text(encoding="utf-8")
    downgrade = DOWN.read_text(encoding="utf-8")

    assert "CREATE TABLE dify_legacy_recommendation_native_parents" in source
    assert "FROM recommendation_generation_specs spec" in source
    assert (
        "spec.spec_payload->>'contract_version' = " "'recommendation-generation-spec-v3'"
    ) in source
    assert "dify_legacy_recommendation_native_parents_immutable" in source
    assert "legacy.parent_job_id = NEW.parent_job_id" in source
    assert "DROP TABLE dify_legacy_recommendation_native_parents" in downgrade


def test_business_terminal_writes_are_atomic_and_lease_fenced() -> None:
    source = UP.read_text(encoding="utf-8")
    assert "CREATE FUNCTION geo_finish_dify_business_attempt" in source
    assert "durable_row.lease_token IS DISTINCT FROM p_lease_token" in source
    assert "p_fencing_generation IS NULL" in source
    assert "durable_row.fencing_generation IS DISTINCT FROM p_fencing_generation" in source
    assert "attempt_row.fencing_generation IS DISTINCT FROM p_fencing_generation" in source
    assert "durable_row.lease_expires_at <= clock_timestamp()" in source
    assert "INSERT INTO dify_workflow_execution_results" in source
    assert "Dify business attempt is already finalized" in source
    assert "CREATE FUNCTION geo_dify_canonical_text" in source
    assert "geo_dify_canonical_text(p_values->'output')" in source
    assert "REVOKE UPDATE ON dify_workflow_execution_attempts FROM geo_worker" in source
    assert "REVOKE INSERT ON dify_workflow_execution_results FROM geo_worker" in source


def test_unknown_outcome_reconciliation_never_reopens_the_old_job() -> None:
    source = UP.read_text(encoding="utf-8")
    assert "'unknown_outcome'" in source
    assert "CREATE TABLE dify_workflow_attempt_reconciliations" in source
    assert "provider_outcome" in source
    assert "evidence_reference" in source
    assert "verification_conclusion = 'resubmit_new_parent_required'" in source
    assert "decision = 'new_parent_token_issued'" in source
    assert "resubmission_token_hash" in source
    assert "business_fingerprint" in source
    assert "CREATE FUNCTION geo_dify_recovery_parent_fingerprint" in source
    assert "CREATE TABLE dify_workflow_reconciliation_consumptions" in source
    assert "CREATE FUNCTION geo_bind_dify_resubmission" in source
    assert "unresolved Dify outcome requires a one-time reconciliation token" in source
    assert "unresolved prior Dify outcome requires recovery_of_attempt_id" in source
    assert "membership.role IN ('owner', 'admin')" in source
    assert "supports only Style Profile and Recommendation parent flows" in source
    assert "geo_current_identity_id() IS DISTINCT FROM p_authorized_by" in source
    assert (
        "UPDATE durable_jobs"
        not in source[source.index("CREATE FUNCTION geo_issue_dify_resubmission_token") :]
    )


def test_downgrade_restores_legacy_grants_only_without_new_evidence() -> None:
    source = DOWN.read_text(encoding="utf-8")
    assert (
        "cannot downgrade while Dify snapshot pins or unresolved outcome evidence exists" in source
    )
    assert "DROP TABLE dify_workflow_release_snapshot_pins" in source
    assert "DROP TABLE dify_workflow_attempt_reconciliations" in source
    assert "DROP TABLE dify_workflow_reconciliation_consumptions" in source
    assert "GRANT UPDATE ON dify_workflow_execution_attempts TO geo_worker" in source
    assert "GRANT INSERT ON dify_workflow_execution_results TO geo_worker" in source
    assert "CREATE OR REPLACE FUNCTION geo_assert_recommendation_model_task_change" in source
    assert (
        "dify_workflow_release_snapshot_pins pin"
        not in source[
            source.index("CREATE OR REPLACE FUNCTION geo_assert_recommendation_model_task_change") :
        ]
    )
