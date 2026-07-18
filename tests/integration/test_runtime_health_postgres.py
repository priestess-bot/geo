from __future__ import annotations

import os
from uuid import UUID, uuid4

import psycopg
import pytest

from geo_core.runtime_health import RuntimeHealthRepository, RuntimeHealthThresholds


ADMIN_URL = os.getenv("GEO_ACCESS_TEST_ADMIN_DATABASE_URL", "").strip()
WORKER_URL = os.getenv("GEO_ACCEPTANCE_TEST_WORKER_DATABASE_URL", "").strip()
APP_URL = os.getenv("GEO_ACCEPTANCE_TEST_APP_DATABASE_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (ADMIN_URL and WORKER_URL and APP_URL),
        reason=(
            "GEO_ACCESS_TEST_ADMIN_DATABASE_URL, GEO_ACCEPTANCE_TEST_WORKER_DATABASE_URL, "
            "and GEO_ACCEPTANCE_TEST_APP_DATABASE_URL are required"
        ),
    ),
]


def _record_ready(
    repository: RuntimeHealthRepository, *, container_id: str, instance: str = "worker-1"
) -> None:
    repository.record_heartbeat(
        service_type="task_worker",
        container_id=container_id,
        instance_id=f"{container_id}:{instance}",
        release_version="integration-release",
        status="ready",
    )


def test_runtime_heartbeat_is_worker_only_and_staleness_is_real() -> None:
    container_id = f"runtime-health-{uuid4().hex}"
    repository = RuntimeHealthRepository(lambda: psycopg.connect(WORKER_URL))
    try:
        _record_ready(repository, container_id=container_id)
        findings = repository.findings(
            service_type="task_worker",
            container_id=container_id,
            expected_instances=1,
            thresholds=RuntimeHealthThresholds(),
        )
        assert not [item for item in findings if item.category == "runtime_heartbeat"]

        with psycopg.connect(ADMIN_URL) as admin:
            security = admin.execute(
                """SELECT relrowsecurity, relforcerowsecurity
                   FROM pg_class WHERE oid = 'runtime_service_heartbeats'::regclass"""
            ).fetchone()
            assert security == (True, True)
            admin.execute(
                """UPDATE runtime_service_heartbeats
                   SET last_heartbeat_at = clock_timestamp() - interval '31 seconds'
                   WHERE service_type = 'task_worker' AND container_id = %s""",
                (container_id,),
            )

        findings = repository.findings(
            service_type="task_worker",
            container_id=container_id,
            expected_instances=1,
            thresholds=RuntimeHealthThresholds(),
        )
        assert [item.code for item in findings if item.category == "runtime_heartbeat"] == [
            "runtime_heartbeat_stale"
        ]

        with psycopg.connect(WORKER_URL) as worker:
            privileges = worker.execute(
                """SELECT
                       has_table_privilege(current_user, 'runtime_service_heartbeats', 'SELECT'),
                       has_function_privilege(
                         current_user,
                         'geo_worker_record_runtime_heartbeat(text,text,text,text,text)',
                         'EXECUTE'
                       )"""
            ).fetchone()
            assert privileges == (False, True)

        with psycopg.connect(APP_URL) as app:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                app.execute(
                    "SELECT geo_worker_record_runtime_heartbeat(%s, %s, %s, %s, %s)",
                    ("task_worker", container_id, "forbidden", "release", "ready"),
                )
    finally:
        with psycopg.connect(ADMIN_URL) as admin:
            admin.execute(
                "DELETE FROM runtime_service_heartbeats WHERE container_id = %s",
                (container_id,),
            )


def test_expected_worker_instance_count_detects_one_dead_process_and_allows_replacement() -> None:
    container_id = f"runtime-processes-{uuid4().hex}"
    repository = RuntimeHealthRepository(lambda: psycopg.connect(WORKER_URL))
    try:
        _record_ready(repository, container_id=container_id, instance="worker-1")
        findings = repository.findings(
            service_type="task_worker",
            container_id=container_id,
            expected_instances=2,
            thresholds=RuntimeHealthThresholds(),
        )
        assert [item.code for item in findings if item.category == "runtime_heartbeat"] == [
            "runtime_heartbeat_missing"
        ]

        _record_ready(repository, container_id=container_id, instance="worker-2")
        assert not [
            item
            for item in repository.findings(
                service_type="task_worker",
                container_id=container_id,
                expected_instances=2,
                thresholds=RuntimeHealthThresholds(),
            )
            if item.category == "runtime_heartbeat"
        ]

        with psycopg.connect(ADMIN_URL) as admin:
            admin.execute(
                """UPDATE runtime_service_heartbeats
                   SET last_heartbeat_at = clock_timestamp() - interval '31 seconds'
                   WHERE service_type = 'task_worker' AND instance_id = %s""",
                (f"{container_id}:worker-1",),
            )
        findings = repository.findings(
            service_type="task_worker",
            container_id=container_id,
            expected_instances=2,
            thresholds=RuntimeHealthThresholds(),
        )
        assert [item.code for item in findings if item.category == "runtime_heartbeat"] == [
            "runtime_heartbeat_stale"
        ]

        _record_ready(repository, container_id=container_id, instance="worker-3")
        assert not [
            item
            for item in repository.findings(
                service_type="task_worker",
                container_id=container_id,
                expected_instances=2,
                thresholds=RuntimeHealthThresholds(),
            )
            if item.category == "runtime_heartbeat"
        ]

        repository.record_heartbeat(
            service_type="task_worker",
            container_id=container_id,
            instance_id=f"{container_id}:worker-3",
            release_version="integration-release",
            status="stopping",
        )
        findings = repository.findings(
            service_type="task_worker",
            container_id=container_id,
            expected_instances=2,
            thresholds=RuntimeHealthThresholds(),
        )
        assert [item.code for item in findings if item.category == "runtime_heartbeat"] == [
            "runtime_heartbeat_not_ready"
        ]
    finally:
        with psycopg.connect(ADMIN_URL) as admin:
            admin.execute(
                "DELETE FROM runtime_service_heartbeats WHERE container_id = %s",
                (container_id,),
            )


def test_runtime_findings_classify_every_required_queue_state_without_sensitive_data() -> None:
    tenant_id, project_id = uuid4(), uuid4()
    container_id = f"runtime-fixtures-{uuid4().hex}"
    jobs: dict[str, UUID] = {
        name: uuid4()
        for name in ("queued", "retry_wait", "running", "finalizing", "failed", "dead_lettered")
    }
    repository = RuntimeHealthRepository(lambda: psycopg.connect(WORKER_URL))
    try:
        with psycopg.connect(ADMIN_URL) as admin:
            admin.execute(
                "INSERT INTO tenants(id, name) VALUES (%s, %s)",
                (tenant_id, f"Runtime health {tenant_id}"),
            )
            admin.execute(
                "INSERT INTO projects(id, tenant_id, name) VALUES (%s, %s, %s)",
                (project_id, tenant_id, f"Runtime health {project_id}"),
            )
            for name in ("queued", "retry_wait"):
                admin.execute(
                    """INSERT INTO durable_jobs
                         (id, project_id, kind, status, input_hash, idempotency_key,
                          next_run_at, created_at, updated_at)
                       VALUES (%s, %s, 'runtime.fixture', %s, %s, %s,
                               clock_timestamp() - interval '601 seconds',
                               clock_timestamp() - interval '601 seconds',
                               clock_timestamp() - interval '601 seconds')""",
                    (jobs[name], project_id, name, "a" * 64, f"runtime-{name}-{jobs[name]}"),
                )
            for name, expired in (("running", 1), ("finalizing", 61)):
                admin.execute(
                    """INSERT INTO durable_jobs
                         (id, project_id, kind, status, input_hash, idempotency_key,
                          lease_owner, lease_token, lease_expires_at, heartbeat_at)
                       VALUES (%s, %s, 'runtime.fixture', %s, %s, %s,
                               'fixture-worker', %s,
                               clock_timestamp() - make_interval(secs => %s),
                               clock_timestamp() - make_interval(secs => %s))""",
                    (
                        jobs[name],
                        project_id,
                        name,
                        "b" * 64,
                        f"runtime-{name}-{jobs[name]}",
                        uuid4(),
                        expired,
                        expired,
                    ),
                )
            for name in ("failed", "dead_lettered"):
                admin.execute(
                    """INSERT INTO durable_jobs
                         (id, project_id, kind, status, input_hash, idempotency_key,
                          error_code, error_detail, completed_at)
                       VALUES (%s, %s, 'runtime.fixture', %s, %s, %s,
                               'private-error-code', %s::jsonb, clock_timestamp())""",
                    (
                        jobs[name],
                        project_id,
                        name,
                        "c" * 64,
                        f"runtime-{name}-{jobs[name]}",
                        '{"secret":"must-not-leak"}',
                    ),
                )
            admin.execute(
                """INSERT INTO broker_outbox
                     (project_id, job_id, topic, payload, idempotency_key,
                      available_at, created_at, last_error)
                   VALUES (%s, %s, 'runtime.fixture', %s::jsonb, %s,
                           clock_timestamp() - interval '301 seconds',
                           clock_timestamp() - interval '301 seconds', %s)""",
                (
                    project_id,
                    jobs["queued"],
                    '{"secret":"outbox-payload-must-not-leak"}',
                    f"runtime-outbox-{jobs['queued']}",
                    "outbox-error-must-not-leak",
                ),
            )
            admin.execute("SET LOCAL enable_seqscan = off")
            plan = "\n".join(
                row[0]
                for row in admin.execute(
                    """EXPLAIN (COSTS OFF)
                       SELECT id FROM durable_jobs
                       WHERE status IN ('failed', 'dead_lettered')
                         AND COALESCE(completed_at, updated_at)
                             >= clock_timestamp() - interval '24 hours'"""
                ).fetchall()
            )
            assert "durable_jobs_runtime_terminal_idx" in plan
        _record_ready(repository, container_id=container_id)

        project_findings = [
            item
            for item in repository.findings(
                service_type="task_worker",
                container_id=container_id,
                expected_instances=1,
                thresholds=RuntimeHealthThresholds(),
            )
            if item.project_id == project_id
        ]
        assert {item.code for item in project_findings} == {
            "durable_job_queued_stalled",
            "durable_job_retry_stalled",
            "durable_job_running_lease_expired",
            "durable_job_finalizing_recovery_overdue",
            "broker_outbox_delivery_stalled",
            "durable_job_terminal_failed",
            "durable_job_dead_lettered",
        }
        rendered = repr([item.public_dict() for item in project_findings])
        assert "must-not-leak" not in rendered
        assert "private-error-code" not in rendered
    finally:
        with psycopg.connect(ADMIN_URL) as admin:
            admin.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))
            admin.execute(
                "DELETE FROM runtime_service_heartbeats WHERE container_id = %s",
                (container_id,),
            )
