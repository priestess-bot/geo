"""Crash recovery, retention and crypto-erasure for Workflow C artifacts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from geo_core.sampling.contracts import SamplingRuleViolation
from geo_core.sampling.manual_artifact_storage import (
    WorkflowCManualArtifactObjectStore,
)


WORKFLOW_C_ARTIFACT_MAINTENANCE_JOB_KIND = "workflow_c.artifact_maintenance"


class WorkflowCArtifactDeletionReason(StrEnum):
    STAGED_TIMEOUT = "staged_timeout"
    EXPIRY = "expiry"
    WRITE_FAILED = "write_failed"
    OPERATOR_DELETE = "operator_delete"


@dataclass(frozen=True)
class WorkflowCArtifactDeletionLease:
    queue_id: UUID
    project_id: UUID
    artifact_id: UUID
    key_reference: UUID
    payload_uri: str
    payload_hash: str
    manifest_uri: str
    manifest_hash: str
    reason: WorkflowCArtifactDeletionReason
    lease_token: UUID
    fencing_generation: int
    attempt_count: int
    object_deleted: bool
    key_destroyed: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason", WorkflowCArtifactDeletionReason(self.reason))
        if self.fencing_generation < 1 or self.attempt_count < 1:
            raise SamplingRuleViolation("Workflow C deletion lease fence is invalid")
        for uri in (self.payload_uri, self.manifest_uri):
            if not uri.startswith("s3://"):
                raise SamplingRuleViolation("Workflow C deletion object URI is invalid")


@dataclass(frozen=True)
class WorkflowCArtifactMaintenanceResult:
    claimed_count: int
    completed_count: int
    retry_count: int
    crypto_erased_count: int


class WorkflowCArtifactLifecycleRepository(Protocol):
    def claim_deletion(
        self,
        *,
        project_id: UUID,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
    ) -> WorkflowCArtifactDeletionLease | None: ...

    def crypto_erase_deletion(
        self,
        lease: WorkflowCArtifactDeletionLease,
        *,
        erased_at: datetime,
    ) -> bool:
        """Persist a fenced DEK erasure receipt before object deletion begins."""

        ...

    def record_deletion_attempt(
        self,
        lease: WorkflowCArtifactDeletionLease,
        *,
        object_deleted: bool,
        key_destroyed: bool,
        error_code: str | None,
        attempted_at: datetime,
        retry_not_before: datetime | None,
    ) -> str: ...


class WorkflowCArtifactMaintenanceService:
    def __init__(
        self,
        *,
        repository: WorkflowCArtifactLifecycleRepository,
        object_store: WorkflowCManualArtifactObjectStore,
        worker_id: str,
        deletion_lease_seconds: int = 120,
        max_deletions: int = 100,
        retry_delay_seconds: int = 60,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not worker_id.strip() or len(worker_id) > 200:
            raise SamplingRuleViolation("Workflow C maintenance worker identity is invalid")
        if not 30 <= deletion_lease_seconds <= 3600:
            raise SamplingRuleViolation("Workflow C deletion lease is out of bounds")
        if not 1 <= max_deletions <= 1000:
            raise SamplingRuleViolation("Workflow C deletion batch size is out of bounds")
        if not 1 <= retry_delay_seconds <= 86_400:
            raise SamplingRuleViolation("Workflow C deletion retry delay is out of bounds")
        self._repository = repository
        self._objects = object_store
        self._worker_id = worker_id
        self._lease_seconds = deletion_lease_seconds
        self._max = max_deletions
        self._retry_delay = retry_delay_seconds
        self._clock = clock

    def run_once(self, *, project_id: UUID) -> WorkflowCArtifactMaintenanceResult:
        """Process only deletion work already scheduled for one Project.

        Expiry/staged-timeout discovery is deliberately outside this worker.  A
        persistent scheduler creates a project-scoped Durable Job and its
        outbox wake atomically; allowing the consumer to sweep globally would
        make an idle Project's retention depend on an unrelated wakeup and
        would let this Job claim another Project's evidence.
        """

        claimed = completed = retried = erased = 0
        for _ in range(self._max):
            lease = self._repository.claim_deletion(
                project_id=project_id,
                worker_id=self._worker_id,
                now=self._now(),
                lease_seconds=self._lease_seconds,
            )
            if lease is not None and lease.project_id != project_id:
                raise SamplingRuleViolation(
                    "Workflow C maintenance claim escaped its Project scope"
                )
            if lease is None:
                break
            claimed += 1
            status, newly_erased = self._delete(lease)
            if newly_erased:
                erased += 1
            if status == "completed":
                completed += 1
            else:
                retried += 1
        return WorkflowCArtifactMaintenanceResult(
            claimed_count=claimed,
            completed_count=completed,
            retry_count=retried,
            crypto_erased_count=erased,
        )

    def _delete(self, lease: WorkflowCArtifactDeletionLease) -> tuple[str, bool]:
        object_deleted = lease.object_deleted
        key_destroyed = lease.key_destroyed
        errors: list[str] = []
        if not key_destroyed:
            # This repository operation checks the deletion lease and records the
            # DEK erasure receipt atomically. Do not delete remote objects until
            # that receipt makes every remaining byte permanently unreadable.
            newly_erased = self._repository.crypto_erase_deletion(
                lease,
                erased_at=self._now(),
            )
            key_destroyed = True
        else:
            newly_erased = False
        if not object_deleted:
            object_deleted = True
            for uri in (lease.manifest_uri, lease.payload_uri):
                try:
                    self._objects.delete_s3_uri(uri=uri)
                except BaseException:
                    object_deleted = False
                    errors.append("object_delete_failed")
        attempted_at = self._now()
        complete = object_deleted and key_destroyed
        status = self._repository.record_deletion_attempt(
            lease,
            object_deleted=object_deleted,
            key_destroyed=key_destroyed,
            error_code=("+".join(sorted(set(errors))) if errors else None),
            attempted_at=attempted_at,
            retry_not_before=(
                None
                if complete
                else attempted_at + timedelta(seconds=self._retry_delay)
            ),
        )
        if status not in {"completed", "retry_wait"}:
            raise SamplingRuleViolation(
                "Workflow C deletion repository returned an invalid status"
            )
        return status, newly_erased

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise SamplingRuleViolation(
                "Workflow C maintenance clock must be timezone-aware"
            )
        return value


__all__ = [
    "WORKFLOW_C_ARTIFACT_MAINTENANCE_JOB_KIND",
    "WorkflowCArtifactDeletionLease",
    "WorkflowCArtifactDeletionReason",
    "WorkflowCArtifactLifecycleRepository",
    "WorkflowCArtifactMaintenanceResult",
    "WorkflowCArtifactMaintenanceService",
]
