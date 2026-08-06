from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_question_coverage_migration_is_bounded_and_reversible() -> None:
    up = (ROOT / "infra/db/alembic/sql/0122_question_coverage_pack.sql").read_text()
    down = (ROOT / "infra/db/alembic/sql/0122_question_coverage_pack.down.sql").read_text()

    assert "generation_mode IN ('single_scenario', 'coverage_pack')" in up
    assert "knowledge_question_generation_batches" in up
    assert "knowledge_question_candidate_revisions" in up
    assert "ENABLE ROW LEVEL SECURITY" in up
    assert "brand_scope_snapshot" in up
    assert "CREATE OR REPLACE FUNCTION geo_assert_question_set_item" in up
    assert "dimension.coverage_role IS NOT DISTINCT FROM NEW.coverage_role_snapshot" in up
    assert "AND btrim(COALESCE(NEW.review_notes, '')) = ''" not in up
    assert "AND btrim(COALESCE(NEW.review_notes, '')) = ''" in down
    assert "cannot downgrade: question coverage pack" in down


def test_question_semantic_duplicate_migration_aligns_database_evidence() -> None:
    up = (ROOT / "infra/db/alembic/sql/0123_question_semantic_dedup.sql").read_text()
    down = (
        ROOT / "infra/db/alembic/sql/0123_question_semantic_dedup.down.sql"
    ).read_text()

    assert "semantic_duplicate_found boolean" in up
    assert "candidate.semantic_fingerprint = NEW.semantic_fingerprint" in up
    assert "AND NOT semantic_duplicate_found" in up
    assert "semantic_duplicate_found" not in down
