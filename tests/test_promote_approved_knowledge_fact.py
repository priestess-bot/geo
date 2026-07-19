from __future__ import annotations

from argparse import Namespace
from typing import Any
from uuid import uuid4

from scripts.promote_approved_knowledge_fact import promote


class FakeApi:
    def __init__(self, proposal: dict[str, Any], result: dict[str, Any]) -> None:
        self.proposal = proposal
        self.result = result
        self.calls: list[tuple[str, str, dict[str, object] | None, str]] = []

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, object] | None = None,
        *,
        key: str = "",
    ) -> dict[str, Any]:
        self.calls.append((method, path, body, key))
        return self.proposal if method == "GET" else self.result


def test_promotion_script_uses_service_proposal_and_submits_only_governance_metadata() -> None:
    project_id, fact_id, entity_id, evidence_id, source_id = (str(uuid4()) for _ in range(5))
    proposal = _proposal(project_id, fact_id)
    result = {
        "outcome": "created",
        "evidence": {
            "id": evidence_id,
            "eligible_for_generation": True,
            "eligible_for_publication": True,
        },
        "lineage": {
            "knowledge_source_id": source_id,
            "evidence_snapshot_hash": "a" * 64,
            "lineage_contract_version": "knowledge-fact-evidence-v1",
        },
    }
    api = FakeApi(proposal, result)

    receipt = promote(api, _args(project_id, fact_id, entity_id, dry_run=False))  # type: ignore[arg-type]

    assert receipt["outcome"] == "created"
    assert receipt["source_id"] == source_id
    assert [call[0] for call in api.calls] == ["GET", "POST"]
    _, path, payload, key = api.calls[1]
    assert path.endswith(f"/{fact_id}/evidence")
    assert key == f"knowledge-fact-evidence:{project_id}:{fact_id}"
    assert payload is not None
    assert set(payload) == {
        "title",
        "subject_entity_id",
        "subject_role",
        "usage_rights",
        "confidentiality",
        "public_citation",
    }
    for derived in ("item_type", "source_id", "locator", "snapshot", "source_revision"):
        assert derived not in payload


def test_promotion_script_dry_run_never_writes_and_exposes_server_proposal() -> None:
    project_id, fact_id, entity_id = (str(uuid4()) for _ in range(3))
    proposal = _proposal(project_id, fact_id)
    api = FakeApi(proposal, {})

    receipt = promote(api, _args(project_id, fact_id, entity_id, dry_run=True))  # type: ignore[arg-type]

    assert receipt["mode"] == "dry_run"
    assert receipt["proposal"] is proposal
    assert len(api.calls) == 1
    assert api.calls[0][0] == "GET"


def _args(project_id: str, fact_id: str, entity_id: str, *, dry_run: bool) -> Namespace:
    return Namespace(
        project_id=project_id,
        fact_id=fact_id,
        title=None,
        subject_entity_id=entity_id,
        subject_role="product",
        usage_rights="public_reference",
        confidentiality="public",
        public_disclosure=True,
        public_source_url=None,
        public_source_title=None,
        citation_label=None,
        quotation_allowed=False,
        attribution_required=True,
        dry_run=dry_run,
    )


def _proposal(project_id: str, fact_id: str) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "promotable": True,
        "blockers": [],
        "fact": {"id": fact_id, "statement": "Governed fact"},
        "defaults": {
            "title": "Governed Fact Evidence",
            "source_url": "https://source.example/fact",
            "source_title": "Official source",
            "citation_label": "Official source",
        },
    }
