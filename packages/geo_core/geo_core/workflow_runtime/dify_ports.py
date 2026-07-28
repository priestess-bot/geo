"""Ports consumed by the Dify workflow executor."""

from __future__ import annotations

from typing import Mapping, Protocol
from uuid import UUID

from geo_core.jobs.postgres import WorkerLease
from geo_core.secrets import SecretValue, SecretVersionHandle

from .contracts import WorkflowExecutionResult, WorkflowRuntimeRelease
from .published import PublishedWorkflowSnapshot, PublishedWorkflowSnapshotPin


class CredentialResolver(Protocol):
    def resolve(self, handle: SecretVersionHandle) -> SecretValue: ...


class WorkflowRuntimeRepository(Protocol):
    def resolve_active(
        self, *, project_id: UUID, purpose: str
    ) -> WorkflowRuntimeRelease | None: ...

    def get_release(self, *, project_id: UUID, release_id: UUID) -> WorkflowRuntimeRelease: ...

    def begin_business_attempt(
        self,
        lease: WorkerLease,
        *,
        release: WorkflowRuntimeRelease,
        published_snapshot_id: UUID | None = None,
        context_hash: str,
        request_hash: str,
    ) -> UUID: ...

    def finish_business_attempt(
        self, lease: WorkerLease, *, attempt_id: UUID, values: Mapping[str, object]
    ) -> None: ...

    def load_successful_business_result(
        self,
        lease: WorkerLease,
        *,
        release: WorkflowRuntimeRelease,
        context_hash: str,
        request_hash: str,
    ) -> WorkflowExecutionResult | None: ...

    def load_published_snapshot_pin(
        self,
        *,
        release: WorkflowRuntimeRelease,
    ) -> PublishedWorkflowSnapshotPin | None: ...

    def find_unresolved_business_attempt(
        self,
        lease: WorkerLease,
        *,
        release: WorkflowRuntimeRelease,
        context_hash: str,
        request_hash: str,
    ) -> UUID | None: ...

    def begin_canary_attempt(
        self,
        *,
        release: WorkflowRuntimeRelease,
        published_snapshot_id: UUID | None = None,
        context_hash: str,
        request_hash: str,
    ) -> UUID: ...

    def finish_canary_attempt(
        self,
        *,
        project_id: UUID,
        attempt_id: UUID,
        values: Mapping[str, object],
    ) -> None: ...

    def record_published_snapshot(
        self,
        *,
        release: WorkflowRuntimeRelease,
        snapshot: PublishedWorkflowSnapshot,
    ) -> UUID: ...
