"""Deterministic helpers used by QuestionSet application commands."""

from __future__ import annotations

import hashlib
from typing import Mapping, Sequence, cast
from uuid import UUID

from geo_core.knowledge.domain import KnowledgeConflict
from geo_core.knowledge.question_domain import (
    FrozenQuestionDimension,
    cosine_similarity,
    normalize_question_text,
    semantic_embedding,
)


def effective_dedup_statuses(
    candidates: Sequence[Mapping[str, object]],
) -> dict[UUID, str]:
    """Re-check the effective text without mutating immutable candidate evidence.

    Candidate-level dedup fields describe the original generated text and are protected by
    PostgreSQL. A revision changes only the text snapshot, so finalization must compare the
    current text deterministically before allowing a previously flagged near-duplicate.
    Semantic fingerprints remain evidence, but are intentionally not treated as a duplicate
    by themselves here: the effective question text is the reviewable object after an edit.
    """
    if not candidates:
        return {}
    threshold = float(str(candidates[0]["semantic_duplicate_threshold"]))
    if not 0.8 <= threshold <= 1.0:
        raise KnowledgeConflict("question duplicate threshold is outside its frozen contract")
    if any(float(str(item["semantic_duplicate_threshold"])) != threshold for item in candidates):
        raise KnowledgeConflict("question candidates crossed duplicate threshold contracts")

    effective: list[tuple[UUID, str, tuple[float, ...], bool, str]] = []
    ordered = sorted(
        candidates,
        key=lambda item: (
            int(str(item["dimension_ordinal"])),
            int(str(item["variant_index"])),
            str(item["id"]),
        ),
    )
    for item in ordered:
        dimension = FrozenQuestionDimension(
            dimension_key=str(item["dimension_key"]),
            ordinal=int(str(item["dimension_ordinal"])),
            turn_index=int(str(item["turn_index"])),
            parent_dimension_key=cast(str | None, item["parent_dimension_key"]),
            persona=str(item["persona"]),
            scenario=str(item["scenario"]),
            intent=str(item["intent"]),
            funnel=str(item["funnel"]),
            region=str(item["region"]),
            language=str(item["language"]),
            brand_scope=str(item["brand_scope"]),
            platform=str(item["platform"]),
            query_kind=str(item["query_kind"]),
            subject=str(item["subject"]),
            competitor_entity_id=cast(UUID | None, item["competitor_entity_id"]),
        )
        text = str(item.get("effective_query_text") or item["query_text"])
        embedding = semantic_embedding(
            text=text,
            semantic_fingerprint=str(item["semantic_fingerprint"]),
            dimension=dimension,
        )
        normalized_hash = hashlib.sha256(normalize_question_text(text).encode()).hexdigest()
        effective.append(
            (
                cast(UUID, item["id"]),
                normalized_hash,
                embedding,
                item.get("effective_revision_id") is not None,
                str(item["dedup_status"]),
            )
        )

    statuses: dict[UUID, str] = {
        candidate_id: original_status
        for candidate_id, _, _, _, original_status in effective
    }
    for candidate_id, normalized_hash, embedding, was_edited, _ in effective:
        if not was_edited:
            continue
        nearest_similarity = -1.0
        status = "unique"
        for other_id, other_hash, other_embedding, _, _ in effective:
            if other_id == candidate_id:
                continue
            similarity = cosine_similarity(embedding, other_embedding)
            nearest_similarity = max(nearest_similarity, similarity)
            if normalized_hash == other_hash:
                status = "exact_duplicate"
                nearest_similarity = 1.0
                break
        if status != "exact_duplicate" and nearest_similarity >= threshold:
            status = "possible_duplicate"
        statuses[candidate_id] = status
    return statuses
