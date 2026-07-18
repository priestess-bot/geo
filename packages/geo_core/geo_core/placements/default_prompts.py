"""Versioned starter prompts loaded from the repository-level prompt directory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from geo_core.prompts.filesystem import (
    PromptFileError,
    load_prompt_json,
    load_prompt_text,
    render_prompt_text,
)


@dataclass(frozen=True)
class DefaultPromptDefinition:
    task_key: str
    skill_key: str
    system_template: str
    source: str


def default_system_template(*, prompt_root: Path | str | None = None) -> str:
    manifest = _catalog_manifest(prompt_root=prompt_root)
    return load_prompt_text(
        _required_string(manifest, "system_template", source="catalog.json"),
        prompt_root=prompt_root,
    )


def default_prompt_definitions(
    *, prompt_root: Path | str | None = None
) -> tuple[DefaultPromptDefinition, ...]:
    """Load a fresh catalog snapshot so prompt edits do not require Python changes."""

    manifest = _catalog_manifest(prompt_root=prompt_root)
    system_template = load_prompt_text(
        _required_string(manifest, "system_template", source="catalog.json"),
        prompt_root=prompt_root,
    )
    user_template_path = _required_string(manifest, "user_template", source="catalog.json")
    user_template = load_prompt_text(user_template_path, prompt_root=prompt_root)
    shared = _required_mapping(manifest, "shared", source="catalog.json")
    consumer_voice = load_prompt_text(
        _required_string(shared, "test_only_consumer_voice", source="catalog.json.shared"),
        prompt_root=prompt_root,
    )
    drafting_protocol = load_prompt_text(
        _required_string(shared, "evidence_led_drafting_protocol", source="catalog.json.shared"),
        prompt_root=prompt_root,
    )
    channels = manifest.get("channels")
    if not isinstance(channels, list) or not channels:
        raise PromptFileError("catalog.json.channels must be a non-empty array")

    definitions: list[DefaultPromptDefinition] = []
    task_keys: set[str] = set()
    skill_keys: set[str] = set()
    for index, raw_channel in enumerate(channels):
        source = f"catalog.json.channels[{index}]"
        if not isinstance(raw_channel, dict):
            raise PromptFileError(f"{source} must be an object")
        task_key = _required_string(raw_channel, "task_key", source=source)
        skill_key = _required_string(raw_channel, "skill_key", source=source)
        prompt_path = _required_string(raw_channel, "prompt", source=source)
        if task_key in task_keys or skill_key in skill_keys:
            raise PromptFileError(f"duplicate task_key or skill_key in {source}")
        channel_instruction = render_prompt_text(
            load_prompt_text(prompt_path, prompt_root=prompt_root),
            {"test_only_consumer_voice": consumer_voice},
            source=prompt_path,
        )
        prompt_source = render_prompt_text(
            user_template,
            {
                "channel_instruction": channel_instruction,
                "evidence_led_drafting_protocol": drafting_protocol,
            },
            source=user_template_path,
        )
        definitions.append(
            DefaultPromptDefinition(task_key, skill_key, system_template, prompt_source)
        )
        task_keys.add(task_key)
        skill_keys.add(skill_key)
    return tuple(definitions)


def default_output_schema(*, prompt_root: Path | str | None = None) -> dict[str, Any]:
    """Return a fresh output contract loaded alongside the editable prompt assets."""

    schema = load_prompt_json("contracts/placement-output-schema.json", prompt_root=prompt_root)
    if not isinstance(schema, dict):
        raise PromptFileError("placement output schema must be a JSON object")
    return schema


def _catalog_manifest(*, prompt_root: Path | str | None = None) -> Mapping[str, object]:
    manifest = load_prompt_json("catalog.json", prompt_root=prompt_root)
    if not isinstance(manifest, dict):
        raise PromptFileError("catalog.json must contain an object")
    if manifest.get("version") != 1:
        raise PromptFileError("catalog.json.version must be 1")
    return manifest


def _required_mapping(
    values: Mapping[str, object], key: str, *, source: str
) -> Mapping[str, object]:
    value = values.get(key)
    if not isinstance(value, dict):
        raise PromptFileError(f"{source}.{key} must be an object")
    return value


def _required_string(values: Mapping[str, object], key: str, *, source: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PromptFileError(f"{source}.{key} must be a non-empty string")
    return value.strip()


# Compatibility snapshots for callers that import the historical constants. Runtime catalog
# installation uses ``default_prompt_definitions`` and therefore reads files afresh.
DEFAULT_SYSTEM_TEMPLATE = default_system_template()
DEFAULT_PROMPT_DEFINITIONS = default_prompt_definitions()
