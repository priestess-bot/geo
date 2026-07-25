from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0088_worker_keyring_sync.py"
UP = ROOT / "infra/db/alembic/sql/0088_worker_keyring_sync.sql"
DOWN = ROOT / "infra/db/alembic/sql/0088_worker_keyring_sync.down.sql"


def test_worker_keyring_sync_migration_follows_the_current_head() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "0088_worker_keyring_sync"' in source
    assert 'down_revision = "0087_wfc_report_receipts"' in source
    assert UP.is_file() and DOWN.is_file()


def test_worker_keyring_sync_grants_only_the_bounded_canary_function() -> None:
    upgrade = UP.read_text(encoding="utf-8")
    downgrade = DOWN.read_text(encoding="utf-8")

    signature = (
        "geo_sync_secret_master_key_version(integer, text, text, bytea, bytea, timestamptz)"
    )
    assert signature in upgrade
    assert "TO geo_worker" in upgrade
    assert "GRANT ALL" not in upgrade
    assert signature in downgrade
    assert "FROM geo_worker" in downgrade
