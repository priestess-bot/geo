from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "infra/db/alembic/versions/0096_style_recommendation_dify.py"
UP = ROOT / "infra/db/alembic/sql/0096_style_recommendation_dify.sql"
DOWN = ROOT / "infra/db/alembic/sql/0096_style_recommendation_dify.down.sql"


def test_style_recommendation_dify_migration_is_linear_and_reversible() -> None:
    version = VERSION.read_text(encoding="utf-8")
    assert 'revision = "0096_style_recommendation_dify"' in version
    assert 'down_revision = "0095_synthetic_dify_closed_loop"' in version
    assert "0096_style_recommendation_dify.sql" in version
    assert "0096_style_recommendation_dify.down.sql" in version


def test_recommendation_task_freezes_one_execution_backend_and_release() -> None:
    source = UP.read_text(encoding="utf-8")
    assert "ADD COLUMN execution_backend text NOT NULL DEFAULT 'model_gateway'" in source
    assert "recommendation_model_tasks_workflow_release_fkey" in source
    assert "recommendation_model_tasks_backend_shape_check" in source
    assert "AND workflow_release_id IS NULL AND workflow_release_hash IS NULL" in source
    assert "execution_backend = 'dify' AND role = 'primary'" in source
    assert "NEW.role = 'arbiter' AND NEW.execution_backend <> 'model_gateway'" in source


def test_recommendation_result_is_backend_exclusive_and_terminal() -> None:
    source = UP.read_text(encoding="utf-8")
    assert "recommendation_model_call_lineage_backend_shape_check" in source
    assert "status <> 'succeeded'" in source
    assert "AND dify_attempt_id IS NULL" in source
    assert "Recommendation terminal model result cannot be rewritten" in source
    assert "Recommendation model result status transition is invalid" in source
    assert "Recommendation Dify success lacks its frozen governed result" in source
    assert "Recommendation native success lacks its frozen governed result" in source


def test_recommendation_evidence_requires_its_owned_success_lineage() -> None:
    source = UP.read_text(encoding="utf-8")
    assert "FROM recommendation_model_call_lineage lineage" in source
    assert "JOIN recommendation_model_tasks task" in source
    assert "attempt.id = lineage.dify_attempt_id" in source
    assert "attempt.id = lineage.model_attempt_id" in source
    assert "lineage.response_hash = result.response_hash" in source
    assert "lineage.model_call_log_id = terminal.gateway_call_log_id" in source
    assert "result.configured_model = task.configured_model" in source


def test_new_trigger_is_not_public_and_old_worker_rpcs_remain_executable() -> None:
    source = UP.read_text(encoding="utf-8")
    assert "REVOKE ALL ON FUNCTION geo_lock_synthetic_dify_child_binding() FROM PUBLIC" in source
    assert source.count("TO geo_worker;") >= 3
    assert "p_execution_backend text" in source
    assert "p_workflow_release_id uuid" in source


def test_downgrade_refuses_to_discard_new_lineage_and_restores_shape() -> None:
    source = DOWN.read_text(encoding="utf-8")
    assert "cannot downgrade while Style Profile or Recommendation Dify lineage exists" in source
    assert "recommendation_model_call_lineage_backend_shape_check" in source
    assert "DROP COLUMN dify_attempt_id" in source
    assert "DROP COLUMN workflow_release_id" in source
