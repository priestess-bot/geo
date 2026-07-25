from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "infra/db/alembic/versions/0076_workflow_c_statistical_protocols.py"
UP = ROOT / "infra/db/alembic/sql/0076_wfc_stat_protocols.sql"
DOWN = ROOT / "infra/db/alembic/sql/0076_wfc_stat_protocols.down.sql"


def test_statistical_protocol_migration_is_linear_and_governed() -> None:
    version = VERSION.read_text(encoding="utf-8")
    source = UP.read_text(encoding="utf-8")

    assert 'revision = "0076_wfc_stat_protocols"' in version
    assert 'down_revision = "0075_wfc_manual_attempt_scope"' in version
    assert "workflow_c_statistical_protocol_versions" in source
    assert "comparison_plan" in source and "drift_protocol" in source
    assert "geo_workflow_c_statistical_protocol_definition_is_valid" in source
    assert "geo_create_workflow_c_statistical_protocol" in source
    assert "geo_transition_workflow_c_statistical_protocol" in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "REVOKE INSERT, UPDATE, DELETE" in source
    assert "approved_by <> NEW.created_by" in source


def test_statistical_protocol_migration_preserves_insufficient_pair_denominator() -> None:
    source = UP.read_text(encoding="utf-8")
    down = DOWN.read_text(encoding="utf-8")

    assert "geo_workflow_c_analysis_job_spec_v1_is_valid" in source
    assert "jsonb_array_length(value->'pairs') = 0" in source
    assert "validation-placeholder" in source
    assert "RENAME TO geo_workflow_c_analysis_job_spec_is_valid" in down
    assert "cannot downgrade governed Statistical Protocol state" in down
