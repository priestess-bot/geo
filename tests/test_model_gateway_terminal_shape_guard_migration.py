from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0033_terminal_shape_guard.py"
UP = ROOT / "infra/db/alembic/sql/0033_terminal_shape_guard.sql"
DOWN = ROOT / "infra/db/alembic/sql/0033_terminal_shape_guard.down.sql"


def test_terminal_shape_guard_extends_the_single_linear_migration_chain() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0033_terminal_shape_guard"' in source
    assert 'down_revision = "0032_recommendation_workflows"' in source
    assert UP.is_file() and DOWN.is_file()


def test_terminal_shape_guard_precedes_artifact_lineage_checks() -> None:
    source = UP.read_text(encoding="utf-8")
    assert "CREATE TRIGGER aaa_model_gateway_terminal_shape_guard" in source
    assert "BEFORE INSERT ON model_gateway_terminal_events" in source
    for contract in (
        "status_shape",
        "reconciliation_pair",
        "reconciliation_class",
        "failed_artifact_shape",
        "raw_storage_shape",
    ):
        assert contract in source
    assert "DROP TRIGGER aaa_model_gateway_terminal_shape_guard" in DOWN.read_text(
        encoding="utf-8"
    )
