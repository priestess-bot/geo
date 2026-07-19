from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0023_promoted_fact_lifecycle.py"
UP = ROOT / "infra/db/alembic/sql/0023_promoted_fact_lifecycle.sql"
DOWN = ROOT / "infra/db/alembic/sql/0023_promoted_fact_lifecycle.down.sql"


def test_promoted_fact_lifecycle_extends_the_linear_revision_chain() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0023_promoted_fact_lifecycle"' in source
    assert 'down_revision = "0022_legacy_fact_hash_repair"' in source
    assert UP.is_file() and DOWN.is_file()


def test_promoted_fact_lifecycle_allows_only_auditable_retirement() -> None:
    source = UP.read_text(encoding="utf-8")
    assert "OLD.lifecycle_status = 'active'" in source
    assert "NEW.lifecycle_status IN ('superseded', 'withdrawn')" in source
    assert "to_jsonb(NEW) - ARRAY['lifecycle_status', 'updated_at']" in source
    assert "knowledge_fact_evidence_lineages" in source
    assert "ERRCODE = '55000'" in source
    assert "DELETE FROM knowledge_fact_candidates" not in source

    downgrade = DOWN.read_text(encoding="utf-8")
    assert "promoted knowledge Facts are immutable" in downgrade
