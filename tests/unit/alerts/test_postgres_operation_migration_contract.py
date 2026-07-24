"""Static contract between alert Worker operations and the 0032 SQL RPCs."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
UP = ROOT / "infra/db/alembic/sql/0032_recommendation_workflows.sql"
DOWN = ROOT / "infra/db/alembic/sql/0032_recommendation_workflows.down.sql"


def test_alert_schedule_and_evaluation_rpcs_preserve_fence_and_replay_contracts() -> None:
    source = UP.read_text(encoding="utf-8")
    schedule = _function(source, "geo_enqueue_workflow_c_alert_evaluation")
    completion = _function(source, "geo_complete_workflow_c_alert_evaluation")

    assert "p_successor_spec_payload jsonb" in schedule
    assert "p_scheduled_for timestamptz" in schedule
    assert "RETURNS TABLE (status text, evaluation_job_id uuid, successor_job_id uuid)" in schedule
    assert "SET next_run_at = p_next_run_at, updated_at = clock_timestamp()" in schedule
    assert "version = version + 1" not in schedule
    assert "RETURNS TABLE (status text, evaluation_hash text, notification_count integer)" in completion
    assert "Workflow C alert evaluation replay Job was fenced" in completion
    assert "'workflow_c.alert.notify'" in completion


def test_alert_evaluation_storage_matches_the_frozen_python_payload() -> None:
    source = UP.read_text(encoding="utf-8")

    assert "CREATE TABLE workflow_c_alert_evaluations" in source
    assert "jsonb_typeof(payload->'evidence') = 'array'" in source
    for field in (
        "'rule_kind'",
        "'rule_hash'",
        "'parameter_schema_version'",
        "'input_schema_version'",
        "'trigger_snapshot_hash'",
    ):
        assert field in source
    assert "connector_failure" not in source


def test_alert_rpc_downgrade_drops_the_actual_overloads() -> None:
    source = _compact(DOWN.read_text(encoding="utf-8"))

    assert "DROP FUNCTION geo_complete_workflow_c_alert_evaluation(" in source
    assert "DROP FUNCTION geo_enqueue_workflow_c_alert_evaluation(" in source
    assert (
        "uuid, uuid, uuid, integer, uuid, integer, timestamptz, uuid, text, jsonb, "
        "text, uuid, text, jsonb, text, timestamptz"
    ) in source
    assert (
        "uuid, uuid, uuid, integer, uuid, uuid, integer, uuid, text, text, text, "
        "text, boolean, jsonb, timestamptz, uuid, text, jsonb, jsonb"
    ) in source


def _function(source: str, name: str) -> str:
    marker = f"CREATE FUNCTION {name}("
    start = source.index(marker)
    end = source.index("\n$$;", start) + len("\n$$;")
    return source[start:end]


def _compact(value: str) -> str:
    return " ".join(value.split())
