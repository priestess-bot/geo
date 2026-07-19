"""Framework-neutral Knowledge contracts for governed RAG extraction."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Mapping, Sequence
from uuid import UUID

from geo_core.rag import CandidateGraph, RagSourceDocument


SHA256 = re.compile(r"^[0-9a-f]{64}$")
SOURCE_LOCATOR = re.compile(r"^line:[1-9][0-9]*$")
RAG_ARTIFACT_SCHEMA = "knowledge-rag-candidate-artifact-v1"


class KnowledgeGraphEntityType(StrEnum):
    BRAND = "brand"
    PRODUCT = "product"
    COMPETITOR = "competitor"
    FEATURE = "feature"
    SPECIFICATION = "specification"
    USE_CASE = "use_case"
    PERSONA = "persona"
    PAIN_POINT = "pain_point"
    MARKET = "market"
    CHANNEL = "channel"


class KnowledgeGraphPredicate(StrEnum):
    BELONGS_TO = "belongs_to"
    HAS_FEATURE = "has_feature"
    HAS_SPECIFICATION = "has_specification"
    COMPETES_WITH = "competes_with"
    BELONGS_TO_MARKET = "belongs_to_market"
    USES_CHANNEL = "uses_channel"
    COMPATIBLE_WITH = "compatible_with"
    HAS_PAIN_POINT = "has_pain_point"
    SUPPORTS_USE_CASE = "supports_use_case"


ADAPTER_ENTITY_TYPES = {
    "Brand": KnowledgeGraphEntityType.BRAND,
    "Product": KnowledgeGraphEntityType.PRODUCT,
    "Competitor": KnowledgeGraphEntityType.COMPETITOR,
    "Feature": KnowledgeGraphEntityType.FEATURE,
    "Specification": KnowledgeGraphEntityType.SPECIFICATION,
    "UseCase": KnowledgeGraphEntityType.USE_CASE,
    "Persona": KnowledgeGraphEntityType.PERSONA,
    "PainPoint": KnowledgeGraphEntityType.PAIN_POINT,
    "Market": KnowledgeGraphEntityType.MARKET,
    "Channel": KnowledgeGraphEntityType.CHANNEL,
}
CATALOG_MAPPABLE_GRAPH_TYPES = frozenset(
    {
        KnowledgeGraphEntityType.BRAND,
        KnowledgeGraphEntityType.PRODUCT,
        KnowledgeGraphEntityType.COMPETITOR,
        KnowledgeGraphEntityType.MARKET,
    }
)


class KnowledgeRagError(RuntimeError):
    pass


class KnowledgeRagContractError(KnowledgeRagError):
    pass


@dataclass(frozen=True)
class KnowledgeRagEnqueuePolicy:
    adapter_release: str
    selection_manifest_hash: str
    configured_model: str
    maximum_attempts: int = 3

    def __post_init__(self) -> None:
        if not self.adapter_release.strip() or not self.configured_model.strip():
            raise KnowledgeRagContractError("RAG enqueue policy identity is incomplete")
        if not SHA256.fullmatch(self.selection_manifest_hash):
            raise KnowledgeRagContractError("RAG selection manifest hash must be lowercase SHA-256")
        if self.maximum_attempts < 1:
            raise KnowledgeRagContractError("RAG job attempt budget must be positive")

    @property
    def model_calls_per_chunk(self) -> int:
        if self.adapter_release == "project-native-rag-v1":
            return 1
        if self.adapter_release == "llamaindex-property-graph-v1":
            return 2
        raise KnowledgeRagContractError("RAG enqueue policy adapter is unsupported")


@dataclass(frozen=True)
class KnowledgeRagChunk:
    chunk_id: UUID
    chunk_index: int
    text: str
    text_hash: str

    def __post_init__(self) -> None:
        if self.chunk_index < 0 or not self.text.strip():
            raise KnowledgeRagContractError("RAG chunks require non-empty ordered text")
        if not SHA256.fullmatch(self.text_hash):
            raise KnowledgeRagContractError("RAG chunk hash must be lowercase SHA-256")
        if hashlib.sha256(self.text.encode()).hexdigest() != self.text_hash:
            raise KnowledgeRagContractError("RAG chunk text does not match its hash")


@dataclass(frozen=True)
class KnowledgeRagClaim:
    project_id: UUID
    pipeline_run_id: UUID
    source_id: UUID
    logical_source_id: UUID
    document_id: UUID
    title: str
    input_hash: str
    adapter_release: str
    selection_manifest_hash: str
    configured_model: str
    model_call_budget: int
    requested_by: UUID
    chunks: tuple[KnowledgeRagChunk, ...]

    def __post_init__(self) -> None:
        if not self.title.strip() or not self.adapter_release.strip():
            raise KnowledgeRagContractError("RAG claim identity is incomplete")
        if not SHA256.fullmatch(self.input_hash) or not SHA256.fullmatch(
            self.selection_manifest_hash
        ):
            raise KnowledgeRagContractError("RAG claim hashes must be lowercase SHA-256")
        calls_per_chunk = 2 if self.adapter_release == "llamaindex-property-graph-v1" else 1
        if (
            not self.configured_model.strip()
            or self.model_call_budget < len(self.chunks) * calls_per_chunk
        ):
            raise KnowledgeRagContractError("RAG claim model budget cannot cover its chunks")
        if not self.chunks:
            raise KnowledgeRagContractError("RAG claim has no active chunks")
        if len({item.chunk_id for item in self.chunks}) != len(self.chunks):
            raise KnowledgeRagContractError("RAG claim contains duplicate chunk identities")

    @property
    def prompt_input_hash(self) -> str:
        return self.input_hash

    def source_documents(self) -> tuple[RagSourceDocument, ...]:
        return tuple(
            RagSourceDocument(
                document_id=str(chunk.chunk_id),
                project_id=str(self.project_id),
                title=f"{self.title} / chunk {chunk.chunk_index + 1}",
                content=chunk.text,
                source_locator=(
                    f"knowledge://{self.project_id}/{self.source_id}/"
                    f"{self.document_id}/{chunk.chunk_id}"
                ),
                document_group_id=str(self.document_id),
            )
            for chunk in self.chunks
        )


@dataclass(frozen=True)
class RagModelCallReservation:
    call_number: int
    request_hash: str
    provider: str


@dataclass(frozen=True)
class StoredRagArtifact:
    uri: str
    content_hash: str

    def __post_init__(self) -> None:
        if not self.uri.startswith("s3://") or not SHA256.fullmatch(self.content_hash):
            raise KnowledgeRagContractError("RAG artifact must be a hashed S3 object")


def canonical_candidate_artifact(
    claim: KnowledgeRagClaim, graph: CandidateGraph
) -> tuple[bytes, str]:
    payload = {
        "schema_version": RAG_ARTIFACT_SCHEMA,
        "project_id": str(claim.project_id),
        "pipeline_run_id": str(claim.pipeline_run_id),
        "source_id": str(claim.source_id),
        "logical_source_id": str(claim.logical_source_id),
        "document_id": str(claim.document_id),
        "input_hash": claim.input_hash,
        "adapter_release": claim.adapter_release,
        "selection_manifest_hash": claim.selection_manifest_hash,
        "facts": [asdict(item) for item in graph.facts],
        "entities": [asdict(item) for item in graph.entities],
        "relations": [asdict(item) for item in graph.relations],
        "questions": [asdict(item) for item in graph.questions],
        "validation_findings": [asdict(item) for item in graph.validation_findings],
    }
    content = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    return content, hashlib.sha256(content).hexdigest()


def artifact_key(claim: KnowledgeRagClaim, content_hash: str) -> str:
    if not SHA256.fullmatch(content_hash):
        raise KnowledgeRagContractError("RAG artifact hash must be lowercase SHA-256")
    return (
        f"knowledge-rag-artifacts/{claim.project_id}/{claim.logical_source_id}/"
        f"{claim.pipeline_run_id}/{content_hash}.json"
    )


def graph_entity_type(value: str) -> KnowledgeGraphEntityType:
    try:
        return ADAPTER_ENTITY_TYPES[value]
    except KeyError as exc:
        raise KnowledgeRagContractError(
            "adapter returned an unsupported graph entity type"
        ) from exc


def graph_predicate(value: str) -> KnowledgeGraphPredicate:
    try:
        return KnowledgeGraphPredicate(value)
    except ValueError as exc:
        raise KnowledgeRagContractError("adapter returned an unsupported graph predicate") from exc


def validate_candidate_graph(claim: KnowledgeRagClaim, graph: CandidateGraph) -> None:
    project = str(claim.project_id)
    chunks = {str(item.chunk_id): item for item in claim.chunks}
    if not graph.facts:
        raise KnowledgeRagContractError("RAG graph has no traceable facts")
    for fact in graph.facts:
        if (
            not fact.candidate_id.strip()
            or not fact.text.strip()
            or fact.project_id != project
            or fact.source_document_id not in chunks
        ):
            raise KnowledgeRagContractError("RAG fact crossed its project or source boundary")
        if fact.text not in chunks[fact.source_document_id].text:
            raise KnowledgeRagContractError("RAG fact is not traceable to its source chunk")
        _validate_locator(fact.source_locator)
    names: dict[str, int] = {}
    for entity in graph.entities:
        graph_entity_type(entity.entity_type)
        if (
            not entity.candidate_id.strip()
            or not entity.name.strip()
            or entity.project_id != project
            or not entity.source_document_ids
        ):
            raise KnowledgeRagContractError("RAG entity crossed its project boundary")
        if any(value not in chunks for value in entity.source_document_ids):
            raise KnowledgeRagContractError("RAG entity references an unknown source chunk")
        if any(entity.name not in chunks[value].text for value in entity.source_document_ids):
            raise KnowledgeRagContractError("RAG entity is not traceable to its source chunk")
        names[entity.name] = names.get(entity.name, 0) + 1
    for relation in graph.relations:
        graph_predicate(relation.predicate)
        if (
            not relation.candidate_id.strip()
            or not relation.subject.strip()
            or not relation.object.strip()
            or relation.project_id != project
            or relation.source_document_id not in chunks
        ):
            raise KnowledgeRagContractError("RAG relation crossed its project or source boundary")
        if names.get(relation.subject) != 1 or names.get(relation.object) != 1:
            raise KnowledgeRagContractError("RAG relation endpoints are missing or ambiguous")
        source_text = chunks[relation.source_document_id].text
        if relation.subject not in source_text or relation.object not in source_text:
            raise KnowledgeRagContractError("RAG relation is not traceable to its source chunk")
        _validate_locator(relation.source_locator)
    for finding in graph.validation_findings:
        if (
            finding.project_id != project
            or finding.source_document_id not in chunks
            or not finding.candidate_kind.strip()
            or not finding.reason_code.strip()
            or not SHA256.fullmatch(finding.candidate_hash)
        ):
            raise KnowledgeRagContractError(
                "RAG validation finding crossed its project or source boundary"
            )
    if graph.questions:
        raise KnowledgeRagContractError(
            "core extraction jobs cannot persist QuestionSet candidates"
        )


def candidate_fingerprint(values: Mapping[str, object] | Sequence[object]) -> str:
    canonical = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _validate_locator(value: str) -> None:
    if not SOURCE_LOCATOR.fullmatch(value):
        raise KnowledgeRagContractError("RAG source locator must use line:<positive integer>")
