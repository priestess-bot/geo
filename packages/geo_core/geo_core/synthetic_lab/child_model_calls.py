"""Deterministic child Durable Jobs for one-Prompt-per-Job model execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid5

from geo_core.jobs.postgres import JobCancellationRequested, WorkerLease
from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.domain import (
    SyntheticLabContractError,
    _require_hash,
    _require_text,
    _require_uuid,
)
from geo_core.synthetic_lab.execution_contracts import (
    ResolvedSyntheticPrompt,
    SyntheticExecutionError,
    SyntheticExecutionStale,
    SyntheticModelInvocation,
    SyntheticModelResult,
)
from geo_core.synthetic_lab.ports import RuntimeInputSnapshot


SYNTHETIC_MODEL_CHILD_KIND = "synthetic.model.call"


class SyntheticChildCallStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN_OUTCOME = "unknown_outcome"


class SyntheticChildModelCallPending(SyntheticExecutionError):
    """The parent must release its lease until one deterministic child completes."""

    def __init__(self, child_job_id: UUID) -> None:
        super().__init__("a deterministic child model call is pending")
        self.child_job_id = child_job_id


@dataclass(frozen=True, kw_only=True)
class SyntheticChildModelCallTask:
    project_id: UUID
    child_job_id: UUID
    parent_job_id: UUID
    parent_job_kind: str
    parent_task_input_hash: str
    step_key: str
    model_job_version: int
    admitted_by: UUID
    runtime_inputs: RuntimeInputSnapshot
    prompt: ResolvedSyntheticPrompt
    structured_input: Mapping[str, object]
    deterministic_seed: int | None
    max_output_tokens: int
    input_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for value, label in (
            (self.project_id, "child model-call Project"),
            (self.child_job_id, "child model-call Job"),
            (self.parent_job_id, "parent Synthetic Job"),
        ):
            _require_uuid(value, label)
        _require_text(self.parent_job_kind, "parent Synthetic Job kind")
        _require_text(self.step_key, "child model-call step key")
        _require_uuid(self.admitted_by, "child model-call admission actor")
        _require_hash(self.parent_task_input_hash, "parent Synthetic task input")
        if self.model_job_version < 1 or self.max_output_tokens < 1:
            raise SyntheticLabContractError("child model-call versions and limits must be positive")
        if (
            self.runtime_inputs.project_id != self.project_id
            or self.prompt.frozen.project_id != self.project_id
        ):
            raise SyntheticLabContractError("child model-call lineage crosses Project scope")
        expected_id = child_model_call_id(parent_job_id=self.parent_job_id, step_key=self.step_key)
        if self.child_job_id != expected_id:
            raise SyntheticLabContractError("child model-call ID is not deterministic")
        object.__setattr__(self, "input_hash", canonical_hash(self.value()))

    def value(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "child_job_id": self.child_job_id,
            "parent_job_id": self.parent_job_id,
            "parent_job_kind": self.parent_job_kind,
            "parent_task_input_hash": self.parent_task_input_hash,
            "step_key": self.step_key,
            "model_job_version": self.model_job_version,
            "admitted_by": self.admitted_by,
            "runtime_inputs": self.runtime_inputs,
            "prompt_identity_hash": self.prompt.frozen.identity_hash,
            "prompt_bundle_hash": self.prompt.prompt_bundle_hash,
            "structured_input_hash": self.prompt.structured_input_hash,
            "output_schema": self.prompt.output_schema,
            "application_output_schema": self.prompt.application_output_schema,
            "deterministic_seed": self.deterministic_seed,
            "max_output_tokens": self.max_output_tokens,
        }

    def child_invocation(self, lease: WorkerLease) -> SyntheticModelInvocation:
        if lease.job_id != self.child_job_id or lease.project_id != self.project_id:
            raise SyntheticLabContractError("child lease does not match model-call task")
        return SyntheticModelInvocation(
            lease=lease,
            expected_job_version=self.model_job_version,
            parent_task_input_hash=self.parent_task_input_hash,
            runtime_inputs=self.runtime_inputs,
            prompt=self.prompt,
            admitted_by=self.admitted_by,
            step_key=self.step_key,
            structured_input=self.structured_input,
            deterministic_seed=self.deterministic_seed,
            max_output_tokens=self.max_output_tokens,
        )


@dataclass(frozen=True, kw_only=True)
class SyntheticChildCallState:
    task: SyntheticChildModelCallTask
    status: SyntheticChildCallStatus
    result: SyntheticModelResult | None = None
    failure_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", SyntheticChildCallStatus(self.status))
        if self.status is SyntheticChildCallStatus.SUCCEEDED:
            if self.result is None or self.failure_code is not None:
                raise SyntheticLabContractError("successful child call requires only its result")
        elif self.result is not None:
            raise SyntheticLabContractError("non-successful child call cannot expose a result")
        if self.status in {
            SyntheticChildCallStatus.FAILED,
            SyntheticChildCallStatus.CANCELLED,
            SyntheticChildCallStatus.UNKNOWN_OUTCOME,
        }:
            _require_text(self.failure_code or "", "child model-call terminal reason")
        elif self.failure_code is not None:
            raise SyntheticLabContractError("non-terminal child call cannot carry a failure")


class SyntheticChildCallCoordinatorPort(Protocol):
    def resolve_or_stage(
        self, task: SyntheticChildModelCallTask, *, parent_lease: WorkerLease
    ) -> SyntheticChildCallState: ...


class SyntheticChildLifecyclePort(Protocol):
    def block_unstarted(self, *, project_id: UUID, parent_job_id: UUID, reason: str) -> None: ...


class SyntheticChildModelCallCoordinator:
    """Return a completed child result or suspend the deterministic parent replay."""

    def __init__(self, repository: SyntheticChildCallCoordinatorPort) -> None:
        self._repository = repository

    def execute(self, invocation: SyntheticModelInvocation) -> SyntheticModelResult:
        task = child_task_from_invocation(invocation)
        state = self._repository.resolve_or_stage(task, parent_lease=invocation.lease)
        if state.task.input_hash != task.input_hash:
            raise SyntheticExecutionStale("child model-call immutable input changed")
        if state.status is SyntheticChildCallStatus.SUCCEEDED:
            if state.result is None:
                raise SyntheticExecutionError("successful child result is unavailable")
            return state.result
        if state.status is SyntheticChildCallStatus.FAILED:
            if state.failure_code == "synthetic_runtime_stale":
                raise SyntheticExecutionStale("child model-call runtime became stale")
            raise SyntheticExecutionError("child model-call failed")
        if state.status is SyntheticChildCallStatus.CANCELLED:
            raise JobCancellationRequested("child model-call was cancelled")
        if state.status is SyntheticChildCallStatus.UNKNOWN_OUTCOME:
            raise SyntheticChildModelCallPending(task.child_job_id)
        raise SyntheticChildModelCallPending(task.child_job_id)


def child_model_call_id(*, parent_job_id: UUID, step_key: str) -> UUID:
    _require_uuid(parent_job_id, "parent Synthetic Job")
    _require_text(step_key, "child model-call step key")
    return uuid5(parent_job_id, step_key)


def child_task_from_invocation(
    invocation: SyntheticModelInvocation,
) -> SyntheticChildModelCallTask:
    return SyntheticChildModelCallTask(
        project_id=invocation.lease.project_id,
        child_job_id=child_model_call_id(
            parent_job_id=invocation.lease.job_id,
            step_key=invocation.step_key,
        ),
        parent_job_id=invocation.lease.job_id,
        parent_job_kind=invocation.lease.kind,
        parent_task_input_hash=invocation.parent_task_input_hash,
        step_key=invocation.step_key,
        model_job_version=invocation.expected_job_version,
        admitted_by=invocation.admitted_by,
        runtime_inputs=invocation.runtime_inputs,
        prompt=invocation.prompt,
        structured_input=invocation.structured_input,
        deterministic_seed=invocation.deterministic_seed,
        max_output_tokens=invocation.max_output_tokens,
    )


__all__ = [
    "SYNTHETIC_MODEL_CHILD_KIND",
    "SyntheticChildCallCoordinatorPort",
    "SyntheticChildCallState",
    "SyntheticChildCallStatus",
    "SyntheticChildLifecyclePort",
    "SyntheticChildModelCallCoordinator",
    "SyntheticChildModelCallPending",
    "SyntheticChildModelCallTask",
    "child_model_call_id",
    "child_task_from_invocation",
]
