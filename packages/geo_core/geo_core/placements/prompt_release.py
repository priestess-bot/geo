"""Pure compilation rules for immutable executable prompt releases."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import uuid4

from geo_core.placements.domain import PlacementRuleViolation
from geo_core.placements.generation_contract import validate_generation_schema
from geo_core.prompts.domain import SkillVersion, TemplateRelease, compile_template


def compile_executable_release(
    *,
    skill_version: SkillVersion,
    system_template: str,
    user_template: str | None,
    output_schema: Mapping[str, object],
    client_variable_names: tuple[str, ...],
) -> tuple[TemplateRelease, str]:
    validate_generation_schema(output_schema)
    normalized_system = system_template.strip()
    if not normalized_system:
        raise PlacementRuleViolation("system prompt is required")
    execution_skill = SkillVersion.create(
        id=skill_version.id,
        skill_id=skill_version.skill_id,
        version=skill_version.version,
        source=user_template if user_template is not None else skill_version.source,
    )
    template = compile_template(release_id=uuid4(), skill=execution_skill)
    authoritative = {"brief", "evidence", "destination_policy"}
    if not authoritative.issubset(template.required_variables):
        raise PlacementRuleViolation(
            "prompt releases must render brief, evidence and destination_policy"
        )
    if not set(client_variable_names).issubset(template.required_variables):
        raise PlacementRuleViolation("client prompt variables must exist in the template")
    if authoritative.intersection(client_variable_names):
        raise PlacementRuleViolation("authoritative prompt variables are server-owned")
    return template, normalized_system
