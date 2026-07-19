from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0013_fact_evidence_lineage.py"
UP = ROOT / "infra/db/alembic/sql/0013_fact_evidence_lineage.sql"
DOWN = ROOT / "infra/db/alembic/sql/0013_fact_evidence_lineage.down.sql"


def test_fact_evidence_lineage_extends_the_linear_revision_chain() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0013_fact_evidence_lineage"' in source
    assert 'down_revision = "0012_campaign_prompt_context"' in source
    assert UP.is_file() and DOWN.is_file()


def test_fact_evidence_lineage_is_exact_idempotent_and_current_only_for_packs() -> None:
    source = UP.read_text(encoding="utf-8")
    for contract in (
        "ADD COLUMN document_id uuid",
        "CREATE TABLE knowledge_fact_evidence_lineages",
        "PRIMARY KEY (project_id, knowledge_fact_id, evidence_item_id)",
        "UNIQUE (project_id, idempotency_key)",
        "knowledge_fact_lineages_current_fact_key",
        "knowledge-fact-evidence-v1",
        "legacy-relational-v1",
        "fact_lineage_status = 'verified'",
        "DEFERRABLE INITIALLY DEFERRED",
        "Evidence Packs require verified Fact lineage",
        "locator JSON is deliberately not consulted",
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
    ):
        assert contract in source


def test_fact_evidence_lineage_downgrade_rejects_verified_data() -> None:
    source = DOWN.read_text(encoding="utf-8")
    assert "cannot downgrade: verified Fact Evidence lineage exists" in source
    assert "DROP TABLE knowledge_fact_evidence_lineages" in source
    assert "DROP COLUMN fact_lineage_status" in source
    assert "DROP COLUMN document_id" in source
