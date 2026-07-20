from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest

from geo_core.knowledge.question_domain import (
    EMBEDDING_DIMENSIONS,
    QuestionContractError,
    QuestionDimensionDraft,
    QuestionEntityInput,
    QuestionFactInput,
    freeze_dimensions,
    normalize_question_text,
    parse_question_candidates,
    question_generation_batch_count,
    question_generation_minimum_call_budget,
    question_set_content_hash,
    question_set_measurements,
    semantic_embedding,
    vector_literal,
)


def _dimension(**changes: object) -> QuestionDimensionDraft:
    values: dict[str, object] = {
        "dimension_key": "awareness-brand",
        "persona": "采购负责人",
        "scenario": "比较工业泵",
        "intent": "核验流量和品牌",
        "funnel": "awareness",
        "region": "CN",
        "language": "zh-CN",
        "brand_scope": "brand",
        "platform": "chatgpt_search",
        "query_kind": "comparison",
        "subject": "A1",
    }
    values.update(changes)
    return QuestionDimensionDraft(**values)  # type: ignore[arg-type]


def _fact(text: str = "A1 的流量为每分钟 2 升。") -> QuestionFactInput:
    return QuestionFactInput(uuid4(), text, hashlib.sha256(text.encode()).hexdigest())


def test_dimensions_freeze_ordered_multi_turn_parent_contract() -> None:
    dimensions = freeze_dimensions(
        (
            _dimension(),
            _dimension(
                dimension_key="follow-up",
                turn_index=2,
                parent_dimension_key="awareness-brand",
                intent="追问适用场景",
            ),
        )
    )

    assert [item.ordinal for item in dimensions] == [1, 2]
    assert dimensions[1].parent_dimension_key == dimensions[0].dimension_key

    with pytest.raises(QuestionContractError, match="earlier lower-turn"):
        freeze_dimensions(
            (
                _dimension(
                    dimension_key="follow-up",
                    turn_index=2,
                    parent_dimension_key="missing",
                ),
            )
        )


def test_question_generation_batch_count_preserves_turn_boundaries() -> None:
    dimensions = freeze_dimensions(
        (
            _dimension(dimension_key="turn-1"),
            _dimension(
                dimension_key="turn-2",
                turn_index=2,
                parent_dimension_key="turn-1",
            ),
            _dimension(
                dimension_key="turn-3",
                turn_index=3,
                parent_dimension_key="turn-2",
            ),
        )
    )

    assert question_generation_batch_count(dimensions) == 3
    assert question_generation_minimum_call_budget(dimensions, 3) == 9


def test_semantic_hash_embedding_is_deterministic_normalized_and_1024_dimensions() -> None:
    dimension = freeze_dimensions((_dimension(),))[0]

    first = semantic_embedding(
        text="A1 的流量和品牌如何？",
        semantic_fingerprint="核验 A1 流量 品牌",
        dimension=dimension,
    )
    second = semantic_embedding(
        text="A1 的流量和品牌如何？",
        semantic_fingerprint="核验 A1 流量 品牌",
        dimension=dimension,
    )

    assert first == second
    assert len(first) == EMBEDDING_DIMENSIONS
    assert sum(value * value for value in first) == pytest.approx(1.0)
    assert vector_literal(first).startswith("[")
    assert normalize_question_text("  A1 的流量如何？？ ") == "a1 的流量如何?"


def test_candidate_parser_requires_frozen_fact_sources_and_marks_semantic_duplicates() -> None:
    dimension = freeze_dimensions((_dimension(),))[0]
    fact = _fact()
    entity = QuestionEntityInput(uuid4(), "product", "A1")
    output = {
        "questions": [
            {
                "candidate_id": "candidate-1",
                "dimension_key": dimension.dimension_key,
                "variant_index": 1,
                "text": "采购负责人应如何核验 A1 的流量和品牌？",
                "semantic_fingerprint": "核验 A1 流量 品牌",
                "supported_fact_ids": [str(fact.fact_candidate_id)],
                "supported_entity_ids": [str(entity.graph_entity_id)],
                "parent_candidate_id": None,
            },
            {
                "candidate_id": "candidate-2",
                "dimension_key": dimension.dimension_key,
                "variant_index": 2,
                "text": "采购负责人怎样确认 A1 的品牌与流量？",
                "semantic_fingerprint": "核验 A1 流量 品牌",
                "supported_fact_ids": [str(fact.fact_candidate_id)],
                "supported_entity_ids": [str(entity.graph_entity_id)],
                "parent_candidate_id": None,
            },
        ]
    }

    candidates = parse_question_candidates(
        output,
        dimensions=(dimension,),
        facts=(fact,),
        entities=(entity,),
        duplicate_threshold=0.92,
    )

    assert candidates[0].dedup_status == "unique"
    assert candidates[1].dedup_status == "possible_duplicate"
    assert candidates[1].nearest_adapter_candidate_id == "candidate-1"
    assert candidates[0].fact_source_ids == (fact.fact_candidate_id,)

    invalid = {"questions": [{**output["questions"][0], "supported_fact_ids": []}]}
    with pytest.raises(QuestionContractError, match="supported_fact_ids"):
        parse_question_candidates(
            invalid,
            dimensions=(dimension,),
            facts=(fact,),
            entities=(entity,),
            duplicate_threshold=0.92,
        )


def test_question_set_gates_and_hash_are_stable() -> None:
    dimensions = freeze_dimensions(tuple(_dimension(dimension_key=f"dim-{index}") for index in range(10)))
    fact = _fact()
    rows = {
        "questions": [
            {
                "candidate_id": f"candidate-{index}",
                "dimension_key": dimension.dimension_key,
                "variant_index": 1,
                "text": f"问题 {index} 应依据什么事实？",
                "semantic_fingerprint": f"intent-{index}",
                "supported_fact_ids": [str(fact.fact_candidate_id)],
                "supported_entity_ids": [],
                "parent_candidate_id": None,
            }
            for index, dimension in enumerate(dimensions[:9])
        ]
    }
    candidates = parse_question_candidates(
        rows,
        dimensions=dimensions,
        facts=(fact,),
        entities=(),
        duplicate_threshold=1.0,
    )

    measurement = question_set_measurements(dimension_count=10, candidates=candidates)
    assert measurement.coverage_ratio == 0.9
    assert measurement.duplicate_ratio == 0

    values = {
        "project_id": uuid4(),
        "campaign_id": uuid4(),
        "generated_by_job_id": uuid4(),
        "series_id": uuid4(),
        "version_number": 1,
        "items": [
            {
                "ordinal": index,
                "candidate_id": item.adapter_candidate_id,
                "dimension_key": item.dimension_key,
                "query_text": item.query_text,
                "source_fact_ids": [str(value) for value in item.fact_source_ids],
            }
            for index, item in enumerate(candidates, 1)
        ],
    }
    assert question_set_content_hash(**values) == question_set_content_hash(**values)
