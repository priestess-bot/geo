from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
import hashlib
import json
import os
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
import pytest

from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.catalog.domain import (
    Confidentiality,
    PublicCitation,
    SubjectRole,
    UsageRights,
)
from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.knowledge import KnowledgeApplication
from geo_core.knowledge.domain import (
    KnowledgeConflict,
    KnowledgeForbidden,
    KnowledgeNotFound,
    SourceInput,
)
from geo_core.knowledge.rag_activation import prepare_rag_activation
from geo_core.knowledge.rag_domain import KnowledgeRagEnqueuePolicy
from geo_core.knowledge.rag_domain import KnowledgeRagContractError
from geo_core.knowledge.rag_postgres import KnowledgeRagPostgresRepository
from geo_core.knowledge.rag_worker import KnowledgeRagExtractHandler
from geo_core.knowledge.worker import KnowledgeProcessHandler
from geo_core.model_gateway import ModelGatewayResult
from geo_core.object_store import S3CompatibleObjectStore
from geo_core.placements.application import PlacementApplication
from geo_core.placements.postgres_uow import placement_uow_factory
from geo_core.placements.worker_composition import (
    EvidencePackHandler,
    PlacementWorkerDispatcher,
)
from geo_core.placements.worker_repository import PlacementWorkerRepository
from geo_core.project_scope import set_project_scope
from geo_core.rag import RagSelection
from tests.integration.placement_worker_support import cleanup_projects, login_url, seed_project
from tests.integration.test_knowledge_fact_evidence_postgres import _seed_brief


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()
MINIO_ENDPOINT = os.getenv("GEO_F019_TEST_MINIO_ENDPOINT", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
    pytest.mark.skipif(not MINIO_ENDPOINT, reason="GEO_F019_TEST_MINIO_ENDPOINT is required"),
]

SELECTION_HASH = "b" * 64
SELECTION = RagSelection(
    "project-native-rag-v1",
    "project-native-rag-v1",
    "f019-corpus-v1",
    "c" * 64,
)


class TraceableGateway:
    provider = "integration-test"

    def generate(self, request, *, policy, budget):
        del policy
        budget.consume()
        user_payload = json.loads(request.messages[1]["content"])
        content = str(user_payload["content"])
        fact = (
            "A1 的流量为每分钟 3 升。" if "每分钟 3 升" in content else "A1 的流量为每分钟 2 升。"
        )
        output = {
            "facts": [{"text": fact, "source_quote": fact}],
            "entities": [
                {"entity_type": "Product", "name": "A1", "source_quote": "A1"},
                {"entity_type": "Brand", "name": "星澜", "source_quote": "星澜"},
            ],
            "relations": [
                {
                    "subject": "A1",
                    "predicate": "belongs_to",
                    "object": "星澜",
                    "source_quote": "A1 belongs_to 星澜",
                }
            ],
        }
        response_hash = hashlib.sha256(
            json.dumps(output, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        return ModelGatewayResult(
            output=output,
            call_log_id=uuid4(),
            provider_request_id=f"integration-{uuid4()}",
            configured_model=request.configured_model,
            provider_reported_model=request.configured_model,
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=Decimal("0.001"),
            finish_reason="stop",
            response_hash=response_hash,
        )


def test_f019_int_01_02_governed_rag_revision_archive_and_project_isolation() -> None:
    suffix = uuid4().hex[:10]
    app_login, worker_login = f"geo_rag_app_{suffix}", f"geo_rag_worker_{suffix}"
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
        primary = seed_project(admin, suffix=f"rag-primary-{suffix}")
        foreign = seed_project(admin, suffix=f"rag-foreign-{suffix}")
        campaign_id, brief_version_id = _seed_brief(admin, primary, suffix)
        admin.commit()

    app_url = login_url(ADMIN_URL, user=app_login, password=app_password)
    worker_url = login_url(ADMIN_URL, user=worker_login, password=worker_password)
    primary_principal = _principal(primary, suffix)
    foreign_principal = _principal(foreign, suffix)
    application = KnowledgeApplication(app_url)
    placements = PlacementApplication(placement_uow_factory(lambda: psycopg.connect(app_url)))
    dispatcher = _dispatcher(worker_url, suffix)
    try:
        first = application.create_source(
            primary_principal,
            project_id=primary["project"],
            source=_source("每分钟 2 升"),
            idempotency_key=f"rag-source-{suffix}",
        )
        first_ids = _process_source(dispatcher, first, primary["project"])
        repeated = application.create_source(
            primary_principal,
            project_id=primary["project"],
            source=_source("每分钟 2 升"),
            idempotency_key=f"rag-source-{suffix}",
        )
        assert repeated["source"]["id"] == first_ids["source_id"]
        assert repeated["pipeline_run"]["id"] == first_ids["run_id"]

        revisions = application.list_rag_revisions(primary_principal, project_id=primary["project"])
        entities = application.list_rag_entity_candidates(
            primary_principal, project_id=primary["project"]
        )
        relations = application.list_rag_relation_candidates(
            primary_principal, project_id=primary["project"]
        )
        assert len(revisions) == 1 and revisions[0]["lifecycle_status"] == "active"
        stored = _object_store(suffix).get_s3_uri(
            uri=str(revisions[0]["artifact_uri"]),
            expected_hash=str(revisions[0]["artifact_hash"]),
        )
        assert json.loads(stored.content)["schema_version"] == "knowledge-rag-candidate-artifact-v1"
        assert {item["entity_type"] for item in entities} == {"product", "brand"}
        assert len(relations) == 1
        _approve_graph(application, primary_principal, primary["project"], entities, relations)

        with psycopg.connect(ADMIN_URL) as admin:
            legacy, rag = admin.execute(
                """SELECT
                     count(*) FILTER (WHERE rag_revision_id IS NULL),
                     count(*) FILTER (WHERE rag_revision_id IS NOT NULL)
                   FROM knowledge_fact_candidates
                   WHERE project_id = %s AND pipeline_run_id = %s""",
                (primary["project"], first_ids["run_id"]),
            ).fetchone()
            assert legacy >= 1 and rag == 1
            assert (
                admin.execute(
                    """SELECT bool_and(lifecycle_status = 'superseded')
                   FROM knowledge_fact_candidates
                   WHERE project_id = %s AND pipeline_run_id = %s
                     AND rag_revision_id IS NULL""",
                    (primary["project"], first_ids["run_id"]),
                ).fetchone()[0]
                is True
            )
            assert admin.execute(
                """SELECT array_agg(status ORDER BY created_at)
                   FROM model_call_logs WHERE project_id = %s AND job_id = %s""",
                (primary["project"], first_ids["rag_job_id"]),
            ).fetchone()[0] == ["reserved", "succeeded"]

        first_fact = next(
            fact
            for fact in application.list_facts(primary_principal, project_id=primary["project"])
            if fact["pipeline_run_id"] == first_ids["run_id"]
        )
        reviewed_fact = application.review_fact(
            primary_principal,
            project_id=primary["project"],
            fact_id=first_fact["id"],
            decision="approved",
            notes="approved before reprocessing",
        )
        assert reviewed_fact["status"] == "approved"

        promoted = application.promote_fact_to_evidence(
            primary_principal,
            project_id=primary["project"],
            fact_id=first_fact["id"],
            idempotency_key=f"rag-promoted-fact-{suffix}",
            title="Approved RAG Fact",
            subject_entity_id=None,
            subject_role=SubjectRole.NEUTRAL,
            usage_rights=UsageRights.OWNED,
            confidentiality=Confidentiality.INTERNAL,
            public_citation=PublicCitation(disclosure_allowed=False),
        )
        assert promoted["outcome"] == "created"
        promoted_evidence_id = promoted["evidence"]["id"]
        frozen_pack, frozen_pack_job = placements.create_evidence_attempt(
            project_id=primary["project"],
            campaign_id=campaign_id,
            brief_version_id=brief_version_id,
            idempotency_key=f"rag-evidence-pack-before-reprocess-{suffix}",
        )
        assert (
            dispatcher.process(job_id=frozen_pack_job.id, project_id=primary["project"])["status"]
            == "ready"
        )
        assert {
            item["id"]
            for item in placements.list_evidence_attempt_items(
                project_id=primary["project"],
                campaign_id=campaign_id,
                attempt_id=frozen_pack.id,
            )
        } == {promoted_evidence_id}
        with pytest.raises(KnowledgeConflict, match="cannot be reviewed again"):
            application.review_fact(
                primary_principal,
                project_id=primary["project"],
                fact_id=first_fact["id"],
                decision="rejected",
                notes="promoted Fact must remain an immutable reviewed snapshot",
            )
        stale_fact_id = uuid4()
        stale_statement = "This old unpromoted candidate must be superseded after reprocessing."
        with psycopg.connect(ADMIN_URL) as admin:
            document_id, chunk_id = admin.execute(
                """SELECT document_id, chunk_id FROM knowledge_fact_candidates
                   WHERE project_id = %s AND id = %s""",
                (primary["project"], first_fact["id"]),
            ).fetchone()
            admin.execute(
                """INSERT INTO knowledge_fact_candidates
                     (id, project_id, pipeline_run_id, source_id, document_id, chunk_id,
                      statement, statement_hash)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    stale_fact_id,
                    primary["project"],
                    first_ids["run_id"],
                    first_ids["source_id"],
                    document_id,
                    chunk_id,
                    stale_statement,
                    hashlib.sha256(stale_statement.encode()).hexdigest(),
                ),
            )
            admin.commit()

        reprocessed = application.reprocess_source(
            primary_principal,
            project_id=primary["project"],
            source_id=first_ids["source_id"],
            idempotency_key=f"rag-reprocess-{suffix}",
        )
        reprocessed_run_id = reprocessed["pipeline_run"]["id"]
        reprocessed_result = dispatcher.process(
            job_id=reprocessed["job"]["id"], project_id=primary["project"]
        )
        assert reprocessed_result["status"] == "succeeded", reprocessed_result
        with psycopg.connect(ADMIN_URL) as admin:
            assert (
                admin.execute(
                    """SELECT bool_and(status = 'active') FROM knowledge_chunks
                   WHERE project_id = %s AND pipeline_run_id = %s""",
                    (primary["project"], first_ids["run_id"]),
                ).fetchone()[0]
                is True
            )
            assert (
                admin.execute(
                    """SELECT lifecycle_status FROM knowledge_fact_candidates
                   WHERE project_id = %s AND id = %s""",
                    (primary["project"], first_fact["id"]),
                ).fetchone()[0]
                == "active"
            )
            assert (
                admin.execute(
                    """SELECT lifecycle_status FROM knowledge_rag_revisions
                   WHERE project_id = %s AND pipeline_run_id = %s""",
                    (primary["project"], first_ids["run_id"]),
                ).fetchone()[0]
                == "active"
            )
        reprocessed_rag = dispatcher.process(
            job_id=UUID(str(reprocessed_result["rag_job_id"])),
            project_id=primary["project"],
        )
        assert reprocessed_rag["status"] == "succeeded", reprocessed_rag
        with psycopg.connect(ADMIN_URL) as admin:
            assert (
                admin.execute(
                    """SELECT bool_and(status = 'disabled') FROM knowledge_chunks
                   WHERE project_id = %s AND pipeline_run_id = %s""",
                    (primary["project"], first_ids["run_id"]),
                ).fetchone()[0]
                is True
            )
            assert (
                admin.execute(
                    """SELECT bool_and(lifecycle_status = 'superseded')
                   FROM knowledge_fact_candidates
                   WHERE project_id = %s AND pipeline_run_id = %s""",
                    (primary["project"], first_ids["run_id"]),
                ).fetchone()[0]
                is True
            )
            assert admin.execute(
                """SELECT status, lifecycle_status FROM knowledge_fact_candidates
                   WHERE project_id = %s AND id = %s""",
                (primary["project"], first_fact["id"]),
            ).fetchone() == ("approved", "superseded")
            assert admin.execute(
                """SELECT status, lifecycle_status FROM knowledge_fact_candidates
                   WHERE project_id = %s AND id = %s""",
                (primary["project"], stale_fact_id),
            ).fetchone() == ("pending_review", "superseded")
            assert (
                admin.execute(
                    """SELECT count(*) FROM knowledge_fact_evidence_lineages
                   WHERE project_id = %s AND knowledge_fact_id = %s""",
                    (primary["project"], first_fact["id"]),
                ).fetchone()[0]
                == 1
            )
            assert (
                admin.execute(
                    """SELECT bool_and(status = 'active') FROM knowledge_chunks
                   WHERE project_id = %s AND pipeline_run_id = %s""",
                    (primary["project"], reprocessed_run_id),
                ).fetchone()[0]
                is True
            )
            assert (
                admin.execute(
                    """SELECT status FROM knowledge_pipeline_runs
                   WHERE project_id = %s AND id = %s""",
                    (primary["project"], first_ids["run_id"]),
                ).fetchone()[0]
                == "succeeded"
            )

        current_pack, current_pack_job = placements.create_evidence_attempt(
            project_id=primary["project"],
            campaign_id=campaign_id,
            brief_version_id=brief_version_id,
            idempotency_key=f"rag-evidence-pack-after-reprocess-{suffix}",
        )
        assert (
            dispatcher.process(job_id=current_pack_job.id, project_id=primary["project"])["status"]
            == "needs_evidence"
        )
        assert (
            placements.list_evidence_attempt_items(
                project_id=primary["project"],
                campaign_id=campaign_id,
                attempt_id=current_pack.id,
            )
            == ()
        )
        assert {
            item["id"]
            for item in placements.list_evidence_attempt_items(
                project_id=primary["project"],
                campaign_id=campaign_id,
                attempt_id=frozen_pack.id,
            )
        } == {promoted_evidence_id}
        with psycopg.connect(ADMIN_URL) as admin:
            assert (
                admin.execute(
                    """SELECT count(*) FROM knowledge_fact_evidence_lineages
                   WHERE project_id = %s AND knowledge_fact_id = %s
                     AND evidence_item_id = %s""",
                    (primary["project"], first_fact["id"], promoted_evidence_id),
                ).fetchone()[0]
                == 1
            )
            assert (
                admin.execute(
                    """SELECT status FROM evidence_pack_attempts
                   WHERE project_id = %s AND id = %s""",
                    (primary["project"], frozen_pack.id),
                ).fetchone()[0]
                == "ready"
            )

        stale = application.reprocess_source(
            primary_principal,
            project_id=primary["project"],
            source_id=first_ids["source_id"],
            idempotency_key=f"rag-stale-{suffix}",
        )
        stale_knowledge = dispatcher.process(
            job_id=stale["job"]["id"], project_id=primary["project"]
        )
        assert stale_knowledge["status"] == "succeeded", stale_knowledge
        stale_rag_job_id = UUID(str(stale_knowledge["rag_job_id"]))
        stale_store = PostgresDurableJobStore(lambda: psycopg.connect(worker_url))
        stale_claim_result = stale_store.claim(
            job_id=stale_rag_job_id,
            project_id=primary["project"],
            expected_kind="knowledge.rag.extract",
            worker_id=f"stale-rag-{suffix}",
            lease_for=timedelta(minutes=5),
        )
        assert stale_claim_result.lease is not None
        stale_lease = stale_claim_result.lease
        stale_claim = KnowledgeRagPostgresRepository(stale_store).load(stale_lease)

        newer = application.reprocess_source(
            primary_principal,
            project_id=primary["project"],
            source_id=first_ids["source_id"],
            idempotency_key=f"rag-newer-{suffix}",
        )
        _process_source(dispatcher, newer, primary["project"])
        with pytest.raises(KnowledgeRagContractError, match="newer run is already active"):
            with stale_store.fenced_transaction(stale_lease) as connection:
                prepare_rag_activation(connection, project_id=primary["project"], claim=stale_claim)
        assert (
            stale_store.fail(
                stale_lease,
                error_code="KnowledgeRagContractError",
                details={"message": "stale completion rejected"},
                retry_delay=None,
            )
            == "failed"
        )

        with psycopg.connect(ADMIN_URL) as admin:
            admin.execute(
                """UPDATE knowledge_sources
                   SET status = 'queued', error_code = NULL, error_detail = NULL
                   WHERE id = %s AND project_id = %s""",
                (first_ids["source_id"], primary["project"]),
            )
            admin.execute(
                """UPDATE knowledge_sources
                   SET status = 'failed', error_code = 'KnowledgeSourceRevisionRequired',
                       error_detail = 'source content changed'
                   WHERE id = %s AND project_id = %s""",
                (first_ids["source_id"], primary["project"]),
            )
            admin.commit()

        second = application.create_source_revision(
            primary_principal,
            project_id=primary["project"],
            source_id=first_ids["source_id"],
            source=_source("每分钟 3 升"),
            idempotency_key=f"rag-revision-{suffix}",
        )
        replayed_reprocess_with_successor = application.reprocess_source(
            primary_principal,
            project_id=primary["project"],
            source_id=first_ids["source_id"],
            idempotency_key=f"rag-newer-{suffix}",
        )
        assert (
            replayed_reprocess_with_successor["pipeline_run"]["id"] == newer["pipeline_run"]["id"]
        )
        assert replayed_reprocess_with_successor["job"]["id"] == newer["job"]["id"]
        with pytest.raises(KnowledgeConflict, match="latest Knowledge source revision"):
            application.reprocess_source(
                primary_principal,
                project_id=primary["project"],
                source_id=first_ids["source_id"],
                idempotency_key=f"stale-predecessor-reprocess-{suffix}",
            )
        second_ids = _process_source(dispatcher, second, primary["project"])
        with psycopg.connect(ADMIN_URL) as admin:
            source_statuses = dict(
                admin.execute(
                    """SELECT id, status FROM knowledge_sources
                       WHERE project_id = %s AND logical_source_id = %s""",
                    (primary["project"], first_ids["source_id"]),
                ).fetchall()
            )
            # A failed predecessor is already excluded from active source
            # consumption; the RAG worker archives only ready predecessors.
            # Preserve its failure reason while the successor becomes ready.
            assert source_statuses == {
                first_ids["source_id"]: "failed",
                second_ids["source_id"]: "ready",
            }
            assert (
                admin.execute(
                    """SELECT bool_and(status = 'disabled') FROM knowledge_chunks
                   WHERE project_id = %s AND pipeline_run_id = %s""",
                    (primary["project"], first_ids["run_id"]),
                ).fetchone()[0]
                is True
            )
            assert admin.execute(
                """SELECT array_agg(lifecycle_status ORDER BY completed_at)
                   FROM knowledge_rag_revisions
                   WHERE project_id = %s AND logical_source_id = %s""",
                (primary["project"], first_ids["source_id"]),
            ).fetchone()[0] == [
                "superseded",
                "superseded",
                "superseded",
                "active",
            ]

        replayed_revision = application.create_source_revision(
            primary_principal,
            project_id=primary["project"],
            source_id=first_ids["source_id"],
            source=_source("每分钟 3 升"),
            idempotency_key=f"rag-revision-{suffix}",
        )
        assert replayed_revision["source"]["id"] == second["source"]["id"]
        assert replayed_revision["pipeline_run"]["id"] == second["pipeline_run"]["id"]
        assert replayed_revision["job"]["id"] == second["job"]["id"]
        with pytest.raises(KnowledgeConflict, match="different content"):
            application.create_source_revision(
                primary_principal,
                project_id=primary["project"],
                source_id=first_ids["source_id"],
                source=_source("每分钟 4 升"),
                idempotency_key=f"rag-revision-{suffix}",
            )

        replayed_reprocess_when_archived = application.reprocess_source(
            primary_principal,
            project_id=primary["project"],
            source_id=first_ids["source_id"],
            idempotency_key=f"rag-newer-{suffix}",
        )
        assert replayed_reprocess_when_archived["pipeline_run"]["id"] == newer["pipeline_run"]["id"]
        assert replayed_reprocess_when_archived["job"]["id"] == newer["job"]["id"]

        archived = application.archive_source(
            primary_principal,
            project_id=primary["project"],
            source_id=second_ids["source_id"],
        )
        assert archived["outcome"] == "archived"
        assert archived["withdrawn_revision_count"] == 1

        queued = application.create_source(
            primary_principal,
            project_id=primary["project"],
            source=_source("每分钟 2 升"),
            idempotency_key=f"rag-cancel-{suffix}",
        )
        cancelled = application.archive_source(
            primary_principal,
            project_id=primary["project"],
            source_id=queued["source"]["id"],
        )
        assert cancelled["outcome"] == "archived"
        assert (
            dispatcher.process(job_id=queued["job"]["id"], project_id=primary["project"])["status"]
            == "cancelled"
        )

        foreign_source = application.create_source(
            foreign_principal,
            project_id=foreign["project"],
            source=_source("每分钟 2 升"),
            idempotency_key=f"rag-foreign-{suffix}",
        )
        _process_source(dispatcher, foreign_source, foreign["project"])
        with pytest.raises(KnowledgeForbidden):
            application.list_rag_revisions(primary_principal, project_id=foreign["project"])
        foreign_candidate = application.list_rag_entity_candidates(
            foreign_principal, project_id=foreign["project"]
        )[0]
        with pytest.raises(KnowledgeNotFound):
            application.review_rag_entity_candidate(
                primary_principal,
                project_id=primary["project"],
                candidate_id=foreign_candidate["id"],
                decision="approved",
                notes="cross-project must fail",
            )
        with psycopg.connect(app_url) as scoped:
            set_project_scope(scoped, primary["project"])
            assert (
                scoped.execute(
                    "SELECT count(*) FROM knowledge_rag_revisions WHERE project_id = %s",
                    (foreign["project"],),
                ).fetchone()[0]
                == 0
            )
    finally:
        with psycopg.connect(ADMIN_URL) as admin:
            cleanup_projects(
                admin,
                projects=[primary, foreign],
                tenant_ids=[primary["tenant"], foreign["tenant"]],
                app_login=app_login,
                worker_login=worker_login,
            )
            admin.commit()


def _dispatcher(
    worker_url: str, suffix: str, *, gateway: Any | None = None
) -> PlacementWorkerDispatcher:
    store = PostgresDurableJobStore(lambda: psycopg.connect(worker_url))
    object_store = _object_store(suffix)
    placement_repository = PlacementWorkerRepository(store)

    policy = KnowledgeRagEnqueuePolicy(
        adapter_release=SELECTION.adapter_release,
        selection_manifest_hash=SELECTION_HASH,
        configured_model="deepseek-v4-flash",
    )
    return PlacementWorkerDispatcher(
        store=store,
        handlers={
            "evidence_pack.build": EvidencePackHandler(placement_repository),
            "knowledge.process": KnowledgeProcessHandler(
                store, rag_policy=policy, lease_for=timedelta(seconds=30)
            ),
            "knowledge.rag.extract": KnowledgeRagExtractHandler(
                store=store,
                repository=KnowledgeRagPostgresRepository(store),
                gateway=gateway or TraceableGateway(),
                object_store=object_store,
                selection=SELECTION,
                selection_manifest_hash=SELECTION_HASH,
                lease_for=timedelta(seconds=30),
            ),
        },
        worker_id=f"f019-integration-{suffix}",
        lease_for=timedelta(seconds=30),
    )


def _object_store(suffix: str) -> S3CompatibleObjectStore:
    return S3CompatibleObjectStore(
        endpoint=MINIO_ENDPOINT,
        bucket=f"geo-f019-{suffix}",
        access_key="geo_dev",
        secret_key="geo_dev_secret",
        auto_create_bucket=True,
    )


def _process_source(
    dispatcher: PlacementWorkerDispatcher,
    created: Any,
    project_id: UUID,
) -> dict[str, UUID]:
    source_id = created["source"]["id"]
    run_id = created["pipeline_run"]["id"]
    process_job_id = created["job"]["id"]
    processed = dispatcher.process(job_id=process_job_id, project_id=project_id)
    assert processed["status"] == "succeeded", processed
    rag_job_id = UUID(str(processed["rag_job_id"]))
    extracted = dispatcher.process(job_id=rag_job_id, project_id=project_id)
    assert extracted["status"] == "succeeded", extracted
    return {
        "source_id": source_id,
        "run_id": run_id,
        "process_job_id": process_job_id,
        "rag_job_id": rag_job_id,
    }


def _approve_graph(
    application: KnowledgeApplication,
    principal: AccessPrincipal,
    project_id: UUID,
    entities: tuple[dict[str, Any], ...],
    relations: tuple[dict[str, Any], ...],
) -> None:
    for entity in entities:
        result = application.review_rag_entity_candidate(
            principal,
            project_id=project_id,
            candidate_id=entity["id"],
            decision="approved",
            notes="integration approval",
        )
        assert result["workflow_status"] == "approved"
    result = application.review_rag_relation_candidate(
        principal,
        project_id=project_id,
        candidate_id=relations[0]["id"],
        decision="approved",
        notes="integration approval",
    )
    assert result["workflow_status"] == "approved"


def _source(rate: str) -> SourceInput:
    content = (f"A1 的流量为{rate}。\n" "Product A1\n" "Brand 星澜\n" "A1 belongs_to 星澜").encode()
    return SourceInput("text", "A1 产品资料", None, "a1.txt", "text/plain", content)


def _principal(seed: dict[str, UUID], suffix: str) -> AccessPrincipal:
    return AccessPrincipal(
        identity_id=seed["owner"],
        actor_id=f"f019-{suffix}",
        tenant_id=seed["tenant"],
        memberships=(MembershipRecord(seed["project"], seed["tenant"], "admin"),),
        auth_method="development",
    )
