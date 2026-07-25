from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0073_workflow_c_metric_protocols.py"
UP = ROOT / "infra/db/alembic/sql/0073_wfc_metric_protocols.sql"
DOWN = ROOT / "infra/db/alembic/sql/0073_wfc_metric_protocols.down.sql"


def test_metric_protocol_migration_extends_the_linear_chain() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0073_wfc_metric_protocols"' in source
    assert 'down_revision = "0072_wfc_artifact_keyring_reader"' in source
    assert UP.is_file() and DOWN.is_file()


def test_metric_protocol_and_manifest_writes_are_controlled() -> None:
    source = UP.read_text(encoding="utf-8")
    for relation in (
        "workflow_c_metric_protocol_versions",
        "workflow_c_metric_protocol_command_receipts",
        "workflow_c_analysis_input_manifests",
        "workflow_c_analysis_input_manifest_items",
    ):
        assert f"CREATE TABLE {relation}" in source
    assert "status IN ('draft', 'in_review', 'approved', 'retired')" in source
    assert "NEW.approved_by <> NEW.created_by" in source
    assert "definition is immutable" in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "SECURITY DEFINER" in source
    assert "TO geo_app;" in source
    assert "GRANT SELECT ON workflow_c_analysis_input_manifests" in source
    assert "GRANT SELECT ON workflow_c_metric_protocol_command_receipts" not in source
    assert "cannot downgrade Metric Protocols after governed analysis state exists" in DOWN.read_text(
        encoding="utf-8"
    )
