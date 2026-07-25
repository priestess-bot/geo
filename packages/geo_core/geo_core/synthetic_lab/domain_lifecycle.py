"""Lifecycle transitions for Synthetic Lab sources, collections and samples."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from enum import StrEnum
from typing import TypeVar
from uuid import UUID

from geo_core.synthetic_lab.domain import (
    COLLECTION_RUN_TRANSITIONS,
    STYLE_SOURCE_TRANSITIONS,
    CollectionRun,
    CollectionRunStatus,
    StyleSample,
    StyleSampleReviewStatus,
    StyleSource,
    SyntheticLabContractError,
    SyntheticLabTransitionError,
)


_EnumT = TypeVar("_EnumT", bound=StrEnum)


def _target_status(
    *,
    current: _EnumT,
    command: str,
    transitions: Mapping[_EnumT, Mapping[str, _EnumT]],
    label: str,
) -> _EnumT:
    target = transitions[current].get(command)
    if target is None:
        raise SyntheticLabTransitionError(
            f"{label} command {command!r} is not allowed from {current.value!r}"
        )
    return target


def transition_style_source(source: StyleSource, *, command: str) -> StyleSource:
    target = _target_status(
        current=source.status,
        command=command,
        transitions=STYLE_SOURCE_TRANSITIONS,
        label="Style Source",
    )
    return replace(source, status=target)


def transition_collection_run(
    run: CollectionRun,
    *,
    command: str,
    raw_manifest_hash: str | None = None,
    reason: str | None = None,
) -> CollectionRun:
    target = _target_status(
        current=run.status,
        command=command,
        transitions=COLLECTION_RUN_TRANSITIONS,
        label="Collection Run",
    )
    if target == CollectionRunStatus.COMPLETED:
        return replace(
            run,
            status=target,
            raw_manifest_hash=raw_manifest_hash,
            terminal_reason=None,
        )
    if target in {CollectionRunStatus.FAILED, CollectionRunStatus.CANCELLED}:
        return replace(run, status=target, terminal_reason=reason)
    if raw_manifest_hash is not None or reason is not None:
        raise SyntheticLabContractError(
            "non-terminal Collection Run transition cannot set terminal evidence"
        )
    return replace(run, status=target)


def transition_style_sample_review(
    sample: StyleSample,
    *,
    command: str,
    reviewer_id: UUID,
    reviewed_at: datetime,
) -> StyleSample:
    if sample.review_status != StyleSampleReviewStatus.PENDING_REVIEW:
        raise SyntheticLabTransitionError("reviewed Style Sample is terminal")
    targets = {
        "approve": StyleSampleReviewStatus.APPROVED,
        "reject": StyleSampleReviewStatus.REJECTED,
    }
    target = targets.get(command)
    if target is None:
        raise SyntheticLabTransitionError(f"unsupported Style Sample command: {command!r}")
    return replace(
        sample,
        review_status=target,
        reviewed_by=reviewer_id,
        reviewed_at=reviewed_at,
    )


__all__ = [
    "_target_status",
    "transition_collection_run",
    "transition_style_sample_review",
    "transition_style_source",
]
