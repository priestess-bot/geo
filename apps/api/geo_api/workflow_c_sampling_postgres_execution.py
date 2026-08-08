"""Durable Provider Sampling admission built only from frozen server inputs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from geo_api.workflow_c_sampling_contracts import (
    EnqueueReadySamplingRunRequest,
    EnqueueSamplingAttemptRequest,
)
from geo_api.workflow_c_sampling_ids import sampling_command_id
from geo_api.workflow_c_sampling_postgres_policy import PostgresWorkflowCSamplingPolicyControl
from geo_core.browser_capture.bulk_admission import (
    BrowserCaptureBulkAdmissionService,
    BrowserCaptureBulkResult,
)
from geo_core.sampling import (
    CaptureMethod,
    PersistentProviderSamplingBulkAttempt,
    PersistentProviderSamplingAttempt,
    PostgresProviderSamplingBulkAttemptRepository,
    PostgresProviderSamplingAttemptRepository,
    PostgresProviderSamplingExecutionInputRepository,
    PostgresSamplingRunRepository,
    PostgresSamplingSuiteRepository,
    ProviderSamplingAttemptAdmission,
    ProviderSamplingBulkAttemptAdmission,
    ProviderSamplingBulkAttemptItem,
    ProviderSamplingExecutionInput,
    SamplingConflict,
    SamplingNotFound,
    SamplingTaskStatus,
)
from geo_core.sampling.postgres_worker_contracts import ProviderSamplingWorkerSpec


@dataclass(frozen=True)
class PostgresProviderSamplingEnqueueResult:
    """The exact spec used for one durable Provider Sampling enqueue."""

    admission: ProviderSamplingAttemptAdmission
    attempt: PersistentProviderSamplingAttempt


class PostgresWorkflowCProviderSamplingControl:
    """Prevent API bodies from choosing execution material or bypassing timing gates."""

    persistence = "durable"

    def __init__(
        self,
        *,
        runs: PostgresSamplingRunRepository,
        suites: PostgresSamplingSuiteRepository,
        execution_inputs: PostgresProviderSamplingExecutionInputRepository,
        attempts: PostgresProviderSamplingAttemptRepository,
        policies: PostgresWorkflowCSamplingPolicyControl,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._runs = runs
        self._suites = suites
        self._execution_inputs = execution_inputs
        self._attempts = attempts
        self._policies = policies
        self._clock = clock

    def enqueue(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        task_id: UUID,
        idempotency_key: str,
        payload: EnqueueSamplingAttemptRequest,
    ) -> PostgresProviderSamplingEnqueueResult:
        run = self._runs.get_run(project_id=project_id, run_id=run_id)
        suite = self._suites.get_suite(project_id=project_id, suite_id=run.suite_id)
        task = next(
            (
                candidate
                for candidate in self._runs.list_tasks(
                    project_id=project_id, run_id=run_id, suite=suite
                )
                if candidate.id == task_id
            ),
            None,
        )
        if task is None:
            raise SamplingNotFound("Sampling Task does not exist")
        if task.identity.capture_method not in {
            CaptureMethod.PROVIDER_API,
            CaptureMethod.PROXY_GROUNDED_API,
        }:
            raise SamplingConflict("manual_ui Attempts require approved manual evidence")
        # A lower version may be a valid idempotent replay after the first
        # admission incremented the Task.  The fenced RPC checks its command
        # ledger before enforcing the optimistic version for a new enqueue.
        if task.version < payload.expected_task_version:
            raise SamplingConflict("Sampling Task optimistic version check failed")

        now = self._clock()
        execution = self._execution_inputs.get_for_suite(
            project_id=project_id, suite_id=suite.id
        ).execution
        attempt_id = sampling_command_id(project_id, "attempt", idempotency_key)
        admitted_by = sampling_command_id(
            project_id,
            "provider-attempt-admission",
            f"{run_id}:{task_id}:{idempotency_key}",
        )
        spec = execution.build_spec(
            run_id=run_id,
            task_id=task.id,
            attempt_id=attempt_id,
            task_version=payload.expected_task_version + 1,
            attempt_version=1,
            question_id=task.identity.question_id,
            question_version=task.identity.question_version,
            admitted_by=admitted_by,
            # The Run admission time is immutable, so an idempotent retry
            # rebuilds the exact same Job spec while the RPC rechecks current
            # authorization with ``now`` before a new enqueue is committed.
            admitted_at=run.admitted_not_before,
            search_mode=suite.source_stratum.search_mode,
        )
        admission = ProviderSamplingAttemptAdmission(
            project_id=project_id,
            run_id=run_id,
            task_id=task.id,
            attempt_id=attempt_id,
            expected_task_version=payload.expected_task_version,
            requested_not_before=payload.requested_not_before,
            authorization_checked_at=now,
            spec_payload=spec_payload(spec),
        )
        return PostgresProviderSamplingEnqueueResult(
            admission=admission,
            attempt=self._attempts.enqueue(admission, idempotency_key=idempotency_key),
        )


class PostgresWorkflowCProviderBulkSamplingControl:
    """Build the exact ready slice from frozen inputs before the 0055 RPC."""

    persistence = "durable"

    def __init__(
        self,
        *,
        runs: PostgresSamplingRunRepository,
        suites: PostgresSamplingSuiteRepository,
        execution_inputs: PostgresProviderSamplingExecutionInputRepository,
        attempts: PostgresProviderSamplingBulkAttemptRepository,
        policies: PostgresWorkflowCSamplingPolicyControl,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._runs = runs
        self._suites = suites
        self._execution_inputs = execution_inputs
        self._attempts = attempts
        # PostgreSQL performs the authoritative current-policy gate after the
        # bulk command ledger lookup so durable retries remain replayable.
        self._policies = policies
        self._clock = clock

    def enqueue_ready(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        idempotency_key: str,
        payload: EnqueueReadySamplingRunRequest,
    ) -> PersistentProviderSamplingBulkAttempt:
        run = self._runs.get_run(project_id=project_id, run_id=run_id)
        suite = self._suites.get_suite(project_id=project_id, suite_id=run.suite_id)
        if suite.source_stratum.capture_method not in {
            CaptureMethod.PROVIDER_API,
            CaptureMethod.PROXY_GROUNDED_API,
        }:
            raise SamplingConflict("manual_ui Tasks require approved manual evidence")
        execution = self._execution_inputs.get_for_suite(
            project_id=project_id, suite_id=suite.id
        ).execution
        tasks = tuple(
            task
            for task in self._runs.list_tasks(
                project_id=project_id, run_id=run_id, suite=suite
            )
            if task.status is SamplingTaskStatus.PLANNED
        )[: min(payload.max_tasks, suite.max_daily_tasks)]
        items = tuple(
            _bulk_item(
                project_id=project_id,
                run_id=run_id,
                task_id=task.id,
                task_version=task.version,
                question_id=task.identity.question_id,
                question_version=task.identity.question_version,
                idempotency_key=idempotency_key,
                execution=execution,
                admitted_at=run.admitted_not_before,
                search_mode=suite.source_stratum.search_mode,
            )
            for task in tasks
        )
        return self._attempts.enqueue_ready(
            ProviderSamplingBulkAttemptAdmission(
                project_id=project_id,
                run_id=run_id,
                requested_not_before=payload.requested_not_before,
                authorization_checked_at=self._clock(),
                max_tasks=payload.max_tasks,
                items=items,
            ),
            idempotency_key=idempotency_key,
        )


class PostgresWorkflowCBrowserBulkSamplingControl:
    """Build and atomically enqueue the ready automated-UI Task slice."""

    persistence = "durable"

    def __init__(
        self,
        *,
        runs: PostgresSamplingRunRepository,
        suites: PostgresSamplingSuiteRepository,
        attempts: BrowserCaptureBulkAdmissionService,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._runs = runs
        self._suites = suites
        self._attempts = attempts
        self._clock = clock

    def enqueue_ready(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        idempotency_key: str,
        payload: EnqueueReadySamplingRunRequest,
    ) -> BrowserCaptureBulkResult:
        run = self._runs.get_run(project_id=project_id, run_id=run_id)
        suite = self._suites.get_suite(project_id=project_id, suite_id=run.suite_id)
        if suite.source_stratum.capture_method is not CaptureMethod.AUTOMATED_UI:
            raise SamplingConflict("Only automated_ui Tasks use Browser Capture bulk enqueue")
        tasks = tuple(
            task
            for task in self._runs.list_tasks(
                project_id=project_id, run_id=run_id, suite=suite
            )
            if task.status is SamplingTaskStatus.PLANNED
        )[: min(payload.max_tasks, suite.max_daily_tasks)]
        now = self._clock()
        return self._attempts.enqueue_ready(
            project_id=project_id,
            run_id=run_id,
            surface_release_id=suite.adapter_release_id,
            egress_endpoint_id=suite.route_policy_id,
            profile_version_id=suite.model_release_id,
            task_versions=tuple((task.id, task.version) for task in tasks),
            requested_not_before=max(payload.requested_not_before, now),
            authorization_checked_at=now,
            max_tasks=payload.max_tasks,
            idempotency_key=idempotency_key,
        )


def _bulk_item(
    *,
    project_id: UUID,
    run_id: UUID,
    task_id: UUID,
    task_version: int,
    question_id: str,
    question_version: str,
    idempotency_key: str,
    execution: ProviderSamplingExecutionInput,
    admitted_at: datetime,
    search_mode: str | None,
) -> ProviderSamplingBulkAttemptItem:
    attempt_id = sampling_command_id(
        project_id,
        "bulk-provider-attempt",
        f"{run_id}:{task_id}:{idempotency_key}",
    )
    admitted_by = sampling_command_id(
        project_id,
        "bulk-provider-attempt-admission",
        f"{run_id}:{task_id}:{idempotency_key}",
    )
    spec = execution.build_spec(
        run_id=run_id,
        task_id=task_id,
        attempt_id=attempt_id,
        task_version=task_version + 1,
        attempt_version=1,
        question_id=question_id,
        question_version=question_version,
        admitted_by=admitted_by,
        admitted_at=admitted_at,
        search_mode=search_mode,
    )
    return ProviderSamplingBulkAttemptItem(
        task_id=task_id,
        attempt_id=attempt_id,
        expected_task_version=task_version,
        spec_payload=spec_payload(spec),
    )


def spec_payload(spec: ProviderSamplingWorkerSpec) -> dict[str, object]:
    """Serialize only the validated immutable worker contract for the 0042 RPC."""

    prompt = spec.prompt
    return {
        "schema_version": 1,
        "kind": "sampling.provider_execute",
        "run_id": str(spec.run_id),
        "task_id": str(spec.task_id),
        "attempt_id": str(spec.attempt_id),
        "task_version": spec.task_version,
        "attempt_version": spec.attempt_version,
        "question": {"text": spec.question_text, "sha256": spec.question_hash},
        "runtime_selection_id": str(spec.runtime_selection_id),
        "admitted_by": str(spec.admitted_by),
        "admitted_at": spec.admitted_at.isoformat(),
        "prompt": {
            "binding_id": str(prompt.binding_id),
            "state_id": str(prompt.state_id),
            "state_version": prompt.state_version,
            "release_id": str(prompt.release_id),
            "release_hash": prompt.release_hash,
            "purpose": prompt.purpose,
            "bundle_hash": prompt.bundle_hash,
            "system_message": prompt.system_message,
            "answer_field": prompt.answer_field,
            "output_schema": dict(prompt.output_schema),
            "application_output_schema": dict(prompt.application_output_schema),
            "temperature": prompt.temperature,
            "max_output_tokens": prompt.max_output_tokens,
            "seed": prompt.seed,
            "tool_mode": prompt.tool_mode,
        },
        "search_mode": spec.search_mode,
        "deadline_at": spec.deadline_at.isoformat() if spec.deadline_at is not None else None,
    }


__all__ = [
    "PostgresProviderSamplingEnqueueResult",
    "PostgresWorkflowCBrowserBulkSamplingControl",
    "PostgresWorkflowCProviderBulkSamplingControl",
    "PostgresWorkflowCProviderSamplingControl",
    "spec_payload",
]
