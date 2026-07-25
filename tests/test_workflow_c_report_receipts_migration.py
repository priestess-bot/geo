from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "infra/db/alembic/versions/0087_wfc_report_receipts.py"
UP = ROOT / "infra/db/alembic/sql/0087_wfc_report_receipts.sql"
DOWN = ROOT / "infra/db/alembic/sql/0087_wfc_report_receipts.down.sql"


def test_workflow_c_report_receipt_migration_is_linear_and_file_backed() -> None:
    version = VERSION.read_text(encoding="utf-8")

    assert 'revision = "0087_wfc_report_receipts"' in version
    assert 'down_revision = "0086_recommendation_summaries"' in version
    assert len("0087_wfc_report_receipts") <= 32
    assert "0087_wfc_report_receipts.sql" in version
    assert "0087_wfc_report_receipts.down.sql" in version


def test_receipts_are_scoped_hashed_immutable_and_bind_the_exact_result() -> None:
    source = UP.read_text(encoding="utf-8")

    assert "PRIMARY KEY (project_id, command_scope, idempotency_key_hash)" in source
    assert "input_hash" in source
    assert "result_version_hash" in source
    assert "workflow_c_report_command_receipts_immutable" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "GRANT SELECT, INSERT" in source
    assert "idempotency_key text" not in source


def test_receipt_downgrade_refuses_to_discard_replay_state() -> None:
    source = DOWN.read_text(encoding="utf-8")

    assert "IF EXISTS (SELECT 1 FROM workflow_c_report_command_receipts)" in source
    assert "DROP TABLE workflow_c_report_command_receipts" in source
