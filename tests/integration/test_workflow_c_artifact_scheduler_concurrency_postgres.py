from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import os
from pathlib import Path
from threading import Barrier
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from alembic import command as alembic_command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest

from geo_core.workflow_c_artifacts.postgres_scheduler import (
    PostgresWorkflowCArtifactMaintenanceSchedulerRepository,
)
from tests.integration.monitoring_postgres_support import isolated_minio_store
from tests.integration.placement_worker_support import login_url, seed_project
from tests.integration.test_workflow_c_artifact_maintenance_postgres import (
    _seed_active_artifact,
)


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_workflow_c_artifact_scheduler_concurrent_seeds_create_one_job_and_outbox() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_wfc_scheduler_race_{suffix}"
    database_url = _database_url(ADMIN_URL, database_name)
    worker_login, worker_password = f"geo_wfc_scheduler_{suffix}", uuid4().hex
    created_database = False
    created_role = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = database_url
        alembic_command.upgrade(migration, "head")
        with psycopg.connect(database_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_worker").format(
                    sql.Identifier(worker_login), sql.Literal(worker_password)
                )
            )
            created_role = True
            project = seed_project(admin, suffix=f"wfc-scheduler-race-{suffix}")["project"]

        now = datetime.now(UTC).replace(microsecond=0)
        with isolated_minio_store() as objects:
            with psycopg.connect(database_url) as admin:
                _seed_active_artifact(
                    admin,
                    objects=objects,
                    project_id=project,
                    now=now,
                    marker="scheduler-race",
                    legal_hold=False,
                )
                admin.execute(
                    """CREATE FUNCTION geo_test_pause_wfc_maintenance_insert()
                           RETURNS trigger LANGUAGE plpgsql AS $$
                           BEGIN
                               IF NEW.kind = 'workflow_c.artifact_maintenance' THEN
                                   PERFORM pg_sleep(0.25);
                               END IF;
                               RETURN NEW;
                           END;
                           $$"""
                )
                admin.execute(
                    """CREATE TRIGGER geo_test_pause_wfc_maintenance_insert
                           BEFORE INSERT ON durable_jobs
                           FOR EACH ROW EXECUTE FUNCTION geo_test_pause_wfc_maintenance_insert()"""
                )

            worker_url = login_url(database_url, user=worker_login, password=worker_password)
            barrier = Barrier(3)

            def seed() -> tuple[object, ...]:
                repository = PostgresWorkflowCArtifactMaintenanceSchedulerRepository(
                    connect=lambda: psycopg.connect(worker_url, row_factory=dict_row)
                )
                barrier.wait(timeout=5)
                return repository.seed_due(
                    now=now,
                    staged_grace_seconds=900,
                    max_projects=10,
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                first, second = executor.submit(seed), executor.submit(seed)
                barrier.wait(timeout=5)
                schedules = first.result(timeout=10) + second.result(timeout=10)

            assert len(schedules) == 2
            assert {schedule.project_id for schedule in schedules} == {project}
            assert len({schedule.job_id for schedule in schedules}) == 1
            assert len({schedule.outbox_id for schedule in schedules}) == 1
            assert {schedule.inserted for schedule in schedules} == {False, True}
            with psycopg.connect(database_url) as admin:
                counts = admin.execute(
                    """SELECT
                           (SELECT count(*) FROM durable_jobs
                             WHERE project_id = %s
                               AND kind = 'workflow_c.artifact_maintenance'
                               AND idempotency_key = 'workflow-c-artifact-maintenance:v1'),
                           (SELECT count(*) FROM broker_outbox
                             WHERE project_id = %s
                               AND topic = 'workflow_c.artifact_maintenance')""",
                    (project, project),
                ).fetchone()
            assert counts == (1, 1)
    finally:
        if created_database:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )
        if created_role:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(worker_login)))


def _database_url(base: str, database_name: str) -> str:
    parsed = urlsplit(base)
    return urlunsplit(parsed._replace(path=f"/{database_name}"))
