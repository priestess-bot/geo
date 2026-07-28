from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "infra/db/alembic/versions/0100_recommendation_type_gate.py"
UP = ROOT / "infra/db/alembic/sql/0100_recommendation_type_gate.sql"
DOWN = ROOT / "infra/db/alembic/sql/0100_recommendation_type_gate.down.sql"


def test_recommendation_type_gate_is_linear_and_file_backed() -> None:
    version = VERSION.read_text(encoding="utf-8")

    assert 'revision = "0100_recommendation_type_gate"' in version
    assert 'down_revision = "0099_style_profile_build_binding"' in version
    assert len("0100_recommendation_type_gate") <= 32
    assert "0100_recommendation_type_gate.sql" in version
    assert "0100_recommendation_type_gate.down.sql" in version


def test_type_signals_come_from_exact_producer_columns_and_fail_closed() -> None:
    source = UP.read_text(encoding="utf-8")

    assert "geo_resolve_recommendation_evidence_pre_0100" in source
    assert "SELECT result.conclusion" in source
    assert "workflow_c_comparison_results" in source
    assert "comparison_conclusion <> 'insufficient_evidence'" in source
    assert "rule.payload->>'kind', rule.payload->>'severity'" in source
    assert "rule.status = 'approved'" in source
    assert "workflow_c_alerts" in source
    assert "alert.severity <> selected_rule_severity" in source
    assert "'not_triggered'" in source
    assert "resolved || jsonb_build_object" in source
    assert "result.payload->" not in source


def test_type_gate_preserves_project_scope_and_least_privilege() -> None:
    source = UP.read_text(encoding="utf-8")

    assert "p_project_id = ANY(geo_current_project_ids())" in source
    assert "SECURITY DEFINER" in source
    assert "SET search_path = pg_catalog, public" in source
    assert "FROM PUBLIC, geo_app, geo_worker, geo_readonly" in source
    assert "TO geo_app, geo_worker" in source
    assert "TO geo_readonly" not in source


def test_type_gate_downgrade_restores_exact_predecessor() -> None:
    source = DOWN.read_text(encoding="utf-8")

    assert "DROP FUNCTION geo_resolve_recommendation_evidence" in source
    assert "geo_resolve_recommendation_evidence_pre_0100" in source
    assert "TO geo_app, geo_worker" in source
