"""Lease-owned production worker for frozen Synthetic Lab execution tasks."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import timedelta
from uuid import UUID

from geo_core.jobs.postgres import (
    JobCancellationRequested,
    LeaseHeartbeat,
    LostJobLease,
    PostgresDurableJobStore,
    WorkerLease,
)
from geo_core.model_gateway.contracts import ModelGatewayError, RetryableModelGatewayError
from geo_core.synthetic_lab.child_model_calls import (
    SyntheticChildLifecyclePort,
    SyntheticChildModelCallPending,
)
from geo_core.synthetic_lab.application_support import assert_runtime_current
from geo_core.synthetic_lab.domain import SyntheticLabContractError
from geo_core.synthetic_lab.execution import SyntheticTaskExecutor
from geo_core.synthetic_lab.execution_contracts import (
    CorpusFinalizeTask,
    OfflineExperimentRunTask,
    ReviewCaseRunTask,
    StyleProfileBuildTask,
    SyntheticExecutionError,
    SyntheticExecutionOutput,
    SyntheticExecutionRepositoryPort,
    SyntheticExecutionStale,
    SyntheticExecutionTask,
    SyntheticManualReconciliationRequired,
    SyntheticPromptResolverPort,
    prompt_refs,
)
from geo_core.synthetic_lab.ports import (
    RuntimeInputPort,
    RuntimeInputSnapshot,
    SyntheticLabStaleInput,
)


_TASK_KINDS: Mapping[type[object], frozenset[str]] = {
    StyleProfileBuildTask: frozenset({"style.profile.build"}),
    ReviewCaseRunTask: frozenset({"review.case.run", "candidate_generation"}),
    CorpusFinalizeTask: frozenset({"corpus.finalize", "corpus_finalize"}),
    OfflineExperimentRunTask: frozenset({"offline_experiment.run", "offline_experiment"}),
}


class SyntheticExecutionHandler:
    """Execute one pre-staged task while preserving cancellation and fencing."""

    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        repository: SyntheticExecutionRepositoryPort,
        runtime_inputs: RuntimeInputPort,
        prompts: SyntheticPromptResolverPort,
        executor: SyntheticTaskExecutor,
        lease_for: timedelta,
        children: SyntheticChildLifecyclePort | None = None,
    ) -> None:
        if lease_for.total_seconds() < 3:
            raise ValueError("Synthetic execution lease must be at least three seconds")
        self._store = store
        self._repository = repository
        self._runtime_inputs = runtime_inputs
        self._prompts = prompts
        self._executor = executor
        self._lease_for = lease_for
        self._children = children

    def handle(self, lease: WorkerLease) -> Mapping[str, object]:
        try:
            task = self._repository.load(lease)
            _assert_task_matches_lease(task, lease)
            with LeaseHeartbeat(
                self._store,
                lease,
                lease_for=self._lease_for,
                interval=min(self._lease_for / 3, timedelta(seconds=30)),
            ) as heartbeat:
                checkpoint = self._checkpoint(lease, task, heartbeat)
                current = checkpoint()
                output = self._executor.run(
                    lease=lease,
                    task=task,
                    checkpoint=checkpoint,
                )
                current = checkpoint()
            self._finalize(lease, task, output, current)
            return {
                "status": "succeeded",
                "job_id": str(lease.job_id),
                "result_hash": output.result_hash,
            }
        except JobCancellationRequested:
            self._block_children(lease, "parent_cancelled")
            raise
        except LostJobLease:
            raise
        except SyntheticChildModelCallPending as pending:
            return self._defer_for_child(lease, pending.child_job_id)
        except SyntheticManualReconciliationRequired as error:
            return self._fail(
                lease,
                error_code="synthetic_manual_reconciliation_required",
                classification="manual_reconciliation_required",
                retry_delay=None,
                details={
                    **(
                        {"child_job_id": str(error.child_job_id)}
                        if error.child_job_id is not None
                        else {}
                    ),
                    "child_failure_code": error.failure_code,
                    "reconciliation_action": (
                        "inspect_child_attempt_then_submit_new_parent_replay"
                    ),
                },
            )
        except (SyntheticExecutionStale, SyntheticLabStaleInput):
            return self._fail(
                lease,
                error_code="synthetic_runtime_stale",
                classification="stale_input",
                retry_delay=None,
            )
        except RetryableModelGatewayError as error:
            seconds = error.retry_after_seconds or 30.0
            return self._fail(
                lease,
                error_code=f"synthetic_model_{error.code.value}",
                classification="retryable_model",
                retry_delay=timedelta(seconds=min(300.0, max(1.0, seconds))),
            )
        except ModelGatewayError as error:
            return self._fail(
                lease,
                error_code=f"synthetic_model_{error.code.value}",
                classification="permanent_model",
                retry_delay=None,
            )
        except (SyntheticExecutionError, SyntheticLabContractError):
            return self._fail(
                lease,
                error_code="synthetic_execution_contract",
                classification="contract",
                retry_delay=None,
            )
        except Exception as error:
            return self._fail(
                lease,
                error_code="synthetic_execution_internal",
                classification=type(error).__name__,
                retry_delay=timedelta(seconds=30),
            )

    def _checkpoint(
        self,
        lease: WorkerLease,
        task: SyntheticExecutionTask,
        heartbeat: LeaseHeartbeat,
    ) -> Callable[[], RuntimeInputSnapshot]:
        def check() -> RuntimeInputSnapshot:
            heartbeat.raise_if_stopped()
            self._store.heartbeat(lease, lease_for=self._lease_for)
            current = assert_runtime_current(
                task.runtime_inputs,
                self._runtime_inputs,
                require_frozen_profile=not isinstance(task, StyleProfileBuildTask),
            )
            for frozen in prompt_refs(task):
                self._prompts.assert_current(frozen)
            heartbeat.raise_if_stopped()
            return current

        return check

    def _finalize(
        self,
        lease: WorkerLease,
        task: SyntheticExecutionTask,
        output: SyntheticExecutionOutput,
        runtime: RuntimeInputSnapshot,
    ) -> None:
        with self._store.fenced_transaction(lease) as connection:
            self._repository.finalize(
                connection=connection,
                lease=lease,
                task=task,
                output=output,
                runtime=runtime,
            )
            self._store.complete_in_transaction(
                connection,
                lease,
                result_ref=f"synthetic://result/{output.result_hash}",
                details={
                    "result_hash": output.result_hash,
                    "task_input_hash": task.input_hash,
                    "task_type": type(task).__name__,
                },
            )

    def _fail(
        self,
        lease: WorkerLease,
        *,
        error_code: str,
        classification: str,
        retry_delay: timedelta | None,
        details: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        self._block_children(lease, error_code)
        self._store.heartbeat(lease, lease_for=self._lease_for)
        status = self._store.fail(
            lease,
            error_code=error_code,
            details={"classification": classification, **dict(details or {})},
            retry_delay=retry_delay,
        )
        return {"status": status, "job_id": str(lease.job_id)}

    def _defer_for_child(
        self, lease: WorkerLease, child_job_id: UUID
    ) -> Mapping[str, object]:
        with self._store.fenced_transaction(lease) as connection:
            self._store.defer_in_transaction(
                connection,
                lease,
                reason_code="synthetic_child_pending",
                details={"child_job_id": str(child_job_id)},
                retry_delay=timedelta(seconds=30),
            )
        return {
            "status": "waiting_child",
            "job_id": str(lease.job_id),
            "child_job_id": str(child_job_id),
        }

    def _block_children(self, lease: WorkerLease, reason: str) -> None:
        if self._children is not None:
            self._children.block_unstarted(
                project_id=lease.project_id,
                parent_job_id=lease.job_id,
                reason=reason,
            )


def _assert_task_matches_lease(task: SyntheticExecutionTask, lease: WorkerLease) -> None:
    if task.project_id != lease.project_id or task.job_id != lease.job_id:
        raise SyntheticExecutionError("staged task does not belong to the claimed Job")
    accepted = _TASK_KINDS.get(type(task), frozenset())
    if lease.kind not in accepted:
        raise SyntheticExecutionError("claimed Job kind cannot execute the staged task type")


__all__ = ["SyntheticExecutionHandler"]
