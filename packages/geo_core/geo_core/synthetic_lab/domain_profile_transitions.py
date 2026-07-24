"""Style Profile lifecycle operation kept separate from immutable value contracts."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from uuid import UUID

from geo_core.synthetic_lab.domain import (
    STYLE_PROFILE_TRANSITIONS,
    StyleProfileStatus,
    StyleProfileVersion,
    StyleSample,
    SyntheticLabContractError,
    _target_status,
    assert_profile_sample_set,
)


def transition_style_profile(
    profile: StyleProfileVersion,
    *,
    command: str,
    reviewer_id: UUID | None = None,
    reviewed_at: datetime | None = None,
    samples: tuple[StyleSample, ...] | None = None,
) -> StyleProfileVersion:
    target = _target_status(
        current=profile.status,
        command=command,
        transitions=STYLE_PROFILE_TRANSITIONS,
        label="Style Profile",
    )
    if target in {StyleProfileStatus.APPROVED, StyleProfileStatus.REJECTED}:
        return replace(
            profile,
            status=target,
            reviewed_by=reviewer_id,
            reviewed_at=reviewed_at,
        )
    if target == StyleProfileStatus.FROZEN:
        if samples is None:
            raise SyntheticLabContractError("freezing Style Profile requires its sample set")
        assert_profile_sample_set(profile, samples)
    elif reviewer_id is not None or reviewed_at is not None or samples is not None:
        raise SyntheticLabContractError(
            "Style Profile transition received evidence that is not applicable"
        )
    return replace(profile, status=target)


__all__ = ["transition_style_profile"]
