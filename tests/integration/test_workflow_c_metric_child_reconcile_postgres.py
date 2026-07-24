from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest

from geo_core.jobs.postgres import PostgresDurableJobStore, WorkerLease
from tests.integration.placement_worker_support import login_url, seed_project


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_metric_child_durable_states_reconcile_retry_failure_and_cancel() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_metric_reconcile_{suffix}"
    database_url = _database_url(ADMIN_URL, database_name)
    worker_login, password = f"geo_metric_reconcile_{suffix}", uuid4().hex
    created_database = False
    created_role = False
    now = datetime.now(UTC).replace(microsecond=0)
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = database_url
        command.upgrade(migration, "head")
        command.downgrade(migration, "0060_metric_rpc_aggregate_fix")
        command.upgrade(migration, "head")

        with psycopg.connect(database_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_worker").format(
                    sql.Identifier(worker_login), sql.Literal(password)
                )
            )
            created_role = True
            project = seed_project(admin, suffix=f"metric-reconcile-{suffix}")
            retried = _seed_metric_batch(
                admin,
                project_id=project["project"],
                now=now,
                sibling_count=1,
                running_sibling=True,
            )
            cancelled = _seed_metric_batch(
                admin, project_id=project["project"], now=now, sibling_count=0
            )
            admin.commit()

        worker_url = login_url(database_url, user=worker_login, password=password)
        store = PostgresDurableJobStore(
            lambda: psycopg.connect(worker_url, row_factory=dict_row)
        )
        first_lease = _lease(project["project"], retried)
        assert (
            store.fail(
                first_lease,
                error_code="metric_upstream_timeout",
                details={"classification": "fixture"},
                retry_delay=timedelta(0),
            )
            == "retry_wait"
        )
        _assert_metric_state(
            database_url,
            batch_id=retried["batch_id"],
            child_job_id=retried["child_job_id"],
            expected_child=("queued", "metric_upstream_timeout"),
            expected_batch=("queued", 1),
            expected_job="retry_wait",
        )

        claimed = store.claim(
            job_id=retried["child_job_id"],
            project_id=project["project"],
            expected_kind="workflow_c.metric_judge",
            worker_id="metric-reconcile-retry",
            lease_for=timedelta(seconds=30),
        )
        assert claimed.lease is not None
        assert (
            store.fail(
                claimed.lease,
                error_code="metric_upstream_timeout",
                details={"classification": "fixture"},
                retry_delay=None,
            )
            == "failed"
        )
        _assert_metric_state(
            database_url,
            batch_id=retried["batch_id"],
            child_job_id=retried["child_job_id"],
            expected_child=("failed", "metric_upstream_timeout"),
            expected_batch=("failed", 2),
            expected_job="failed",
        )
        sibling = retried["sibling_job_id"]
        assert sibling is not None
        with psycopg.connect(database_url) as admin:
            sibling_row = admin.execute(
                """SELECT child.status, child.error_code, job.status
                       FROM workflow_c_metric_model_children AS child
                       JOIN durable_jobs AS job
                         ON job.project_id = child.project_id AND job.id = child.child_job_id
                      WHERE child.project_id = %s AND child.child_job_id = %s""",
                (project["project"], sibling),
            ).fetchone()
        assert sibling_row == ("cancelled", "cancelled", "cancelled")
        running_sibling = retried["running_sibling_job_id"]
        assert running_sibling is not None
        with psycopg.connect(database_url) as admin:
            running_sibling_row = admin.execute(
                """SELECT child.status, job.status, job.cancel_requested_at IS NOT NULL
                       FROM workflow_c_metric_model_children AS child
                       JOIN durable_jobs AS job
                         ON job.project_id = child.project_id AND job.id = child.child_job_id
                      WHERE child.project_id = %s AND child.child_job_id = %s""",
                (project["project"], running_sibling),
            ).fetchone()
        assert running_sibling_row == ("running", "running", True)
        store.cancel(_running_sibling_lease(project["project"], retried))
        with psycopg.connect(database_url) as admin:
            running_sibling_row = admin.execute(
                """SELECT child.status, child.error_code, job.status
                       FROM workflow_c_metric_model_children AS child
                       JOIN durable_jobs AS job
                         ON job.project_id = child.project_id AND job.id = child.child_job_id
                      WHERE child.project_id = %s AND child.child_job_id = %s""",
                (project["project"], running_sibling),
            ).fetchone()
        assert running_sibling_row == ("cancelled", "cancelled", "cancelled")

        cancel_lease = _lease(project["project"], cancelled)
        store.cancel(cancel_lease)
        _assert_metric_state(
            database_url,
            batch_id=cancelled["batch_id"],
            child_job_id=cancelled["child_job_id"],
            expected_child=("cancelled", "cancelled"),
            expected_batch=("cancelled", 2),
            expected_job="cancelled",
        )
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
                server.execute(
                    sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(worker_login))
                )


def _seed_metric_batch(
    connection: psycopg.Connection,
    *,
    project_id: UUID,
    now: datetime,
    sibling_count: int,
    running_sibling: bool = False,
) -> dict[str, UUID | None]:
    parent_job, child_job, batch_id, lease_token = uuid4(), uuid4(), uuid4(), uuid4()
    task_hash, parent_input_hash = _hash(f"metric-task:{batch_id}"), _hash(f"metric-parent:{batch_id}")
    connection.execute(
        """INSERT INTO durable_jobs(
               id, project_id, kind, status, input_hash, idempotency_key, next_run_at
           ) VALUES (%s, %s, 'workflow_c.analysis.semantic_metrics', 'queued', %s, %s, %s)""",
        (parent_job, project_id, parent_input_hash, f"metric-parent:{parent_job}", now),
    )
    _insert_metric_job(
        connection,
        project_id=project_id,
        job_id=child_job,
        task_hash=task_hash,
        idempotency_key=f"metric-child:{child_job}",
        status="running",
        lease_token=lease_token,
        now=now,
    )
    connection.execute("SET LOCAL session_replication_role = replica")
    connection.execute(
        """INSERT INTO workflow_c_metric_judge_batches(
               id, project_id, parent_job_id, run_id, observation_id, ordinal,
               planned_batch_count, plans_hash, parent_input_hash, input_set_hash,
               metric_suite_hash, status, aggregate_version, created_at
           ) VALUES (%s, %s, %s, %s, %s, 1, 1, %s, %s, %s, %s, 'queued', 1, %s)""",
        (
            batch_id,
            project_id,
            parent_job,
            uuid4(),
            uuid4(),
            _hash(f"plans:{batch_id}"),
            parent_input_hash,
            _hash(f"input-set:{batch_id}"),
            _hash(f"metric-suite:{batch_id}"),
            now,
        ),
    )
    _insert_metric_child(
        connection,
        project_id=project_id,
        parent_job_id=parent_job,
        child_job_id=child_job,
        batch_id=batch_id,
        ordinal=1,
        task_hash=task_hash,
        parent_input_hash=parent_input_hash,
        status="running",
        now=now,
    )
    sibling_job_id: UUID | None = None
    if sibling_count:
        sibling_job_id = uuid4()
        _insert_metric_job(
            connection,
            project_id=project_id,
            job_id=sibling_job_id,
            task_hash=_hash(f"metric-task:{sibling_job_id}"),
            idempotency_key=f"metric-child:{sibling_job_id}",
            status="queued",
            lease_token=None,
            now=now,
        )
        _insert_metric_child(
            connection,
            project_id=project_id,
            parent_job_id=parent_job,
            child_job_id=sibling_job_id,
            batch_id=batch_id,
            ordinal=2,
            task_hash=_hash(f"metric-task:{sibling_job_id}"),
            parent_input_hash=parent_input_hash,
            status="queued",
            now=now,
        )
    running_sibling_job_id: UUID | None = None
    running_sibling_lease_token: UUID | None = None
    if running_sibling:
        running_sibling_job_id, running_sibling_lease_token = uuid4(), uuid4()
        _insert_metric_job(
            connection,
            project_id=project_id,
            job_id=running_sibling_job_id,
            task_hash=_hash(f"metric-task:{running_sibling_job_id}"),
            idempotency_key=f"metric-child:{running_sibling_job_id}",
            status="running",
            lease_token=running_sibling_lease_token,
            now=now,
        )
        _insert_metric_child(
            connection,
            project_id=project_id,
            parent_job_id=parent_job,
            child_job_id=running_sibling_job_id,
            batch_id=batch_id,
            ordinal=3,
            task_hash=_hash(f"metric-task:{running_sibling_job_id}"),
            parent_input_hash=parent_input_hash,
            status="running",
            now=now,
        )
    return {
        "batch_id": batch_id,
        "child_job_id": child_job,
        "lease_token": lease_token,
        "sibling_job_id": sibling_job_id,
        "running_sibling_job_id": running_sibling_job_id,
        "running_sibling_lease_token": running_sibling_lease_token,
    }


def _insert_metric_job(
    connection: psycopg.Connection,
    *,
    project_id: UUID,
    job_id: UUID,
    task_hash: str,
    idempotency_key: str,
    status: str,
    lease_token: UUID | None,
    now: datetime,
) -> None:
    connection.execute(
        """INSERT INTO durable_jobs(
               id, project_id, kind, status, input_hash, idempotency_key, next_run_at,
               lease_owner, lease_token, lease_expires_at, heartbeat_at, fencing_generation,
               attempt_count, max_attempts
           ) VALUES (%s, %s, 'workflow_c.metric_judge', %s, %s, %s, %s,
                     %s, %s, %s, %s, %s, %s, 3)""",
        (
            job_id,
            project_id,
            status,
            task_hash,
            idempotency_key,
            now,
            "metric-worker" if lease_token is not None else None,
            lease_token,
            now + timedelta(hours=1) if lease_token is not None else None,
            now if lease_token is not None else None,
            1 if lease_token is not None else 0,
            1 if lease_token is not None else 0,
        ),
    )


def _insert_metric_child(
    connection: psycopg.Connection,
    *,
    project_id: UUID,
    parent_job_id: UUID,
    child_job_id: UUID,
    batch_id: UUID,
    ordinal: int,
    task_hash: str,
    parent_input_hash: str,
    status: str,
    now: datetime,
) -> None:
    runtime_option_id = uuid4()
    connection.execute(
        """INSERT INTO workflow_c_metric_model_children(
               project_id, parent_job_id, child_job_id, batch_id, role, ordinal,
               evaluator_id, candidate_id, parent_input_hash, runtime_selection_id,
               runtime_manifest_id, runtime_manifest_hash, runtime_option_id,
               runtime_option_hash, prompt_binding_id, prompt_binding_version,
               prompt_frozen_state_id, prompt_state_version, prompt_release_id,
               prompt_release_version, prompt_release_hash, prompt_purpose,
               prompt_bundle_hash, portable_output_schema_hash,
               application_output_schema_hash, task_ciphertext, task_data_nonce,
               task_wrapped_data_key, task_wrap_nonce, task_master_key_version,
               task_algorithm, task_hash, status, created_at
           ) VALUES (%s, %s, %s, %s, 'metric_judge', %s, %s, %s, %s,
                     %s, %s, %s, %s, %s, %s, 1, %s, 1, %s, 1, %s, 'metric_judge',
                     %s, %s, %s, %s, %s, %s, %s, 1, 'AES-256-GCM', %s, %s, %s)""",
        (
            project_id,
            parent_job_id,
            child_job_id,
            batch_id,
            ordinal,
            f"fixture-judge-{ordinal}",
            uuid4(),
            parent_input_hash,
            runtime_option_id,
            uuid4(),
            _hash(f"runtime-manifest:{child_job_id}"),
            runtime_option_id,
            _hash(f"runtime-option:{child_job_id}"),
            uuid4(),
            uuid4(),
            uuid4(),
            _hash(f"prompt-release:{child_job_id}"),
            _hash(f"prompt-bundle:{child_job_id}"),
            _hash(f"portable-schema:{child_job_id}"),
            _hash(f"application-schema:{child_job_id}"),
            b"fixture-ciphertext",
            b"a" * 12,
            b"fixture-wrapped-key",
            b"b" * 12,
            task_hash,
            status,
            now,
        ),
    )


def _lease(project_id: UUID, values: dict[str, UUID | None]) -> WorkerLease:
    child_job_id, lease_token = values["child_job_id"], values["lease_token"]
    assert child_job_id is not None and lease_token is not None
    return WorkerLease(
        job_id=child_job_id,
        project_id=project_id,
        kind="workflow_c.metric_judge",
        worker_id="metric-reconcile",
        lease_token=lease_token,
        fencing_generation=1,
        attempt_count=1,
        max_attempts=3,
    )


def _running_sibling_lease(project_id: UUID, values: dict[str, UUID | None]) -> WorkerLease:
    child_job_id = values["running_sibling_job_id"]
    lease_token = values["running_sibling_lease_token"]
    assert child_job_id is not None and lease_token is not None
    return WorkerLease(
        job_id=child_job_id,
        project_id=project_id,
        kind="workflow_c.metric_judge",
        worker_id="metric-reconcile-running-sibling",
        lease_token=lease_token,
        fencing_generation=1,
        attempt_count=1,
        max_attempts=3,
    )


def _assert_metric_state(
    database_url: str,
    *,
    batch_id: UUID | None,
    child_job_id: UUID | None,
    expected_child: tuple[str, str],
    expected_batch: tuple[str, int],
    expected_job: str,
) -> None:
    assert batch_id is not None and child_job_id is not None
    with psycopg.connect(database_url) as admin:
        child_row = admin.execute(
            """SELECT status, error_code FROM workflow_c_metric_model_children
                  WHERE child_job_id = %s""",
            (child_job_id,),
        ).fetchone()
        batch_row = admin.execute(
            """SELECT status, aggregate_version FROM workflow_c_metric_judge_batches
                  WHERE id = %s""",
            (batch_id,),
        ).fetchone()
        job_row = admin.execute("SELECT status FROM durable_jobs WHERE id = %s", (child_job_id,)).fetchone()
    assert child_row == expected_child
    assert batch_row == expected_batch
    assert job_row == (expected_job,)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _database_url(base: str, database_name: str) -> str:
    parsed = urlsplit(base)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database_name}", "", ""))
