from __future__ import annotations

from uuid import uuid4

import pytest

from geo_core.workflow_runtime import WorkflowContractError
from scripts.manage_dify_workflows import canary_contract


@pytest.mark.parametrize(
    ("purpose", "valid"),
    [
        (
            "knowledge.question_generation",
            {
                "questions": [
                    {
                        "candidate_id": "canary-question-1",
                        "dimension_key": "au-geo-awareness",
                        "variant_index": 1,
                        "text": "How can Advinsys help with GEO analytics in Australia?",
                        "semantic_fingerprint": "geo analytics australia",
                        "supported_fact_ids": [
                            "00000000-0000-4000-8000-000000000101"
                        ],
                        "supported_entity_ids": [
                            "00000000-0000-4000-8000-000000000102"
                        ],
                        "parent_candidate_id": None,
                    }
                ]
            },
        ),
        (
            "knowledge.rag_grounding",
            {
                "facts": [
                    {
                        "text": "Advinsys provides GEO analytics in Australia.",
                        "source_quote": "Advinsys provides GEO analytics in Australia.",
                    }
                ],
                "entities": [],
                "relations": [],
            },
        ),
        (
            "placements.generation",
            {
                "content_json": {
                    "title": "GEO analytics",
                    "body": "Australian coverage.",
                    "required_disclosures": [],
                    "expected_links": [],
                },
                "rendered_text": "GEO analytics for Australian teams.",
                "claims": [],
                "internal_evidence_refs": [],
                "public_citation_refs": [],
            },
        ),
        (
            "placements.simulation",
            {
                "content_json": {
                    "title": "Simulation",
                    "body": "Australian response.",
                    "required_disclosures": [],
                    "expected_links": [],
                },
                "rendered_text": "An Australian simulation response.",
                "claims": [],
                "internal_evidence_refs": [],
                "public_citation_refs": [],
            },
        ),
    ],
)
def test_canary_contract_accepts_only_business_shaped_output(purpose, valid) -> None:
    request, validator = canary_contract(uuid4(), purpose)

    assert request.purpose == purpose
    assert len(request.input_hash) == 64
    assert request.output_schema.get("x-geo-runtime-contract") is None
    validator(valid)
    with pytest.raises(WorkflowContractError):
        validator({})
