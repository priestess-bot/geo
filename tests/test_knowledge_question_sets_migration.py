from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0019_knowledge_question_sets.py"
UP = ROOT / "infra/db/alembic/sql/0019_knowledge_question_sets.sql"
DOWN = ROOT / "infra/db/alembic/sql/0019_knowledge_question_sets.down.sql"


def test_question_sets_extend_the_linear_revision_chain() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0019_knowledge_question_sets"' in source
    assert 'down_revision = "0018_metric_membership"' in source
    assert UP.is_file() and DOWN.is_file()


def test_question_sets_persist_generation_sources_versions_and_bindings() -> None:
    source = UP.read_text(encoding="utf-8")
    for contract in (
        "knowledge_question_generation_specs",
        "knowledge_question_dimensions",
        "knowledge_question_generation_fact_inputs",
        "knowledge_question_generation_entity_inputs",
        "knowledge_question_generation_results",
        "knowledge_question_candidates",
        "knowledge_question_candidate_fact_sources",
        "knowledge_question_candidate_entity_sources",
        "knowledge_question_sets",
        "knowledge_question_set_items",
        "vector(1024)",
        "knowledge.question.generate",
        "question_set_id",
        "question_set_item_id",
        "geo_question_set_content_hash",
        "DEFERRABLE INITIALLY DEFERRED",
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
    ):
        assert contract in source


def test_question_set_downgrade_is_data_preserving_and_fail_closed() -> None:
    down = DOWN.read_text(encoding="utf-8")
    assert "cannot downgrade: QuestionSet generation or binding data exists" in down
    assert "DELETE FROM knowledge_" not in down
    assert "UPDATE monitoring_protocols" not in down
    assert "UPDATE prompt_simulations" not in down
