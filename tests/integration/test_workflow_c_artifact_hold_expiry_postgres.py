from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from alembic import command as alembic_command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest

from geo_core.workflow_c_artifacts.holds import (
    WorkflowCArtifactHoldAction,
    WorkflowCArtifactHoldApplication,
    WorkflowCArtifactHoldStatus,
)
from geo_core.workflow_c_artifacts.lifecycle import WorkflowCArtifactMaintenanceService
from geo_core.workflow_c_artifacts.postgres_holds import (
    PostgresWorkflowCArtifactHoldRepository,
)
from geo_core.workflow_c_artifacts.postgres_lifecycle import (
    PostgresWorkflowCArtifactLifecycleRepository,
)
from geo_core.workflow_c_artifacts.postgres_scheduler import (
    PostgresWorkflowCArtifactMaintenanceSchedulerRepository,
)
from geo_core.workflow_c_artifacts.scheduler import WorkflowCArtifactMaintenanceScheduler
from tests.integration.monitoring_postgres_support import isolated_minio_store
from tests.integration.placement_worker_support import login_url, seed_project
from tests.integration.test_workflow_c_artifact_maintenance_postgres import (
    _create_manual_sampling_lineage,
    _seed_active_artifact,
    _seed_manual_runtime_option,
)


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_bounded_hold_extension_expires_then_retention_deletes_real_objects() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_wfc_hold_expiry_{suffix}"
    database_url = _database_url(ADMIN_URL, database_name)
    app_login, app_password = f"geo_wfc_hold_app_{suffix}", uuid4().hex
    worker_login, worker_password = f"geo_wfc_hold_worker_{suffix}", uuid4().hex
    created_database = False
    created_logins = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = database_url
        alembic_command.upgrade(migration, "head")
        with psycopg.connect(database_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                    sql.Identifier(app_login), sql.Literal(app_password)
                )
            )
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_worker").format(
                    sql.Identifier(worker_login), sql.Literal(worker_password)
                )
            )
            created_logins = True
            project_id = seed_project(admin, suffix=f"wfc-hold-expiry-{suffix}")["project"]
            _seed_manual_runtime_option(admin, project_id=project_id)

        app_url = login_url(database_url, user=app_login, password=app_password)
        worker_url = login_url(database_url, user=worker_login, password=worker_password)
        now = datetime.now(UTC).replace(microsecond=0)
        apply_requested_at = now - timedelta(days=1, hours=2)
        first_hold_until = now + timedelta(minutes=10)
        extended_hold_until = now + timedelta(minutes=20)

        def app_connect():
            return psycopg.connect(app_url, row_factory=dict_row)

        def worker_connect():
            return psycopg.connect(worker_url, row_factory=dict_row)

        with isolated_minio_store() as objects:
            run_id, task_id = _create_manual_sampling_lineage(
                app_connect=app_connect,
                project_id=project_id,
                now=now,
            )
            with psycopg.connect(database_url) as admin:
                artifact = _seed_active_artifact(
                    admin,
                    objects=objects,
                    project_id=project_id,
                    now=now,
                    marker="bounded-hold-expiry",
                    legal_hold=False,
                    run_id=run_id,
                    task_id=task_id,
                )

            holds = WorkflowCArtifactHoldApplication(
                PostgresWorkflowCArtifactHoldRepository(connect=app_connect)
            )
            apply_request_id = uuid4()
            apply_request = holds.request(
                project_id=project_id,
                artifact_id=artifact["artifact_id"],
                request_id=apply_request_id,
                action=WorkflowCArtifactHoldAction.APPLY,
                actor_id="legal-maker-1",
                reason="Preserve evidence for the open legal matter.",
                requested_at=apply_requested_at,
                hold_until=first_hold_until,
            )
            assert apply_request.status is WorkflowCArtifactHoldStatus.PENDING
            apply_approval = holds.decide(
                project_id=project_id,
                request_id=apply_request_id,
                expected_version=1,
                actor_id="legal-checker-1",
                approved=True,
                reason="Matter and bounded retention period verified.",
                decided_at=apply_requested_at + timedelta(minutes=1),
            )
            assert apply_approval.status is WorkflowCArtifactHoldStatus.APPROVED
            assert apply_approval.hold_until == first_hold_until

            scheduler = WorkflowCArtifactMaintenanceScheduler(
                repository=PostgresWorkflowCArtifactMaintenanceSchedulerRepository(
                    connect=worker_connect
                ),
                staged_grace_seconds=60,
                clock=lambda: now,
            )
            held = scheduler.run_once()
            assert held.scheduled_project_count == 0

            extend_request_id = uuid4()
            extend_request = holds.request(
                project_id=project_id,
                artifact_id=artifact["artifact_id"],
                request_id=extend_request_id,
                action=WorkflowCArtifactHoldAction.EXTEND,
                actor_id="legal-maker-2",
                reason="Approved matter remains active; extend the preservation period.",
                requested_at=now,
                hold_until=extended_hold_until,
            )
            assert extend_request.status is WorkflowCArtifactHoldStatus.PENDING
            extend_approval = holds.decide(
                project_id=project_id,
                request_id=extend_request_id,
                expected_version=1,
                actor_id="legal-checker-2",
                approved=True,
                reason="Extension and its new bounded period verified.",
                decided_at=now + timedelta(minutes=1),
            )
            assert extend_approval.status is WorkflowCArtifactHoldStatus.APPROVED
            assert extend_approval.hold_until == extended_hold_until

            expiry_scheduler = WorkflowCArtifactMaintenanceScheduler(
                repository=PostgresWorkflowCArtifactMaintenanceSchedulerRepository(
                    connect=worker_connect
                ),
                staged_grace_seconds=60,
                clock=lambda: extended_hold_until + timedelta(minutes=1),
            )
            expired = expiry_scheduler.run_once()
            assert (expired.scheduled_project_count, expired.inserted_job_count) == (1, 1)
            _assert_expired_hold_and_queued_retention(
                database_url,
                project_id=project_id,
                artifact_id=artifact["artifact_id"],
                extension_request_id=extend_request_id,
            )

            result = WorkflowCArtifactMaintenanceService(
                repository=PostgresWorkflowCArtifactLifecycleRepository(connect=worker_connect),
                object_store=objects,
                worker_id="wfc-hold-expiry-maintenance",
                clock=lambda: extended_hold_until + timedelta(minutes=2),
            ).run_once(project_id=project_id)
            assert (result.claimed_count, result.crypto_erased_count, result.completed_count) == (
                1,
                1,
                1,
            )
            assert not objects.head_object(key=_key(artifact["payload"].uri))
            assert not objects.head_object(key=_key(artifact["manifest"].uri))
            _assert_tombstoned(database_url, artifact_id=artifact["artifact_id"])
    finally:
        if created_database:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )
        if created_logins:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(app_login)))
                server.execute(
                    sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(worker_login))
                )


def _assert_expired_hold_and_queued_retention(
    database_url: str,
    *,
    project_id: UUID,
    artifact_id: UUID,
    extension_request_id: UUID,
) -> None:
    with psycopg.connect(database_url) as admin:
        artifact = admin.execute(
            """SELECT legal_hold, legal_hold_until, status
                 FROM workflow_c_manual_artifacts
                WHERE project_id = %s AND artifact_id = %s""",
            (project_id, artifact_id),
        ).fetchone()
        request = admin.execute(
            """SELECT status, decided_by, decision_reason
                 FROM workflow_c_artifact_hold_requests
                WHERE project_id = %s AND id = %s""",
            (project_id, extension_request_id),
        ).fetchone()
        event_types = {
            row[0]
            for row in admin.execute(
                """SELECT event_type
                     FROM workflow_c_artifact_lifecycle_events
                    WHERE project_id = %s AND artifact_id = %s""",
                (project_id, artifact_id),
            ).fetchall()
        }
        queue = admin.execute(
            """SELECT reason, status
                 FROM workflow_c_artifact_deletion_queue
                WHERE project_id = %s AND artifact_id = %s""",
            (project_id, artifact_id),
        ).fetchone()
    assert artifact == (False, None, "delete_pending")
    assert request == ("expired", "legal-checker-2", "Extension and its new bounded period verified.")
    assert {"hold_applied", "hold_extended", "hold_expired", "delete_enqueued"} <= event_types
    assert queue == ("expiry", "pending")


def _assert_tombstoned(database_url: str, *, artifact_id: UUID) -> None:
    with psycopg.connect(database_url) as admin:
        row = admin.execute(
            """SELECT artifact.status, dek.status, queue.status, queue.reason
                 FROM workflow_c_manual_artifacts AS artifact
                 JOIN workflow_c_artifact_deks AS dek
                   ON dek.project_id = artifact.project_id
                  AND dek.artifact_id = artifact.artifact_id
                 JOIN workflow_c_artifact_deletion_queue AS queue
                   ON queue.project_id = artifact.project_id
                  AND queue.artifact_id = artifact.artifact_id
                WHERE artifact.artifact_id = %s""",
            (artifact_id,),
        ).fetchone()
    assert row == ("tombstoned", "destroyed", "completed", "expiry")


def _key(uri: str) -> str:
    return uri.split("/", 3)[3]


def _database_url(base: str, database_name: str) -> str:
    parsed = urlsplit(base)
    return urlunsplit(parsed._replace(path=f"/{database_name}"))
