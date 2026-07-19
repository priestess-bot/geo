"""Project-owned RAG contracts with no framework or benchmark dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence


class RagAdapterError(RuntimeError):
    """A candidate engine returned unsafe, untraceable, or invalid output."""


@dataclass(frozen=True)
class RagSourceDocument:
    document_id: str
    project_id: str
    title: str
    content: str
    source_locator: str
    document_group_id: str | None = None

    def __post_init__(self) -> None:
        required = (
            self.document_id,
            self.project_id,
            self.title,
            self.content,
            self.source_locator,
        )
        if not all(value.strip() for value in required):
            raise RagAdapterError("RAG source documents require non-empty identity and content")
        if self.document_group_id is not None and not self.document_group_id.strip():
            raise RagAdapterError("RAG document group identity must be non-empty")

    @property
    def group_id(self) -> str:
        return self.document_group_id or self.document_id


@dataclass(frozen=True)
class QuestionPlan:
    dimension_key: str
    source_document_id: str
    persona: str
    scenario: str
    intent: str
    funnel: str
    region: str
    language: str
    brand_scope: str
    platform: str
    subject: str

    def __post_init__(self) -> None:
        if not all(
            str(value).strip()
            for value in (
                self.dimension_key,
                self.source_document_id,
                self.persona,
                self.scenario,
                self.intent,
                self.funnel,
                self.region,
                self.language,
                self.brand_scope,
                self.platform,
                self.subject,
            )
        ):
            raise RagAdapterError("question plans require every governed dimension")


@dataclass(frozen=True)
class CandidateFact:
    candidate_id: str
    project_id: str
    text: str
    source_document_id: str
    source_locator: str


@dataclass(frozen=True)
class CandidateEntity:
    candidate_id: str
    project_id: str
    entity_type: str
    name: str
    source_document_ids: tuple[str, ...]


@dataclass(frozen=True)
class CandidateRelation:
    candidate_id: str
    project_id: str
    subject: str
    predicate: str
    object: str
    source_document_id: str
    source_locator: str


@dataclass(frozen=True)
class CandidateQuestion:
    candidate_id: str
    project_id: str
    text: str
    dimension_key: str
    source_fact_ids: tuple[str, ...]
    source_document_ids: tuple[str, ...]


@dataclass(frozen=True)
class CandidateValidationFinding:
    project_id: str
    source_document_id: str
    candidate_kind: str
    reason_code: str
    candidate_hash: str


@dataclass(frozen=True)
class CandidateGraph:
    facts: tuple[CandidateFact, ...]
    entities: tuple[CandidateEntity, ...]
    relations: tuple[CandidateRelation, ...]
    questions: tuple[CandidateQuestion, ...]
    validation_findings: tuple[CandidateValidationFinding, ...] = ()


class JsonModelInvoker(Protocol):
    """Audited model boundary supplied by a Worker or an isolated benchmark."""

    def complete_json(
        self,
        *,
        project_id: str,
        purpose: str,
        messages: Sequence[Mapping[str, str]],
        request_hash: str,
        max_output_tokens: int,
    ) -> Mapping[str, object]: ...
