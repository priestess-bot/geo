"""Immutable input material for one direct synthetic generation run."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.domain import (
    STANDARD_STYLE_CHANNELS,
    SyntheticLabContractError,
    SyntheticOnly,
    _require_hash,
    _require_text,
    _require_uuid,
)
from geo_core.synthetic_lab.review_cases import ScenarioMode


@dataclass(frozen=True, kw_only=True)
class DirectKnowledgeItem(SyntheticOnly):
    evidence_id: UUID
    subject_entity_id: UUID
    subject_name: str
    kind: str
    summary: str
    snapshot_hash: str
    source_title: str | None = None
    source_url: str | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.evidence_id, "Direct Knowledge evidence")
        _require_uuid(self.subject_entity_id, "Direct Knowledge subject")
        _require_text(self.subject_name, "Direct Knowledge subject name")
        if self.kind not in {"approved_fact", "citation"}:
            raise SyntheticLabContractError("Direct Knowledge kind is unsupported")
        _require_text(self.summary, "Direct Knowledge summary")
        _require_hash(self.snapshot_hash, "Direct Knowledge snapshot")
        for value, label in (
            (self.source_title, "Direct Knowledge source title"),
            (self.source_url, "Direct Knowledge source URL"),
        ):
            if value is not None:
                _require_text(value, label)

    @property
    def ref(self) -> str:
        return f"evidence:{self.evidence_id}:{self.snapshot_hash}"


@dataclass(frozen=True, kw_only=True)
class DirectKnowledgeSnapshot(SyntheticOnly):
    id: UUID
    project_id: UUID
    primary_subject_id: UUID
    items: tuple[DirectKnowledgeItem, ...]
    snapshot_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_uuid(self.id, "Direct Knowledge snapshot ID")
        _require_uuid(self.project_id, "Direct Knowledge Project ID")
        _require_uuid(self.primary_subject_id, "Direct Knowledge primary subject")
        items = tuple(self.items)
        object.__setattr__(self, "items", items)
        if not items or len({item.evidence_id for item in items}) != len(items):
            raise SyntheticLabContractError(
                "Direct Knowledge snapshot requires unique evidence"
            )
        if self.primary_subject_id not in {item.subject_entity_id for item in items}:
            raise SyntheticLabContractError(
                "Direct Knowledge snapshot lacks primary-subject evidence"
            )
        object.__setattr__(
            self,
            "snapshot_hash",
            canonical_hash(
                {
                    "project_id": self.project_id,
                    "primary_subject_id": self.primary_subject_id,
                    "items": items,
                }
            ),
        )


@dataclass(frozen=True, kw_only=True)
class DirectGenerationScenario(SyntheticOnly):
    id: UUID
    project_id: UUID
    input_snapshot_id: UUID
    channel: str
    persona: str
    use_case: str
    subject: str
    generation_goal: str
    mode: ScenarioMode = ScenarioMode.GUIDED
    competitor_scenario: bool = False
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for value, label in (
            (self.id, "Direct Generation scenario ID"),
            (self.project_id, "Direct Generation Project ID"),
            (self.input_snapshot_id, "Direct Generation input snapshot ID"),
        ):
            _require_uuid(value, label)
        if self.channel not in STANDARD_STYLE_CHANNELS:
            raise SyntheticLabContractError("Direct Generation channel is unsupported")
        for value, label in (
            (self.persona, "Direct Generation persona"),
            (self.use_case, "Direct Generation use case"),
            (self.subject, "Direct Generation subject"),
            (self.generation_goal, "Direct Generation goal"),
        ):
            _require_text(value, label)
        if len(self.generation_goal) > 4_000:
            raise SyntheticLabContractError("Direct Generation goal exceeds 4000 characters")
        mode = ScenarioMode(self.mode)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(
            self,
            "content_hash",
            canonical_hash(
                {
                    "project_id": self.project_id,
                    "input_snapshot_id": self.input_snapshot_id,
                    "channel": self.channel,
                    "persona": self.persona,
                    "use_case": self.use_case,
                    "subject": self.subject,
                    "generation_goal": self.generation_goal,
                    "mode": mode.value,
                    "competitor_scenario": self.competitor_scenario,
                }
            ),
        )

    @property
    def creative_reference(self) -> str:
        return self.generation_goal

    @property
    def review_suite_version_id(self) -> UUID:
        return self.input_snapshot_id

    @property
    def case_key(self) -> str:
        return f"direct:{self.id}"


__all__ = [
    "DirectGenerationScenario",
    "DirectKnowledgeItem",
    "DirectKnowledgeSnapshot",
]
