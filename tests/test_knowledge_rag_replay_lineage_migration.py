from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "infra/db/alembic/versions/0117_knowledge_rag_replay_link.py"
UP = ROOT / "infra/db/alembic/sql/0117_knowledge_rag_replay_link.sql"
DOWN = ROOT / "infra/db/alembic/sql/0117_knowledge_rag_replay_link.down.sql"


def test_knowledge_rag_replay_lineage_preserves_root_uniqueness() -> None:
    version = VERSION.read_text(encoding="utf-8")
    upgrade = UP.read_text(encoding="utf-8")
    downgrade = DOWN.read_text(encoding="utf-8")

    assert 'revision = "0117_knowledge_rag_replay_link"' in version
    assert 'down_revision = "0116_knowledge_rag_replay"' in version
    assert "ADD COLUMN replayed_from_job_id uuid" in upgrade
    assert "knowledge_rag_job_specs_root_run_document_key" in upgrade
    assert "WHERE replayed_from_job_id IS NULL" in upgrade
    assert "REFERENCES durable_jobs(id, project_id)" in upgrade
    assert "cannot downgrade: Knowledge RAG replay lineage exists" in downgrade
