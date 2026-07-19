from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import hashlib
import os
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
import pytest

from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.catalog.domain import Confidentiality, PublicCitation, SubjectRole, UsageRights
from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.knowledge import KnowledgeApplication
from geo_core.knowledge.domain import KnowledgeConflict, KnowledgeForbidden
from geo_core.placements.application import PlacementApplication
from geo_core.placements.postgres_uow import placement_uow_factory
from geo_core.placements.worker_composition import (
    EvidencePackHandler,
    PlacementWorkerDispatcher,
)
from geo_core.placements.worker_repository import PlacementWorkerRepository
from geo_core.project_scope import set_project_scope
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


def test_concurrent_fact_promotion_is_idempotent_and_pack_requires_verified_lineage() -> None:
    suffix = uuid4().hex[:10]
    app_login, worker_login = f"geo_fact_app_{suffix}", f"geo_fact_worker_{suffix}"
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
        seeded = seed_project(admin, suffix=f"fact-evidence-{suffix}")
        foreign = seed_project(admin, suffix=f"fact-evidence-foreign-{suffix}")
        lineage = _seed_knowledge_chain(admin, seeded)
        foreign_lineage = _seed_knowledge_chain(admin, foreign)
        campaign_id, brief_version_id = _seed_brief(admin, seeded, suffix)
        legacy_evidence_id = _seed_unverified_approved_fact(admin, seeded, lineage)
        admin.commit()

    app_url = login_url(ADMIN_URL, user=app_login, password=app_password)
    worker_url = login_url(ADMIN_URL, user=worker_login, password=worker_password)
    principal = AccessPrincipal(
        identity_id=seeded["owner"],
        actor_id=f"fact-evidence-{suffix}",
        tenant_id=seeded["tenant"],
        memberships=(
            MembershipRecord(seeded["project"], seeded["tenant"], "admin"),
        ),
        auth_method="development",
    )
    knowledge = KnowledgeApplication(app_url)
    placements = PlacementApplication(placement_uow_factory(lambda: psycopg.connect(app_url)))
    try:
        promotion_key = f"fact-evidence:{lineage['fact']}"
        proposal = knowledge.evidence_proposal(
            principal,
            project_id=seeded["project"],
            fact_id=lineage["fact"],
        )
        assert proposal["promotable"] is True
        assert proposal["existing"] is None
        pending = knowledge.evidence_proposal(
            principal,
            project_id=seeded["project"],
            fact_id=lineage["pending_fact"],
        )
        assert pending["promotable"] is False
        assert set(pending["blockers"]) >= {
            "fact_not_approved",
            "fact_review_metadata_missing",
        }
        with pytest.raises(
            KnowledgeConflict,
            match="fact_not_approved, fact_review_metadata_missing",
        ):
            _promote(
                knowledge,
                principal,
                seeded,
                lineage["pending_fact"],
                idempotency_key=f"fact-evidence:pending:{suffix}",
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    _promote,
                    knowledge,
                    principal,
                    seeded,
                    lineage["fact"],
                    idempotency_key=promotion_key,
                )
                for _ in range(2)
            ]
            results = [future.result(timeout=15) for future in futures]

        assert sorted(result["outcome"] for result in results) == ["created", "existing"]
        evidence_ids = {result["evidence"]["id"] for result in results}
        assert len(evidence_ids) == 1
        evidence_id = evidence_ids.pop()
        repeated = _promote(
            knowledge,
            principal,
            seeded,
            lineage["fact"],
            idempotency_key=promotion_key,
        )
        assert repeated["outcome"] == "existing"
        assert repeated["evidence"]["id"] == evidence_id
        with pytest.raises(KnowledgeConflict, match="different promotion metadata"):
            _promote(
                knowledge,
                principal,
                seeded,
                lineage["fact"],
                idempotency_key=promotion_key,
                title="Changed metadata under the same key",
            )
        new_key_replay = _promote(
            knowledge,
            principal,
            seeded,
            lineage["fact"],
            idempotency_key=f"fact-evidence:new-key:{lineage['fact']}",
            title="A different key still reuses immutable Evidence",
        )
        assert new_key_replay["evidence"]["id"] == evidence_id

        with ThreadPoolExecutor(max_workers=2) as executor:
            different_key_results = [
                future.result(timeout=15)
                for future in (
                    executor.submit(
                        _promote,
                        knowledge,
                        principal,
                        seeded,
                        lineage["second_fact"],
                        idempotency_key=f"fact-evidence:second:{index}:{suffix}",
                    )
                    for index in range(2)
                )
            ]
        assert sorted(item["outcome"] for item in different_key_results) == [
            "created",
            "existing",
        ]
        second_evidence_ids = {
            item["evidence"]["id"] for item in different_key_results
        }
        assert len(second_evidence_ids) == 1
        second_evidence_id = second_evidence_ids.pop()
        with pytest.raises(KnowledgeConflict, match="different Knowledge Fact"):
            _promote(
                knowledge,
                principal,
                seeded,
                lineage["second_fact"],
                idempotency_key=promotion_key,
            )

        foreign_principal = AccessPrincipal(
            identity_id=foreign["owner"],
            actor_id=f"fact-evidence-foreign-{suffix}",
            tenant_id=foreign["tenant"],
            memberships=(
                MembershipRecord(foreign["project"], foreign["tenant"], "admin"),
            ),
            auth_method="development",
        )
        foreign_result = _promote(
            knowledge,
            foreign_principal,
            foreign,
            foreign_lineage["fact"],
            idempotency_key=promotion_key,
        )
        with pytest.raises(KnowledgeForbidden):
            knowledge.evidence_proposal(
                principal,
                project_id=foreign["project"],
                fact_id=foreign_lineage["fact"],
            )
        with psycopg.connect(app_url) as scoped:
            set_project_scope(scoped, seeded["project"])
            assert scoped.execute(
                """SELECT count(*) FROM knowledge_fact_evidence_lineages
                   WHERE project_id = %s AND evidence_item_id = %s""",
                (foreign["project"], foreign_result["evidence"]["id"]),
            ).fetchone()[0] == 0

        with psycopg.connect(ADMIN_URL) as admin:
            row = admin.execute(
                """SELECT source_id, source_revision_value, fact_lineage_status
                   FROM evidence_items WHERE id = %s AND project_id = %s""",
                (evidence_id, seeded["project"]),
            ).fetchone()
            assert row == (lineage["fact"], lineage["fact_hash"], "verified")
            stored = admin.execute(
                """SELECT pipeline_run_id, knowledge_source_id, knowledge_document_id,
                          knowledge_chunk_id, knowledge_fact_id, idempotency_key,
                          promotion_request_hash, lineage_contract_version,
                          source_content_hash, document_cleaned_text_hash, chunk_text_hash,
                          fact_statement_hash, evidence_snapshot_hash
                   FROM knowledge_fact_evidence_lineages
                   WHERE evidence_item_id = %s AND project_id = %s""",
                (evidence_id, seeded["project"]),
            ).fetchone()
            assert stored == (
                lineage["run"],
                lineage["source"],
                lineage["document"],
                lineage["chunk"],
                lineage["fact"],
                promotion_key,
                repeated["lineage"]["promotion_request_hash"],
                "knowledge-fact-evidence-v1",
                lineage["source_hash"],
                lineage["document_hash"],
                lineage["chunk_hash"],
                lineage["fact_hash"],
                lineage["fact_hash"],
            )

        attempt, job = placements.create_evidence_attempt(
            project_id=seeded["project"],
            campaign_id=campaign_id,
            brief_version_id=brief_version_id,
            idempotency_key=f"fact-evidence-pack-{suffix}",
        )
        store = PostgresDurableJobStore(lambda: psycopg.connect(worker_url))
        repository = PlacementWorkerRepository(store)
        dispatcher = PlacementWorkerDispatcher(
            store=store,
            handlers={"evidence_pack.build": EvidencePackHandler(repository)},
            worker_id=f"fact-evidence-worker-{suffix}",
            lease_for=timedelta(seconds=30),
        )
        assert dispatcher.process(job_id=job.id, project_id=seeded["project"])["status"] == "ready"
        items = placements.list_evidence_attempt_items(
            project_id=seeded["project"],
            campaign_id=campaign_id,
            attempt_id=attempt.id,
        )
        assert {item["id"] for item in items} == {evidence_id, second_evidence_id}
        assert legacy_evidence_id not in {item["id"] for item in items}
        first_item = next(item for item in items if item["id"] == evidence_id)
        pack_lineage = first_item["knowledge_lineage"]
        assert pack_lineage["knowledge_fact_id"] == str(lineage["fact"])
        assert pack_lineage["evidence_item_id"] == str(evidence_id)
        assert pack_lineage["idempotency_key"] == promotion_key
        assert (
            pack_lineage["promotion_request_hash"]
            == repeated["lineage"]["promotion_request_hash"]
        )
        assert pack_lineage["evidence_snapshot_hash"] == lineage["fact_hash"]
        assert all(
            item["knowledge_lineage"]["lineage_contract_version"]
            == "knowledge-fact-evidence-v1"
            for item in items
        )
    finally:
        with psycopg.connect(ADMIN_URL) as admin:
            cleanup_projects(
                admin,
                projects=[seeded, foreign],
                tenant_ids=[seeded["tenant"], foreign["tenant"]],
                app_login=app_login,
                worker_login=worker_login,
            )
            admin.commit()


def _promote(
    application: KnowledgeApplication,
    principal: AccessPrincipal,
    seeded: dict[str, UUID],
    fact_id: UUID,
    *,
    idempotency_key: str,
    title: str = "Governed Fact Evidence",
) -> dict[str, Any]:
    return dict(
        application.promote_fact_to_evidence(
            principal,
            project_id=seeded["project"],
            fact_id=fact_id,
            idempotency_key=idempotency_key,
            title=title,
            subject_entity_id=seeded["entity"],
            subject_role=SubjectRole.PRODUCT,
            usage_rights=UsageRights.PUBLIC_REFERENCE,
            confidentiality=Confidentiality.PUBLIC,
            public_citation=PublicCitation(
                True,
                "https://source.example/fact",
                "Official source",
                "Official source",
                False,
                True,
            ),
        )
    )


def _seed_knowledge_chain(
    connection: psycopg.Connection[Any], seeded: dict[str, UUID]
) -> dict[str, Any]:
    ids = {
        name: uuid4()
        for name in (
            "source",
            "run",
            "document",
            "chunk",
            "fact",
            "second_fact",
            "pending_fact",
        )
    }
    raw = b"Official product material"
    cleaned = "Official product material"
    statement = "The product has an official documented capability."
    second_statement = "The product has a second documented capability."
    values: dict[str, Any] = {
        **ids,
        "source_hash": hashlib.sha256(raw).hexdigest(),
        "document_hash": hashlib.sha256(cleaned.encode()).hexdigest(),
        "chunk_hash": hashlib.sha256(cleaned.encode()).hexdigest(),
        "fact_hash": hashlib.sha256(statement.encode()).hexdigest(),
        "second_fact_hash": hashlib.sha256(second_statement.encode()).hexdigest(),
        "statement": statement,
    }
    connection.execute(
        """INSERT INTO knowledge_sources
             (id, project_id, logical_source_id, source_kind, title, source_url,
              media_type, status, raw_content, content_hash, created_by)
           VALUES (%s, %s, %s, 'url', 'Official source',
                   'https://source.example/fact', 'text/plain', 'ready', %s, %s, %s)""",
        (
            ids["source"],
            seeded["project"],
            ids["source"],
            raw,
            values["source_hash"],
            seeded["owner"],
        ),
    )
    connection.execute(
        """INSERT INTO knowledge_pipeline_runs
             (id, project_id, source_id, status, input_hash, created_by, completed_at)
           VALUES (%s, %s, %s, 'succeeded', %s, %s, clock_timestamp())""",
        (ids["run"], seeded["project"], ids["source"], "1" * 64, seeded["owner"]),
    )
    connection.execute(
        """INSERT INTO knowledge_documents
             (id, project_id, pipeline_run_id, source_id, parser_version, raw_text,
              cleaned_text, raw_text_hash, cleaned_text_hash)
           VALUES (%s, %s, %s, %s, 'test-v1', %s, %s, %s, %s)""",
        (
            ids["document"], seeded["project"], ids["run"], ids["source"], cleaned,
            cleaned, values["document_hash"], values["document_hash"],
        ),
    )
    connection.execute(
        """INSERT INTO knowledge_chunks
             (id, project_id, pipeline_run_id, source_id, document_id, chunk_index,
              text, text_hash, char_count, status)
           VALUES (%s, %s, %s, %s, %s, 0, %s, %s, %s, 'active')""",
        (
            ids["chunk"], seeded["project"], ids["run"], ids["source"], ids["document"],
            cleaned, values["chunk_hash"], len(cleaned),
        ),
    )
    connection.execute(
        """INSERT INTO knowledge_fact_candidates
             (id, project_id, pipeline_run_id, source_id, document_id, chunk_id,
              statement, statement_hash, status, reviewed_by, reviewed_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'approved', %s,
                   clock_timestamp())""",
        (
            ids["fact"], seeded["project"], ids["run"], ids["source"], ids["document"],
            ids["chunk"], statement, values["fact_hash"], seeded["owner"],
        ),
    )
    connection.execute(
        """INSERT INTO knowledge_fact_candidates
             (id, project_id, pipeline_run_id, source_id, document_id, chunk_id,
              statement, statement_hash, status, reviewed_by, reviewed_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'approved', %s,
                   clock_timestamp())""",
        (
            ids["second_fact"], seeded["project"], ids["run"], ids["source"],
            ids["document"], ids["chunk"], second_statement, values["second_fact_hash"],
            seeded["owner"],
        ),
    )
    pending_statement = "This candidate has not completed governed human review."
    connection.execute(
        """INSERT INTO knowledge_fact_candidates
             (id, project_id, pipeline_run_id, source_id, document_id, chunk_id,
              statement, statement_hash, status)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending_review')""",
        (
            ids["pending_fact"],
            seeded["project"],
            ids["run"],
            ids["source"],
            ids["document"],
            ids["chunk"],
            pending_statement,
            hashlib.sha256(pending_statement.encode()).hexdigest(),
        ),
    )
    return values


def _seed_brief(
    connection: psycopg.Connection[Any], seeded: dict[str, UUID], suffix: str
) -> tuple[UUID, UUID]:
    destination_id, campaign_id, opportunity_id, brief_id, version_id = (
        uuid4() for _ in range(5)
    )
    connection.execute(
        """INSERT INTO publication_destinations
             (id, project_id, publication_channel, destination_key, canonical_url,
              canonical_host, allowed_hosts, policy_status)
           VALUES (%s, %s, 'owned_site', %s, 'https://source.example/',
                   'source.example', ARRAY['source.example'], 'approved')""",
        (destination_id, seeded["project"], f"fact-{suffix}"),
    )
    connection.execute(
        """INSERT INTO geo_campaigns
             (id, project_id, market_profile_id, primary_product_entity_id, name, created_by)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (
            campaign_id, seeded["project"], seeded["market"], seeded["entity"],
            f"Fact evidence {suffix}", seeded["owner"],
        ),
    )
    connection.execute(
        """INSERT INTO placement_opportunities
             (id, project_id, campaign_id, destination_id, opportunity_ref, rationale, status)
           VALUES (%s, %s, %s, %s, %s, 'fact evidence integration', 'briefing')""",
        (opportunity_id, seeded["project"], campaign_id, destination_id, f"fact:{suffix}"),
    )
    connection.execute(
        """INSERT INTO opportunity_prompt_release_bindings
             (project_id, campaign_id, opportunity_id, destination_id, binding_version,
              binding_state, changed_by)
           VALUES (%s, %s, %s, %s, 1, 'unbound', %s)""",
        (
            seeded["project"], campaign_id, opportunity_id, destination_id,
            seeded["owner"],
        ),
    )
    connection.execute(
        """INSERT INTO placement_briefs
             (id, project_id, campaign_id, opportunity_id, destination_id,
              primary_brand_entity_id)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (
            brief_id, seeded["project"], campaign_id, opportunity_id, destination_id,
            seeded["entity"],
        ),
    )
    connection.execute(
        """INSERT INTO placement_brief_versions
             (id, project_id, campaign_id, opportunity_id, destination_id, brief_id,
              version_number, goals, constraints, content_hash, created_by)
           VALUES (%s, %s, %s, %s, %s, %s, 1, '{}'::jsonb, '{}'::jsonb, %s, %s)""",
        (
            version_id, seeded["project"], campaign_id, opportunity_id, destination_id,
            brief_id, "d" * 64, seeded["owner"],
        ),
    )
    return campaign_id, version_id


def _seed_unverified_approved_fact(
    connection: psycopg.Connection[Any],
    seeded: dict[str, UUID],
    lineage: dict[str, Any],
) -> UUID:
    evidence_id = uuid4()
    legacy_key = f"legacy-relational-v1:{evidence_id}"
    connection.execute("SET LOCAL session_replication_role = 'replica'")
    connection.execute(
        """INSERT INTO evidence_items
             (id, project_id, item_type, source_id, subject_entity_id, subject_role,
              snapshot_text, snapshot_hash, source_revision_kind, source_revision_value,
              usage_rights, confidentiality, fact_lineage_status)
           VALUES (%s, %s, 'approved_fact', %s, %s, 'product', %s, %s,
                   'content_hash', %s, 'owned', 'internal', 'legacy_unverified')""",
        (
            evidence_id, seeded["project"], lineage["source"], seeded["entity"],
            lineage["statement"], lineage["fact_hash"], lineage["source_hash"],
        ),
    )
    connection.execute(
        """INSERT INTO knowledge_fact_evidence_lineages
             (project_id, pipeline_run_id, knowledge_source_id, knowledge_document_id,
              knowledge_chunk_id, knowledge_fact_id, evidence_item_id, evidence_title,
              promoted_by, idempotency_key, promotion_request_hash,
              source_content_hash, document_cleaned_text_hash, chunk_text_hash,
              fact_statement_hash, evidence_snapshot_hash, lineage_contract_version)
           VALUES (%s, %s, %s, %s, %s, %s, %s, 'Legacy audit Evidence', %s,
                   %s, %s, %s, %s, %s, %s, %s, 'legacy-relational-v1')""",
        (
            seeded["project"], lineage["run"], lineage["source"], lineage["document"],
            lineage["chunk"], lineage["fact"], evidence_id, seeded["owner"], legacy_key,
            hashlib.sha256(legacy_key.encode()).hexdigest(), lineage["source_hash"],
            lineage["document_hash"], lineage["chunk_hash"], lineage["fact_hash"],
            lineage["fact_hash"],
        ),
    )
    connection.execute("SET LOCAL session_replication_role = 'origin'")
    return evidence_id
