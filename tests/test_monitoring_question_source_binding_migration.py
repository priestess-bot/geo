from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0025_monitoring_source_guard.py"
UP = ROOT / "infra/db/alembic/sql/0025_monitoring_source_guard.sql"
DOWN = ROOT / "infra/db/alembic/sql/0025_monitoring_source_guard.down.sql"


def test_monitoring_question_source_binding_extends_the_linear_revision_chain() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0025_monitoring_source_guard"' in source
    assert 'down_revision = "0024_active_chunk_consumers"' in source
    assert UP.is_file() and DOWN.is_file()


def test_monitoring_question_source_binding_guards_only_new_bindings() -> None:
    source = UP.read_text(encoding="utf-8")
    assert "OLD.question_set_id IS NULL AND NEW.question_set_id IS NOT NULL" in source
    assert "geo_question_candidate_sources_current(" in source
    assert "BEFORE UPDATE OF question_set_id ON monitoring_protocols" in source
    assert "UPDATE monitoring_queries" not in source
    assert "UPDATE monitoring_protocol_queries" not in source

    downgrade = DOWN.read_text(encoding="utf-8")
    assert "monitoring_protocol_question_sources_current_guard" in downgrade
    assert "geo_assert_monitoring_question_sources_current" in downgrade
