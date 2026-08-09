from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0019_knowledge_question_sets.py"
UP = ROOT / "infra/db/alembic/sql/0019_knowledge_question_sets.sql"
DOWN = ROOT / "infra/db/alembic/sql/0019_knowledge_question_sets.down.sql"
EFFECTIVE_DEDUP_MIGRATION = (
    ROOT / "infra/db/alembic/versions/0127_question_set_dedup.py"
)
EFFECTIVE_DEDUP_UP = ROOT / "infra/db/alembic/sql/0127_question_set_dedup.sql"
EFFECTIVE_DEDUP_DOWN = (
    ROOT / "infra/db/alembic/sql/0127_question_set_dedup.down.sql"
)
QUESTION_REPAIR_MIGRATION = ROOT / "infra/db/alembic/versions/0129_question_repair.py"
QUESTION_REPAIR_UP = ROOT / "infra/db/alembic/sql/0129_question_repair.sql"
QUESTION_REPAIR_DOWN = ROOT / "infra/db/alembic/sql/0129_question_repair.down.sql"


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


def test_effective_question_dedup_supersedes_only_revised_candidate_admission() -> None:
    migration = EFFECTIVE_DEDUP_MIGRATION.read_text(encoding="utf-8")
    up = EFFECTIVE_DEDUP_UP.read_text(encoding="utf-8")
    down = EFFECTIVE_DEDUP_DOWN.read_text(encoding="utf-8")
    assert 'revision = "0127_question_set_dedup"' in migration
    assert 'down_revision = "0126_sampling_question_selection"' in migration
    assert "knowledge_question_candidate_revisions AS revision" in up
    assert "NOT EXISTS" in up
    assert "cannot downgrade effective QuestionSet dedup" in down


def test_rejected_duplicate_repair_requires_a_new_post_review_revision() -> None:
    migration = QUESTION_REPAIR_MIGRATION.read_text(encoding="utf-8")
    up = QUESTION_REPAIR_UP.read_text(encoding="utf-8")
    down = QUESTION_REPAIR_DOWN.read_text(encoding="utf-8")
    assert 'revision = "0129_question_repair"' in migration
    assert 'down_revision = "0128_connector_test_scopes"' in migration
    for contract in (
        "repair_revision_found",
        "OLD.workflow_status = 'rejected'",
        "NEW.workflow_status = 'pending_review'",
        "OLD.dedup_status <> 'possible_duplicate'",
        "revision.created_at > OLD.reviewed_at",
        "revision.query_text_hash <> OLD.query_text_hash",
        "digest(convert_to(revision.query_text, 'UTF8'), 'sha256')",
        "newer.revision_number > revision.revision_number",
        "NEW.reviewed_by IS NOT NULL",
        "NEW.review_notes IS NOT NULL",
        "NEW.reviewed_at IS NOT NULL",
    ):
        assert contract in up
    assert "repair_revision_found" not in down
    assert "revision.created_at > OLD.reviewed_at" not in down
