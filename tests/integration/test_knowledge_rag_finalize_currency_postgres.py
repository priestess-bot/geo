from __future__ import annotations

from collections.abc import Callable
import os
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
import pytest

from geo_core.knowledge import KnowledgeApplication
from tests.integration.placement_worker_support import cleanup_projects, login_url, seed_project
from tests.integration.test_knowledge_rag_postgres import (
    TraceableGateway,
    _dispatcher,
    _principal,
    _process_source,
    _source,
)


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()
MINIO_ENDPOINT = os.getenv("GEO_F019_TEST_MINIO_ENDPOINT", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
    pytest.mark.skipif(not MINIO_ENDPOINT, reason="GEO_F019_TEST_MINIO_ENDPOINT is required"),
]


class LifecycleMutatingGateway(TraceableGateway):
    def __init__(self, mutate: Callable[[], None]) -> None:
        self._mutate = mutate
        self._mutated = False

    def generate(self, request: Any, *, policy: Any, budget: Any):
        result = super().generate(request, policy=policy, budget=budget)
        if not self._mutated:
            self._mutate()
            self._mutated = True
        return result


@pytest.mark.parametrize(
    ("lifecycle_change", "expected_status"),
    (("disable_chunk", "failed"), ("archive_source", "cancelled")),
)
def test_rag_finalize_rejects_claim_when_loaded_content_is_no_longer_current(
    lifecycle_change: str, expected_status: str
) -> None:
    suffix = uuid4().hex[:10]
    app_login = f"geo_rag_currency_app_{suffix}"
    worker_login = f"geo_rag_currency_worker_{suffix}"
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
        project = seed_project(admin, suffix=f"rag-currency-{suffix}")
        admin.commit()

    app_url = login_url(ADMIN_URL, user=app_login, password=app_password)
    worker_url = login_url(ADMIN_URL, user=worker_login, password=worker_password)
    principal = _principal(project, suffix)
    application = KnowledgeApplication(app_url)
    dispatcher = _dispatcher(worker_url, suffix)
    try:
        baseline = application.create_source(
            principal,
            project_id=project["project"],
            source=_source("每分钟 2 升"),
            idempotency_key=f"rag-currency-baseline-{suffix}",
        )
        baseline_ids = _process_source(dispatcher, baseline, project["project"])
        with psycopg.connect(ADMIN_URL) as admin:
            baseline_revision_id = admin.execute(
                """SELECT id FROM knowledge_rag_revisions
                   WHERE project_id = %s AND pipeline_run_id = %s
                     AND lifecycle_status = 'active'""",
                (project["project"], baseline_ids["run_id"]),
            ).fetchone()[0]

        if lifecycle_change == "disable_chunk":
            candidate = application.reprocess_source(
                principal,
                project_id=project["project"],
                source_id=baseline_ids["source_id"],
                idempotency_key=f"rag-currency-reprocess-{suffix}",
            )
        else:
            candidate = application.create_source_revision(
                principal,
                project_id=project["project"],
                source_id=baseline_ids["source_id"],
                source=_source("每分钟 3 升"),
                idempotency_key=f"rag-currency-revision-{suffix}",
            )
        processed = dispatcher.process(job_id=candidate["job"]["id"], project_id=project["project"])
        assert processed["status"] == "succeeded", processed
        candidate_run_id = candidate["pipeline_run"]["id"]
        candidate_source_id = candidate["source"]["id"]
        with psycopg.connect(ADMIN_URL) as admin:
            candidate_chunk_id = admin.execute(
                """SELECT id FROM knowledge_chunks
                   WHERE project_id = %s AND pipeline_run_id = %s
                   ORDER BY chunk_index LIMIT 1""",
                (project["project"], candidate_run_id),
            ).fetchone()[0]

        def mutate() -> None:
            if lifecycle_change == "disable_chunk":
                application.disable_chunk(
                    principal,
                    project_id=project["project"],
                    chunk_id=candidate_chunk_id,
                )
                return
            _archive_without_job_cancellation(
                project_id=project["project"], source_id=candidate_source_id
            )

        mutating_dispatcher = _dispatcher(
            worker_url, suffix, gateway=LifecycleMutatingGateway(mutate)
        )
        result = mutating_dispatcher.process(
            job_id=UUID(str(processed["rag_job_id"])), project_id=project["project"]
        )
        assert result["status"] == expected_status, result
        _assert_previous_activation_unchanged(
            project_id=project["project"],
            baseline_run_id=baseline_ids["run_id"],
            baseline_revision_id=baseline_revision_id,
            rejected_run_id=candidate_run_id,
        )
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


def _archive_without_job_cancellation(*, project_id: UUID, source_id: UUID) -> None:
    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute(
            """UPDATE knowledge_fact_candidates
               SET lifecycle_status = 'withdrawn', updated_at = clock_timestamp()
               WHERE project_id = %s AND source_id = %s
                 AND lifecycle_status = 'active'""",
            (project_id, source_id),
        )
        admin.execute(
            """UPDATE knowledge_chunks SET status = 'disabled',
                      updated_at = clock_timestamp()
               WHERE project_id = %s AND source_id = %s AND status = 'active'""",
            (project_id, source_id),
        )
        admin.execute(
            """UPDATE knowledge_sources SET status = 'archived',
                      updated_at = clock_timestamp()
               WHERE project_id = %s AND id = %s""",
            (project_id, source_id),
        )
        admin.commit()


def _assert_previous_activation_unchanged(
    *,
    project_id: UUID,
    baseline_run_id: UUID,
    baseline_revision_id: UUID,
    rejected_run_id: UUID,
) -> None:
    with psycopg.connect(ADMIN_URL) as admin:
        assert (
            admin.execute(
                """SELECT lifecycle_status FROM knowledge_rag_revisions
               WHERE project_id = %s AND id = %s""",
                (project_id, baseline_revision_id),
            ).fetchone()[0]
            == "active"
        )
        assert (
            admin.execute(
                """SELECT bool_and(status = 'active') FROM knowledge_chunks
                   WHERE project_id = %s AND pipeline_run_id = %s""",
                (project_id, baseline_run_id),
            ).fetchone()[0]
            is True
        )
        assert (
            admin.execute(
                """SELECT bool_and(lifecycle_status = 'active')
                   FROM knowledge_fact_candidates
                   WHERE project_id = %s AND rag_revision_id = %s""",
                (project_id, baseline_revision_id),
            ).fetchone()[0]
            is True
        )
        assert (
            admin.execute(
                """SELECT count(*) FROM knowledge_rag_revisions
                   WHERE project_id = %s AND pipeline_run_id = %s""",
                (project_id, rejected_run_id),
            ).fetchone()[0]
            == 0
        )
