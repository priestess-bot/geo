from __future__ import annotations

from decimal import Decimal
import hashlib
import json
import os
from typing import Any
from uuid import UUID, uuid4

from alembic import command
from alembic.script import ScriptDirectory
import psycopg
import pytest

from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.catalog.domain import (
    Confidentiality,
    PublicCitation,
    SubjectRole,
    UsageRights,
)
from geo_core.knowledge import KnowledgeApplication
from geo_core.knowledge.domain import SourceInput
from geo_core.model_gateway import ModelGatewayResult
from tests.integration.test_batch2_migrations_postgres import (
    _seed_legacy_fixture,
    _temporary_database,
)
from tests.integration.test_knowledge_rag_postgres import _dispatcher


ADMIN_URL = os.getenv("GEO_ACCESS_TEST_ADMIN_DATABASE_URL", "").strip()
MINIO_ENDPOINT = os.getenv("GEO_F019_TEST_MINIO_ENDPOINT", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not ADMIN_URL,
        reason="GEO_ACCESS_TEST_ADMIN_DATABASE_URL is required",
    ),
    pytest.mark.skipif(
        not MINIO_ENDPOINT,
        reason="GEO_F019_TEST_MINIO_ENDPOINT is required",
    ),
]

REVISION_TEXT = (
    "Legacy Product is documented in the upgraded Knowledge source. "
    "Legacy Product remains traceable after migration."
)


class _LegacySourceGateway:
    provider = "legacy-upgrade-integration"

    def generate(self, request: Any, *, policy: Any, budget: Any) -> ModelGatewayResult:
        del policy
        budget.consume()
        payload = json.loads(request.messages[1]["content"])
        assert REVISION_TEXT in payload["content"]
        output = {
            "facts": [
                {
                    "text": "Legacy Product is documented in the upgraded Knowledge source.",
                    "source_quote": (
                        "Legacy Product is documented in the upgraded Knowledge source."
                    ),
                }
            ],
            "entities": [
                {
                    "entity_type": "Product",
                    "name": "Legacy Product",
                    "source_quote": "Legacy Product",
                }
            ],
            "relations": [],
        }
        response_hash = hashlib.sha256(
            json.dumps(output, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        return ModelGatewayResult(
            output=output,
            call_log_id=uuid4(),
            provider_request_id=f"legacy-upgrade-{uuid4()}",
            configured_model=request.configured_model,
            provider_reported_model=request.configured_model,
            prompt_tokens=30,
            completion_tokens=15,
            cost_usd=Decimal("0.001"),
            finish_reason="stop",
            response_hash=response_hash,
        )


def test_legacy_knowledge_survives_head_upgrade_and_current_rag_workflow() -> None:
    with _temporary_database() as (database_url, configuration):
        command.upgrade(configuration, "0010_campaign_destinations")
        with psycopg.connect(database_url) as connection:
            fixture = _seed_legacy_fixture(connection)

        command.upgrade(configuration, "head")
        with psycopg.connect(database_url) as connection:
            assert (
                connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
                == ScriptDirectory.from_config(configuration).get_current_head()
            )
            connection.execute(
                """INSERT INTO project_memberships
                     (tenant_id, project_id, identity_id, role)
                   VALUES (%s, %s, %s, 'admin')""",
                (fixture["tenant"], fixture["project"], fixture["owner"]),
            )
            source = connection.execute(
                """SELECT id, logical_source_id, status, content_hash
                   FROM knowledge_sources WHERE id = %s AND project_id = %s""",
                (fixture["source"], fixture["project"]),
            ).fetchone()
            assert source == (
                fixture["source"],
                fixture["source"],
                "ready",
                fixture["source_content_hash"],
            )
            fact = connection.execute(
                """SELECT id, document_id, status, lifecycle_status, statement_hash
                   FROM knowledge_fact_candidates
                   WHERE id = %s AND project_id = %s""",
                (fixture["fact"], fixture["project"]),
            ).fetchone()
            assert fact == (
                fixture["fact"],
                fixture["document"],
                "approved",
                "active",
                fixture["fact_statement_hash"],
            )
            legacy_evidence = connection.execute(
                """SELECT source_id, snapshot_hash, fact_lineage_status
                   FROM evidence_items WHERE id = %s AND project_id = %s""",
                (fixture["evidence"], fixture["project"]),
            ).fetchone()
            assert legacy_evidence == (
                fixture["source"],
                fixture["fact_statement_hash"],
                "legacy_unverified",
            )
            legacy_lineage = connection.execute(
                """SELECT pipeline_run_id, knowledge_source_id,
                          knowledge_document_id, knowledge_chunk_id,
                          knowledge_fact_id, evidence_item_id,
                          lineage_contract_version
                   FROM knowledge_fact_evidence_lineages
                   WHERE project_id = %s AND knowledge_fact_id = %s""",
                (fixture["project"], fixture["fact"]),
            ).fetchone()
            assert legacy_lineage == (
                fixture["run"],
                fixture["source"],
                fixture["document"],
                fixture["chunk"],
                fixture["fact"],
                fixture["evidence"],
                "legacy-relational-v1",
            )
            connection.commit()

        principal = AccessPrincipal(
            identity_id=fixture["owner"],
            actor_id=f"legacy-upgrade-{fixture['owner']}",
            tenant_id=fixture["tenant"],
            memberships=(
                MembershipRecord(
                    fixture["project"],
                    fixture["tenant"],
                    "admin",
                ),
            ),
            auth_method="development",
        )
        application = KnowledgeApplication(database_url)
        assert {
            item["id"]
            for item in application.list_sources(principal, project_id=fixture["project"])
        } == {fixture["source"]}
        assert {
            item["id"] for item in application.list_facts(principal, project_id=fixture["project"])
        } == {fixture["fact"]}

        suffix = uuid4().hex[:10]
        dispatcher = _dispatcher(database_url, suffix, gateway=_LegacySourceGateway())
        revised = application.create_source_revision(
            principal,
            project_id=fixture["project"],
            source_id=fixture["source"],
            source=SourceInput(
                source_kind="text",
                title="Legacy source current revision",
                source_url=None,
                filename="legacy-current.txt",
                media_type="text/plain",
                raw_content=REVISION_TEXT.encode(),
            ),
            idempotency_key=f"legacy-upgrade-revision-{suffix}",
        )
        revised_ids = _process_current_source(
            dispatcher,
            database_url=database_url,
            project_id=fixture["project"],
            created=revised,
        )
        reprocessed = application.reprocess_source(
            principal,
            project_id=fixture["project"],
            source_id=revised_ids["source_id"],
            idempotency_key=f"legacy-upgrade-reprocess-{suffix}",
        )
        current = _process_current_source(
            dispatcher,
            database_url=database_url,
            project_id=fixture["project"],
            created=reprocessed,
        )

        revisions = application.list_rag_revisions(principal, project_id=fixture["project"])
        assert len(revisions) == 2
        assert {(item["pipeline_run_id"], item["lifecycle_status"]) for item in revisions} == {
            (revised_ids["run_id"], "superseded"),
            (current["run_id"], "active"),
        }

        current_facts = application.list_facts(principal, project_id=fixture["project"])
        assert len(current_facts) == 1
        current_fact = current_facts[0]
        assert current_fact["pipeline_run_id"] == current["run_id"]
        assert current_fact["statement"] == (
            "Legacy Product is documented in the upgraded Knowledge source."
        )
        reviewed = application.review_fact(
            principal,
            project_id=fixture["project"],
            fact_id=current_fact["id"],
            decision="approved",
            notes="approved after legacy database upgrade",
        )
        assert reviewed["status"] == "approved"
        promoted = application.promote_fact_to_evidence(
            principal,
            project_id=fixture["project"],
            fact_id=current_fact["id"],
            idempotency_key=f"legacy-upgrade-promotion-{suffix}",
            title="Post-upgrade governed Fact Evidence",
            subject_entity_id=fixture["product"],
            subject_role=SubjectRole.PRODUCT,
            usage_rights=UsageRights.OWNED,
            confidentiality=Confidentiality.INTERNAL,
            public_citation=PublicCitation(disclosure_allowed=False),
        )
        assert promoted["outcome"] == "created"
        assert promoted["lineage"]["knowledge_fact_id"] == current_fact["id"]
        assert promoted["lineage"]["lineage_contract_version"] == ("knowledge-fact-evidence-v1")

        with psycopg.connect(database_url) as connection:
            retired_legacy = connection.execute(
                """SELECT fact.status, fact.lifecycle_status, chunk.status
                   FROM knowledge_fact_candidates AS fact
                   JOIN knowledge_chunks AS chunk
                     ON chunk.id = fact.chunk_id AND chunk.project_id = fact.project_id
                   WHERE fact.id = %s AND fact.project_id = %s""",
                (fixture["fact"], fixture["project"]),
            ).fetchone()
            assert retired_legacy == ("approved", "superseded", "disabled")
            assert (
                connection.execute(
                    """SELECT fact_lineage_status
                   FROM evidence_items WHERE id = %s AND project_id = %s""",
                    (fixture["evidence"], fixture["project"]),
                ).fetchone()[0]
                == "legacy_unverified"
            )
            assert (
                connection.execute(
                    """SELECT lineage_contract_version
                   FROM knowledge_fact_evidence_lineages
                   WHERE project_id = %s AND knowledge_fact_id = %s
                     AND evidence_item_id = %s""",
                    (fixture["project"], fixture["fact"], fixture["evidence"]),
                ).fetchone()[0]
                == "legacy-relational-v1"
            )
            new_evidence = connection.execute(
                """SELECT evidence.source_id, evidence.fact_lineage_status,
                          lineage.pipeline_run_id, lineage.knowledge_source_id,
                          lineage.knowledge_fact_id, lineage.lineage_contract_version
                   FROM evidence_items AS evidence
                   JOIN knowledge_fact_evidence_lineages AS lineage
                     ON lineage.evidence_item_id = evidence.id
                    AND lineage.project_id = evidence.project_id
                   WHERE evidence.id = %s AND evidence.project_id = %s""",
                (promoted["evidence"]["id"], fixture["project"]),
            ).fetchone()
            assert new_evidence == (
                current_fact["id"],
                "verified",
                current["run_id"],
                current["source_id"],
                current_fact["id"],
                "knowledge-fact-evidence-v1",
            )


def _process_current_source(
    dispatcher: Any,
    *,
    database_url: str,
    project_id: UUID,
    created: Any,
) -> dict[str, UUID]:
    process_job_id = created["job"]["id"]
    processed = dispatcher.process(job_id=process_job_id, project_id=project_id)
    assert processed["status"] == "succeeded", _job_failure(
        database_url, project_id, process_job_id
    )
    rag_job_id = UUID(str(processed["rag_job_id"]))
    extracted = dispatcher.process(job_id=rag_job_id, project_id=project_id)
    assert extracted["status"] == "succeeded", _job_failure(database_url, project_id, rag_job_id)
    return {
        "source_id": created["source"]["id"],
        "run_id": created["pipeline_run"]["id"],
        "process_job_id": process_job_id,
        "rag_job_id": rag_job_id,
    }


def _job_failure(database_url: str, project_id: UUID, job_id: UUID) -> tuple[Any, ...]:
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            """SELECT status, error_code, error_detail
               FROM durable_jobs WHERE id = %s AND project_id = %s""",
            (job_id, project_id),
        ).fetchone()
    return row or ("job_missing",)
