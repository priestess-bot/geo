from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from geo_core.sampling import SamplingRuleViolation
from geo_core.workflow_c_artifacts.holds import (
    WorkflowCArtifactHoldAction,
    WorkflowCArtifactHoldApplication,
    WorkflowCArtifactHoldRequest,
    WorkflowCArtifactHoldStatus,
)
from geo_core.workflow_c_artifacts.lifecycle import (
    WorkflowCArtifactDeletionLease,
    WorkflowCArtifactDeletionReason,
    WorkflowCArtifactMaintenanceService,
)


NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
PROJECT_ID = UUID("cc100000-0000-0000-0000-000000000001")
ARTIFACT_ID = UUID("cc100000-0000-0000-0000-000000000002")
QUEUE_ID = UUID("cc100000-0000-0000-0000-000000000003")
KEY_ID = UUID("cc100000-0000-0000-0000-000000000004")
TOKEN_ONE = UUID("cc100000-0000-0000-0000-000000000005")
TOKEN_TWO = UUID("cc100000-0000-0000-0000-000000000006")
OTHER_PROJECT_ID = UUID("cc100000-0000-0000-0000-000000000008")


def _lease(*, retry: bool = False) -> WorkflowCArtifactDeletionLease:
    return WorkflowCArtifactDeletionLease(
        queue_id=QUEUE_ID,
        project_id=PROJECT_ID,
        artifact_id=ARTIFACT_ID,
        key_reference=KEY_ID,
        payload_uri="s3://geo-restricted-workflow-c-artifacts/workflow-c/manual/payload",
        payload_hash="a" * 64,
        manifest_uri="s3://geo-restricted-workflow-c-artifacts/workflow-c/manual/manifest",
        manifest_hash="b" * 64,
        reason=WorkflowCArtifactDeletionReason.EXPIRY,
        lease_token=TOKEN_TWO if retry else TOKEN_ONE,
        fencing_generation=2 if retry else 1,
        attempt_count=2 if retry else 1,
        object_deleted=False,
        key_destroyed=retry,
    )


class _Repository:
    def __init__(self, leases: list[WorkflowCArtifactDeletionLease]) -> None:
        self.leases = leases
        self.attempts: list[tuple[bool, bool, str | None]] = []
        self.events: list[str] = []

    def claim_deletion(
        self, *, project_id: UUID, worker_id: str, now: datetime, lease_seconds: int
    ):
        assert project_id == PROJECT_ID
        assert worker_id == "maintenance-1"
        assert now == NOW
        assert lease_seconds == 120
        return self.leases.pop(0) if self.leases else None

    def crypto_erase_deletion(self, lease, *, erased_at: datetime) -> bool:
        assert erased_at == NOW
        assert lease.project_id == PROJECT_ID
        self.events.append("crypto_erased")
        return not lease.key_destroyed

    def record_deletion_attempt(
        self,
        lease,
        *,
        object_deleted: bool,
        key_destroyed: bool,
        error_code: str | None,
        attempted_at: datetime,
        retry_not_before,
    ) -> str:
        assert attempted_at == NOW
        self.attempts.append((object_deleted, key_destroyed, error_code))
        if object_deleted and key_destroyed:
            assert retry_not_before is None
            return "completed"
        assert retry_not_before is not None
        return "retry_wait"


class _Objects:
    def __init__(self, *, fail_once: bool, events: list[str]) -> None:
        self.fail_once = fail_once
        self.deleted: list[str] = []
        self._events = events

    def delete_s3_uri(self, *, uri: str) -> bool:
        self._events.append("object_delete")
        self.deleted.append(uri)
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("fixture object delete failure")
        return True


def test_object_delete_failure_still_crypto_erases_then_retries_idempotently() -> None:
    repository = _Repository([_lease(), _lease(retry=True)])
    objects = _Objects(fail_once=True, events=repository.events)
    result = WorkflowCArtifactMaintenanceService(
        repository=repository,
        object_store=objects,
        worker_id="maintenance-1",
        clock=lambda: NOW,
    ).run_once(project_id=PROJECT_ID)

    assert result.claimed_count == 2
    assert result.completed_count == result.retry_count == 1
    assert result.crypto_erased_count == 1
    assert repository.events[:2] == ["crypto_erased", "object_delete"]
    assert repository.attempts == [
        (False, True, "object_delete_failed"),
        (True, True, None),
    ]


def test_maintenance_rejects_a_claim_that_escapes_the_leased_project() -> None:
    repository = _Repository([replace(_lease(), project_id=OTHER_PROJECT_ID)])
    objects = _Objects(fail_once=False, events=repository.events)

    with pytest.raises(SamplingRuleViolation, match="escaped its Project scope"):
        WorkflowCArtifactMaintenanceService(
            repository=repository,
            object_store=objects,
            worker_id="maintenance-1",
            clock=lambda: NOW,
        ).run_once(project_id=PROJECT_ID)

    assert objects.deleted == []
    assert repository.events == []


class _HoldRepository:
    def __init__(self) -> None:
        self.requested_by = ""

    def request(self, **values):
        self.requested_by = values["actor_id"]
        return WorkflowCArtifactHoldRequest(
            id=values["request_id"],
            project_id=values["project_id"],
            artifact_id=values["artifact_id"],
            action=values["action"],
            status=WorkflowCArtifactHoldStatus.PENDING,
            requested_by=values["actor_id"],
            requested_at=values["requested_at"],
            request_reason=values["reason"],
            hold_until=values["hold_until"],
            decided_by=None,
            decided_at=None,
            decision_reason=None,
            aggregate_version=1,
        )

    def decide(self, **values):
        return WorkflowCArtifactHoldRequest(
            id=values["request_id"],
            project_id=values["project_id"],
            artifact_id=ARTIFACT_ID,
            action=WorkflowCArtifactHoldAction.APPLY,
            status=(
                WorkflowCArtifactHoldStatus.APPROVED
                if values["approved"]
                else WorkflowCArtifactHoldStatus.REJECTED
            ),
            requested_by=self.requested_by,
            requested_at=NOW,
            request_reason="Preserve legal evidence.",
            hold_until=NOW + timedelta(days=30),
            decided_by=values["actor_id"],
            decided_at=values["decided_at"],
            decision_reason=values["reason"],
            aggregate_version=2,
        )


def test_hold_application_preserves_two_person_decision_contract() -> None:
    repository = _HoldRepository()
    application = WorkflowCArtifactHoldApplication(repository)
    request_id = UUID("cc100000-0000-0000-0000-000000000007")
    pending = application.request(
        project_id=PROJECT_ID,
        artifact_id=ARTIFACT_ID,
        request_id=request_id,
        action=WorkflowCArtifactHoldAction.APPLY,
        actor_id="maker",
        reason="Preserve legal evidence.",
        requested_at=NOW,
        hold_until=NOW + timedelta(days=30),
    )
    assert pending.status is WorkflowCArtifactHoldStatus.PENDING
    approved = application.decide(
        project_id=PROJECT_ID,
        request_id=request_id,
        expected_version=1,
        actor_id="checker",
        approved=True,
        reason="Legal request verified.",
        decided_at=NOW,
    )
    assert approved.status is WorkflowCArtifactHoldStatus.APPROVED

    with pytest.raises(SamplingRuleViolation, match="requester cannot decide"):
        application.decide(
            project_id=PROJECT_ID,
            request_id=request_id,
            expected_version=1,
            actor_id="maker",
            approved=True,
            reason="Self approval is forbidden.",
            decided_at=NOW,
        )


def test_hold_application_rejects_missing_or_overlong_expiry() -> None:
    application = WorkflowCArtifactHoldApplication(_HoldRepository())

    with pytest.raises(SamplingRuleViolation, match="expiry is required"):
        application.request(
            project_id=PROJECT_ID,
            artifact_id=ARTIFACT_ID,
            request_id=UUID("cc100000-0000-0000-0000-000000000009"),
            action=WorkflowCArtifactHoldAction.APPLY,
            actor_id="maker",
            reason="Preserve legal evidence.",
            requested_at=NOW,
            hold_until=None,
        )

    with pytest.raises(SamplingRuleViolation, match="cannot exceed 90 days"):
        application.request(
            project_id=PROJECT_ID,
            artifact_id=ARTIFACT_ID,
            request_id=UUID("cc100000-0000-0000-0000-000000000010"),
            action=WorkflowCArtifactHoldAction.EXTEND,
            actor_id="maker",
            reason="Continue legal preservation.",
            requested_at=NOW,
            hold_until=NOW + timedelta(days=90, microseconds=1),
        )
