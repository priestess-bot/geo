from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from types import MappingProxyType
from typing import Mapping
from uuid import UUID


_VARIABLE = re.compile(r"\{\{\s*([a-zA-Z][a-zA-Z0-9_]*)\s*\}\}")


class PromptCompilationError(ValueError):
    pass


@dataclass(frozen=True)
class SkillVersion:
    id: UUID
    skill_id: UUID
    version: int
    source: str
    source_hash: str

    @classmethod
    def create(cls, *, id: UUID, skill_id: UUID, version: int, source: str) -> "SkillVersion":
        normalized = source.strip()
        if version < 1 or not normalized:
            raise PromptCompilationError("skill version and source are required")
        return cls(id, skill_id, version, normalized, _hash(normalized))


@dataclass(frozen=True)
class TemplateRelease:
    id: UUID
    skill_version_id: UUID
    template: str
    required_variables: tuple[str, ...]
    release_hash: str


@dataclass(frozen=True)
class PromptBundle:
    id: UUID
    project_id: UUID
    brief_version_id: UUID
    evidence_pack_id: UUID
    template_release_id: UUID
    variables: Mapping[str, object]
    rendered_prompt: str
    evidence_pack_hash: str
    model_policy_hash: str
    bundle_hash: str


def compile_template(*, release_id: UUID, skill: SkillVersion) -> TemplateRelease:
    variables = tuple(sorted(set(_VARIABLE.findall(skill.source))))
    release_payload = {"skill_version_id": str(skill.id), "source_hash": skill.source_hash, "variables": variables}
    return TemplateRelease(release_id, skill.id, skill.source, variables, _hash(release_payload))


def render_bundle(
    *,
    bundle_id: UUID,
    project_id: UUID,
    brief_version_id: UUID,
    evidence_pack_id: UUID,
    template: TemplateRelease,
    variables: dict[str, object],
    evidence_pack_hash: str,
    model_policy_hash: str,
) -> PromptBundle:
    missing = sorted(set(template.required_variables) - set(variables))
    if missing:
        raise PromptCompilationError(f"missing prompt variables: {', '.join(missing)}")
    rendered = _VARIABLE.sub(lambda match: str(variables[match.group(1)]), template.template)
    payload = {
        "project_id": str(project_id),
        "brief_version_id": str(brief_version_id),
        "evidence_pack_id": str(evidence_pack_id),
        "template_release_id": str(template.id),
        "variables": variables,
        "rendered_prompt": rendered,
        "evidence_pack_hash": evidence_pack_hash,
        "model_policy_hash": model_policy_hash,
    }
    return PromptBundle(
        bundle_id,
        project_id,
        brief_version_id,
        evidence_pack_id,
        template.id,
        MappingProxyType(dict(variables)),
        rendered,
        evidence_pack_hash,
        model_policy_hash,
        _hash(payload),
    )


def _hash(value: object) -> str:
    payload = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
