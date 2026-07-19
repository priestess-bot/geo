from __future__ import annotations

from datetime import timedelta
import os
from typing import Mapping, cast
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
import pytest

from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.knowledge import KnowledgeApplication
from geo_core.knowledge.domain import KnowledgeProcessingError, SourceInput
from geo_core.knowledge.worker import KnowledgeProcessHandler
from geo_core.placements.worker_composition import PlacementWorkerDispatcher
from tests.integration.placement_worker_support import (
    cleanup_projects,
    login_url,
    seed_project,
)


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_retryable_processing_failure_reaches_a_consistent_terminal_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:10]
    app_login = f"geo_knowledge_retry_app_{suffix}"
    worker_login = f"geo_knowledge_retry_worker_{suffix}"
    app_password, worker_password = uuid4().hex, uuid4().hex
    with psycopg.connect(ADMIN_URL) as admin:
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
        project = seed_project(admin, suffix=f"knowledge-retry-{suffix}")
        admin.commit()

    application = KnowledgeApplication(login_url(ADMIN_URL, user=app_login, password=app_password))
    principal = _principal(project, suffix)
    created = application.create_source(
        principal,
        project_id=project["project"],
        source=SourceInput(
            source_kind="text",
            title="Retry state source",
            source_url=None,
            filename="retry.txt",
            media_type="text/plain",
            raw_content=b"Temporary upstream failure fixture.",
        ),
        idempotency_key=f"knowledge-retry-{suffix}",
    )
    job_id = cast(UUID, cast(Mapping[str, object], created["job"])["id"])
    store = PostgresDurableJobStore(
        lambda: psycopg.connect(login_url(ADMIN_URL, user=worker_login, password=worker_password))
    )
    dispatcher = PlacementWorkerDispatcher(
        store=store,
        handlers={
            "knowledge.process": KnowledgeProcessHandler(store, lease_for=timedelta(seconds=30))
        },
        worker_id=f"knowledge-retry-{suffix}",
        lease_for=timedelta(seconds=30),
    )

    def fail_temporarily(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise KnowledgeProcessingError("temporary source outage", retryable=True)

    monkeypatch.setattr("geo_core.knowledge.worker.process_source", fail_temporarily)
    try:
        first = dispatcher.process(job_id=job_id, project_id=project["project"])
        assert first["status"] == "retry_wait"
        with psycopg.connect(ADMIN_URL) as admin:
            assert admin.execute(
                """SELECT job.status, run.status, source.status,
                          array_agg(DISTINCT stage.status ORDER BY stage.status)
                   FROM durable_jobs job
                   JOIN knowledge_job_specs spec
                     ON spec.job_id = job.id AND spec.project_id = job.project_id
                   JOIN knowledge_pipeline_runs run
                     ON run.id = spec.pipeline_run_id AND run.project_id = spec.project_id
                   JOIN knowledge_sources source
                     ON source.id = run.source_id AND source.project_id = run.project_id
                   JOIN knowledge_pipeline_stages stage
                     ON stage.pipeline_run_id = run.id AND stage.project_id = run.project_id
                   WHERE job.id = %s
                   GROUP BY job.status, run.status, source.status""",
                (job_id,),
            ).fetchone() == ("retry_wait", "queued", "processing", ["pending"])

        second = _make_due_and_process(dispatcher, job_id, project["project"])
        assert second["status"] == "retry_wait"
        final = _make_due_and_process(dispatcher, job_id, project["project"])
        assert final["status"] == "dead_lettered"
        with psycopg.connect(ADMIN_URL) as admin:
            assert admin.execute(
                """SELECT job.status, job.attempt_count, run.status, source.status,
                          array_agg(DISTINCT stage.status ORDER BY stage.status)
                   FROM durable_jobs job
                   JOIN knowledge_job_specs spec
                     ON spec.job_id = job.id AND spec.project_id = job.project_id
                   JOIN knowledge_pipeline_runs run
                     ON run.id = spec.pipeline_run_id AND run.project_id = spec.project_id
                   JOIN knowledge_sources source
                     ON source.id = run.source_id AND source.project_id = run.project_id
                   JOIN knowledge_pipeline_stages stage
                     ON stage.pipeline_run_id = run.id AND stage.project_id = run.project_id
                   WHERE job.id = %s
                   GROUP BY job.status, job.attempt_count, run.status, source.status""",
                (job_id,),
            ).fetchone() == ("dead_lettered", 3, "failed", "failed", ["failed", "skipped"])
    finally:
        with psycopg.connect(ADMIN_URL) as admin:
            cleanup_projects(
                admin,
                projects=[project],
                tenant_ids=[project["tenant"]],
                app_login=app_login,
                worker_login=worker_login,
            )
            admin.commit()


def test_expired_lease_attempt_budget_reconciles_knowledge_terminal_state() -> None:
    suffix = uuid4().hex[:10]
    app_login = f"geo_knowledge_crash_app_{suffix}"
    worker_login = f"geo_knowledge_crash_worker_{suffix}"
    app_password, worker_password = uuid4().hex, uuid4().hex
    with psycopg.connect(ADMIN_URL) as admin:
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
        project = seed_project(admin, suffix=f"knowledge-crash-{suffix}")
        admin.commit()

    application = KnowledgeApplication(login_url(ADMIN_URL, user=app_login, password=app_password))
    principal = _principal(project, suffix)
    created = application.create_source(
        principal,
        project_id=project["project"],
        source=SourceInput(
            source_kind="text",
            title="Crashed lease source",
            source_url=None,
            filename="crash.txt",
            media_type="text/plain",
            raw_content=b"Worker crash state fixture.",
        ),
        idempotency_key=f"knowledge-crash-{suffix}",
    )
    job_id = cast(UUID, cast(Mapping[str, object], created["job"])["id"])
    worker_url = login_url(ADMIN_URL, user=worker_login, password=worker_password)
    store = PostgresDurableJobStore(lambda: psycopg.connect(worker_url))
    handler = KnowledgeProcessHandler(store, lease_for=timedelta(seconds=30))
    dispatcher = PlacementWorkerDispatcher(
        store=store,
        handlers={"knowledge.process": handler},
        worker_id=f"knowledge-reclaimer-{suffix}",
        lease_for=timedelta(seconds=30),
    )
    try:
        with psycopg.connect(ADMIN_URL) as admin:
            admin.execute("UPDATE durable_jobs SET max_attempts = 1 WHERE id = %s", (job_id,))
            admin.commit()
        claimed = store.claim(
            job_id=job_id,
            project_id=project["project"],
            expected_kind="knowledge.process",
            worker_id=f"crashed-worker-{suffix}",
            lease_for=timedelta(seconds=30),
        )
        assert claimed.lease is not None
        handler._load(claimed.lease)
        with psycopg.connect(ADMIN_URL) as admin:
            admin.execute(
                """UPDATE durable_jobs
                   SET lease_expires_at = clock_timestamp() - interval '1 second'
                   WHERE id = %s""",
                (job_id,),
            )
            admin.commit()

        result = dispatcher.process(job_id=job_id, project_id=project["project"])
        assert result["status"] == "dead_lettered"
        with psycopg.connect(ADMIN_URL) as admin:
            assert admin.execute(
                """SELECT job.status, run.status, source.status,
                          array_agg(DISTINCT stage.status ORDER BY stage.status)
                   FROM durable_jobs job
                   JOIN knowledge_job_specs spec
                     ON spec.job_id = job.id AND spec.project_id = job.project_id
                   JOIN knowledge_pipeline_runs run
                     ON run.id = spec.pipeline_run_id AND run.project_id = spec.project_id
                   JOIN knowledge_sources source
                     ON source.id = run.source_id AND source.project_id = run.project_id
                   JOIN knowledge_pipeline_stages stage
                     ON stage.pipeline_run_id = run.id AND stage.project_id = run.project_id
                   WHERE job.id = %s
                   GROUP BY job.status, run.status, source.status""",
                (job_id,),
            ).fetchone() == ("dead_lettered", "failed", "failed", ["failed", "skipped"])
    finally:
        with psycopg.connect(ADMIN_URL) as admin:
            cleanup_projects(
                admin,
                projects=[project],
                tenant_ids=[project["tenant"]],
                app_login=app_login,
                worker_login=worker_login,
            )
            admin.commit()


def _make_due_and_process(
    dispatcher: PlacementWorkerDispatcher, job_id: UUID, project_id: UUID
) -> dict[str, object]:
    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute(
            "UPDATE durable_jobs SET next_run_at = clock_timestamp() WHERE id = %s",
            (job_id,),
        )
        admin.commit()
    return dict(dispatcher.process(job_id=job_id, project_id=project_id))


def _principal(project: Mapping[str, UUID], suffix: str) -> AccessPrincipal:
    return AccessPrincipal(
        identity_id=project["owner"],
        actor_id=f"knowledge-retry-{suffix}",
        tenant_id=project["tenant"],
        memberships=(MembershipRecord(project["project"], project["tenant"], "admin"),),
        auth_method="development",
    )
