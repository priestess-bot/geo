from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "infra/db/alembic/versions/0098_synthetic_dify_lineage.py"
UP = ROOT / "infra/db/alembic/sql/0098_synthetic_dify_lineage.sql"
DOWN = ROOT / "infra/db/alembic/sql/0098_synthetic_dify_lineage.down.sql"


def test_synthetic_dify_lineage_migration_is_linear_and_reversible() -> None:
    version = VERSION.read_text(encoding="utf-8")
    assert 'revision = "0098_synthetic_dify_lineage"' in version
    assert 'down_revision = "0097_dify_snapshot_fencing"' in version
    assert "0098_synthetic_dify_lineage.sql" in version
    assert "0098_synthetic_dify_lineage.down.sql" in version


def test_child_backend_and_exact_release_are_frozen_at_admission() -> None:
    source = UP.read_text(encoding="utf-8")
    assert "ADD COLUMN execution_backend text NOT NULL DEFAULT 'model_gateway'" in source
    assert "backend_lineage_source text NOT NULL DEFAULT 'migration_backfill_native'" in source
    assert "ALTER COLUMN backend_lineage_source SET DEFAULT 'runtime_admission'" in source
    assert "THEN 'migration_backfill_verified'" in source
    assert "ELSE 'migration_backfill_historical_mismatch'" in source
    assert "DROP TRIGGER synthetic_lab_model_call_children_immutable" in source
    assert "CREATE TRIGGER synthetic_lab_model_call_children_immutable" in source
    assert "new Synthetic child lineage must be admitted at runtime" in source
    assert "synthetic_lab_model_call_children_backend_shape_check" in source
    assert "synthetic_lab_model_call_children_workflow_release_fkey" in source
    assert "geo_assert_synthetic_child_execution_backend" in source
    assert "differs from the active pinned Workflow Release" in source
    assert "deploy the backend-aware worker before enqueue" in source
    assert "geo_enqueue_synthetic_model_call_child_v1" in source


def test_nonterminal_migration_and_success_gates_fail_closed() -> None:
    source = UP.read_text(encoding="utf-8")
    assert "a non-terminal Synthetic child lacks its exact pinned execution backend" in source
    assert "job.status IN ('queued', 'running', 'retry_wait', 'finalizing')" in source
    assert "release.configured_model <> child.configured_model" in source
    assert "active_binding.release_id IS DISTINCT FROM child.workflow_release_id" in source
    assert "latest_attempt.published_snapshot_id" in source
    assert "IS DISTINCT FROM pin.published_snapshot_id" in source
    assert "pin.published_snapshot_id = attempt.published_snapshot_id" in source
    assert "native Synthetic child success lacks its exact Model Gateway result" in source
    assert "Dify Synthetic child success lacks its exact pinned Workflow result" in source


def test_status_view_never_aliases_backend_specific_attempt_ids() -> None:
    source = UP.read_text(encoding="utf-8")
    assert "child.execution_backend, child.backend_lineage_source" in source
    assert "THEN native.attempt_id END AS model_attempt_id" in source
    assert "THEN native.gateway_call_log_id END AS gateway_call_log_id" in source
    assert "THEN dify.attempt_id END AS workflow_attempt_id" in source
    assert "AS published_snapshot_id" in source
    assert "AS published_snapshot_hash" in source
    assert "THEN dify.attempt_id ELSE native.attempt_id" not in source


def test_downgrade_only_accepts_lossless_legacy_dify_lineage_and_restores_v1() -> None:
    source = DOWN.read_text(encoding="utf-8")
    assert "'migration_backfill_verified'" in source
    assert "'migration_backfill_historical_mismatch'" in source
    assert "attempt.release_id = child.workflow_release_id" in source
    assert "legacy attempt evidence is missing" in source
    assert "RENAME TO geo_enqueue_synthetic_model_call_child" in source
    assert "DROP COLUMN backend_lineage_source" in source
    assert "DROP COLUMN execution_backend" in source
