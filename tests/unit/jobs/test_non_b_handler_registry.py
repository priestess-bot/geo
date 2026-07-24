from __future__ import annotations

import pytest

from geo_worker.non_b_handlers import (
    NON_B_SHARED_REQUIRED_JOB_KINDS,
    assert_non_b_handlers_registered,
    merge_non_b_handlers,
)
from geo_worker.workflow_c_handlers import WORKFLOW_C_REQUIRED_JOB_KINDS


class _Handler:
    def handle(self, lease):
        del lease
        return {}


def _handlers(kinds: frozenset[str]) -> dict[str, _Handler]:
    return {kind: _Handler() for kind in kinds}


def test_shared_non_b_registry_requires_every_enqueuable_kind() -> None:
    with pytest.raises(RuntimeError, match="unavailable"):
        assert_non_b_handlers_registered({})

    handlers = _handlers(NON_B_SHARED_REQUIRED_JOB_KINDS)
    assert_non_b_handlers_registered(handlers)


def test_merge_rejects_collisions_and_produces_the_closed_world_set() -> None:
    prompt = {"prompt.test.execute": _Handler()}
    synthetic_kinds = frozenset(
        {
            "style.profile.build",
            "review.case.run",
            "offline_experiment.run",
            "synthetic.model.call",
        }
    )
    recommendations = {
        kind: _Handler()
        for kind in NON_B_SHARED_REQUIRED_JOB_KINDS
        - frozenset(prompt)
        - synthetic_kinds
        - WORKFLOW_C_REQUIRED_JOB_KINDS
    }
    merged = merge_non_b_handlers(
        base={},
        prompt=prompt,
        synthetic=_handlers(synthetic_kinds),
        recommendations=recommendations,
        workflow_c=_handlers(WORKFLOW_C_REQUIRED_JOB_KINDS),
    )
    assert NON_B_SHARED_REQUIRED_JOB_KINDS <= frozenset(merged)

    with pytest.raises(RuntimeError, match="duplicates"):
        merge_non_b_handlers(
            base={"prompt.test.execute": _Handler()},
            prompt=prompt,
            synthetic=_handlers(synthetic_kinds),
            recommendations=recommendations,
            workflow_c=_handlers(WORKFLOW_C_REQUIRED_JOB_KINDS),
        )
