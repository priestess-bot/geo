"""Project-owned benchmark contracts; no RAG framework types belong here."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol, Sequence


SCHEMA_VERSION = "f019-candidate-output-v1"
REPORT_SCHEMA_VERSION = "f019-benchmark-report-v1"


@dataclass(frozen=True)
class Document:
    document_id: str
    project_id: str
    source_format: Literal["html", "pdf", "docx", "text"]
    category: Literal["product", "competitor", "market"]
    title: str
    source_uri: str
    license_id: str
    valid_from: str
    content: str
    question_contexts: tuple[dict[str, str], ...] = ()
    conflict_group: str | None = None


@dataclass(frozen=True)
class DeltaOperation:
    operation_id: str
    operation: Literal["reimport", "update", "delete", "add"]
    project_id: str
    document_id: str
    document: Document | None = None


@dataclass(frozen=True)
class CandidateControl:
    workflow_status: Literal["candidate", "approved"] = "candidate"
    requires_human_approval: bool = True


@dataclass(frozen=True)
class FactCandidate:
    candidate_id: str
    project_id: str
    text: str
    source_document_id: str
    source_locator: str
    control: CandidateControl = field(default_factory=CandidateControl)


@dataclass(frozen=True)
class EntityCandidate:
    candidate_id: str
    project_id: str
    entity_type: str
    name: str
    source_document_ids: tuple[str, ...]
    control: CandidateControl = field(default_factory=CandidateControl)


@dataclass(frozen=True)
class RelationCandidate:
    candidate_id: str
    project_id: str
    subject: str
    predicate: str
    object: str
    source_document_id: str
    source_locator: str
    control: CandidateControl = field(default_factory=CandidateControl)


@dataclass(frozen=True)
class QuestionCandidate:
    candidate_id: str
    project_id: str
    text: str
    dimension_key: str
    source_fact_ids: tuple[str, ...]
    source_document_ids: tuple[str, ...]
    control: CandidateControl = field(default_factory=CandidateControl)


@dataclass(frozen=True)
class SimulationCandidate:
    candidate_id: str
    project_id: str
    source_fact_ids: tuple[str, ...]
    test_only: bool
    publication_eligible: bool


@dataclass(frozen=True)
class CandidateArtifacts:
    facts: tuple[FactCandidate, ...] = ()
    entities: tuple[EntityCandidate, ...] = ()
    relations: tuple[RelationCandidate, ...] = ()
    questions: tuple[QuestionCandidate, ...] = ()
    simulations: tuple[SimulationCandidate, ...] = ()


@dataclass(frozen=True)
class UsageMetrics:
    input_tokens: int
    output_tokens: int
    model_calls: int
    estimated_cost_usd: float
    wall_clock_ms: int


@dataclass(frozen=True)
class CandidateRun:
    candidate_id: str
    adapter_kind: str
    framework_version: str | None
    eligible_for_selection: bool
    available: bool
    unavailable_reason: str | None
    base: CandidateArtifacts | None
    delta: CandidateArtifacts | None
    usage: UsageMetrics | None
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BenchmarkAdapter(Protocol):
    candidate_id: str
    adapter_kind: str
    eligible_for_selection: bool

    def run(
        self,
        documents: Sequence[Document],
        delta_operations: Sequence[DeltaOperation],
    ) -> CandidateRun: ...
