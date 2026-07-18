from pathlib import Path
import shutil

import pytest

from geo_core.placements.default_prompts import (
    DEFAULT_PROMPT_DEFINITIONS,
    default_prompt_definitions,
    default_output_schema,
)
from geo_core.placements.generation_contract import validate_generation_schema
from geo_core.prompts.filesystem import PromptFileError, load_prompt_text, render_prompt_text
from geo_core.prompts.domain import SkillVersion, compile_template
from uuid import uuid4


PROMPT_ROOT = Path(__file__).resolve().parents[3] / "prompt"


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
        version = SkillVersion.create(id=uuid4(), skill_id=uuid4(), version=1, source=item.source)
        template = compile_template(release_id=uuid4(), skill=version)
        assert set(template.required_variables) == {
            "brief",
            "destination_policy",
            "evidence",
        }


def test_catalog_reloads_channel_files_without_python_changes(tmp_path: Path) -> None:
    editable_root = tmp_path / "prompt"
    shutil.copytree(PROMPT_ROOT, editable_root)
    channel = editable_root / "channels" / "owned-site.md"
    channel.write_text(
        channel.read_text(encoding="utf-8") + "\n\nOperator-only prompt revision.",
        encoding="utf-8",
    )

    definitions = default_prompt_definitions(prompt_root=editable_root)

    owned_site = next(item for item in definitions if item.task_key == "owned_site")
    assert "Operator-only prompt revision." in owned_site.source
    assert (
        "Operator-only prompt revision."
        not in next(
            item for item in DEFAULT_PROMPT_DEFINITIONS if item.task_key == "owned_site"
        ).source
    )


def test_prompt_files_reject_path_escape_and_missing_internal_variables() -> None:
    with pytest.raises(PromptFileError, match="escapes configured root"):
        load_prompt_text("../README.md", prompt_root=PROMPT_ROOT)
    with pytest.raises(PromptFileError, match="missing internal prompt variables"):
        render_prompt_text("[[required_value]]", {}, source="unit-test")


def test_default_output_schema_is_complete_and_isolated_per_caller() -> None:
    first = default_output_schema()
    second = default_output_schema()

    validate_generation_schema(first)
    first["required"].append("caller_only")

    assert "caller_only" not in second["required"]
    assert second["additionalProperties"] is False
    claim_status = second["properties"]["claims"]["items"]["properties"]["support_status"]
    assert set(claim_status["enum"]) == {
        "supported",
        "unsupported",
        "conflict",
        "not_required",
    }


def test_priority_channel_prompts_preserve_researched_user_writing_conventions() -> None:
    sources = {item.task_key: " ".join(item.source.split()) for item in DEFAULT_PROMPT_DEFINITIONS}

    common = sources["productreview"]
    assert "Evidence ledger" in common
    assert "Channel blueprint" in common
    assert "Sentence audit" in common
    assert 'rendered_text exactly `title + "\\n\\n" + body`' in common
    assert "higher-priority instruction explicitly selects an isolated" in common
    assert "G'day, I'm an Aussie homeowner" in common
    assert "Never copy a sentence or distinctive phrase from a real post" in common
    assert "use that snapshot as the sole experience storyline" in common
    assert "Do not add a second experience event" in common
    assert "mark it as unsupported with no evidence IDs" in common
    assert "Never add a time, quantity, speed, quality, outcome" in common
    assert "Setup felt simple" in common
    assert '"after each run" must not become "daily"' in common
    assert "Do not fill gaps around a supported fact" in common
    assert "Do not decorate an Evidence noun" in common
    assert "do not prepend the merchant or seller name" in common
    assert "The only unsupported claims allowed" in common
    assert "Do not include unsupported time saved" in common
    assert "boundary wires, apps, scheduling" in common
    assert "classify such statements as factual, never as experience" in common

    assert "ownership duration" in sources["productreview"]
    assert "trade-off or residual task" in sources["productreview"]
    assert "do not manufacture a flaw" in sources["productreview"]
    assert "specific suitability condition or measured personal verdict" in sources["productreview"]
    assert "75-to-120-word body" in sources["productreview"]
    assert "exactly two short paragraphs of four sentences each" in sources["productreview"]
    assert (
        "reason for keeping that routine without alleging a product defect"
        in sources["productreview"]
    )
    assert "without judging its accuracy, reliability, speed or result" in sources["productreview"]
    assert "first-person verdict beginning with 'For my routine,'" in sources["productreview"]
    assert "never address the reader in that final sentence" in sources["productreview"]
    assert "Do not derive performance from dimensions" in sources["productreview"]
    assert "Do not add an unrelated fact" in sources["productreview"]
    assert "whether the setup and checking routine suits" in sources["productreview"]

    assert "Answer the exact thread question in the first lines" in sources["reddit"]
    assert "Separate hardware, software, setup and support" in sources["reddit"]
    assert "promotional call to action" in sources["reddit"]
    assert "Write 65 to 110 words with no title and exactly six sentences" in sources["reddit"]
    assert "first-person conclusion limited to those facts" in sources["reddit"]

    assert "two-to-six-sentence body" in sources["amazon"]
    assert "Never claim Verified Purchase" in sources["amazon"]
    assert "55-to-85-word body" in sources["amazon"]
    assert "Use exactly five body sentences" in sources["amazon"]
    assert "Do not add warranty, returns, price" in sources["amazon"]
    assert "must not claim results, performance or quality" in sources["amazon"]

    assert "final price" in sources["ozbargain"]
    assert "historical lows" in sources["ozbargain"]
    assert "Never invent a price, coupon, saving" in sources["ozbargain"]

    assert "State test conditions and method" in sources["youtube"]
    assert "one failure, workaround or limitation" in sources["youtube"]
    assert "who the product is and is not suited to" in sources["youtube"]
