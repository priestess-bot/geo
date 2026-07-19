from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0018_metric_membership.py"
UP = ROOT / "infra/db/alembic/sql/0018_metric_membership.sql"
DOWN = ROOT / "infra/db/alembic/sql/0018_metric_membership.down.sql"


def test_metric_membership_extends_the_linear_revision_chain() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0018_metric_membership"' in source
    assert 'down_revision = "0017_knowledge_rag_graph"' in source
    assert UP.is_file() and DOWN.is_file()


def test_metric_membership_freezes_exact_append_only_inputs() -> None:
    source = UP.read_text(encoding="utf-8")
    for contract in (
        "monitoring_metric_snapshot_observations",
        "observation_membership_version",
        "observation_membership_count",
        "observation_membership_hash",
        "metric-observation-membership-v1",
        "payload_hash",
        "ordinal > 0",
        "DEFERRABLE INITIALLY DEFERRED",
        "geo_assert_metric_membership_member",
        "geo_assert_metric_membership_manifest",
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
    ):
        assert contract in source


def test_metric_membership_preserves_legacy_unknowns_and_downgrades_fail_closed() -> None:
    source = UP.read_text(encoding="utf-8")
    down = DOWN.read_text(encoding="utf-8")
    assert "observation_membership_version text" in source
    assert "cannot downgrade: frozen metric observation membership exists" in down
    assert "UPDATE monitoring_metric_snapshots" not in source
    assert "DELETE FROM monitoring_" not in down
    assert "UPDATE monitoring_" not in down
