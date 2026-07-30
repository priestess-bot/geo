from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "infra/db/alembic/versions/0116_knowledge_rag_replay.py"
UP = ROOT / "infra/db/alembic/sql/0116_knowledge_rag_replay.sql"
DOWN = ROOT / "infra/db/alembic/sql/0116_knowledge_rag_replay.down.sql"


def test_knowledge_rag_replay_permission_is_linear_and_minimal() -> None:
    version = VERSION.read_text(encoding="utf-8")
    upgrade = UP.read_text(encoding="utf-8")
    downgrade = DOWN.read_text(encoding="utf-8")

    assert 'revision = "0116_knowledge_rag_replay"' in version
    assert 'down_revision = "0115_external_operational_alerts"' in version
    assert "GRANT SELECT, INSERT ON knowledge_rag_job_specs TO geo_app" in upgrade
    assert "UPDATE" not in upgrade
    assert "DELETE" not in upgrade
    assert "REVOKE INSERT ON knowledge_rag_job_specs FROM geo_app" in downgrade
