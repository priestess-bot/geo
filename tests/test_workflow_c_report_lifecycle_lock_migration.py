from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0035_workflow_c_report_lifecycle_locks.py"
UP = ROOT / "infra/db/alembic/sql/0035_workflow_c_report_locks.sql"
DOWN = ROOT / "infra/db/alembic/sql/0035_workflow_c_report_locks.down.sql"


def test_report_lifecycle_lock_compatibility_fix_extends_the_linear_chain() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "0035_workflow_c_report_locks"' in source
    assert 'down_revision = "0034_workflow_c_job_enqueue"' in source
    assert UP.is_file() and DOWN.is_file()


def test_report_append_trigger_relies_on_predecessor_and_primary_key_not_app_update_privilege() -> None:
    source = UP.read_text(encoding="utf-8")

    assert "geo_assert_workflow_c_report_snapshot_version_append" in source
    assert "version = NEW.version - 1;" in source
    assert "\n    FOR SHARE;" not in source
    assert "Workflow C approved report source is not Customer eligible" in source
    assert "metric.evidence_status = 'complete'" in source
    assert "metric.approved_at IS NOT NULL" in source
    assert "NOT metric.test_only AND NOT metric.synthetic" in source
    assert "append-only" in source
    assert "FOR SHARE" in DOWN.read_text(encoding="utf-8")
