from datetime import UTC, datetime
from decimal import Decimal
import hashlib
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from geo_core.jobs.outbox import PostgresOutboxStore
from geo_core.model_gateway import ModelGatewayRequest, ModelGatewayResult
from geo_core.model_gateway.contracts import RetryableModelGatewayError
from geo_core.object_store import ObjectStoreError, RetrievedObject, StoredObject
from geo_core.placements.url_verifier import PermanentVerificationError, UrlVerificationResult


class FakeGateway:
    provider = "deepseek"

    def __init__(self, evidence_id: UUID) -> None:
        self.evidence_id = evidence_id
        self.requests: list[ModelGatewayRequest] = []

    def generate(self, request, *, policy, budget):
        del policy
        self.requests.append(request)
        budget.consume()
        return ModelGatewayResult(
            output={
                "content_json": {
                    "disclosure": "Posted on behalf of the brand.",
                    "cta_url": "https://brand.example/product",
                },
                "rendered_text": "扫地机器人评测记录了两居室中的日常清洁体验。",
                "claims": [
                    {
                        "text": "消费者描述了两居室的日常清洁体验。",
                        "kind": "experience",
                        "support_status": "supported",
                        "evidence_item_ids": [str(self.evidence_id)],
                    }
                ],
                "internal_evidence_refs": [str(self.evidence_id)],
                "public_citation_refs": [str(self.evidence_id)],
            },
            call_log_id=uuid4(),
            provider_request_id="integration-request",
            configured_model="deepseek-v4-flash",
            provider_reported_model="deepseek-v4-flash",
            prompt_tokens=10,
            completion_tokens=20,
            cost_usd=Decimal("0.001"),
            finish_reason="stop",
            response_hash="c" * 64,
        )


class FakeVerifier:
    def verify(self, url: str, **expected):
        assert expected["expected_text_fragments"]
        assert expected["required_disclosures"]
        assert expected["expected_links"]
        return UrlVerificationResult(
            True, 200, url, datetime.now(UTC), "d" * 64, True, True, True, True
        )


class RetryableGateway:
    provider = "deepseek"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, request, *, policy, budget):
        del request, policy
        budget.consume()
        self.calls += 1
        raise RetryableModelGatewayError("temporary provider failure")


class PermanentVerifier:
    def verify(self, url: str, **expected):
        del url, expected
        raise PermanentVerificationError("verification URL must use HTTPS")


class MemoryArtifactStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail_next = True

    def put_object(self, *, key, content, content_type, expected_hash):
        if self.fail_next:
            self.fail_next = False
            raise ObjectStoreError("temporary MinIO failure")
        digest = hashlib.sha256(content).hexdigest()
        assert digest == expected_hash
        self.objects[key] = content
        return StoredObject(
            f"s3://geo-artifacts/{key}",
            "geo-artifacts",
            key,
            content_type,
            digest,
            "integration-etag",
        )

    def get_object(self, *, key, expected_hash):
        content = self.objects[key]
        digest = hashlib.sha256(content).hexdigest()
        assert digest == expected_hash
        return RetrievedObject(
            content,
            "geo-artifacts",
            key,
            "application/json",
            digest,
            "integration-etag",
        )


def assert_run_scoped_outbox_delivery(
    *,
    admin_url: str,
    worker_url: str,
    run_id: str,
    expected_messages: set[tuple[UUID, UUID]],
) -> None:
    worker_id = f"integration-relay-{run_id}"
    with psycopg.connect(admin_url, autocommit=True) as claim_lock:
        claim_lock.execute("SELECT pg_advisory_lock(1501520250719)")
        try:
            with psycopg.connect(admin_url) as admin:
                owned_rows = admin.execute(
                    """UPDATE broker_outbox
                       SET available_at = '-infinity'::timestamptz
                       WHERE job_id = ANY(%s) AND published_at IS NULL
                       RETURNING project_id, job_id""",
                    ([job_id for _, job_id in expected_messages],),
                ).fetchall()
                assert set(owned_rows) == expected_messages
                admin.commit()
            outbox = PostgresOutboxStore(lambda: psycopg.connect(worker_url))
            messages = outbox.claim(
                worker_id=worker_id,
                batch_size=len(expected_messages),
                lease_seconds=30,
            )
            assert {(item.project_id, item.job_id) for item in messages} == expected_messages
            for message in messages:
                assert outbox.acknowledge(message, worker_id=worker_id)
        finally:
            claim_lock.execute("SELECT pg_advisory_unlock(1501520250719)")


def login_url(base: str, *, user: str, password: str) -> str:
    values = conninfo_to_dict(base)
    values.update(user=user, password=password)
    return make_conninfo(**values)


def seed_project(connection, *, suffix: str) -> dict[str, UUID]:
    ids = {name: uuid4() for name in ("tenant", "owner", "reviewer", "project", "entity", "market")}
    connection.execute("INSERT INTO tenants(id, name) VALUES (%s, %s)", (ids["tenant"], suffix))
    connection.execute(
        """INSERT INTO identities(id, issuer, subject)
           VALUES (%s, 'integration', %s), (%s, 'integration', %s)""",
        (ids["owner"], f"owner-{suffix}", ids["reviewer"], f"reviewer-{suffix}"),
    )
    connection.execute(
        "INSERT INTO projects(id, tenant_id, name) VALUES (%s, %s, %s)",
        (ids["project"], ids["tenant"], suffix),
    )
    connection.execute(
        """INSERT INTO project_memberships(tenant_id, project_id, identity_id, role)
           VALUES (%s, %s, %s, 'admin'), (%s, %s, %s, 'admin')""",
        (
            ids["tenant"],
            ids["project"],
            ids["owner"],
            ids["tenant"],
            ids["project"],
            ids["reviewer"],
        ),
    )
    connection.execute(
        """INSERT INTO product_entities(id, project_id, entity_type, canonical_name)
           VALUES (%s, %s, 'product', %s)""",
        (ids["entity"], ids["project"], f"Product {suffix}"),
    )
    connection.execute(
        """INSERT INTO market_profiles(id, project_id, market_code, locale, timezone)
           VALUES (%s, %s, 'AU', 'en-AU', 'UTC')""",
        (ids["market"], ids["project"]),
    )
    return ids


def seed_frozen_protocol(
    connection,
    *,
    project_id: UUID,
    campaign_id: UUID,
    market_profile_id: UUID,
    monitoring_query_id: UUID,
    actor_id: UUID,
) -> UUID:
    protocol_id, suggestion_id = uuid4(), uuid4()
    connection.execute(
        """INSERT INTO monitoring_protocols
             (id, project_id, campaign_id, market_profile_id, name, platform,
              locale, device, sample_size, window_days, created_by)
           VALUES (%s, %s, %s, %s, %s, 'chatgpt_search', 'en-AU', 'desktop',
                   1, 84, %s)""",
        (
            protocol_id, project_id, campaign_id, market_profile_id,
            f"Frozen placement protocol {protocol_id}", actor_id,
        ),
    )
    connection.execute(
        """INSERT INTO monitoring_query_suggestions
             (id, project_id, protocol_id, query_text, query_kind, rationale,
              status, suggested_by, decided_by, decided_at)
           VALUES (%s, %s, %s, 'best robot vacuum', 'recommendation',
                   'placement integration', 'approved', %s, %s, clock_timestamp())""",
        (suggestion_id, project_id, protocol_id, actor_id, actor_id),
    )
    connection.execute(
        """INSERT INTO monitoring_protocol_queries
             (project_id, protocol_id, monitoring_query_id, suggestion_id, ordinal,
              query_text_snapshot, query_kind_snapshot, locale_snapshot, approved_by)
           VALUES (%s, %s, %s, %s, 1, 'best robot vacuum',
                   'recommendation', 'en-AU', %s)""",
        (project_id, protocol_id, monitoring_query_id, suggestion_id, actor_id),
    )
    connection.execute(
        """UPDATE monitoring_protocols
           SET status = 'approved', approved_by = %s, approved_at = clock_timestamp()
           WHERE id = %s AND project_id = %s""",
        (actor_id, protocol_id, project_id),
    )
    connection.execute(
        """UPDATE monitoring_protocols
           SET status = 'frozen', protocol_hash = %s, frozen_by = %s,
               frozen_at = clock_timestamp()
           WHERE id = %s AND project_id = %s""",
        ("f" * 64, actor_id, protocol_id, project_id),
    )
    return protocol_id


def cleanup_projects(
    connection,
    *,
    projects: list[dict[str, UUID]],
    tenant_ids: list[UUID],
    app_login: str,
    worker_login: str | None = None,
) -> None:
    project_ids = [item["project"] for item in projects]
    identity_ids = [
        identity_id for item in projects for identity_id in (item["owner"], item["reviewer"])
    ]
    connection.execute("SET LOCAL session_replication_role = replica")
    project_tables = connection.execute(
        """SELECT table_name FROM information_schema.columns
           WHERE table_schema = 'public' AND column_name = 'project_id'"""
    ).fetchall()
    for (table,) in project_tables:
        connection.execute(
            sql.SQL("DELETE FROM {} WHERE project_id = ANY(%s)").format(sql.Identifier(table)),
            (project_ids,),
        )
    connection.execute("DELETE FROM projects WHERE id = ANY(%s)", (project_ids,))
    connection.execute("DELETE FROM identities WHERE id = ANY(%s)", (identity_ids,))
    connection.execute("DELETE FROM tenants WHERE id = ANY(%s)", (tenant_ids,))
    connection.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(app_login)))
    if worker_login is not None:
        connection.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(worker_login)))
