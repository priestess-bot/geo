from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0024_active_chunk_consumers.py"
UP = ROOT / "infra/db/alembic/sql/0024_active_chunk_consumers.sql"
DOWN = ROOT / "infra/db/alembic/sql/0024_active_chunk_consumers.down.sql"


def test_active_chunk_consumers_extends_the_linear_revision_chain() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0024_active_chunk_consumers"' in source
    assert 'down_revision = "0023_promoted_fact_lifecycle"' in source
    assert UP.is_file() and DOWN.is_file()


def test_active_chunk_consumers_gate_facts_and_graph_sources() -> None:
    source = UP.read_text(encoding="utf-8")
    assert "CREATE OR REPLACE FUNCTION geo_question_candidate_sources_current" in source
    assert "LEFT JOIN knowledge_chunks AS chunk" in source
    assert "chunk.id IS NULL OR chunk.status <> 'active'" in source
    assert "JOIN knowledge_chunks AS chunk" in source
    assert "lineage.lifecycle_status = 'active'" in source
    assert "chunk.status = 'active'" in source

    downgrade = DOWN.read_text(encoding="utf-8")
    assert "CREATE OR REPLACE FUNCTION geo_question_candidate_sources_current" in downgrade
    assert "JOIN knowledge_chunks AS chunk" not in downgrade
