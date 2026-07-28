from __future__ import annotations

from uuid import uuid4

import pytest

from geo_core.prompts.bootstrap_catalog import default_prompt_bootstrap_spec
from geo_core.prompts.bootstrap_contracts import thaw_mapping
from geo_core.prompts.program_contracts import ProgramKind
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


@pytest.mark.parametrize(
    "kind",
    [
        ProgramKind.GENERATION,
        ProgramKind.CLAIM_EXTRACTION,
        ProgramKind.CONFLICT_CHECK,
        ProgramKind.REVISION,
        ProgramKind.STYLE_PROFILE,
        ProgramKind.RECOMMENDATION,
    ],
)
def test_bootstrap_canary_keeps_task_contract_out_of_business_validation(kind) -> None:
    purpose = (
        "recommendations.recommendation"
        if kind is ProgramKind.RECOMMENDATION
        else f"synthetic_lab.{kind.value}"
    )
    request, validator = canary_contract(uuid4(), purpose)
    spec = default_prompt_bootstrap_spec(kind)
    fixture = next(item for item in spec.fixtures if item.expected_valid)
    output = dict(thaw_mapping(fixture.expected_output))
    if kind is ProgramKind.CONFLICT_CHECK:
        assessments = output["assessments"]
        assert isinstance(assessments, list) and isinstance(assessments[0], dict)
        assessments[0]["status"] = "explicit_conflict"
        output["requires_revision"] = True
    elif kind is ProgramKind.REVISION:
        output["resolved_issue_codes"] = ["explicit_conflict"]
        output["revised_text"] = (
            "The placeholder subject has the approved synthetic attribute."
        )

    assert "task_contract" in request.context
    validator(output)
    with pytest.raises(WorkflowContractError):
        validator({})


@pytest.mark.parametrize(
    "purpose",
    [
        "synthetic_lab.style_judge",
        "synthetic_lab.arbiter",
        "monitoring.metric_judge",
        "synthetic_lab.offline_answer",
    ],
)
def test_native_workflow_has_no_dify_canary(purpose: str) -> None:
    with pytest.raises(WorkflowContractError, match="unsupported Dify canary purpose"):
        canary_contract(uuid4(), purpose)


def test_style_profile_canary_requires_the_frozen_approved_sample_lineage() -> None:
    _request, validator = canary_contract(uuid4(), "synthetic_lab.style_profile")
    fixture = next(
        item
        for item in default_prompt_bootstrap_spec(ProgramKind.STYLE_PROFILE).fixtures
        if item.expected_valid
    )
    output = dict(thaw_mapping(fixture.expected_output))
    output["evidence_refs"] = ["evidence-style-sample-002"]

    with pytest.raises(
        WorkflowContractError,
        match="did not preserve its approved sample lineage",
    ):
        validator(output)


def test_recommendation_canary_is_deterministically_bound_to_selected_evidence() -> None:
    _request, validator = canary_contract(uuid4(), "recommendations.recommendation")
    fixture = next(
        item
        for item in default_prompt_bootstrap_spec(ProgramKind.RECOMMENDATION).fixtures
        if item.expected_valid
    )
    output = dict(thaw_mapping(fixture.expected_output))
    selected = output["selected_evidence"]
    evidence_refs = output["evidence_refs"]
    assert isinstance(selected, list) and isinstance(evidence_refs, list)
    output["selected_evidence"] = list(reversed(selected))
    output["evidence_refs"] = list(reversed(evidence_refs))

    with pytest.raises(
        WorkflowContractError,
        match="escaped its frozen evidence or scope",
    ):
        validator(output)
