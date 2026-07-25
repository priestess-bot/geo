from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "infra/db/alembic/versions/0084_recommendation_stale.py"
UP = ROOT / "infra/db/alembic/sql/0084_recommendation_stale.sql"
DOWN = ROOT / "infra/db/alembic/sql/0084_recommendation_stale.down.sql"


def test_recommendation_stale_migration_is_linear_and_file_backed() -> None:
    version = VERSION.read_text(encoding="utf-8")

    assert 'revision = "0084_recommendation_stale"' in version
    assert 'down_revision = "0083_prompt_release_retirement"' in version
    assert len("0084_recommendation_stale") <= 32
    assert "0084_recommendation_stale.sql" in version
    assert "0084_recommendation_stale.down.sql" in version


def test_fact_resolution_exposes_retired_source_as_invalid_evidence() -> None:
    source = UP.read_text(encoding="utf-8")

    assert "fact.lifecycle_status = 'active'" in source
    assert "fact.lifecycle_status <> 'active'" in source
    assert "AND fact.status = 'approved'" not in source
    assert "geo_resolve_recommendation_evidence_pre_0084" in source


def test_only_unstarted_drafts_are_blocked_after_invalidation() -> None:
    source = UP.read_text(encoding="utf-8")

    assert "AND status = 'draft'" in source
    assert "status IN ('draft', 'started')" not in source


def test_downgrade_restores_predecessor_and_prior_trigger_contract() -> None:
    source = DOWN.read_text(encoding="utf-8")

    assert "geo_resolve_recommendation_evidence_pre_0084" in source
    assert "TO geo_app, geo_worker" in source
    assert "status IN ('draft', 'started')" in source
