from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "infra/db/alembic/versions/0083_prompt_release_retirement.py"
UP = ROOT / "infra/db/alembic/sql/0083_prompt_release_retirement.sql"
DOWN = ROOT / "infra/db/alembic/sql/0083_prompt_release_retirement.down.sql"


def test_prompt_retirement_migration_is_linear_and_file_backed() -> None:
    version = VERSION.read_text(encoding="utf-8")

    assert 'revision = "0083_prompt_release_retirement"' in version
    assert 'down_revision = "0082_recommendation_evidence"' in version
    assert len("0083_prompt_release_retirement") <= 32
    assert "0083_prompt_release_retirement.sql" in version
    assert "0083_prompt_release_retirement.down.sql" in version


def test_prompt_retirement_is_one_way_audited_and_idempotent() -> None:
    source = UP.read_text(encoding="utf-8")

    assert "previous_status = 'frozen' AND NEW.status = 'retired'" in source
    assert "'retire:' || previous.id || ':' || previous.release_hash" in source
    assert "'approve', 'freeze', 'retire'" in source
    assert "operation IN (" in source and "'retire'" in source


def test_prompt_retirement_downgrade_refuses_to_drop_evidence() -> None:
    source = DOWN.read_text(encoding="utf-8")

    assert "WHERE status = 'retired'" in source
    assert "WHERE operation = 'retire'" in source
    assert "Prompt Release retirement evidence exists" in source
