from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "infra/db/alembic/versions/0101_dify_published_identity.py"
UP = ROOT / "infra/db/alembic/sql/0101_dify_published_identity.sql"
DOWN = ROOT / "infra/db/alembic/sql/0101_dify_published_identity.down.sql"


def test_published_identity_is_a_linear_release_migration() -> None:
    version = VERSION.read_text(encoding="utf-8")
    assert 'revision = "0101_dify_published_identity"' in version
    assert 'down_revision = "0100_recommendation_type_gate"' in version


def test_release_and_snapshot_share_one_immutable_published_identity() -> None:
    source = UP.read_text(encoding="utf-8")
    assert "ADD COLUMN registered_workflow_hash" in source
    assert "ADD COLUMN registered_snapshot_hash" in source
    assert "ADD COLUMN registered_identity_source" in source
    assert "dify_workflow_release_snapshot_pins pin" in source
    assert "attempt.status = 'succeeded'" in source
    assert "DISTINCT ON" not in source
    assert "registered_identity_source = 'migration_backfill'" in source
    assert "geo_require_dify_release_registered_identity" in source
    assert "NEW.registered_identity_source <> 'runtime_enrollment'" in source
    assert "CREATE FUNCTION geo_assert_dify_snapshot_registered_identity" in source
    assert "NEW.workflow_hash <> release_row.registered_workflow_hash" in source
    assert "NEW.snapshot_hash <> release_row.registered_snapshot_hash" in source
    assert "BEFORE INSERT ON dify_workflow_published_snapshots" in source


def test_downgrade_removes_only_the_registered_identity_contract() -> None:
    source = DOWN.read_text(encoding="utf-8")
    assert "registered_identity_source = 'runtime_enrollment'" in source
    assert "cannot downgrade 0101" in source
    assert "DROP TRIGGER dify_workflow_snapshot_registered_identity_guard" in source
    assert "DROP TRIGGER dify_workflow_release_registered_identity_guard" in source
    assert "DROP COLUMN registered_workflow_hash" in source
    assert "DROP COLUMN registered_snapshot_hash" in source
    assert "DROP COLUMN registered_identity_source" in source
