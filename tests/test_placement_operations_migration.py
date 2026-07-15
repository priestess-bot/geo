from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0007_placement_operations.py"
UP = ROOT / "infra/db/alembic/sql/0007_placement_operations.sql"
DOWN = ROOT / "infra/db/alembic/sql/0007_placement_operations.down.sql"


def test_placement_operations_migration_extends_monitoring_lineage() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0007_placement_operations"' in source
    assert 'down_revision = "0006_monitoring_lineage"' in source
    assert UP.is_file() and DOWN.is_file()


def test_placement_operations_schema_persists_required_guards() -> None:
    source = UP.read_text(encoding="utf-8") + (
        ROOT / "packages/geo_core/geo_core/placements/postgres_measurement_tasks.py"
    ).read_text(encoding="utf-8")
    for contract in (
        "publication_submissions_project_idempotency_key_key",
        "submitted_by uuid",
        "payload_hash text",
        "CREATE TABLE measurement_collection_tasks",
        "expected_sample_count",
        "monitoring_observations",
        "status IN ('open', 'completed', 'cancelled')",
        "geo_assert_opportunity_transition",
        "transition: %% -> %%",
        "ENABLE ROW LEVEL SECURITY",
    ):
        assert contract in source
