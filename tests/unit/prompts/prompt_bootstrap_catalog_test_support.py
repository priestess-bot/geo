from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from geo_core.prompts.bootstrap_contracts import EvalScenario, PromptEvalFixture
from geo_core.prompts.program import ProgramKind


PROJECT_ID = UUID("10000000-0000-4000-8000-000000000001")
OWNER_ID = UUID("20000000-0000-4000-8000-000000000002")
CATALOG_HASH = "ed6213ec92831de472b9d597856119fd50c262177a499015443d9e8740bb4cc8"

AUXILIARY_SYNTHETIC_OUTPUT_FIELDS: Mapping[ProgramKind, frozenset[str]] = {
    ProgramKind.STYLE_PROFILE: frozenset(
        {
            "subject_id",
            "evidence_refs",
            "citation_refs",
            "output_locale",
            "automatic_action_authorised",
            "injection_detected",
            "untrusted_instruction_followed",
            "sample_manifest_hash",
            "voice_traits",
            "lexical_patterns",
            "structure_patterns",
            "avoid_patterns",
        }
    ),
    ProgramKind.OFFLINE_ANSWER: frozenset(
        {
            "subject_id",
            "evidence_refs",
            "citation_refs",
            "output_locale",
            "automatic_action_authorised",
            "injection_detected",
            "untrusted_instruction_followed",
            "answer_text",
            "metric_value",
        }
    ),
}


def fixture_for(
    fixtures: tuple[PromptEvalFixture, ...], scenario: EvalScenario
) -> PromptEvalFixture:
    return next(fixture for fixture in fixtures if fixture.scenario is scenario)


def assert_every_object_is_closed_and_fully_required(value: object) -> None:
    if not isinstance(value, Mapping):
        return
    if value.get("type") == "object":
        properties = value["properties"]
        required = value["required"]
        assert isinstance(properties, Mapping)
        assert isinstance(required, list)
        assert value["additionalProperties"] is False
        assert set(required) == set(properties)
    for child in value.values():
        if isinstance(child, list):
            for item in child:
                assert_every_object_is_closed_and_fully_required(item)
        else:
            assert_every_object_is_closed_and_fully_required(child)
