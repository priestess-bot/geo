"""Private helpers shared by the question generation worker."""

from __future__ import annotations

import hashlib
import json
from typing import Mapping, Sequence

from geo_core.knowledge.question_coverage import coverage_question_identity_error
from geo_core.knowledge.question_domain import (
    FrozenQuestionDimension,
    QuestionCandidateDraft,
    QuestionContractError,
    QuestionGenerationClaim,
    QUESTION_GENERATION_BATCH_SIZE,
)


def batches_by_turn(
    claim: QuestionGenerationClaim,
) -> tuple[tuple[FrozenQuestionDimension, ...], ...]:
    batches: list[tuple[FrozenQuestionDimension, ...]] = []
    for turn in range(1, 4):
        values = [item for item in claim.dimensions if item.turn_index == turn]
        batches.extend(
            tuple(values[index : index + QUESTION_GENERATION_BATCH_SIZE])
            for index in range(0, len(values), QUESTION_GENERATION_BATCH_SIZE)
        )
    return tuple(batches)


def validate_coverage_batch(
    claim: QuestionGenerationClaim,
    dimensions: Sequence[FrozenQuestionDimension],
    candidates: Sequence[QuestionCandidateDraft],
) -> None:
    expected = {item.dimension_key for item in dimensions}
    if (
        len(candidates) != len(dimensions)
        or {item.dimension_key for item in candidates} != expected
        or any(item.variant_index != 1 for item in candidates)
        or any(item.dedup_status == "exact_duplicate" for item in candidates)
    ):
        raise QuestionContractError(
            "coverage batch must contain one unique variant for every frozen slot"
        )
    slots = {item.dimension_key: item for item in claim.coverage_slots}
    for candidate in candidates:
        slot = slots[candidate.dimension_key]
        identity_error = coverage_question_identity_error(
            text=candidate.query_text,
            coverage_role=slot.coverage_role,
            product_name=claim.product_name or "",
        )
        if identity_error:
            raise QuestionContractError(identity_error)


def validate_complete_coverage_pack(
    claim: QuestionGenerationClaim, candidates: Sequence[QuestionCandidateDraft]
) -> None:
    if (
        len(candidates) != claim.target_count
        or len({item.dimension_key for item in candidates}) != claim.target_count
        or len({item.normalized_text_hash for item in candidates}) != claim.target_count
    ):
        raise QuestionContractError(
            "coverage generation must finish with 100 slots and 100 unique question texts"
        )


def request_hash_for_payload(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
