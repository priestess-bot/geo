from __future__ import annotations

from collections.abc import Callable
import os
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from geo_core.knowledge import KnowledgeApplication
from geo_core.knowledge.rag_domain import KnowledgeRagEnqueuePolicy
from tests.integration.placement_worker_support import cleanup_projects, login_url, seed_project
from tests.integration.test_knowledge_question_sets_postgres import (
    QuestionGateway,
    _dimensions,
    _question_dispatcher,
)
from tests.integration.test_knowledge_rag_postgres import (
    SELECTION,
    SELECTION_HASH,
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


class LifecycleMutatingQuestionGateway(QuestionGateway):
    def __init__(self, mutate: Callable[[], None]) -> None:
        self._mutate = mutate
        self.mutated = False

    def generate(self, request, *, policy, budget):
        result = super().generate(request, policy=policy, budget=budget)
        if not self.mutated:
            self._mutate()
            self.mutated = True
        return result


@pytest.mark.parametrize("lifecycle_change", ("disable_fact_chunk", "archive_entity_source"))
def test_question_finalize_rejects_frozen_inputs_that_expire_after_load(
    lifecycle_change: str,
) -> None:
    suffix = uuid4().hex[:10]
    app_login = f"geo_question_currency_app_{suffix}"
    worker_login = f"geo_question_currency_worker_{suffix}"
    app_password, worker_password = uuid4().hex, uuid4().hex
    campaign_id = uuid4()
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
        project = seed_project(admin, suffix=f"question-currency-{suffix}")
        admin.execute(
            """INSERT INTO geo_campaigns
                 (id, project_id, market_profile_id, primary_product_entity_id,
                  name, status, created_by)
               VALUES (%s, %s, %s, %s, %s, 'active', %s)""",
            (
                campaign_id,
                project["project"],
                project["market"],
                project["entity"],
                f"Question currency campaign {suffix}",
                project["owner"],
            ),
        )
        admin.commit()

    app_url = login_url(ADMIN_URL, user=app_login, password=app_password)
    worker_url = login_url(ADMIN_URL, user=worker_login, password=worker_password)
    principal = _principal(project, suffix)
    policy = KnowledgeRagEnqueuePolicy(
        adapter_release=SELECTION.adapter_release,
        selection_manifest_hash=SELECTION_HASH,
        configured_model="deepseek-v4-flash",
    )
    knowledge = KnowledgeApplication(app_url, question_policy=policy)
    try:
        fact_source = knowledge.create_source(
            principal,
            project_id=project["project"],
            source=_source("每分钟 2 升"),
            idempotency_key=f"question-currency-fact-{suffix}",
        )
        fact_source_ids = _process_source(
            _dispatcher(worker_url, suffix), fact_source, project["project"]
        )
        entity_source = knowledge.create_source(
            principal,
            project_id=project["project"],
            source=_source("每分钟 3 升"),
            idempotency_key=f"question-currency-entity-{suffix}",
        )
        entity_source_ids = _process_source(
            _dispatcher(worker_url, suffix), entity_source, project["project"]
        )

        fact = next(
            item
            for item in knowledge.list_facts(principal, project_id=project["project"])
            if item["pipeline_run_id"] == fact_source_ids["run_id"]
        )
        knowledge.review_fact(
            principal,
            project_id=project["project"],
            fact_id=fact["id"],
            decision="approved",
            notes="freeze Fact for question currency test",
        )
        with psycopg.connect(ADMIN_URL) as admin:
            entity_candidate_id = admin.execute(
                """SELECT id FROM knowledge_entity_candidates
                   WHERE project_id = %s AND pipeline_run_id = %s
                     AND lifecycle_status = 'active'
                   ORDER BY id LIMIT 1""",
                (project["project"], entity_source_ids["run_id"]),
            ).fetchone()[0]
        reviewed_entity = knowledge.review_rag_entity_candidate(
            principal,
            project_id=project["project"],
            candidate_id=entity_candidate_id,
            decision="approved",
            notes="freeze Entity for question currency test",
        )
        graph_entity_id = reviewed_entity["graph_entity_id"]

        created = knowledge.create_question_generation(
            principal,
            project_id=project["project"],
            campaign_id=campaign_id,
            dimensions=_dimensions(),
            fact_candidate_ids=(fact["id"],),
            graph_entity_ids=(graph_entity_id,),
            configured_model="deepseek-v4-flash",
            model_call_budget=10,
            semantic_duplicate_threshold=0.92,
            idempotency_key=f"question-currency-generation-{suffix}",
        )

        def mutate() -> None:
            if lifecycle_change == "disable_fact_chunk":
                knowledge.disable_chunk(
                    principal,
                    project_id=project["project"],
                    chunk_id=fact["chunk_id"],
                )
                return
            knowledge.archive_source(
                principal,
                project_id=project["project"],
                source_id=entity_source_ids["source_id"],
            )

        gateway = LifecycleMutatingQuestionGateway(mutate)
        result = _question_dispatcher(worker_url, suffix, gateway=gateway).process(
            job_id=created["job_id"], project_id=project["project"]
        )
        assert gateway.mutated is True
        assert result["status"] == "failed", result
        _assert_rejected_without_outputs(project_id=project["project"], job_id=created["job_id"])
        _assert_only_selected_input_expired(
            project_id=project["project"],
            fact_id=fact["id"],
            graph_entity_id=graph_entity_id,
            lifecycle_change=lifecycle_change,
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


def _assert_rejected_without_outputs(*, project_id, job_id) -> None:
    with psycopg.connect(ADMIN_URL) as admin:
        assert admin.execute(
            "SELECT status, error_code FROM durable_jobs WHERE project_id = %s AND id = %s",
            (project_id, job_id),
        ).fetchone() == ("failed", "QuestionContractError")
        assert admin.execute(
            """SELECT
                 (SELECT count(*) FROM knowledge_question_candidates
                  WHERE project_id = %s AND generated_by_job_id = %s),
                 (SELECT count(*) FROM knowledge_question_generation_results
                  WHERE project_id = %s AND job_id = %s)""",
            (project_id, job_id, project_id, job_id),
        ).fetchone() == (0, 0)
        assert admin.execute(
            """SELECT array_agg(status ORDER BY created_at)
               FROM model_call_logs WHERE project_id = %s AND job_id = %s""",
            (project_id, job_id),
        ).fetchone()[0] == ["reserved", "succeeded"]


def _assert_only_selected_input_expired(
    *, project_id, fact_id, graph_entity_id, lifecycle_change: str
) -> None:
    with psycopg.connect(ADMIN_URL) as admin:
        fact_state = admin.execute(
            """SELECT fact.status, fact.lifecycle_status, chunk.status
               FROM knowledge_fact_candidates fact
               JOIN knowledge_chunks chunk
                 ON chunk.id = fact.chunk_id AND chunk.project_id = fact.project_id
               WHERE fact.project_id = %s AND fact.id = %s""",
            (project_id, fact_id),
        ).fetchone()
        graph_state = admin.execute(
            """SELECT entity.status,
                      EXISTS (
                        SELECT 1 FROM knowledge_graph_entity_sources source
                        JOIN knowledge_chunks chunk
                          ON chunk.id = source.chunk_id
                         AND chunk.project_id = source.project_id
                        WHERE source.project_id = entity.project_id
                          AND source.graph_entity_id = entity.id
                          AND source.lifecycle_status = 'active'
                          AND chunk.status = 'active'
                      )
               FROM knowledge_graph_entities entity
               WHERE entity.project_id = %s AND entity.id = %s""",
            (project_id, graph_entity_id),
        ).fetchone()
    if lifecycle_change == "disable_fact_chunk":
        assert fact_state == ("approved", "active", "disabled")
        assert graph_state == ("current", True)
    else:
        assert fact_state == ("approved", "active", "active")
        assert graph_state == ("archived", False)
