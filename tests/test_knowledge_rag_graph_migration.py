from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0017_knowledge_rag_graph.py"
UP = ROOT / "infra/db/alembic/sql/0017_knowledge_rag_graph.sql"
DOWN = ROOT / "infra/db/alembic/sql/0017_knowledge_rag_graph.down.sql"


def test_knowledge_rag_graph_extends_the_linear_revision_chain() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0017_knowledge_rag_graph"' in source
    assert 'down_revision = "0016_publication_verification"' in source
    assert UP.is_file() and DOWN.is_file()


def test_knowledge_rag_graph_persists_exact_governed_context() -> None:
    source = UP.read_text(encoding="utf-8")
    for contract in (
        "logical_source_id",
        "supersedes_source_id",
        "knowledge_rag_job_specs",
        "knowledge_rag_revisions",
        "knowledge_fact_candidate_sources",
        "knowledge_entity_candidates",
        "knowledge_entity_candidate_sources",
        "knowledge_relation_candidates",
        "knowledge_rag_validation_findings",
        "knowledge_graph_entities",
        "knowledge_graph_entity_sources",
        "knowledge_graph_relations",
        "knowledge_graph_relation_sources",
        "project-native-rag-v1",
        "llamaindex-property-graph-v1",
        "^line:[1-9][0-9]*$",
        "knowledge.rag.extract",
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
    ):
        assert contract in source


def test_knowledge_rag_graph_preserves_legacy_facts_and_downgrades_fail_closed() -> None:
    source = UP.read_text(encoding="utf-8")
    down = DOWN.read_text(encoding="utf-8")
    assert "extractor_release text NOT NULL DEFAULT 'legacy-sentence-v1'" in source
    assert "rag_revision_id IS NULL" in source
    assert "cannot downgrade: Knowledge RAG or source revision data exists" in down
    assert "DELETE FROM knowledge_" not in down
    assert "UPDATE knowledge_fact_candidates" not in down
