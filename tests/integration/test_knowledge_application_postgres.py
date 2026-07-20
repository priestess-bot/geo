from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from threading import Barrier
import time
from typing import Any, Mapping
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
import pytest

from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.knowledge import KnowledgeApplication
from geo_core.knowledge.domain import KnowledgeConflict, SourceInput
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


class _SlowCommitKnowledgeApplication(KnowledgeApplication):
    def _creation_result(
        self, connection: Any, project_id: UUID, source_id: UUID, run_id: UUID
    ) -> Mapping[str, object]:
        result = super()._creation_result(connection, project_id, source_id, run_id)
        # Keep the winning transaction open so the competing request overlaps it.
        time.sleep(0.25)
        return result


def test_create_source_serializes_concurrent_idempotent_requests() -> None:
    suffix = uuid4().hex[:10]
    app_login = f"geo_knowledge_app_{suffix}"
    app_password = uuid4().hex
    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                sql.Identifier(app_login), sql.Literal(app_password)
            )
        )
        project = seed_project(admin, suffix=f"knowledge-idempotency-{suffix}")
        admin.commit()

    application = _SlowCommitKnowledgeApplication(
        login_url(ADMIN_URL, user=app_login, password=app_password)
    )
    principal = _principal(project, suffix)
    try:
        key = f"knowledge-source-{suffix}"
        source = _source("Concurrent source")
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    _create_after_barrier,
                    application,
                    principal,
                    project["project"],
                    source,
                    key,
                    barrier,
                )
                for _ in range(2)
            ]
            results = [future.result(timeout=15) for future in futures]

        assert len({_result_id(result, "source") for result in results}) == 1
        assert len({_result_id(result, "pipeline_run") for result in results}) == 1
        assert len({_result_id(result, "job") for result in results}) == 1

        conflict_key = f"knowledge-source-conflict-{suffix}"
        conflict_barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    _capture_create,
                    application,
                    principal,
                    project["project"],
                    candidate,
                    conflict_key,
                    conflict_barrier,
                )
                for candidate in (
                    _source("Concurrent payload A"),
                    _source("Concurrent payload B"),
                )
            ]
            outcomes = [future.result(timeout=15) for future in futures]

        assert sorted(outcome for outcome, _ in outcomes) == ["conflict", "created"]
        conflict = next(detail for outcome, detail in outcomes if outcome == "conflict")
        assert "different source content" in str(conflict)

        with psycopg.connect(ADMIN_URL) as admin:
            source_id = _result_id(results[0], "source")
            run_id = _result_id(results[0], "pipeline_run")
            job_id = _result_id(results[0], "job")
            counts = admin.execute(
                """SELECT
                     (SELECT count(*) FROM knowledge_sources WHERE id = %s) AS sources,
                     (SELECT count(*) FROM knowledge_pipeline_runs WHERE id = %s) AS runs,
                     (SELECT count(*) FROM durable_jobs WHERE id = %s) AS jobs,
                     (SELECT count(*) FROM knowledge_pipeline_stages
                       WHERE pipeline_run_id = %s) AS stages""",
                (source_id, run_id, job_id, run_id),
            ).fetchone()
            assert counts == (1, 1, 1, 6)
    finally:
        with psycopg.connect(ADMIN_URL) as admin:
            cleanup_projects(
                admin,
                projects=[project],
                tenant_ids=[project["tenant"]],
                app_login=app_login,
            )
            admin.commit()


def test_review_fact_requires_active_chunk_for_approval_but_allows_rejection() -> None:
    suffix = uuid4().hex[:10]
    app_login = f"geo_knowledge_app_{suffix}"
    app_password = uuid4().hex
    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                sql.Identifier(app_login), sql.Literal(app_password)
            )
        )
        project = seed_project(admin, suffix=f"knowledge-review-{suffix}")
        lineage = _seed_review_chain(admin, project)
        admin.commit()

    application = KnowledgeApplication(login_url(ADMIN_URL, user=app_login, password=app_password))
    principal = _principal(project, suffix)
    try:
        approved = application.review_fact(
            principal,
            project_id=project["project"],
            fact_id=lineage["active_fact"],
            decision="approved",
            notes="active chunk review",
        )
        assert approved["status"] == "approved"

        application.disable_chunk(
            principal,
            project_id=project["project"],
            chunk_id=lineage["chunk"],
        )
        with pytest.raises(KnowledgeConflict, match="disabled chunk"):
            application.review_fact(
                principal,
                project_id=project["project"],
                fact_id=lineage["disabled_fact"],
                decision="approved",
                notes="must fail closed",
            )

        rejected = application.review_fact(
            principal,
            project_id=project["project"],
            fact_id=lineage["disabled_fact"],
            decision="rejected",
            notes="reject disabled content",
        )
        assert rejected["status"] == "rejected"
        with psycopg.connect(ADMIN_URL) as admin:
            stored = admin.execute(
                """SELECT status, reviewed_by, review_notes, reviewed_at IS NOT NULL
                   FROM knowledge_fact_candidates WHERE id = %s""",
                (lineage["disabled_fact"],),
            ).fetchone()
            assert stored == (
                "rejected",
                project["owner"],
                "reject disabled content",
                True,
            )
    finally:
        with psycopg.connect(ADMIN_URL) as admin:
            cleanup_projects(
                admin,
                projects=[project],
                tenant_ids=[project["tenant"]],
                app_login=app_login,
            )
            admin.commit()


def _create_after_barrier(
    application: KnowledgeApplication,
    principal: AccessPrincipal,
    project_id: UUID,
    source: SourceInput,
    idempotency_key: str,
    barrier: Barrier,
) -> Mapping[str, object]:
    barrier.wait(timeout=10)
    return application.create_source(
        principal,
        project_id=project_id,
        source=source,
        idempotency_key=idempotency_key,
    )


def _capture_create(
    application: KnowledgeApplication,
    principal: AccessPrincipal,
    project_id: UUID,
    source: SourceInput,
    idempotency_key: str,
    barrier: Barrier,
) -> tuple[str, object]:
    try:
        return (
            "created",
            _create_after_barrier(
                application,
                principal,
                project_id,
                source,
                idempotency_key,
                barrier,
            ),
        )
    except KnowledgeConflict as error:
        return "conflict", error


def _result_id(result: Mapping[str, object], key: str) -> object:
    nested = result[key]
    assert isinstance(nested, Mapping)
    return nested["id"]


def _source(title: str) -> SourceInput:
    return SourceInput(
        source_kind="text",
        title=title,
        source_url=None,
        filename=None,
        media_type="text/plain",
        raw_content=b"Governed source content",
    )


def _principal(project: Mapping[str, UUID], suffix: str) -> AccessPrincipal:
    return AccessPrincipal(
        identity_id=project["owner"],
        actor_id=f"knowledge-application-{suffix}",
        tenant_id=project["tenant"],
        memberships=(MembershipRecord(project["project"], project["tenant"], "admin"),),
        auth_method="development",
    )


def _seed_review_chain(
    connection: psycopg.Connection[Any], project: Mapping[str, UUID]
) -> dict[str, UUID]:
    ids = {
        name: uuid4()
        for name in (
            "source",
            "run",
            "document",
            "chunk",
            "active_fact",
            "disabled_fact",
        )
    }
    content = "Governed source content"
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    connection.execute(
        """INSERT INTO knowledge_sources
             (id, project_id, logical_source_id, source_kind, title, media_type,
              status, raw_content, content_hash, created_by)
           VALUES (%s, %s, %s, 'text', 'Review source', 'text/plain', 'ready',
                   %s, %s, %s)""",
        (
            ids["source"],
            project["project"],
            ids["source"],
            content.encode(),
            content_hash,
            project["owner"],
        ),
    )
    connection.execute(
        """INSERT INTO knowledge_pipeline_runs
             (id, project_id, source_id, status, input_hash, created_by, completed_at)
           VALUES (%s, %s, %s, 'succeeded', %s, %s, clock_timestamp())""",
        (
            ids["run"],
            project["project"],
            ids["source"],
            "1" * 64,
            project["owner"],
        ),
    )
    connection.execute(
        """INSERT INTO knowledge_documents
             (id, project_id, pipeline_run_id, source_id, parser_version, raw_text,
              cleaned_text, raw_text_hash, cleaned_text_hash)
           VALUES (%s, %s, %s, %s, 'test-v1', %s, %s, %s, %s)""",
        (
            ids["document"],
            project["project"],
            ids["run"],
            ids["source"],
            content,
            content,
            content_hash,
            content_hash,
        ),
    )
    connection.execute(
        """INSERT INTO knowledge_chunks
             (id, project_id, pipeline_run_id, source_id, document_id, chunk_index,
              text, text_hash, char_count)
           VALUES (%s, %s, %s, %s, %s, 0, %s, %s, %s)""",
        (
            ids["chunk"],
            project["project"],
            ids["run"],
            ids["source"],
            ids["document"],
            content,
            content_hash,
            len(content),
        ),
    )
    for fact_id, statement in (
        (ids["active_fact"], "Active chunk fact."),
        (ids["disabled_fact"], "Disabled chunk fact."),
    ):
        connection.execute(
            """INSERT INTO knowledge_fact_candidates
                 (id, project_id, pipeline_run_id, source_id, document_id, chunk_id,
                  statement, statement_hash)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                fact_id,
                project["project"],
                ids["run"],
                ids["source"],
                ids["document"],
                ids["chunk"],
                statement,
                hashlib.sha256(statement.lower().encode()).hexdigest(),
            ),
        )
    return ids
