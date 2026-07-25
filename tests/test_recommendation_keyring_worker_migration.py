from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0089_recommendation_keyring.py"
UP = ROOT / "infra/db/alembic/sql/0089_recommendation_keyring.sql"
DOWN = ROOT / "infra/db/alembic/sql/0089_recommendation_keyring.down.sql"


def test_recommendation_keyring_worker_migration_is_linear_and_narrow() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    upgrade = UP.read_text(encoding="utf-8")
    downgrade = DOWN.read_text(encoding="utf-8")

    assert 'revision = "0089_recommendation_keyring"' in source
    assert 'down_revision = "0088_worker_keyring_sync"' in source
    assert "GRANT INSERT ON recommendation_artifact_master_key_versions TO geo_worker" in upgrade
    assert "GRANT UPDATE" not in upgrade
    assert "REVOKE INSERT ON recommendation_artifact_master_key_versions FROM geo_worker" in downgrade
