from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0034_workflow_c_job_enqueue.py"
UP = ROOT / "infra/db/alembic/sql/0034_workflow_c_job_enqueue.sql"
DOWN = ROOT / "infra/db/alembic/sql/0034_workflow_c_job_enqueue.down.sql"


def test_workflow_c_job_enqueue_extends_the_single_linear_migration_chain() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0034_workflow_c_job_enqueue"' in source
    assert 'down_revision = "0033_terminal_shape_guard"' in source
    assert UP.is_file() and DOWN.is_file()


def test_workflow_c_producer_is_atomic_and_application_roles_only_execute_it() -> None:
    source = UP.read_text(encoding="utf-8")
    assert "SECURITY DEFINER" in source
    assert "SET row_security = off" in source
    assert "CREATE OR REPLACE FUNCTION geo_workflow_c_job_spec_payload_is_safe" in source
    assert "ELSE\n            NULL;" in source
    for relation in (
        "INSERT INTO durable_jobs",
        "INSERT INTO workflow_c_job_specs",
        "INSERT INTO broker_outbox",
        "INSERT INTO durable_job_events",
    ):
        assert relation in source
    assert "REVOKE INSERT ON workflow_c_job_specs FROM geo_app, geo_worker" in source
    assert "GRANT EXECUTE ON FUNCTION geo_enqueue_workflow_c_job_spec" in source
    assert "DROP FUNCTION geo_enqueue_workflow_c_job_spec" in DOWN.read_text(encoding="utf-8")
