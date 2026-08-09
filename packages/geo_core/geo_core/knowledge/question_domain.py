"""Framework-neutral GEO question planning, grounding, and deduplication."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re
import unicodedata
from typing import Literal, Mapping, Sequence
from uuid import UUID


DIMENSION_SCHEMA_VERSION = "geo-question-dimensions-v1"
EMBEDDING_MODEL_KEY = "geo-question-semantic-hash-v1"
EMBEDDING_DIMENSIONS = 1024
QUESTION_GENERATION_BATCH_SIZE = 10
QUESTION_ARTIFACT_SCHEMA = "knowledge-question-candidate-artifact-v1"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TERMINAL_PUNCTUATION = re.compile(r"[?？!！。．.]+$")
_WHITESPACE = re.compile(r"\s+")

FUNNELS = frozenset({"awareness", "consideration", "decision", "retention"})
BRAND_SCOPES = frozenset({"brand", "non_brand", "competitor"})
PLATFORMS = frozenset(
    {
        "chatgpt_search",
        "google_ai_overviews",
        "google_search",
        "perplexity",
        "gemini",
        "other",
    }
)
QUERY_KINDS = frozenset({"recommendation", "comparison", "research", "support"})


class QuestionContractError(RuntimeError):
    pass


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def question_generation_batch_count(
    dimensions: Sequence["FrozenQuestionDimension"],
) -> int:
    """Match the Worker's per-turn batching when validating its call budget."""
    return sum(
        math.ceil(
            sum(dimension.turn_index == turn for dimension in dimensions)
            / QUESTION_GENERATION_BATCH_SIZE
        )
        for turn in range(1, 4)
    )


def question_generation_minimum_call_budget(
    dimensions: Sequence["FrozenQuestionDimension"], maximum_attempts: int
) -> int:
    return question_generation_batch_count(dimensions) * maximum_attempts


@dataclass(frozen=True)
class QuestionDimensionDraft:
    persona: str
    scenario: str
    intent: str
    funnel: str
    region: str
    language: str
    brand_scope: str
    platform: str
    query_kind: str
    subject: str
    turn_index: int = 1
    parent_dimension_key: str | None = None
    competitor_entity_id: UUID | None = None
    dimension_key: str | None = None


@dataclass(frozen=True)
class FrozenQuestionDimension:
    dimension_key: str
    ordinal: int
    turn_index: int
    parent_dimension_key: str | None
    persona: str
    scenario: str
    intent: str
    funnel: str
    region: str
    language: str
    brand_scope: str
    platform: str
    query_kind: str
    subject: str
    competitor_entity_id: UUID | None

    def canonical_value(self) -> Mapping[str, object]:
        return {key: value for key, value in asdict(self).items() if key != "ordinal"}


@dataclass(frozen=True)
class QuestionFactInput:
    fact_candidate_id: UUID
    statement: str
    statement_hash: str

    def __post_init__(self) -> None:
        if not self.statement.strip() or not SHA256.fullmatch(self.statement_hash):
            raise QuestionContractError("question Fact input is incomplete")
        if _sha(self.statement) != self.statement_hash:
            raise QuestionContractError("question Fact input hash does not match its statement")


@dataclass(frozen=True)
class QuestionEntityInput:
    graph_entity_id: UUID
    entity_type: str
    canonical_name: str

    def __post_init__(self) -> None:
        if not self.entity_type.strip() or not self.canonical_name.strip():
            raise QuestionContractError("question graph entity input is incomplete")


@dataclass(frozen=True)
class QuestionCoverageSlotClaim:
    dimension_key: str
    coverage_role: Literal["category_benchmark", "product_fit", "brand_control"]
    topic_cluster: str
    planned_query_text: str | None = None

    def __post_init__(self) -> None:
        if not self.dimension_key.strip() or not self.topic_cluster.strip():
            raise QuestionContractError("question coverage slot identity is incomplete")
        if self.planned_query_text is not None:
            normalize_question_text(self.planned_query_text)


@dataclass(frozen=True)
class QuestionCandidateDraft:
    adapter_candidate_id: str
    dimension_key: str
    variant_index: int
    turn_index: int
    parent_adapter_candidate_id: str | None
    query_text: str
    query_text_hash: str
    normalized_text_hash: str
    semantic_fingerprint: str
    embedding: tuple[float, ...]
    fact_source_ids: tuple[UUID, ...]
    entity_source_ids: tuple[UUID, ...]
    dedup_status: str = "unique"
    nearest_adapter_candidate_id: str | None = None
    nearest_similarity: float | None = None


@dataclass(frozen=True)
class QuestionSetMeasurements:
    dimension_count: int
    covered_dimension_count: int
    possible_duplicate_count: int
    item_count: int
    coverage_ratio: float
    duplicate_ratio: float


@dataclass(frozen=True)
class QuestionGenerationClaim:
    project_id: UUID
    campaign_id: UUID
    input_hash: str
    configured_model: str
    model_call_budget: int
    adapter_release: str
    selection_manifest_hash: str
    duplicate_threshold: float
    dimensions: tuple[FrozenQuestionDimension, ...]
    facts: tuple[QuestionFactInput, ...]
    entities: tuple[QuestionEntityInput, ...]
    generation_mode: Literal["single_scenario", "coverage_pack"] = "single_scenario"
    coverage_profile: str | None = None
    coverage_profile_hash: str | None = None
    target_count: int | None = None
    product_entity_id: UUID | None = None
    product_category: str | None = None
    product_name: str | None = None
    coverage_slots: tuple[QuestionCoverageSlotClaim, ...] = ()

    def __post_init__(self) -> None:
        if not SHA256.fullmatch(self.input_hash) or not SHA256.fullmatch(
            self.selection_manifest_hash
        ):
            raise QuestionContractError("question generation hashes must be SHA-256")
        if not self.configured_model.strip() or self.model_call_budget < 1:
            raise QuestionContractError("question generation model budget is incomplete")
        if self.adapter_release not in {
            "project-native-rag-v1",
            "llamaindex-property-graph-v1",
        }:
            raise QuestionContractError("question generation adapter is unsupported")
        if not 0.8 <= self.duplicate_threshold <= 1.0:
            raise QuestionContractError("question duplicate threshold is outside its contract")
        if not self.dimensions or not self.facts:
            raise QuestionContractError("question generation requires dimensions and Facts")
        if self.generation_mode == "single_scenario":
            if any(
                value is not None
                for value in (
                    self.coverage_profile,
                    self.coverage_profile_hash,
                    self.target_count,
                    self.product_entity_id,
                    self.product_category,
                    self.product_name,
                )
            ) or self.coverage_slots:
                raise QuestionContractError("single-scenario question claim has coverage fields")
            return
        if self.generation_mode != "coverage_pack":
            raise QuestionContractError("question generation mode is unsupported")
        if (
            not self.coverage_profile
            or not self.coverage_profile_hash
            or not SHA256.fullmatch(self.coverage_profile_hash)
            or self.target_count != len(self.dimensions)
            or self.product_entity_id is None
            or not self.product_category
            or not self.product_name
            or len(self.coverage_slots) != len(self.dimensions)
        ):
            raise QuestionContractError("question coverage claim is incomplete")
        dimension_keys = {item.dimension_key for item in self.dimensions}
        if {item.dimension_key for item in self.coverage_slots} != dimension_keys:
            raise QuestionContractError("question coverage slots crossed frozen dimensions")
        if self.target_count != 100:
            raise QuestionContractError("current question coverage profile requires 100 slots")


def canonical_question_artifact(
    claim: QuestionGenerationClaim, candidates: Sequence[QuestionCandidateDraft]
) -> tuple[bytes, str]:
    rows = []
    for candidate in candidates:
        value = asdict(candidate)
        embedding = value.pop("embedding")
        value["embedding_hash"] = _sha(
            json.dumps(embedding, separators=(",", ":"), ensure_ascii=True)
        )
        value["fact_source_ids"] = [str(item) for item in candidate.fact_source_ids]
        value["entity_source_ids"] = [str(item) for item in candidate.entity_source_ids]
        rows.append(value)
    payload = {
        "schema_version": QUESTION_ARTIFACT_SCHEMA,
        "project_id": str(claim.project_id),
        "campaign_id": str(claim.campaign_id),
        "input_hash": claim.input_hash,
        "adapter_release": claim.adapter_release,
        "selection_manifest_hash": claim.selection_manifest_hash,
        "dimension_schema_version": DIMENSION_SCHEMA_VERSION,
        "embedding_model_key": EMBEDDING_MODEL_KEY,
        "generation_mode": claim.generation_mode,
        "coverage_profile": claim.coverage_profile,
        "coverage_profile_hash": claim.coverage_profile_hash,
        "target_count": claim.target_count,
        "product_entity_id": str(claim.product_entity_id) if claim.product_entity_id else None,
        "product_category": claim.product_category,
        "product_name": claim.product_name,
        "dimensions": [asdict(item) for item in claim.dimensions],
        "coverage_slots": [asdict(item) for item in claim.coverage_slots],
        "candidates": rows,
    }
    content = (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        + "\n"
    ).encode()
    return content, hashlib.sha256(content).hexdigest()


def question_artifact_key(
    *, project_id: UUID, campaign_id: UUID, job_id: UUID, content_hash: str
) -> str:
    if not SHA256.fullmatch(content_hash):
        raise QuestionContractError("question artifact hash must be SHA-256")
    return f"knowledge-question-artifacts/{project_id}/{campaign_id}/{job_id}/{content_hash}.json"


def freeze_dimensions(
    drafts: Sequence[QuestionDimensionDraft],
) -> tuple[FrozenQuestionDimension, ...]:
    if not drafts or len(drafts) > 200:
        raise QuestionContractError("question generation requires 1 to 200 dimensions")
    result: list[FrozenQuestionDimension] = []
    by_key: dict[str, FrozenQuestionDimension] = {}
    for ordinal, draft in enumerate(drafts, 1):
        values = _validated_dimension_values(draft)
        key = (draft.dimension_key or _dimension_key(values)).strip()
        if not key or len(key) > 200 or key in by_key:
            raise QuestionContractError("question dimension keys must be unique and bounded")
        parent = draft.parent_dimension_key.strip() if draft.parent_dimension_key else None
        if (draft.turn_index == 1) != (parent is None):
            raise QuestionContractError("only first-turn dimensions omit a parent")
        if parent is not None:
            previous = by_key.get(parent)
            if previous is None or previous.turn_index >= draft.turn_index:
                raise QuestionContractError(
                    "follow-up dimensions must reference an earlier lower-turn dimension"
                )
        frozen = FrozenQuestionDimension(
            dimension_key=key,
            ordinal=ordinal,
            turn_index=draft.turn_index,
            parent_dimension_key=parent,
            competitor_entity_id=draft.competitor_entity_id,
            **values,
        )
        result.append(frozen)
        by_key[key] = frozen
    return tuple(result)


def normalize_question_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    normalized = _WHITESPACE.sub(" ", normalized)
    normalized = _TERMINAL_PUNCTUATION.sub("", normalized).strip()
    if not normalized or len(normalized) > 2000:
        raise QuestionContractError("question text must contain 1 to 2000 normalized characters")
    return normalized + "?"


def semantic_embedding(
    *, text: str, semantic_fingerprint: str, dimension: FrozenQuestionDimension
) -> tuple[float, ...]:
    normalized = normalize_question_text(text)
    fingerprint = _bounded_text(semantic_fingerprint, "semantic fingerprint", maximum=500)
    dimension_tokens = (
        dimension.persona,
        dimension.scenario,
        dimension.intent,
        dimension.funnel,
        dimension.region,
        dimension.language,
        dimension.brand_scope,
        dimension.platform,
        dimension.query_kind,
        dimension.subject,
    )
    features: list[tuple[str, float]] = []
    for namespace, value in (
        ("question", normalized),
        ("semantic", unicodedata.normalize("NFKC", fingerprint).casefold()),
    ):
        features.extend((f"{namespace}:char:{char}", 1.0) for char in value if not char.isspace())
        compact = "".join(char for char in value if not char.isspace())
        features.extend(
            (f"{namespace}:bigram:{compact[index:index + 2]}", 1.5)
            for index in range(max(0, len(compact) - 1))
        )
        words = value.split()
        features.extend((f"{namespace}:word:{word}", 1.5) for word in words)
        features.extend(
            (f"{namespace}:word-bigram:{words[index]}|{words[index + 1]}", 2.0)
            for index in range(max(0, len(words) - 1))
        )
    features.extend(
        (f"dimension:{index}:{unicodedata.normalize('NFKC', value).casefold()}", 2.5)
        for index, value in enumerate(dimension_tokens)
    )
    vector = [0.0] * EMBEDDING_DIMENSIONS
    for feature, weight in features:
        digest = hashlib.sha256(feature.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSIONS
        vector[index] += weight if digest[4] & 1 else -weight
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        raise QuestionContractError("question semantic embedding has no features")
    return tuple(value / norm for value in vector)


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != EMBEDDING_DIMENSIONS or len(right) != EMBEDDING_DIMENSIONS:
        raise QuestionContractError("question embeddings must contain 1024 dimensions")
    return max(-1.0, min(1.0, sum(a * b for a, b in zip(left, right, strict=True))))


from geo_core.knowledge.question_domain_support import (  # noqa: E402
    bounded_text as _bounded_text,
    deduplicate as _deduplicate,
    dimension_key as _dimension_key,
    model_ids as _model_ids,
    model_text as _model_text,
    validated_dimension_values as _validated_dimension_values,
)


def parse_question_candidates(
    output: Mapping[str, object],
    *,
    dimensions: Sequence[FrozenQuestionDimension],
    facts: Sequence[QuestionFactInput],
    entities: Sequence[QuestionEntityInput],
    duplicate_threshold: float,
    prior_candidates: Sequence[QuestionCandidateDraft] = (),
) -> tuple[QuestionCandidateDraft, ...]:
    if set(output) != {"questions"} or not isinstance(output["questions"], list):
        raise QuestionContractError("question model output must contain only a questions array")
    rows = output["questions"]
    if not rows or len(rows) > len(dimensions) * 3:
        raise QuestionContractError("question model output exceeds its frozen fan-out")
    if not 0.8 <= duplicate_threshold <= 1.0:
        raise QuestionContractError("question duplicate threshold is outside its contract")
    by_dimension = {item.dimension_key: item for item in dimensions}
    fact_ids = {str(item.fact_candidate_id): item.fact_candidate_id for item in facts}
    entity_ids = {str(item.graph_entity_id): item.graph_entity_id for item in entities}
    candidates: list[QuestionCandidateDraft] = []
    existing = list(prior_candidates)
    adapters: dict[str, QuestionCandidateDraft] = {
        item.adapter_candidate_id: item for item in prior_candidates
    }
    for value in rows:
        if not isinstance(value, Mapping):
            raise QuestionContractError("question candidate must be an object")
        expected = {
            "candidate_id",
            "dimension_key",
            "variant_index",
            "text",
            "semantic_fingerprint",
            "supported_fact_ids",
            "supported_entity_ids",
            "parent_candidate_id",
        }
        if set(value) != expected:
            raise QuestionContractError("question candidate contains unexpected fields")
        adapter_id = _model_text(value, "candidate_id", maximum=200)
        key = _model_text(value, "dimension_key", maximum=200)
        dimension = by_dimension.get(key)
        if dimension is None:
            raise QuestionContractError("question candidate references an unknown dimension")
        variant = value["variant_index"]
        if not isinstance(variant, int) or not 1 <= variant <= 3:
            raise QuestionContractError("question candidate variant is outside 1 to 3")
        text = _model_text(value, "text", maximum=2000)
        semantic = _model_text(value, "semantic_fingerprint", maximum=500)
        supported_facts = _model_ids(value, "supported_fact_ids", fact_ids, required=True)
        supported_entities = _model_ids(
            value, "supported_entity_ids", entity_ids, required=False
        )
        parent_value = value["parent_candidate_id"]
        if parent_value is not None and not isinstance(parent_value, str):
            raise QuestionContractError("question candidate parent must be text or null")
        parent = parent_value.strip() if isinstance(parent_value, str) else None
        if dimension.turn_index == 1:
            if parent is not None:
                raise QuestionContractError("first-turn question candidate cannot have a parent")
        else:
            parent_candidate = adapters.get(parent or "")
            parent_dimension = by_dimension.get(dimension.parent_dimension_key or "")
            if (
                parent_candidate is None
                or parent_dimension is None
                or parent_candidate.dimension_key != parent_dimension.dimension_key
            ):
                raise QuestionContractError("follow-up question candidate parent is invalid")
        if adapter_id in adapters:
            raise QuestionContractError("question candidate identity is duplicated")
        normalized_hash = _sha(normalize_question_text(text))
        embedding = semantic_embedding(
            text=text, semantic_fingerprint=semantic, dimension=dimension
        )
        candidate = QuestionCandidateDraft(
            adapter_candidate_id=adapter_id,
            dimension_key=key,
            variant_index=variant,
            turn_index=dimension.turn_index,
            parent_adapter_candidate_id=parent,
            query_text=text,
            query_text_hash=_sha(text),
            normalized_text_hash=normalized_hash,
            semantic_fingerprint=semantic,
            embedding=embedding,
            fact_source_ids=supported_facts,
            entity_source_ids=supported_entities,
        )
        candidate = _deduplicate(candidate, existing + candidates, duplicate_threshold)
        candidates.append(candidate)
        adapters[adapter_id] = candidate
    return tuple(candidates)


def question_set_measurements(
    *, dimension_count: int, candidates: Sequence[QuestionCandidateDraft]
) -> QuestionSetMeasurements:
    if dimension_count < 1 or not candidates:
        raise QuestionContractError("QuestionSet requires dimensions and approved candidates")
    if any(item.dedup_status == "exact_duplicate" for item in candidates):
        raise QuestionContractError("QuestionSet cannot contain exact duplicate questions")
    covered = len({item.dimension_key for item in candidates})
    possible = sum(item.dedup_status == "possible_duplicate" for item in candidates)
    coverage = covered / dimension_count
    duplicate_ratio = possible / len(candidates)
    if coverage < 0.90:
        raise QuestionContractError("QuestionSet dimension coverage is below 90 percent")
    if duplicate_ratio > 0.10:
        raise QuestionContractError("QuestionSet possible duplicate ratio exceeds 10 percent")
    return QuestionSetMeasurements(
        dimension_count,
        covered,
        possible,
        len(candidates),
        coverage,
        duplicate_ratio,
    )


def question_set_content_hash(
    *,
    project_id: UUID,
    campaign_id: UUID,
    generated_by_job_id: UUID,
    series_id: UUID,
    version_number: int,
    items: Sequence[Mapping[str, object]],
) -> str:
    if version_number < 1 or not items:
        raise QuestionContractError("QuestionSet hash requires a positive non-empty version")
    payload = {
        "schema": "geo-question-set-v1",
        "project_id": str(project_id),
        "campaign_id": str(campaign_id),
        "generated_by_job_id": str(generated_by_job_id),
        "series_id": str(series_id),
        "version_number": version_number,
        "items": [dict(value) for value in items],
    }
    return _sha(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def vector_literal(values: Sequence[float]) -> str:
    if len(values) != EMBEDDING_DIMENSIONS or not all(math.isfinite(item) for item in values):
        raise QuestionContractError("question embedding cannot be serialized")
    return "[" + ",".join(f"{item:.12g}" for item in values) + "]"
