"""Lease-owned execution of one exact Prompt in a Synthetic child Durable Job."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import timedelta
from typing import Protocol

from geo_core.jobs.postgres import (
    JobCancellationRequested,
    LeaseHeartbeat,
    LostJobLease,
    PostgresDurableJobStore,
    WorkerLease,
)
from geo_core.model_gateway.application_support import ModelCallUnknownOutcome
from geo_core.model_gateway.contracts import ModelGatewayError, RetryableModelGatewayError
from geo_core.synthetic_lab.application_support import assert_runtime_current
from geo_core.synthetic_lab.child_model_calls import SyntheticChildModelCallTask
from geo_core.synthetic_lab.execution_contracts import (
    SyntheticExecutionError,
    SyntheticExecutionStale,
    SyntheticModelCallPort,
    SyntheticPromptResolverPort,
)
from geo_core.synthetic_lab.ports import RuntimeInputPort, SyntheticLabStaleInput


class SyntheticChildExecutionRepository(Protocol):
    def load_claimed(self, lease: WorkerLease) -> SyntheticChildModelCallTask: ...

    def assert_parent_active(self, lease: WorkerLease) -> None: ...


class SyntheticChildModelCallHandler:
    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        repository: SyntheticChildExecutionRepository,
        runtime_inputs: RuntimeInputPort,
        prompts: SyntheticPromptResolverPort,
        model_gateway: SyntheticModelCallPort,
        lease_for: timedelta,
    ) -> None:
        if lease_for.total_seconds() < 3:
            raise ValueError("Synthetic child lease must be at least three seconds")
        self._store = store
        self._repository = repository
        self._runtime_inputs = runtime_inputs
        self._prompts = prompts
        self._models = model_gateway
        self._lease_for = lease_for

    def handle(self, lease: WorkerLease) -> Mapping[str, object]:
        try:
            task = self._repository.load_claimed(lease)
            with LeaseHeartbeat(
                self._store,
                lease,
                lease_for=self._lease_for,
                interval=min(self._lease_for / 3, timedelta(seconds=30)),
            ) as heartbeat:
                checkpoint = self._checkpoint(lease, task, heartbeat)
                checkpoint()
                result = self._models.execute(task.child_invocation(lease))
                checkpoint()
            with self._store.fenced_transaction(lease) as connection:
                self._store.complete_in_transaction(
                    connection,
                    lease,
                    result_ref=f"model-gateway://attempt/{result.model_attempt_id}",
                    details={
                        "model_attempt_id": str(result.model_attempt_id),
                        "response_hash": result.response_hash,
                        "task_input_hash": task.input_hash,
                    },
                )
            return {
                "status": "succeeded",
                "job_id": str(lease.job_id),
                "model_attempt_id": str(result.model_attempt_id),
            }
        except (JobCancellationRequested, LostJobLease):
            raise
        except (SyntheticExecutionStale, SyntheticLabStaleInput):
            return self._fail(lease, "synthetic_runtime_stale", None)
        except ModelCallUnknownOutcome:
            return self._fail(lease, "model_unknown_outcome", None)
        except RetryableModelGatewayError as error:
            retry_after = error.retry_after_seconds or 30.0
            return self._fail(
                lease,
                f"synthetic_model_{error.code.value}",
                timedelta(seconds=min(300.0, max(1.0, retry_after))),
            )
        except ModelGatewayError as error:
            return self._fail(lease, f"synthetic_model_{error.code.value}", None)
        except SyntheticExecutionError:
            return self._fail(lease, "synthetic_child_contract", None)
        except Exception as error:
            return self._fail(
                lease,
                "synthetic_child_internal",
                timedelta(seconds=30),
                classification=type(error).__name__,
            )

    def _checkpoint(
        self,
        lease: WorkerLease,
        task: SyntheticChildModelCallTask,
        heartbeat: LeaseHeartbeat,
    ) -> Callable[[], None]:
        def check() -> None:
            heartbeat.raise_if_stopped()
            self._store.heartbeat(lease, lease_for=self._lease_for)
            self._repository.assert_parent_active(lease)
            assert_runtime_current(task.runtime_inputs, self._runtime_inputs)
            self._prompts.assert_current(task.prompt.frozen)
            heartbeat.raise_if_stopped()

        return check

    def _fail(
        self,
        lease: WorkerLease,
        error_code: str,
        retry_delay: timedelta | None,
        *,
        classification: str | None = None,
    ) -> Mapping[str, object]:
        self._store.heartbeat(lease, lease_for=self._lease_for)
        status = self._store.fail(
            lease,
            error_code=error_code,
            details={"classification": classification or error_code},
            retry_delay=retry_delay,
        )
        return {"status": status, "job_id": str(lease.job_id)}


__all__ = [
    "SyntheticChildExecutionRepository",
    "SyntheticChildModelCallHandler",
]
