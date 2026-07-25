from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "infra/db/alembic/versions/0077_workflow_c_alert_report_api.py"
UP = ROOT / "infra/db/alembic/sql/0077_wfc_alert_report_api.sql"
DOWN = ROOT / "infra/db/alembic/sql/0077_wfc_alert_report_api.down.sql"


def test_alert_report_migration_is_linear_and_governed() -> None:
    version = VERSION.read_text(encoding="utf-8")
    source = UP.read_text(encoding="utf-8")

    assert 'revision = "0077_wfc_alert_report_api"' in version
    assert 'down_revision = "0076_wfc_stat_protocols"' in version
    assert "workflow_c_alert_rule_command_receipts" in source
    assert "geo_create_workflow_c_alert_rule" in source
    assert "geo_transition_workflow_c_alert_rule" in source
    assert "approved_by <> created_by" in source
    assert "NEW.actor_id = draft_actor" in source
    assert "Workflow C approved report source is not Customer eligible" in source
    assert "REVOKE INSERT, UPDATE, DELETE" in source
    for rule_kind in (
        "threshold",
        "baseline_delta",
        "negative_question",
        "completion_freshness",
        "model_drift",
        "source_drift",
    ):
        assert rule_kind in source


def test_alert_completion_compatibility_patch_is_explicit_and_reversible() -> None:
    source = UP.read_text(encoding="utf-8")
    down = DOWN.read_text(encoding="utf-8")

    assert "SET plpgsql.variable_conflict = 'use_column'" in source
    assert "RESET plpgsql.variable_conflict" in down
    assert "safe_expression" in source
    assert "safe_wake_expression" in source
    assert "Expected alert notification idempotency expression was not found" in source
    assert "Expected alert notification wake expression was not found" in source
    assert "patched alert notification idempotency expression" in down
    assert "patched alert notification wake expression" in down
