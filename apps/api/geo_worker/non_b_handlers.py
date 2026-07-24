"""Closed-world registration contract for every shared non-B durable job.

The browser collection worker intentionally owns only login/browser work.  All
other roadmap jobs are executed by ``geo_worker.tasks`` and must be registered
before the generic durable dispatcher starts consuming messages.
"""

from __future__ import annotations

from collections.abc import Mapping

from geo_core.placements.worker_composition import JobHandler
from geo_core.prompts.test_execution_contracts import PROMPT_TEST_REQUIRED_JOB_KINDS
from geo_core.recommendations.generation_worker_contracts import (
    RECOMMENDATION_REQUIRED_JOB_KINDS,
)
from geo_core.synthetic_lab.child_model_calls import SYNTHETIC_MODEL_CHILD_KIND

from geo_worker.workflow_c_handlers import WORKFLOW_C_REQUIRED_JOB_KINDS


SYNTHETIC_REQUIRED_JOB_KINDS = frozenset(
    {
        "style.profile.build",
        "review.case.run",
        "offline_experiment.run",
        SYNTHETIC_MODEL_CHILD_KIND,
    }
)

NON_B_SHARED_REQUIRED_JOB_KINDS = frozenset().union(
    PROMPT_TEST_REQUIRED_JOB_KINDS,
    SYNTHETIC_REQUIRED_JOB_KINDS,
    RECOMMENDATION_REQUIRED_JOB_KINDS,
    WORKFLOW_C_REQUIRED_JOB_KINDS,
)


def merge_non_b_handlers(
    *,
    base: Mapping[str, JobHandler],
    prompt: Mapping[str, JobHandler],
    synthetic: Mapping[str, JobHandler],
    recommendations: Mapping[str, JobHandler],
    workflow_c: Mapping[str, JobHandler],
) -> dict[str, JobHandler]:
    """Merge production handler maps and fail closed on omissions/collisions."""

    result = dict(base)
    for name, handlers in (
        ("prompt", prompt),
        ("synthetic", synthetic),
        ("recommendation", recommendations),
        ("workflow_c", workflow_c),
    ):
        overlap = frozenset(result).intersection(handlers)
        if overlap:
            raise RuntimeError(
                f"{name} handler registry duplicates durable Job kinds: {sorted(overlap)!r}"
            )
        result.update(handlers)
    assert_non_b_handlers_registered(result)
    return result


def assert_non_b_handlers_registered(handlers: Mapping[str, JobHandler]) -> None:
    """Fail startup/readiness when a route can enqueue a Job this worker cannot run."""

    missing = NON_B_SHARED_REQUIRED_JOB_KINDS - frozenset(handlers)
    if missing:
        raise RuntimeError(
            "Shared non-B Worker handlers are unavailable: "
            f"{sorted(missing)!r}"
        )


__all__ = [
    "NON_B_SHARED_REQUIRED_JOB_KINDS",
    "SYNTHETIC_REQUIRED_JOB_KINDS",
    "assert_non_b_handlers_registered",
    "merge_non_b_handlers",
]
