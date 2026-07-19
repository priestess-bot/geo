from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
import pytest

from geo_core.knowledge import KnowledgeApplication
from geo_core.knowledge.domain import KnowledgeConflict
from geo_core.knowledge.rag_domain import KnowledgeRagEnqueuePolicy
from geo_core.monitoring.domain import Device, MonitoringConflict, Platform
from tests.integration.placement_worker_support import cleanup_projects, login_url, seed_project
from tests.integration.test_knowledge_question_sets_postgres import (
    _dimensions,
    _monitoring,
    _question_dispatcher,
    _stratum,
)
from tests.integration.test_knowledge_rag_postgres import (
    SELECTION,
    SELECTION_HASH,
    _approve_graph,
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


def test_disabled_fact_and_graph_chunks_invalidate_question_sources() -> None:
    suffix = uuid4().hex[:10]
    app_login = f"geo_chunk_app_{suffix}"
    worker_login = f"geo_chunk_worker_{suffix}"
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
        project = seed_project(admin, suffix=f"active-chunk-{suffix}")
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
                f"Active chunk campaign {suffix}",
                project["owner"],
            ),
        )
        admin.commit()

    app_url = login_url(ADMIN_URL, user=app_login, password=app_password)
    worker_url = login_url(ADMIN_URL, user=worker_login, password=worker_password)
    principal = _principal(project, suffix)
    knowledge = KnowledgeApplication(
        app_url,
        question_policy=KnowledgeRagEnqueuePolicy(
            adapter_release=SELECTION.adapter_release,
            selection_manifest_hash=SELECTION_HASH,
            configured_model="deepseek-v4-flash",
        ),
    )
    try:
        source = knowledge.create_source(
            principal,
            project_id=project["project"],
            source=_source("每分钟 2 升"),
            idempotency_key=f"active-chunk-source-{suffix}",
        )
        _process_source(_dispatcher(worker_url, suffix), source, project["project"])
        entities = knowledge.list_rag_entity_candidates(principal, project_id=project["project"])
        relations = knowledge.list_rag_relation_candidates(principal, project_id=project["project"])
        _approve_graph(knowledge, principal, project["project"], entities, relations)
        entities = knowledge.list_rag_entity_candidates(principal, project_id=project["project"])
        _assert_catalog_mapping_requires_current_sources(
            knowledge=knowledge,
            principal=principal,
            project_id=project["project"],
            entities=entities,
        )
        fact = knowledge.list_facts(principal, project_id=project["project"])[0]
        knowledge.review_fact(
            principal,
            project_id=project["project"],
            fact_id=fact["id"],
            decision="approved",
            notes="approved for active Chunk contract",
        )
        generation = knowledge.create_question_generation(
            principal,
            project_id=project["project"],
            campaign_id=campaign_id,
            dimensions=_dimensions(),
            fact_candidate_ids=(fact["id"],),
            graph_entity_ids=tuple(dict.fromkeys(item["graph_entity_id"] for item in entities)),
            configured_model="deepseek-v4-flash",
            model_call_budget=10,
            semantic_duplicate_threshold=0.92,
            idempotency_key=f"active-chunk-generation-{suffix}",
        )
        generated = _question_dispatcher(worker_url, suffix).process(
            job_id=generation["job_id"], project_id=project["project"]
        )
        assert generated["status"] == "succeeded", generated
        candidates = knowledge.list_question_candidates(
            principal,
            project_id=project["project"],
            campaign_id=campaign_id,
            generation_job_id=generation["job_id"],
        )
        for candidate in candidates:
            knowledge.review_question_candidate(
                principal,
                project_id=project["project"],
                campaign_id=campaign_id,
                candidate_id=candidate["id"],
                decision="approved",
                notes="approved for active Chunk contract",
            )
        question_set = knowledge.create_question_set(
            principal,
            project_id=project["project"],
            campaign_id=campaign_id,
            name="Active Chunk contract QuestionSet",
            generation_job_id=generation["job_id"],
            candidate_ids=tuple(item["id"] for item in candidates),
            series_id=None,
            previous_version_id=None,
            idempotency_key=f"active-chunk-question-set-{suffix}",
        )
        knowledge.approve_question_set(
            principal,
            project_id=project["project"],
            campaign_id=campaign_id,
            question_set_id=question_set["id"],
        )
        _assert_active_chunk_source_contract(
            knowledge=knowledge,
            principal=principal,
            app_url=app_url,
            project_id=project["project"],
            campaign_id=campaign_id,
            market_profile_id=project["market"],
            fact_id=fact["id"],
            candidate_ids=tuple(item["id"] for item in candidates),
            question_set_id=question_set["id"],
            suffix=suffix,
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


def _assert_active_chunk_source_contract(
    *,
    knowledge: KnowledgeApplication,
    principal: Any,
    app_url: str,
    project_id: UUID,
    campaign_id: UUID,
    market_profile_id: UUID,
    fact_id: UUID,
    candidate_ids: tuple[UUID, ...],
    question_set_id: UUID,
    suffix: str,
) -> None:
    with psycopg.connect(ADMIN_URL) as admin:
        fact_chunk = admin.execute(
            """SELECT chunk_id FROM knowledge_fact_candidates
               WHERE id = %s AND project_id = %s""",
            (fact_id, project_id),
        ).fetchone()
        assert fact_chunk is not None
        fact_chunk_id = fact_chunk[0]
        graph_chunk_id = uuid4()
        admin.execute(
            """INSERT INTO knowledge_chunks
                 (id, project_id, pipeline_run_id, source_id, document_id,
                  chunk_index, text, text_hash, char_count, status, quality_flags)
               SELECT %s, project_id, pipeline_run_id, source_id, document_id,
                      (SELECT max(other.chunk_index) + 1
                       FROM knowledge_chunks AS other
                       WHERE other.document_id = original.document_id),
                      text, text_hash, char_count, 'active', quality_flags
               FROM knowledge_chunks AS original
               WHERE original.id = %s AND original.project_id = %s""",
            (graph_chunk_id, fact_chunk_id, project_id),
        )
        admin.execute(
            """INSERT INTO knowledge_graph_entity_sources
                 (project_id, graph_entity_id, rag_revision_id, entity_candidate_id,
                  pipeline_run_id, source_id, document_id, chunk_id, source_locator,
                  approved_by, lifecycle_status)
               SELECT project_id, graph_entity_id, rag_revision_id, entity_candidate_id,
                      pipeline_run_id, source_id, document_id, %s, source_locator,
                      approved_by, 'active'
               FROM knowledge_graph_entity_sources
               WHERE project_id = %s AND chunk_id = %s
                 AND lifecycle_status = 'active'
                 AND graph_entity_id IN (
                     SELECT graph_entity_id
                     FROM knowledge_question_candidate_entity_sources
                     WHERE candidate_id = ANY(%s)
                 )""",
            (graph_chunk_id, project_id, fact_chunk_id, list(candidate_ids)),
        )
        moved = admin.execute(
            """UPDATE knowledge_graph_entity_sources
               SET lifecycle_status = 'superseded'
               WHERE project_id = %s AND chunk_id = %s
                 AND lifecycle_status = 'active'
                 AND graph_entity_id IN (
                     SELECT graph_entity_id
                     FROM knowledge_question_candidate_entity_sources
                     WHERE candidate_id = ANY(%s)
                 )""",
            (project_id, fact_chunk_id, list(candidate_ids)),
        ).rowcount
        assert moved > 0
        admin.commit()

        admin.execute(
            """UPDATE knowledge_chunks SET status = 'disabled'
               WHERE id = %s AND project_id = %s""",
            (fact_chunk_id, project_id),
        )
        admin.commit()
        assert _candidate_sources_current(admin, candidate_ids) == [False]
        graph_sources_active = admin.execute(
            """SELECT bool_and(EXISTS (
                     SELECT 1
                     FROM knowledge_graph_entity_sources AS lineage
                     JOIN knowledge_chunks AS chunk
                       ON chunk.id = lineage.chunk_id
                      AND chunk.project_id = lineage.project_id
                     WHERE lineage.project_id = %s
                       AND lineage.graph_entity_id = source.graph_entity_id
                       AND lineage.lifecycle_status = 'active'
                       AND chunk.status = 'active'
                 ))
               FROM knowledge_question_candidate_entity_sources AS source
               WHERE source.candidate_id = ANY(%s)""",
            (project_id, list(candidate_ids)),
        ).fetchone()
        assert graph_sources_active == (True,)

    _assert_freeze_rejected(knowledge, principal, project_id, campaign_id, question_set_id)

    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute(
            """UPDATE knowledge_chunks SET status = 'active'
               WHERE id = %s AND project_id = %s""",
            (fact_chunk_id, project_id),
        )
        admin.commit()
        assert _candidate_sources_current(admin, candidate_ids) == [True]
        admin.execute(
            """UPDATE knowledge_chunks SET status = 'disabled'
               WHERE id = %s AND project_id = %s""",
            (graph_chunk_id, project_id),
        )
        admin.commit()
        assert _candidate_sources_current(admin, candidate_ids) == [False]
        fact_source_active = admin.execute(
            """SELECT fact.status = 'approved'
                      AND fact.lifecycle_status = 'active'
                      AND chunk.status = 'active'
               FROM knowledge_fact_candidates AS fact
               JOIN knowledge_chunks AS chunk
                 ON chunk.id = fact.chunk_id AND chunk.project_id = fact.project_id
               WHERE fact.id = %s AND fact.project_id = %s""",
            (fact_id, project_id),
        ).fetchone()
        assert fact_source_active == (True,)

    _assert_freeze_rejected(knowledge, principal, project_id, campaign_id, question_set_id)

    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute(
            """UPDATE knowledge_chunks SET status = 'active'
               WHERE id = %s AND project_id = %s""",
            (graph_chunk_id, project_id),
        )
        admin.commit()
        assert _candidate_sources_current(admin, candidate_ids) == [True]

    frozen = knowledge.freeze_question_set(
        principal,
        project_id=project_id,
        campaign_id=campaign_id,
        question_set_id=question_set_id,
    )
    monitoring = _monitoring(app_url)
    current_protocol = _new_protocol(
        monitoring=monitoring,
        principal=principal,
        project_id=project_id,
        campaign_id=campaign_id,
        market_profile_id=market_profile_id,
        suffix=f"current-{suffix}",
    )
    current_bound = monitoring.bind_question_set(
        principal,
        project_id=project_id,
        campaign_id=campaign_id,
        protocol_id=current_protocol.id,
        question_set_id=question_set_id,
        confirmed_content_hash=str(frozen["content_hash"]),
    )
    assert current_bound.question_set_id == question_set_id
    historical_inventory = _protocol_binding_inventory(project_id, current_protocol.id)
    assert historical_inventory == (question_set_id, len(candidate_ids), len(candidate_ids))

    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute(
            """UPDATE knowledge_chunks SET status = 'disabled'
               WHERE id = %s AND project_id = %s""",
            (fact_chunk_id, project_id),
        )
        admin.commit()
        assert _candidate_sources_current(admin, candidate_ids) == [False]

    _assert_stale_binding_rejected(
        monitoring=monitoring,
        principal=principal,
        project_id=project_id,
        campaign_id=campaign_id,
        market_profile_id=market_profile_id,
        question_set_id=question_set_id,
        content_hash=str(frozen["content_hash"]),
        suffix=f"fact-{suffix}",
    )
    _assert_direct_binding_rejected(
        monitoring=monitoring,
        principal=principal,
        project_id=project_id,
        campaign_id=campaign_id,
        market_profile_id=market_profile_id,
        question_set_id=question_set_id,
        content_hash=str(frozen["content_hash"]),
        actor_id=principal.identity_id,
        suffix=f"direct-{suffix}",
    )
    assert _protocol_binding_inventory(project_id, current_protocol.id) == historical_inventory

    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute(
            """UPDATE knowledge_chunks SET status = 'active'
               WHERE id = %s AND project_id = %s""",
            (fact_chunk_id, project_id),
        )
        admin.execute(
            """UPDATE knowledge_chunks SET status = 'disabled'
               WHERE id = %s AND project_id = %s""",
            (graph_chunk_id, project_id),
        )
        admin.commit()
        assert _candidate_sources_current(admin, candidate_ids) == [False]

    _assert_stale_binding_rejected(
        monitoring=monitoring,
        principal=principal,
        project_id=project_id,
        campaign_id=campaign_id,
        market_profile_id=market_profile_id,
        question_set_id=question_set_id,
        content_hash=str(frozen["content_hash"]),
        suffix=f"graph-{suffix}",
    )
    assert _protocol_binding_inventory(project_id, current_protocol.id) == historical_inventory


def _assert_freeze_rejected(
    knowledge: KnowledgeApplication,
    principal: Any,
    project_id: UUID,
    campaign_id: UUID,
    question_set_id: UUID,
) -> None:
    with pytest.raises(
        psycopg.errors.CheckViolation,
        match="QuestionSet state requires all candidate sources to remain approved and current",
    ):
        knowledge.freeze_question_set(
            principal,
            project_id=project_id,
            campaign_id=campaign_id,
            question_set_id=question_set_id,
        )


def _candidate_sources_current(
    connection: psycopg.Connection[Any], candidate_ids: tuple[UUID, ...]
) -> list[bool]:
    return [
        row[0]
        for row in connection.execute(
            """SELECT DISTINCT geo_question_candidate_sources_current(id)
               FROM knowledge_question_candidates
               WHERE id = ANY(%s)""",
            (list(candidate_ids),),
        ).fetchall()
    ]


def _assert_catalog_mapping_requires_current_sources(
    *,
    knowledge: KnowledgeApplication,
    principal: Any,
    project_id: UUID,
    entities: tuple[dict[str, Any], ...],
) -> None:
    product = next(item for item in entities if item["entity_type"] == "product")
    brand = next(item for item in entities if item["entity_type"] == "brand")
    product_catalog_id, brand_catalog_id = uuid4(), uuid4()
    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute(
            """INSERT INTO product_entities
                 (id, project_id, entity_type, canonical_name)
               VALUES (%s, %s, 'product', %s), (%s, %s, 'brand', %s)""",
            (
                product_catalog_id,
                project_id,
                product["name"],
                brand_catalog_id,
                project_id,
                brand["name"],
            ),
        )
        brand_sources = admin.execute(
            """SELECT array_agg(DISTINCT chunk_id), count(*)
               FROM knowledge_graph_entity_sources
               WHERE project_id = %s AND graph_entity_id = %s
                 AND lifecycle_status = 'active'""",
            (project_id, brand["graph_entity_id"]),
        ).fetchone()
        admin.commit()
    assert brand_sources is not None and brand_sources[1] == 1
    brand_chunk_ids = brand_sources[0]

    mapped = knowledge.map_graph_entity_to_catalog(
        principal,
        project_id=project_id,
        graph_entity_id=product["graph_entity_id"],
        catalog_entity_id=product_catalog_id,
    )
    assert mapped["catalog_entity_id"] == product_catalog_id

    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute(
            """UPDATE knowledge_chunks SET status = 'disabled',
                      updated_at = clock_timestamp()
               WHERE project_id = %s AND id = ANY(%s)""",
            (project_id, brand_chunk_ids),
        )
        admin.commit()
    with pytest.raises(KnowledgeConflict, match="current graph entity with an active source Chunk"):
        knowledge.map_graph_entity_to_catalog(
            principal,
            project_id=project_id,
            graph_entity_id=brand["graph_entity_id"],
            catalog_entity_id=brand_catalog_id,
        )
    replayed = knowledge.map_graph_entity_to_catalog(
        principal,
        project_id=project_id,
        graph_entity_id=product["graph_entity_id"],
        catalog_entity_id=product_catalog_id,
    )
    assert replayed["catalog_entity_id"] == product_catalog_id
    assert _graph_catalog_mapping(project_id, brand["graph_entity_id"]) is None

    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute(
            """UPDATE knowledge_chunks SET status = 'active',
                      updated_at = clock_timestamp()
               WHERE project_id = %s AND id = ANY(%s)""",
            (project_id, brand_chunk_ids),
        )
        admin.execute(
            """UPDATE knowledge_graph_entities SET status = 'archived',
                      updated_at = clock_timestamp()
               WHERE project_id = %s AND id = %s""",
            (project_id, brand["graph_entity_id"]),
        )
        admin.commit()
    with pytest.raises(KnowledgeConflict, match="current graph entity with an active source Chunk"):
        knowledge.map_graph_entity_to_catalog(
            principal,
            project_id=project_id,
            graph_entity_id=brand["graph_entity_id"],
            catalog_entity_id=brand_catalog_id,
        )
    assert _graph_catalog_mapping(project_id, brand["graph_entity_id"]) is None

    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute(
            """UPDATE knowledge_graph_entities SET status = 'current',
                      updated_at = clock_timestamp()
               WHERE project_id = %s AND id = %s""",
            (project_id, brand["graph_entity_id"]),
        )
        admin.commit()
    with (
        psycopg.connect(ADMIN_URL) as admin,
        ThreadPoolExecutor(max_workers=1) as executor,
    ):
        admin.execute(
            """SELECT id FROM product_entities
               WHERE project_id = %s AND id = %s FOR UPDATE""",
            (project_id, brand_catalog_id),
        )
        concurrent_mapping = executor.submit(
            knowledge.map_graph_entity_to_catalog,
            principal,
            project_id=project_id,
            graph_entity_id=brand["graph_entity_id"],
            catalog_entity_id=brand_catalog_id,
        )
        admin.execute(
            """UPDATE product_entities SET status = 'archived'
               WHERE project_id = %s AND id = %s""",
            (project_id, brand_catalog_id),
        )
        admin.commit()
        with pytest.raises(KnowledgeConflict, match="Catalog mapping must match"):
            concurrent_mapping.result(timeout=5)
    assert _graph_catalog_mapping(project_id, brand["graph_entity_id"]) is None

    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute(
            """UPDATE product_entities SET status = 'active'
               WHERE project_id = %s AND id = %s""",
            (project_id, brand_catalog_id),
        )
        admin.commit()
    mapped_brand = knowledge.map_graph_entity_to_catalog(
        principal,
        project_id=project_id,
        graph_entity_id=brand["graph_entity_id"],
        catalog_entity_id=brand_catalog_id,
    )
    assert mapped_brand["catalog_entity_id"] == brand_catalog_id


def _graph_catalog_mapping(project_id: UUID, graph_entity_id: UUID) -> UUID | None:
    with psycopg.connect(ADMIN_URL) as admin:
        row = admin.execute(
            """SELECT catalog_entity_id FROM knowledge_graph_entities
               WHERE project_id = %s AND id = %s""",
            (project_id, graph_entity_id),
        ).fetchone()
    assert row is not None
    return row[0]


def _new_protocol(
    *,
    monitoring: Any,
    principal: Any,
    project_id: UUID,
    campaign_id: UUID,
    market_profile_id: UUID,
    suffix: str,
) -> Any:
    return monitoring.create_protocol(
        principal,
        project_id=project_id,
        campaign_id=campaign_id,
        market_profile_id=market_profile_id,
        name=f"Active source protocol {suffix}",
        platform=Platform.CHATGPT_SEARCH,
        locale="en-AU",
        device=Device.DESKTOP,
        sample_size=3,
        minimum_valid_repeats=3,
        window_days=84,
        source_strata=(_stratum(),),
    )


def _assert_stale_binding_rejected(
    *,
    monitoring: Any,
    principal: Any,
    project_id: UUID,
    campaign_id: UUID,
    market_profile_id: UUID,
    question_set_id: UUID,
    content_hash: str,
    suffix: str,
) -> None:
    protocol = _new_protocol(
        monitoring=monitoring,
        principal=principal,
        project_id=project_id,
        campaign_id=campaign_id,
        market_profile_id=market_profile_id,
        suffix=suffix,
    )
    before = _project_monitoring_counts(project_id)
    with pytest.raises(MonitoringConflict, match="stale Knowledge sources"):
        monitoring.bind_question_set(
            principal,
            project_id=project_id,
            campaign_id=campaign_id,
            protocol_id=protocol.id,
            question_set_id=question_set_id,
            confirmed_content_hash=content_hash,
        )
    assert _project_monitoring_counts(project_id) == before
    assert _protocol_binding_inventory(project_id, protocol.id) == (None, 0, 0)


def _assert_direct_binding_rejected(
    *,
    monitoring: Any,
    principal: Any,
    project_id: UUID,
    campaign_id: UUID,
    market_profile_id: UUID,
    question_set_id: UUID,
    content_hash: str,
    actor_id: UUID,
    suffix: str,
) -> None:
    protocol = _new_protocol(
        monitoring=monitoring,
        principal=principal,
        project_id=project_id,
        campaign_id=campaign_id,
        market_profile_id=market_profile_id,
        suffix=suffix,
    )
    before = _project_monitoring_counts(project_id)
    with psycopg.connect(ADMIN_URL) as admin:
        with pytest.raises(
            psycopg.errors.CheckViolation,
            match="cannot bind a QuestionSet with stale Knowledge sources",
        ):
            admin.execute(
                """UPDATE monitoring_protocols
                   SET question_set_id = %s, question_set_hash = %s,
                       question_set_bound_by = %s,
                       question_set_bound_at = clock_timestamp()
                   WHERE id = %s AND project_id = %s AND campaign_id = %s""",
                (
                    question_set_id,
                    content_hash,
                    actor_id,
                    protocol.id,
                    project_id,
                    campaign_id,
                ),
            )
        admin.rollback()
    assert _project_monitoring_counts(project_id) == before
    assert _protocol_binding_inventory(project_id, protocol.id) == (None, 0, 0)


def _protocol_binding_inventory(
    project_id: UUID, protocol_id: UUID
) -> tuple[UUID | None, int, int]:
    with psycopg.connect(ADMIN_URL) as admin:
        row = admin.execute(
            """SELECT protocol.question_set_id,
                      (SELECT count(*) FROM monitoring_query_suggestions suggestion
                       WHERE suggestion.project_id = protocol.project_id
                         AND suggestion.protocol_id = protocol.id),
                      (SELECT count(*) FROM monitoring_protocol_queries query
                       WHERE query.project_id = protocol.project_id
                         AND query.protocol_id = protocol.id)
               FROM monitoring_protocols protocol
               WHERE protocol.id = %s AND protocol.project_id = %s""",
            (protocol_id, project_id),
        ).fetchone()
    assert row is not None
    return row[0], int(row[1]), int(row[2])


def _project_monitoring_counts(project_id: UUID) -> tuple[int, int, int]:
    with psycopg.connect(ADMIN_URL) as admin:
        row = admin.execute(
            """SELECT
                 (SELECT count(*) FROM monitoring_queries WHERE project_id = %s),
                 (SELECT count(*) FROM monitoring_query_suggestions WHERE project_id = %s),
                 (SELECT count(*) FROM monitoring_protocol_queries WHERE project_id = %s)""",
            (project_id, project_id, project_id),
        ).fetchone()
    assert row is not None
    return int(row[0]), int(row[1]), int(row[2])
