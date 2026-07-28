from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "infra/db/alembic/versions/0095_synthetic_dify_closed_loop.py"
UP = ROOT / "infra/db/alembic/sql/0095_synthetic_dify_closed_loop.sql"
DOWN = ROOT / "infra/db/alembic/sql/0095_synthetic_dify_closed_loop.down.sql"


def test_synthetic_dify_migration_is_linear_and_reversible() -> None:
    version = VERSION.read_text(encoding="utf-8")
    assert 'revision = "0095_synthetic_dify_closed_loop"' in version
    assert 'down_revision = "0094_dify_published_snapshot"' in version
    assert "0095_synthetic_dify_closed_loop.sql" in version
    assert "0095_synthetic_dify_closed_loop.down.sql" in version


def test_synthetic_dify_results_are_immutable_project_scoped_worker_data() -> None:
    source = UP.read_text(encoding="utf-8")
    assert "CREATE TABLE dify_workflow_execution_results" in source
    assert "dify_workflow_results_immutable" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "CREATE POLICY project_scope ON dify_workflow_execution_results" in source
    assert "GRANT SELECT, INSERT ON dify_workflow_execution_results TO geo_worker" in source
    assert "successful Dify child lacks a governed result" not in source


def test_synthetic_child_status_uses_the_recorded_execution_backend() -> None:
    source = UP.read_text(encoding="utf-8")
    assert "model-gateway://attempt/%" in source
    assert "dify-workflow://attempt/%" in source
    assert "THEN dify.attempt_id ELSE native.attempt_id END AS model_attempt_id" in source
    assert "THEN dify.output END AS dify_output" in source
    assert "coalesce(dify.attempt_id, native.attempt_id)" not in source


def test_downgrade_refuses_to_discard_synthetic_dify_evidence() -> None:
    source = DOWN.read_text(encoding="utf-8")
    assert "cannot downgrade while Synthetic Dify releases or results exist" in source
    assert "purpose LIKE 'synthetic_lab.%'" in source
    assert "DROP TABLE dify_workflow_execution_results" in source


def test_snapshot_constraints_remain_owned_by_the_published_snapshot_revision() -> None:
    up = UP.read_text(encoding="utf-8")
    down = DOWN.read_text(encoding="utf-8")
    for source in (up, down):
        assert "DROP CONSTRAINT dify_workflow_attempts_snapshot_fkey" not in source
        assert "DROP CONSTRAINT dify_published_snapshots_project_key" not in source
        assert "DROP CONSTRAINT dify_published_snapshots_identity_key" not in source


def test_downgrade_restores_the_exact_pre_0095_guard_and_view_comment() -> None:
    source = DOWN.read_text(encoding="utf-8")
    assert "FROM model_gateway_call_attempts AS attempt" in source
    assert "JOIN model_gateway_terminal_events AS terminal" in source
    assert "WHERE id = link.parent_job_id AND project_id = link.project_id\n        FOR SHARE;" in source
    assert "ORDER BY attempt.attempt_number DESC\n        LIMIT 1;" in source
    assert (
        "COMMENT ON VIEW synthetic_lab_model_call_child_status IS\n"
        "    'Admin/worker status projection over child Durable Jobs and governed Model Gateway terminals.';"
        in source
    )
