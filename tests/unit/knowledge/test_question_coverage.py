from __future__ import annotations

from collections import Counter

import pytest

from geo_core.knowledge.question_coverage import (
    COVERAGE_PROFILE_KEY,
    QuestionCoverageError,
    build_coverage_question_plan,
    coverage_profile_hash,
    coverage_profile_summary,
    coverage_question_identity_error,
)
from geo_core.knowledge.question_domain import freeze_dimensions


def _plan(product: str, category: str = "robotic_lawn_mower"):
    return build_coverage_question_plan(
        category_key=category,
        product_name=product,
        product_context="marketed area 600 sqm",
    )


def test_balanced_profile_produces_exactly_100_standalone_au_slots() -> None:
    plan = _plan("ADVINSYS TerraMow V600")

    assert plan.profile_key == COVERAGE_PROFILE_KEY
    assert plan.profile_hash == coverage_profile_hash()
    assert len(plan.slots) == plan.target_count == 100
    assert len({slot.dimension.dimension_key for slot in plan.slots}) == 100
    assert {slot.dimension.turn_index for slot in plan.slots} == {1}
    assert {slot.dimension.region for slot in plan.slots} == {"AU"}
    assert {slot.dimension.language for slot in plan.slots} == {"en-AU"}
    assert {slot.dimension.platform for slot in plan.slots} == {"other"}

    roles = Counter(slot.coverage_role for slot in plan.slots)
    assert roles == {
        "category_benchmark": 50,
        "product_fit": 40,
        "brand_control": 10,
    }
    non_brand = [slot for slot in plan.slots if slot.dimension.brand_scope == "non_brand"]
    assert len(non_brand) == 90
    assert Counter(slot.dimension.query_kind for slot in non_brand) == {
        "recommendation": 35,
        "comparison": 25,
        "research": 20,
        "support": 10,
    }
    assert Counter(slot.dimension.funnel for slot in plan.slots) == {
        "awareness": 20,
        "consideration": 40,
        "decision": 30,
        "retention": 10,
    }


def test_real_product_context_stays_inside_the_frozen_dimension_contract() -> None:
    plan = build_coverage_question_plan(
        category_key="robotic_lawn_mower",
        product_name="ADVINSYS TerraMow V600",
        product_context=(
            "marketed lawn area 600 sqm; operator focus: "
            + "x" * 120
        ),
    )

    frozen = freeze_dimensions(tuple(slot.dimension for slot in plan.slots))

    assert len(frozen) == 100
    assert max(len(item.scenario) for item in frozen) <= 300


def test_same_category_products_share_exactly_the_same_50_benchmark_queries() -> None:
    v600 = _plan("ADVINSYS TerraMow V600")
    v1000 = _plan("ADVINSYS TerraMow V1000")

    first = [slot.planned_query_text for slot in v600.slots if slot.planned_query_text]
    second = [slot.planned_query_text for slot in v1000.slots if slot.planned_query_text]
    assert first == second
    assert len(first) == len(set(first)) == 50
    assert all("V600" not in text and "V1000" not in text for text in first)


def test_pool_profile_has_category_specific_benchmarks_and_stable_manifest() -> None:
    pool = _plan("ADVINSYS Seauto SAT30", "robotic_pool_cleaner")
    benchmark = [slot.planned_query_text for slot in pool.slots if slot.planned_query_text]

    assert len(benchmark) == 50
    assert all("pool" in text.lower() for text in benchmark)
    summary = coverage_profile_summary()
    assert summary["hash"] == pool.profile_hash
    assert len(summary["topic_clusters"]) == 10


def test_profile_rejects_unknown_categories_and_versions() -> None:
    with pytest.raises(QuestionCoverageError, match="unsupported product category"):
        _plan("Unknown", "unknown")
    with pytest.raises(QuestionCoverageError, match="unsupported question coverage profile"):
        build_coverage_question_plan(
            category_key="robotic_lawn_mower",
            product_name="V600",
            profile_key="future-profile",
        )


def test_coverage_identity_rules_keep_brand_and_non_brand_denominators_separate() -> None:
    product = "ADVINSYS TerraMow V600"
    assert coverage_question_identity_error(
        text="Which robot lawn mower suits a sloping Australian garden?",
        coverage_role="product_fit",
        product_name=product,
    ) is None
    assert coverage_question_identity_error(
        text="Is the TerraMow V600 suitable for a sloping garden?",
        coverage_role="product_fit",
        product_name=product,
    ) == "non-brand coverage question exposed product identity"
    assert coverage_question_identity_error(
        text="How does the V600 handle narrow passages?",
        coverage_role="brand_control",
        product_name=product,
    ) is None
    assert coverage_question_identity_error(
        text="How does this mower handle narrow passages?",
        coverage_role="brand_control",
        product_name=product,
    ) == "brand-control question omitted the product model"
