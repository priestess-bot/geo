from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "infra/db/alembic/versions/0085_recommendation_worker_result.py"
UP = ROOT / "infra/db/alembic/sql/0085_recommendation_worker_res.sql"
DOWN = ROOT / "infra/db/alembic/sql/0085_recommendation_worker_res.down.sql"


def test_recommendation_worker_result_migration_is_linear_and_file_backed() -> None:
    version = VERSION.read_text(encoding="utf-8")

    assert 'revision = "0085_recommendation_worker_res"' in version
    assert 'down_revision = "0084_recommendation_stale"' in version
    assert len("0085_recommendation_worker_res") <= 32
    assert "0085_recommendation_worker_res.sql" in version
    assert "0085_recommendation_worker_res.down.sql" in version


def test_worker_can_only_insert_the_immutable_generation_result_projection() -> None:
    source = UP.read_text(encoding="utf-8")

    assert source.count("GRANT") == 1
    assert "GRANT INSERT ON recommendation_generation_results TO geo_worker" in source
    assert "recommendation_workflow_versions" not in source
    assert "recommendation_drafts" not in source


def test_downgrade_removes_the_narrow_worker_grant() -> None:
    source = DOWN.read_text(encoding="utf-8")

    assert "REVOKE INSERT ON recommendation_generation_results FROM geo_worker" in source
