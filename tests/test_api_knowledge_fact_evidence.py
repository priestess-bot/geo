from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from geo_api.app_factory import create_api_app
from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.knowledge import KnowledgeApplication


class PrincipalServices:
    def __init__(self, principal: AccessPrincipal) -> None:
        self.principal = principal

    def authenticate(self, authentication: object) -> AccessPrincipal:
        del authentication
        return self.principal


def test_fact_evidence_post_requires_idempotency_and_forbids_derived_lineage(
    monkeypatch: Any,
) -> None:
    tenant_id, identity_id, project_id, fact_id, entity_id = (uuid4() for _ in range(5))
    principal = AccessPrincipal(
        identity_id=identity_id,
        actor_id="knowledge-fact-test",
        tenant_id=tenant_id,
        memberships=(MembershipRecord(project_id, tenant_id, "analyst"),),
        auth_method="development",
    )
    application = KnowledgeApplication("postgresql://unused")
    captured: dict[str, object] = {}

    def promote(_self: object, _principal: object, **values: object) -> dict[str, object]:
        captured.update(values)
        return _promotion_response(project_id, fact_id, identity_id, entity_id)

    monkeypatch.setattr(KnowledgeApplication, "promote_fact_to_evidence", promote)
    app = create_api_app(
        surface="internal",
        services=PrincipalServices(principal),  # type: ignore[arg-type]
        knowledge_application=application,
    )
    payload = {
        "title": "Governed Fact Evidence",
        "subject_entity_id": str(entity_id),
        "subject_role": "product",
        "usage_rights": "public_reference",
        "confidentiality": "public",
        "public_citation": {
            "disclosure_allowed": True,
            "source_url": "https://source.example/fact",
            "source_title": "Official source",
            "label": "Official source",
            "attribution_required": True,
        },
    }
    path = f"/v1/projects/{project_id}/knowledge/fact-candidates/{fact_id}/evidence"

    with TestClient(app) as client:
        missing_key = client.post(path, json=payload)
        derived = client.post(
            path,
            headers={"Idempotency-Key": "fact-key"},
            json={**payload, "source_id": str(uuid4())},
        )
        created = client.post(
            path,
            headers={"Idempotency-Key": "fact-key"},
            json=payload,
        )

    assert missing_key.status_code == 422
    assert derived.status_code == 422
    assert created.status_code == 200
    assert captured["idempotency_key"] == "fact-key"
    assert captured["fact_id"] == fact_id
    assert created.json()["lineage"]["promotion_request_hash"] == "1" * 64


def _promotion_response(
    project_id: UUID, fact_id: UUID, identity_id: UUID, entity_id: UUID
) -> dict[str, object]:
    evidence_id = uuid4()
    now = datetime(2026, 7, 19, tzinfo=UTC)
    return {
        "outcome": "created",
        "evidence": {
            "id": evidence_id,
            "project_id": project_id,
            "title": "Governed Fact Evidence",
            "item_type": "approved_fact",
            "subject_entity_id": entity_id,
            "subject_role": "product",
            "snapshot": {"kind": "text", "text": "Fact", "uri": None, "sha256": "a" * 64},
            "source_revision": {"kind": "content_hash", "value": "b" * 64},
            "usage_rights": "public_reference",
            "confidentiality": "public",
            "public_citation": {
                "disclosure_allowed": True,
                "source_url": "https://source.example/fact",
                "source_title": "Official source",
                "label": "Official source",
                "quotation_allowed": False,
                "attribution_required": True,
            },
            "eligible_for_generation": True,
            "eligible_for_publication": True,
            "created_at": now,
        },
        "lineage": {
            "project_id": project_id,
            "pipeline_run_id": uuid4(),
            "knowledge_source_id": uuid4(),
            "knowledge_document_id": uuid4(),
            "knowledge_chunk_id": uuid4(),
            "knowledge_fact_id": fact_id,
            "evidence_item_id": evidence_id,
            "evidence_title": "Governed Fact Evidence",
            "promoted_by": identity_id,
            "promoted_at": now,
            "idempotency_key": "fact-key",
            "promotion_request_hash": "1" * 64,
            "lineage_contract_version": "knowledge-fact-evidence-v1",
            "source_content_hash": "2" * 64,
            "document_cleaned_text_hash": "3" * 64,
            "chunk_text_hash": "4" * 64,
            "fact_statement_hash": "5" * 64,
            "evidence_snapshot_hash": "a" * 64,
        },
    }
