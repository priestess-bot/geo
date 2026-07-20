from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0011_runtime_health.py"
UP = ROOT / "infra/db/alembic/sql/0011_runtime_health.sql"
DOWN = ROOT / "infra/db/alembic/sql/0011_runtime_health.down.sql"


def test_runtime_health_migration_extends_the_single_revision_chain() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0011_runtime_health"' in source
    assert 'down_revision = "0010_campaign_destinations"' in source
    assert UP.is_file() and DOWN.is_file()


def test_runtime_health_schema_has_minimal_privilege_and_safe_findings() -> None:
    source = UP.read_text(encoding="utf-8")
    for contract in (
        "PRIMARY KEY (service_type, instance_id)",
        "runtime_service_heartbeats_container_last_idx",
        "durable_jobs_runtime_terminal_idx",
        "COALESCE(completed_at, updated_at)",
        "p_expected_instances",
        "freshness_rank <= p_expected_instances",
        "CASE item.finding_category WHEN 'runtime_heartbeat' THEN 0 ELSE 1 END",
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
        "SECURITY DEFINER",
        "geo_worker_record_runtime_heartbeat",
        "geo_worker_runtime_findings",
        "FROM PUBLIC, geo_app, geo_worker, geo_readonly",
        "TO geo_worker",
        "durable_job_queued_stalled",
        "durable_job_retry_stalled",
        "durable_job_running_lease_expired",
        "durable_job_finalizing_recovery_overdue",
        "broker_outbox_delivery_stalled",
        "durable_job_dead_lettered",
        "durable_job_terminal_failed",
    ):
        assert contract in source

    returns_contract = source.split(") RETURNS TABLE (", maxsplit=1)[1].split(")\nLANGUAGE", maxsplit=1)[0]
    assert "payload" not in returns_contract
    assert "error_detail" not in returns_contract
    assert "last_error" not in returns_contract
    assert "DROP INDEX IF EXISTS durable_jobs_runtime_terminal_idx" in DOWN.read_text(
        encoding="utf-8"
    )
