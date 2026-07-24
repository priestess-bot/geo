"""Frozen subject-inventory validation shared by Synthetic execution contracts."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol
from uuid import UUID

from geo_core.synthetic_lab.domain import SyntheticLabContractError


class SubjectEvidence(Protocol):
    @property
    def subject_id(self) -> str: ...


def validate_review_subject_inventory(
    subject_id: UUID,
    evidence: Iterable[SubjectEvidence],
) -> None:
    try:
        subjects = {UUID(item.subject_id) for item in evidence}
    except ValueError as error:
        raise SyntheticLabContractError(
            "Review Case evidence subject identities must be UUIDs"
        ) from error
    if subject_id not in subjects:
        raise SyntheticLabContractError("Review Case evidence omits the frozen subject")


__all__ = ["validate_review_subject_inventory"]
