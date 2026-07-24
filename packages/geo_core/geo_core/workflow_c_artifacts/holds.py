"""Two-person legal-hold commands for restricted Workflow C artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from geo_core.sampling.contracts import SamplingRuleViolation


class WorkflowCArtifactHoldAction(StrEnum):
    APPLY = "apply"
    EXTEND = "extend"
    RELEASE = "release"


class WorkflowCArtifactHoldStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass(frozen=True)
class WorkflowCArtifactHoldRequest:
    id: UUID
    project_id: UUID
    artifact_id: UUID
    action: WorkflowCArtifactHoldAction
    status: WorkflowCArtifactHoldStatus
    requested_by: str
    requested_at: datetime
    request_reason: str
    hold_until: datetime | None
    decided_by: str | None
    decided_at: datetime | None
    decision_reason: str | None
    aggregate_version: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "action", WorkflowCArtifactHoldAction(self.action))
        status = WorkflowCArtifactHoldStatus(self.status)
        object.__setattr__(self, "status", status)
        _actor(self.requested_by)
        _reason(self.request_reason)
        _aware(self.requested_at)
        _hold_until(self.action, self.requested_at, self.hold_until)
        if self.aggregate_version < 1:
            raise SamplingRuleViolation("Workflow C hold version must be positive")
        decided = status is not WorkflowCArtifactHoldStatus.PENDING
        if decided != all(
            item is not None
            for item in (self.decided_by, self.decided_at, self.decision_reason)
        ):
            raise SamplingRuleViolation("Workflow C hold decision audit is incomplete")
        if self.decided_by is not None:
            _actor(self.decided_by)
            _reason(self.decision_reason or "")
            _aware(self.decided_at)  # type: ignore[arg-type]
            if self.decided_by == self.requested_by:
                raise SamplingRuleViolation(
                    "Workflow C hold requester cannot decide the request"
                )


class WorkflowCArtifactHoldRepository(Protocol):
    def request(
        self,
        *,
        project_id: UUID,
        artifact_id: UUID,
        request_id: UUID,
        action: WorkflowCArtifactHoldAction,
        actor_id: str,
        reason: str,
        requested_at: datetime,
        hold_until: datetime | None,
    ) -> WorkflowCArtifactHoldRequest: ...

    def decide(
        self,
        *,
        project_id: UUID,
        request_id: UUID,
        expected_version: int,
        actor_id: str,
        approved: bool,
        reason: str,
        decided_at: datetime,
    ) -> WorkflowCArtifactHoldRequest: ...


class WorkflowCArtifactHoldApplication:
    def __init__(self, repository: WorkflowCArtifactHoldRepository) -> None:
        self._repository = repository

    def request(
        self,
        *,
        project_id: UUID,
        artifact_id: UUID,
        request_id: UUID,
        action: WorkflowCArtifactHoldAction,
        actor_id: str,
        reason: str,
        requested_at: datetime,
        hold_until: datetime | None,
    ) -> WorkflowCArtifactHoldRequest:
        _actor(actor_id)
        _reason(reason)
        _aware(requested_at)
        action = WorkflowCArtifactHoldAction(action)
        _hold_until(action, requested_at, hold_until)
        return self._repository.request(
            project_id=project_id,
            artifact_id=artifact_id,
            request_id=request_id,
            action=action,
            actor_id=actor_id,
            reason=reason,
            requested_at=requested_at,
            hold_until=hold_until,
        )

    def decide(
        self,
        *,
        project_id: UUID,
        request_id: UUID,
        expected_version: int,
        actor_id: str,
        approved: bool,
        reason: str,
        decided_at: datetime,
    ) -> WorkflowCArtifactHoldRequest:
        if expected_version < 1:
            raise SamplingRuleViolation("Workflow C hold expected version is invalid")
        _actor(actor_id)
        _reason(reason)
        _aware(decided_at)
        return self._repository.decide(
            project_id=project_id,
            request_id=request_id,
            expected_version=expected_version,
            actor_id=actor_id,
            approved=approved,
            reason=reason,
            decided_at=decided_at,
        )


def _actor(value: str) -> None:
    if not value.strip() or len(value) > 200:
        raise SamplingRuleViolation("Workflow C hold actor is invalid")


def _reason(value: str) -> None:
    if not value.strip() or len(value) > 1000:
        raise SamplingRuleViolation("Workflow C hold reason is invalid")


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SamplingRuleViolation("Workflow C hold time must be timezone-aware")


def _hold_until(
    action: WorkflowCArtifactHoldAction,
    requested_at: datetime,
    hold_until: datetime | None,
) -> None:
    if action is WorkflowCArtifactHoldAction.RELEASE:
        if hold_until is not None:
            raise SamplingRuleViolation("Workflow C release hold cannot set an expiry")
        return
    if hold_until is None:
        raise SamplingRuleViolation("Workflow C hold expiry is required")
    _aware(hold_until)
    if hold_until <= requested_at:
        raise SamplingRuleViolation("Workflow C hold expiry must follow its request")
    if hold_until > requested_at + timedelta(days=90):
        raise SamplingRuleViolation("Workflow C hold expiry cannot exceed 90 days")


__all__ = [
    "WorkflowCArtifactHoldAction",
    "WorkflowCArtifactHoldApplication",
    "WorkflowCArtifactHoldRepository",
    "WorkflowCArtifactHoldRequest",
    "WorkflowCArtifactHoldStatus",
]
