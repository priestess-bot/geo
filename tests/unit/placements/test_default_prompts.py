from geo_core.placements.default_prompts import (
    DEFAULT_PROMPT_DEFINITIONS,
    default_output_schema,
)
from geo_core.placements.generation_contract import validate_generation_schema
from geo_core.prompts.domain import SkillVersion, compile_template
from uuid import uuid4


def test_default_catalog_covers_every_supported_channel_with_authoritative_inputs() -> None:
    expected = {
        "owned_site",
        "productreview",
        "youtube",
        "reddit",
        "amazon",
        "ozbargain",
        "tiktok",
        "instagram",
        "quora",
    }
    assert {item.task_key for item in DEFAULT_PROMPT_DEFINITIONS} == expected
    assert len({item.skill_key for item in DEFAULT_PROMPT_DEFINITIONS}) == len(expected)
    assert len({item.source for item in DEFAULT_PROMPT_DEFINITIONS}) == len(expected)
    for item in DEFAULT_PROMPT_DEFINITIONS:
        assert item.system_template.strip()
        version = SkillVersion.create(
            id=uuid4(), skill_id=uuid4(), version=1, source=item.source
        )
        template = compile_template(release_id=uuid4(), skill=version)
        assert set(template.required_variables) == {
            "brief",
            "destination_policy",
            "evidence",
        }


def test_default_output_schema_is_complete_and_isolated_per_caller() -> None:
    first = default_output_schema()
    second = default_output_schema()

    validate_generation_schema(first)
    first["required"].append("caller_only")

    assert "caller_only" not in second["required"]
    assert second["additionalProperties"] is False
