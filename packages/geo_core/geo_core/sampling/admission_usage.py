"""Immutable admission reservation and UTC usage-window records."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from geo_core.sampling.contracts import (
    SamplingRuleViolation,
    canonical_hash,
    _require_aware,
    _text,
)


@dataclass(frozen=True)
class SamplingAdmissionReservation:
    project_id: UUID
    policy_id: UUID
    policy_hash: str
    policy_version: str
    run_id: UUID
    suite_id: UUID
    suite_hash: str
    purpose: str
    idempotency_key: str
    reserved_task_count: int
    consumed_task_count: int
    released_task_count: int
    created_at: datetime
    updated_at: datetime
    aggregate_version: int = 1
    reservation_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for digest in (self.policy_hash, self.suite_hash):
            if len(digest) != 64 or any(value not in "0123456789abcdef" for value in digest):
                raise SamplingRuleViolation("admission reservation lineage must use SHA-256")
        for name in ("policy_version", "purpose", "idempotency_key"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.reserved_task_count < 1 or min(
            self.consumed_task_count,
            self.released_task_count,
        ) < 0:
            raise SamplingRuleViolation("admission reservation counts are invalid")
        if self.consumed_task_count + self.released_task_count > self.reserved_task_count:
            raise SamplingRuleViolation("admission reservation exceeds its frozen denominator")
        if self.aggregate_version < 1:
            raise SamplingRuleViolation("admission reservation version must be positive")
        _require_aware(self.created_at, "admission reservation creation time")
        _require_aware(self.updated_at, "admission reservation update time")
        if self.updated_at < self.created_at:
            raise SamplingRuleViolation("admission reservation time cannot move backwards")
        object.__setattr__(
            self,
            "reservation_hash",
            canonical_hash(
                {
                    "project_id": str(self.project_id),
                    "policy_id": str(self.policy_id),
                    "policy_hash": self.policy_hash,
                    "policy_version": self.policy_version,
                    "run_id": str(self.run_id),
                    "suite_id": str(self.suite_id),
                    "suite_hash": self.suite_hash,
                    "purpose": self.purpose,
                    "idempotency_key": self.idempotency_key,
                    "reserved_task_count": self.reserved_task_count,
                    "created_at": self.created_at.isoformat(),
                }
            ),
        )

    @property
    def unused_task_count(self) -> int:
        return self.reserved_task_count - self.consumed_task_count - self.released_task_count

    @property
    def charged_task_count(self) -> int:
        return self.reserved_task_count - self.released_task_count


@dataclass(frozen=True)
class SamplingAdmissionUsageWindow:
    project_id: UUID
    policy_id: UUID
    window_start: datetime
    window_end: datetime
    consumed_task_count: int
    updated_at: datetime
    aggregate_version: int = 1

    def __post_init__(self) -> None:
        for value, label in (
            (self.window_start, "usage window start"),
            (self.window_end, "usage window end"),
            (self.updated_at, "usage window update time"),
        ):
            _require_aware(value, label)
        if self.window_end <= self.window_start or self.consumed_task_count < 0:
            raise SamplingRuleViolation("admission usage window is invalid")
        if self.aggregate_version < 1:
            raise SamplingRuleViolation("admission usage window version must be positive")


def new_reservation(
    *,
    project_id: UUID,
    policy_id: UUID,
    policy_hash: str,
    policy_version: str,
    run_id: UUID,
    suite_id: UUID,
    suite_hash: str,
    purpose: str,
    idempotency_key: str,
    reserved_task_count: int,
    created_at: datetime,
) -> SamplingAdmissionReservation:
    return SamplingAdmissionReservation(
        project_id=project_id,
        policy_id=policy_id,
        policy_hash=policy_hash,
        policy_version=policy_version,
        run_id=run_id,
        suite_id=suite_id,
        suite_hash=suite_hash,
        purpose=purpose,
        idempotency_key=idempotency_key,
        reserved_task_count=reserved_task_count,
        consumed_task_count=0,
        released_task_count=0,
        created_at=created_at,
        updated_at=created_at,
    )


def consume_reservation(
    reservation: SamplingAdmissionReservation,
    *,
    task_count: int,
    occurred_at: datetime,
) -> SamplingAdmissionReservation:
    if task_count < 0 or task_count > reservation.unused_task_count:
        raise SamplingRuleViolation("admission reservation cannot cover new usage")
    if task_count == 0:
        return reservation
    return replace(
        reservation,
        consumed_task_count=reservation.consumed_task_count + task_count,
        updated_at=occurred_at,
        aggregate_version=reservation.aggregate_version + 1,
    )


def release_unused_reservation(
    reservation: SamplingAdmissionReservation,
    *,
    task_count: int,
    occurred_at: datetime,
) -> SamplingAdmissionReservation:
    if task_count < 0 or task_count > reservation.unused_task_count:
        raise SamplingRuleViolation("only unused admission reservations can be released")
    if task_count == 0:
        return reservation
    return replace(
        reservation,
        released_task_count=reservation.released_task_count + task_count,
        updated_at=occurred_at,
        aggregate_version=reservation.aggregate_version + 1,
    )


def utc_usage_window(at: datetime) -> tuple[datetime, datetime]:
    _require_aware(at, "admission usage time")
    start = at.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)
