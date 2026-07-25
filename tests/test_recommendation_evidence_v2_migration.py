from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "infra/db/alembic/versions/0082_recommendation_evidence.py"
UP = ROOT / "infra/db/alembic/sql/0082_recommendation_evidence.sql"
DOWN = ROOT / "infra/db/alembic/sql/0082_recommendation_evidence.down.sql"


def test_recommendation_evidence_migration_is_linear_and_file_backed() -> None:
    version = VERSION.read_text(encoding="utf-8")

    assert 'revision = "0082_recommendation_evidence"' in version
    assert 'down_revision = "0081_surface_parser_results"' in version
    assert len("0082_recommendation_evidence") <= 32
    assert "0082_recommendation_evidence.sql" in version
    assert "0082_recommendation_evidence.down.sql" in version


def test_observation_projection_uses_typed_real_identity_and_source_stratum() -> None:
    source = UP.read_text(encoding="utf-8")

    assert "'evidence_class', 'real_observation'" in source
    assert "'surface_resource_id', task.source_stratum_hash" in source
    assert "'question_resource_id', task.question_id" in source
    assert "'real' ELSE 'ineligible'" not in source


def test_comparison_membership_is_rebuilt_from_frozen_producer_lineage() -> None:
    source = UP.read_text(encoding="utf-8")

    assert "workflow_c_analysis_input_manifest_items" in source
    assert "workflow-c-comparison:" in source
    assert "workflow-c-semantic-metrics:" in source
    assert "manifest_item.observation_id" in source
    assert "result.payload->'observation_resource_ids'" not in source
    assert "lineage.conclusion IN ('win', 'equivalent', 'loss')" in source


def test_recommendation_evidence_downgrade_restores_predecessor() -> None:
    source = DOWN.read_text(encoding="utf-8")

    assert "DROP FUNCTION geo_resolve_recommendation_evidence" in source
    assert "geo_resolve_recommendation_evidence_pre_0082" in source
    assert "TO geo_app, geo_worker" in source
