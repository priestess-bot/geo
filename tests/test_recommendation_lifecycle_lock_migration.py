from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0036_recommendation_lifecycle_locks.py"
UP = ROOT / "infra/db/alembic/sql/0036_recommendation_locks.sql"
DOWN = ROOT / "infra/db/alembic/sql/0036_recommendation_locks.down.sql"


def test_recommendation_lifecycle_lock_compatibility_fix_extends_linear_chain() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "0036_recommendation_locks"' in source
    assert 'down_revision = "0035_workflow_c_report_locks"' in source
    assert UP.is_file() and DOWN.is_file()


def test_recommendation_append_trigger_uses_exact_predecessor_without_app_update_privilege() -> (
    None
):
    source = UP.read_text(encoding="utf-8")

    assert "geo_assert_recommendation_workflow_append" in source
    assert "version = NEW.version - 1;" in source
    assert "\n    FOR UPDATE" not in source
    assert "append-only" in source
    assert "recommendation_workflow_versions_draft_type_check" in source
    assert "proposed_draft_kind = 'sampling_plan'" in source
    assert "FOR UPDATE" in DOWN.read_text(encoding="utf-8")
