from datetime import UTC, datetime
from decimal import Decimal
import hashlib
from uuid import UUID, uuid4

from psycopg.conninfo import conninfo_to_dict, make_conninfo

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
