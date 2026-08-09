from __future__ import annotations

from types import SimpleNamespace

import pytest

from geo_api.workflow_c_sampling_catalog import select_sampling_questions
from geo_core.sampling import SamplingConflict, SamplingQuestion


def _input(count: int) -> SimpleNamespace:
    return SimpleNamespace(
        questions=tuple(
            SamplingQuestion(f"item-{index}", "v1", f"{index:064x}")
            for index in range(count)
        )
    )


def test_production_input_requires_explicit_ten_question_selection() -> None:
    with pytest.raises(SamplingConflict, match="exactly 10"):
        select_sampling_questions(_input(11), None)


def test_selection_is_resolved_only_against_frozen_input() -> None:
    selected, selected_ids = select_sampling_questions(
        _input(12), [f"item-{index}" for index in range(1, 11)]
    )

    assert selected_ids == tuple(f"item-{index}" for index in range(1, 11))
    assert tuple(item.question_id for item in selected) == selected_ids

    with pytest.raises(SamplingConflict, match="outside the frozen input"):
        select_sampling_questions(
            _input(12), [f"item-{index}" for index in range(1, 10)] + ["unknown"]
        )


def test_exact_ten_input_can_use_default_selection_and_exposes_ids() -> None:
    selected, selected_ids = select_sampling_questions(_input(10), None)

    assert selected_ids == tuple(f"item-{index}" for index in range(10))
    assert tuple(item.question_id for item in selected) == selected_ids
