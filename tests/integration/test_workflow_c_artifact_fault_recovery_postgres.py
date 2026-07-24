from __future__ import annotations

from dataclasses import dataclass
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

from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.object_store import S3CompatibleObjectStore, parse_s3_uri
from geo_core.sampling.manual_artifact_governance import AUTOMATIC_POLICY_KEY
from geo_core.sampling.manual_artifact_storage import (
    IndependentWorkflowCArtifactEncryptor,
    MinioWorkflowCManualArtifactWriter,
)
from geo_core.secrets import EnvelopeCipher, MasterKeyring
from geo_core.workflow_c_artifacts.lifecycle import (
    WORKFLOW_C_ARTIFACT_MAINTENANCE_JOB_KIND,
    WorkflowCArtifactMaintenanceService,
)
from geo_core.workflow_c_artifacts.postgres import (
    PostgresWorkflowCArtifactKeyVault,
    PostgresWorkflowCManualArtifactRepository,
    synchronize_workflow_c_artifact_master_keys,
)
from geo_core.workflow_c_artifacts.postgres_lifecycle import (
    PostgresWorkflowCArtifactLifecycleRepository,
)
from geo_core.workflow_c_artifacts.postgres_scheduler import (
    PostgresWorkflowCArtifactMaintenanceSchedulerRepository,
)
from geo_core.workflow_c_artifacts.scheduler import WorkflowCArtifactMaintenanceScheduler
from geo_worker.workflow_c_artifact_maintenance import WorkflowCArtifactMaintenanceOperation
from tests.integration.monitoring_postgres_support import isolated_minio_store
from tests.integration.placement_worker_support import login_url, seed_project
from tests.integration.test_workflow_c_artifact_maintenance_postgres import (
    _create_manual_sampling_lineage,
    _seed_manual_runtime_option,
)


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


@dataclass
class _FailSecondObjectWrite:
    """Inject a manifest write failure without granting Writer delete capability."""

    store: S3CompatibleObjectStore
    writes: int = 0

    def uri_for_key(self, key: str) -> str:
        return self.store.uri_for_key(key)

    def put_object(self, **values):
        self.writes += 1
        if self.writes == 2:
            raise RuntimeError("fixture manifest write failure")
        return self.store.put_object(**values)

    def get_s3_uri(self, **values):
        return self.store.get_s3_uri(**values)


@dataclass
class _CleanupErrorRecorder:
    repository: PostgresWorkflowCManualArtifactRepository
    cleanup_error: BaseException | None = None

    def stage(self, record) -> None:
        self.repository.stage(record)

    def activate(self, **values) -> None:
        self.repository.activate(**values)

    def queue_failed_stage_cleanup(self, **values) -> None:
        try:
            self.repository.queue_failed_stage_cleanup(**values)
        except BaseException as error:
            self.cleanup_error = error
            raise


def test_workflow_c_fault_cleanup_wakes_durable_worker_for_write_failure_and_staged_timeout() -> (
    None
):
    suffix = uuid4().hex[:10]
    database_name = f"geo_wfc_artifact_fault_{suffix}"
    database_url = _database_url(ADMIN_URL, database_name)
    app_login, app_password = f"geo_wfc_fault_app_{suffix}", uuid4().hex
    worker_login, worker_password = f"geo_wfc_fault_worker_{suffix}", uuid4().hex
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
            project_id = seed_project(admin, suffix=f"wfc-artifact-fault-{suffix}")["project"]
            _seed_manual_runtime_option(admin, project_id=project_id)

        app_url = login_url(database_url, user=app_login, password=app_password)
        worker_url = login_url(database_url, user=worker_login, password=worker_password)
        now = datetime.now(UTC).replace(microsecond=0)
        cipher = EnvelopeCipher(MasterKeyring(keys={1: b"F" * 32}, active_version=1))
        with psycopg.connect(database_url, row_factory=dict_row) as admin:
            assert synchronize_workflow_c_artifact_master_keys(admin, cipher) == (1,)

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
            failed_artifact_id = uuid4()
            failed_repository = _CleanupErrorRecorder(
                PostgresWorkflowCManualArtifactRepository(connect=app_connect)
            )
            failed_writer = _writer(
                app_connect=app_connect,
                object_store=_FailSecondObjectWrite(objects),
                cipher=cipher,
                clock=lambda: now,
                repository=failed_repository,
            )
            with pytest.raises(RuntimeError, match="manifest write failure"):
                failed_writer.write(
                    project_id=project_id,
                    run_id=run_id,
                    task_id=task_id,
                    artifact_manifest_id=failed_artifact_id,
                    capture_session_id=uuid4(),
                    evidence_kind="transcript_export",
                    content_type="application/json",
                    content=bytearray(b'{"answer":"failed artifact fixture"}'),
                    governance_policy_key=AUTOMATIC_POLICY_KEY,
                    pre_redacted_attestation=False,
                )

            assert failed_repository.cleanup_error is None, repr(
                failed_repository.cleanup_error.__cause__
            )
            failed_payload_key = _assert_enqueued_failure(
                database_url,
                project_id=project_id,
                artifact_id=failed_artifact_id,
            )
            assert objects.head_object(key=failed_payload_key)
            failed_job_id = _maintenance_job_id(database_url, project_id=project_id)
            _execute_maintenance_job(
                worker_connect=worker_connect,
                object_store=objects,
                project_id=project_id,
                job_id=failed_job_id,
                now=datetime.now(UTC) + timedelta(seconds=1),
            )
            assert not objects.head_object(key=failed_payload_key)
            _assert_terminal_cleanup(
                database_url,
                artifact_id=failed_artifact_id,
                reason="write_failed",
            )

            staged_artifact_id = uuid4()
            staged_writer = _writer(
                app_connect=app_connect,
                object_store=objects,
                cipher=cipher,
                clock=lambda: datetime.now(UTC) - timedelta(seconds=61),
            )
            staged_writer.write(
                project_id=project_id,
                run_id=run_id,
                task_id=task_id,
                artifact_manifest_id=staged_artifact_id,
                capture_session_id=uuid4(),
                evidence_kind="transcript_export",
                content_type="application/json",
                content=bytearray(b'{"answer":"staged timeout fixture"}'),
                governance_policy_key=AUTOMATIC_POLICY_KEY,
                pre_redacted_attestation=False,
                activate=False,
            )

            timeout_at = datetime.now(UTC)
            scheduler = WorkflowCArtifactMaintenanceScheduler(
                repository=PostgresWorkflowCArtifactMaintenanceSchedulerRepository(
                    connect=worker_connect
                ),
                staged_grace_seconds=60,
                clock=lambda: timeout_at,
            )
            scheduled = scheduler.run_once()
            assert (scheduled.scheduled_project_count, scheduled.inserted_job_count) == (1, 1)
            staged_payload_key = _payload_key(database_url, artifact_id=staged_artifact_id)
            assert objects.head_object(key=staged_payload_key)
            _execute_maintenance_job(
                worker_connect=worker_connect,
                object_store=objects,
                project_id=project_id,
                job_id=_maintenance_job_id(database_url, project_id=project_id),
                now=datetime.now(UTC) + timedelta(seconds=1),
            )
            assert not objects.head_object(key=staged_payload_key)
            _assert_terminal_cleanup(
                database_url,
                artifact_id=staged_artifact_id,
                reason="staged_timeout",
            )
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


def _writer(*, app_connect, object_store, cipher: EnvelopeCipher, clock, repository=None):
    return MinioWorkflowCManualArtifactWriter(
        object_store=object_store,
        encryptor=IndependentWorkflowCArtifactEncryptor(
            PostgresWorkflowCArtifactKeyVault(
                connect=app_connect,
                cipher=cipher,
                synchronize=False,
            )
        ),
        repository=repository or PostgresWorkflowCManualArtifactRepository(connect=app_connect),
        clock=clock,
    )


def _execute_maintenance_job(
    *,
    worker_connect,
    object_store: S3CompatibleObjectStore,
    project_id: UUID,
    job_id: UUID,
    now: datetime,
) -> None:
    durable_jobs = PostgresDurableJobStore(worker_connect)
    claim = durable_jobs.claim(
        job_id=job_id,
        project_id=project_id,
        expected_kind=WORKFLOW_C_ARTIFACT_MAINTENANCE_JOB_KIND,
        worker_id="workflow-c-artifact-fault-integration",
        lease_for=timedelta(minutes=2),
    )
    assert claim.disposition == "claimed" and claim.lease is not None
    operation = WorkflowCArtifactMaintenanceOperation(
        store=durable_jobs,
        service=WorkflowCArtifactMaintenanceService(
            repository=PostgresWorkflowCArtifactLifecycleRepository(connect=worker_connect),
            object_store=object_store,
            worker_id="workflow-c-artifact-fault-integration",
            clock=lambda: now,
        ),
        lease_for=timedelta(minutes=2),
    )
    assert operation.execute(claim.lease) == {
        "status": "succeeded",
        "job_id": str(job_id),
        "claimed_count": 1,
        "completed_count": 1,
        "retry_count": 0,
        "crypto_erased_count": 1,
    }


def _assert_enqueued_failure(database_url: str, *, project_id: UUID, artifact_id: UUID) -> str:
    with psycopg.connect(database_url, row_factory=dict_row) as admin:
        row = admin.execute(
            """SELECT artifact.status AS artifact_status, dek.status AS dek_status,
                      queue.reason, queue.status AS queue_status, artifact.object_uri,
                      (SELECT count(*) FROM durable_jobs
                        WHERE project_id = %s
                          AND kind = 'workflow_c.artifact_maintenance'
                          AND status = 'queued') AS job_count,
                      (SELECT count(*) FROM broker_outbox
                        WHERE project_id = %s
                          AND topic = 'workflow_c.artifact_maintenance'
                          AND published_at IS NULL) AS outbox_count
                 FROM workflow_c_manual_artifacts AS artifact
                 JOIN workflow_c_artifact_deks AS dek
                   ON dek.project_id = artifact.project_id
                  AND dek.artifact_id = artifact.artifact_id
                 JOIN workflow_c_artifact_deletion_queue AS queue
                   ON queue.project_id = artifact.project_id
                  AND queue.artifact_id = artifact.artifact_id
                WHERE artifact.project_id = %s AND artifact.artifact_id = %s""",
            (project_id, project_id, project_id, artifact_id),
        ).fetchone()
    assert row is not None
    assert (
        row["artifact_status"],
        row["dek_status"],
        row["reason"],
        row["queue_status"],
        row["job_count"],
        row["outbox_count"],
    ) == ("delete_pending", "active", "write_failed", "pending", 1, 1)
    _bucket, key = parse_s3_uri(str(row["object_uri"]))
    return key


def _maintenance_job_id(database_url: str, *, project_id: UUID) -> UUID:
    with psycopg.connect(database_url, row_factory=dict_row) as admin:
        row = admin.execute(
            """SELECT id FROM durable_jobs
                 WHERE project_id = %s
                   AND kind = 'workflow_c.artifact_maintenance'
                   AND status = 'queued'
                 ORDER BY created_at DESC
                 LIMIT 1""",
            (project_id,),
        ).fetchone()
    assert row is not None
    return UUID(str(row["id"]))


def _payload_key(database_url: str, *, artifact_id: UUID) -> str:
    with psycopg.connect(database_url, row_factory=dict_row) as admin:
        row = admin.execute(
            """SELECT object_uri FROM workflow_c_manual_artifacts
                 WHERE artifact_id = %s""",
            (artifact_id,),
        ).fetchone()
    assert row is not None
    _bucket, key = parse_s3_uri(str(row["object_uri"]))
    return key


def _assert_terminal_cleanup(database_url: str, *, artifact_id: UUID, reason: str) -> None:
    with psycopg.connect(database_url, row_factory=dict_row) as admin:
        row = admin.execute(
            """SELECT artifact.status AS artifact_status, dek.status AS dek_status,
                      queue.reason, queue.status AS queue_status,
                      artifact.object_uri, artifact.manifest_uri, artifact.key_ref,
                      job.status AS job_status
                 FROM workflow_c_manual_artifacts AS artifact
                 JOIN workflow_c_artifact_deks AS dek
                   ON dek.project_id = artifact.project_id
                  AND dek.artifact_id = artifact.artifact_id
                 JOIN workflow_c_artifact_deletion_queue AS queue
                   ON queue.project_id = artifact.project_id
                  AND queue.artifact_id = artifact.artifact_id
                 JOIN durable_jobs AS job
                   ON job.project_id = artifact.project_id
                  AND job.kind = 'workflow_c.artifact_maintenance'
                WHERE artifact.artifact_id = %s
                ORDER BY job.created_at DESC
                LIMIT 1""",
            (artifact_id,),
        ).fetchone()
    assert row is not None
    assert (
        row["artifact_status"],
        row["dek_status"],
        row["reason"],
        row["queue_status"],
        row["object_uri"],
        row["manifest_uri"],
        row["key_ref"],
        row["job_status"],
    ) == ("tombstoned", "destroyed", reason, "completed", None, None, None, "succeeded")


def _database_url(base: str, database_name: str) -> str:
    parsed = urlsplit(base)
    return urlunsplit(parsed._replace(path=f"/{database_name}"))
