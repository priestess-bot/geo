"""Private helpers for the question domain contract."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Mapping, Sequence
from uuid import UUID

from geo_core.knowledge.question_domain import (
    BRAND_SCOPES,
    FUNNELS,
    PLATFORMS,
    QUERY_KINDS,
    QuestionCandidateDraft,
    QuestionContractError,
    QuestionDimensionDraft,
    _sha,
    cosine_similarity,
    normalize_question_text,
)


def validated_dimension_values(draft: QuestionDimensionDraft) -> dict[str, str]:
    if not 1 <= draft.turn_index <= 3:
        raise QuestionContractError("question dimension turn must be between 1 and 3")
    values = {
        "persona": bounded_text(draft.persona, "persona"),
        "scenario": bounded_text(draft.scenario, "scenario"),
        "intent": bounded_text(draft.intent, "intent"),
        "funnel": bounded_text(draft.funnel, "funnel"),
        "region": bounded_text(draft.region, "region"),
        "language": bounded_text(draft.language, "language"),
        "brand_scope": bounded_text(draft.brand_scope, "brand scope"),
        "platform": bounded_text(draft.platform, "platform"),
        "query_kind": bounded_text(draft.query_kind, "query kind"),
        "subject": bounded_text(draft.subject, "subject"),
    }
    if values["funnel"] not in FUNNELS or values["brand_scope"] not in BRAND_SCOPES:
        raise QuestionContractError("question funnel or brand scope is unsupported")
    if values["platform"] not in PLATFORMS or values["query_kind"] not in QUERY_KINDS:
        raise QuestionContractError("question platform or query kind is unsupported")
    if (values["brand_scope"] == "competitor") != (draft.competitor_entity_id is not None):
        raise QuestionContractError("competitor dimensions require exactly one competitor entity")
    return values


def dimension_key(values: Mapping[str, str]) -> str:
    return "dim-" + _sha(
        json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )[:24]


def deduplicate(
    candidate: QuestionCandidateDraft,
    existing: Sequence[QuestionCandidateDraft],
    threshold: float,
) -> QuestionCandidateDraft:
    nearest: QuestionCandidateDraft | None = None
    nearest_similarity = -1.0
    status = "unique"
    for previous in existing:
        similarity = cosine_similarity(candidate.embedding, previous.embedding)
        if similarity > nearest_similarity:
            nearest, nearest_similarity = previous, similarity
        if candidate.normalized_text_hash == previous.normalized_text_hash:
            status = "exact_duplicate"
            nearest, nearest_similarity = previous, 1.0
            break
        if (
            normalize_question_text(candidate.semantic_fingerprint)
            == normalize_question_text(previous.semantic_fingerprint)
            or similarity >= threshold
        ):
            status = "possible_duplicate"
    if nearest is None:
        return candidate
    persisted_similarity = round(nearest_similarity, 4)
    if status == "unique" and persisted_similarity >= threshold:
        status = "possible_duplicate"
    return replace(
        candidate,
        dedup_status=status,
        nearest_adapter_candidate_id=nearest.adapter_candidate_id,
        nearest_similarity=persisted_similarity,
    )


def model_ids(
    row: Mapping[str, object],
    key: str,
    allowed: Mapping[str, UUID],
    *,
    required: bool,
) -> tuple[UUID, ...]:
    value = row[key]
    if not isinstance(value, list) or (required and not value) or len(value) > len(allowed):
        raise QuestionContractError(f"question candidate {key} is invalid")
    result: list[UUID] = []
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            raise QuestionContractError(f"question candidate {key} crossed frozen sources")
        identifier = allowed[item]
        if identifier not in result:
            result.append(identifier)
    return tuple(result)


def model_text(row: Mapping[str, object], key: str, *, maximum: int) -> str:
    value = row[key]
    if not isinstance(value, str):
        raise QuestionContractError(f"question candidate {key} must be text")
    return bounded_text(value, key, maximum=maximum)


def bounded_text(value: str, label: str, *, maximum: int = 300) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise QuestionContractError(f"question {label} is required and bounded")
    return normalized
