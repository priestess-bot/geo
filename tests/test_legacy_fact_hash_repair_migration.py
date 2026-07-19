from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0022_legacy_fact_hash_repair.py"
UP = ROOT / "infra/db/alembic/sql/0022_legacy_fact_hash_repair.sql"
DOWN = ROOT / "infra/db/alembic/sql/0022_legacy_fact_hash_repair.down.sql"


def test_legacy_fact_hash_repair_extends_the_linear_revision_chain() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0022_legacy_fact_hash_repair"' in source
    assert 'down_revision = "0021_observation_source_details"' in source
    assert UP.is_file() and DOWN.is_file()


def test_legacy_fact_hash_repair_is_exact_audited_and_fail_closed() -> None:
    source = UP.read_text(encoding="utf-8")
    for contract in (
        "legacy-sentence-v1",
        "octet_length(convert_to(fact.statement, 'UTF8'))",
        "= char_length(fact.statement)",
        "<> char_length(fact.statement)",
        "translate(",
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZ'",
        "'abcdefghijklmnopqrstuvwxyz'",
        "legacy-ascii-lower-sha256-to-exact-v1",
        "convert_to(fact.statement, 'UTF8')",
        "knowledge_legacy_fact_hash_repairs",
        "knowledge_fact_evidence_lineages",
        "knowledge_fact_candidate_sources",
        "knowledge_question_generation_fact_inputs",
        "knowledge_question_candidate_fact_sources",
        "evidence.item_type = 'approved_fact'",
        "prompt_simulations",
        "prompt_simulation_results",
        "source_fact_ids",
        "invalid_hash_count",
        "referenced_count",
        "duplicate_target_count",
        "ERRCODE = '55000'",
        "DEFERRABLE INITIALLY DEFERRED",
        "SET LOCAL session_replication_role = 'replica'",
        "SET LOCAL session_replication_role = 'origin'",
        "FORCE ROW LEVEL SECURITY",
    ):
        assert contract in source
    assert "lower(fact.statement)" not in source
    assert "DELETE FROM knowledge_fact_candidates" not in source


def test_legacy_fact_hash_repair_downgrade_restores_only_audited_rows() -> None:
    source = DOWN.read_text(encoding="utf-8")
    assert "SET statement_hash = repair.previous_statement_hash" in source
    assert "cannot revert legacy Fact hash repair" in source
    assert "referenced_count" in source
    assert "duplicate_target_count" in source
    assert "DELETE FROM knowledge_fact_candidates" not in source
