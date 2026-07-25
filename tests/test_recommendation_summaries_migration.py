from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "infra/db/alembic/versions/0086_recommendation_summaries.py"
UP = ROOT / "infra/db/alembic/sql/0086_recommendation_summaries.sql"
DOWN = ROOT / "infra/db/alembic/sql/0086_recommendation_summaries.down.sql"


def test_recommendation_summary_migration_is_linear_and_file_backed() -> None:
    version = VERSION.read_text(encoding="utf-8")

    assert 'revision = "0086_recommendation_summaries"' in version
    assert 'down_revision = "0085_recommendation_worker_res"' in version
    assert len("0086_recommendation_summaries") <= 32
    assert "0086_recommendation_summaries.sql" in version
    assert "0086_recommendation_summaries.down.sql" in version


def test_summaries_are_bounded_hashed_and_owned_by_producer_projections() -> None:
    source = UP.read_text(encoding="utf-8")

    assert "observation.evidence_json->'surface_parse'" in source
    assert "workflow_c_comparison_results" in source
    assert "workflow_c_alert_rule_versions" in source
    assert "left(format(" in source
    assert "), 4000)" in source
    assert "'summary_hash'" in source
    assert "answer_text" not in source
    assert "geo_resolve_recommendation_evidence_pre_0086" in source


def test_summary_downgrade_restores_predecessor() -> None:
    source = DOWN.read_text(encoding="utf-8")

    assert "geo_resolve_recommendation_evidence_pre_0086" in source
    assert "TO geo_app, geo_worker" in source
