"""Durable composition for the Workflow C Sampling Internal API vertical."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable
from uuid import UUID

from geo_api.workflow_c_sampling_catalog import ResolvedSamplingSuiteInputs
from geo_api.workflow_c_sampling_contracts import (
    AdmissionPolicyDecisionRequest,
    AdmissionPolicySubmitRequest,
    CancelSamplingAttemptRequest,
    CreateAdmissionPolicyRequest,
    CreateSamplingSuiteRequest,
    EnqueueReadySamplingRunRequest,
    EnqueueSamplingAttemptRequest,
    ReviewManualEvidenceRequest,
    StartSamplingRunRequest,
    SubmitManualEvidenceRequest,
)
from geo_api.workflow_c_sampling_postgres_execution import (
    PostgresWorkflowCBrowserBulkSamplingControl,
    PostgresWorkflowCProviderBulkSamplingControl,
    PostgresWorkflowCProviderSamplingControl,
)
from geo_api.workflow_c_sampling_postgres_manual import (
    PostgresWorkflowCManualEvidenceControl,
)
from geo_api.workflow_c_manual_artifacts import ManualArtifactWriter
from geo_api.workflow_c_sampling_postgres_policy import (
    PostgresWorkflowCSamplingPolicyControl,
)
from geo_api.workflow_c_sampling_postgres_run import PostgresWorkflowCSamplingRunControl
from geo_api.workflow_c_sampling_postgres_suite import (
    PostgresWorkflowCSamplingSuiteControl,
)
from geo_api.workflow_c_sampling_runtime import (
    BulkSamplingCancelView,
    BulkSamplingEnqueueView,
    SamplingAdmissionPolicyView,
    SamplingRunView,
)
from geo_core.browser_capture.bulk_admission import BrowserCaptureBulkAdmissionService
from geo_core.sampling import (
    CaptureMethod,
    ManualEvidenceImport,
    PostgresManualEvidenceRepository,
    PostgresProviderSamplingAttemptRepository,
    PostgresProviderSamplingBulkAttemptRepository,
    PostgresProviderSamplingExecutionInputRepository,
    PostgresSamplingCancellationRepository,
    PostgresSamplingReadRepository,
    PostgresSamplingRunRepository,
    PostgresSamplingSuiteRepository,
    SamplingAttempt,
    SamplingRun,
    SamplingSuite,
    SamplingTask,
    assess_sampling_run,
)
from geo_core.sampling.postgres_admission import PostgresSamplingAdmissionRepository


@dataclass(frozen=True)
class DurableSamplingAttemptCommandResult:
    """Route-compatible result reconstructed from the committed durable record."""

    attempt: SamplingAttempt


class PostgresWorkflowCSamplingRuntime:
    """Compose the complete Sampling route surface without memory fallbacks.

    Every command delegates to a typed PostgreSQL control.  Read-after-write
    responses are reconstructed from the RLS-scoped aggregate and Durable Job,
    never from an HTTP body or an in-process command cache.
    """

    persistence = "durable"

    def __init__(
        self,
        *,
        policies: PostgresWorkflowCSamplingPolicyControl,
        suites: PostgresWorkflowCSamplingSuiteControl,
        runs: PostgresWorkflowCSamplingRunControl,
        provider_attempts: PostgresWorkflowCProviderSamplingControl,
        provider_bulk_attempts: PostgresWorkflowCProviderBulkSamplingControl,
        browser_bulk_attempts: PostgresWorkflowCBrowserBulkSamplingControl,
        manual: PostgresWorkflowCManualEvidenceControl,
        cancellation: PostgresSamplingCancellationRepository,
        reads: PostgresSamplingReadRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.policies = policies
        self.suite_control = suites
        self.suite_inputs = suites.inputs
        self._runs = runs
        self._provider_attempts = provider_attempts
        self._provider_bulk_attempts = provider_bulk_attempts
        self._browser_bulk_attempts = browser_bulk_attempts
        self.manual = manual
        self._cancellation = cancellation
        self._reads = reads
        self._clock = clock

    def create_admission_policy(
        self,
        *,
        project_id: UUID,
        actor_id: str,
        idempotency_key: str,
        payload: CreateAdmissionPolicyRequest,
    ) -> SamplingAdmissionPolicyView:
        return self.policies.create(
            project_id=project_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            payload=payload,
        )

    def get_admission_policy(
        self, *, project_id: UUID, policy_id: UUID
    ) -> SamplingAdmissionPolicyView:
        return self.policies.get(project_id=project_id, policy_id=policy_id)

    def list_admission_policies(
        self, *, project_id: UUID
    ) -> tuple[SamplingAdmissionPolicyView, ...]:
        return self.policies.list(project_id=project_id)

    def submit_admission_policy(
        self,
        *,
        project_id: UUID,
        policy_id: UUID,
        actor_id: str,
        idempotency_key: str,
        payload: AdmissionPolicySubmitRequest,
    ) -> SamplingAdmissionPolicyView:
        return self.policies.submit(
            project_id=project_id,
            policy_id=policy_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            payload=payload,
        )

    def decide_admission_policy(
        self,
        *,
        project_id: UUID,
        policy_id: UUID,
        actor_id: str,
        idempotency_key: str,
        payload: AdmissionPolicyDecisionRequest,
        approved: bool,
    ) -> SamplingAdmissionPolicyView:
        return self.policies.decide(
            project_id=project_id,
            policy_id=policy_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            payload=payload,
            approved=approved,
        )

    def revoke_admission_policy(
        self,
        *,
        project_id: UUID,
        policy_id: UUID,
        actor_id: str,
        idempotency_key: str,
        payload: AdmissionPolicyDecisionRequest,
    ) -> SamplingAdmissionPolicyView:
        return self.policies.revoke(
            project_id=project_id,
            policy_id=policy_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            payload=payload,
        )

    def create_suite(
        self,
        *,
        project_id: UUID,
        actor_id: str,
        idempotency_key: str,
        payload: CreateSamplingSuiteRequest,
    ) -> SamplingSuite:
        return self.suite_control.create(
            project_id=project_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            payload=payload,
        )

    def install_suite_inputs(
        self,
        *,
        project_id: UUID,
        resolved: ResolvedSamplingSuiteInputs,
    ) -> None:
        self.suite_control.install(project_id=project_id, resolved=resolved)

    def get_suite(self, *, project_id: UUID, suite_id: UUID) -> SamplingSuite:
        return self.suite_control.get(project_id=project_id, suite_id=suite_id)

    def list_suites(self, *, project_id: UUID) -> tuple[SamplingSuite, ...]:
        return self.suite_control.list(project_id=project_id)

    def start_run(
        self,
        *,
        project_id: UUID,
        suite_id: UUID,
        idempotency_key: str,
        payload: StartSamplingRunRequest,
    ) -> tuple[SamplingRun, tuple[SamplingTask, ...]]:
        return self._runs.start_run(
            project_id=project_id,
            suite_id=suite_id,
            idempotency_key=idempotency_key,
            payload=payload,
        )

    def list_runs(self, *, project_id: UUID) -> tuple[SamplingRun, ...]:
        return self._runs.list(project_id=project_id)

    def get_run_view(self, *, project_id: UUID, run_id: UUID) -> SamplingRunView:
        run = self._runs.get(project_id=project_id, run_id=run_id)
        suite = self.get_suite(project_id=project_id, suite_id=run.suite_id)
        tasks = self._runs.list_tasks(project_id=project_id, run_id=run_id, suite=suite)
        attempts = self._reads.attempts_for_run(
            project_id=project_id, run_id=run_id, source=suite.source_stratum
        )
        observations = self._reads.observations_for_run(
            project_id=project_id, run_id=run_id, source=suite.source_stratum
        )
        return SamplingRunView(
            suite=suite,
            run=run,
            tasks=tasks,
            attempts=attempts,
            observations=observations,
            assessment=assess_sampling_run(
                suite, run, tasks=tasks, observations=observations
            ),
        )

    def enqueue_attempt(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        task_id: UUID,
        idempotency_key: str,
        payload: EnqueueSamplingAttemptRequest,
    ) -> DurableSamplingAttemptCommandResult:
        result = self._provider_attempts.enqueue(
            project_id=project_id,
            run_id=run_id,
            task_id=task_id,
            idempotency_key=idempotency_key,
            payload=payload,
        )
        return DurableSamplingAttemptCommandResult(
            attempt=self._attempt(
                project_id=project_id,
                run_id=run_id,
                attempt_id=result.attempt.attempt_id,
            )
        )

    def enqueue_ready_attempts(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        idempotency_key: str,
        payload: EnqueueReadySamplingRunRequest,
    ) -> BulkSamplingEnqueueView:
        run = self._runs.get(project_id=project_id, run_id=run_id)
        suite = self.get_suite(project_id=project_id, suite_id=run.suite_id)
        control = (
            self._browser_bulk_attempts
            if suite.source_stratum.capture_method is CaptureMethod.AUTOMATED_UI
            else self._provider_bulk_attempts
        )
        result = control.enqueue_ready(
            project_id=project_id,
            run_id=run_id,
            idempotency_key=idempotency_key,
            payload=payload,
        )
        return BulkSamplingEnqueueView(
            run_id=result.run_id,
            planned_task_count=result.planned_task_count,
            enqueued_count=0 if result.replayed else result.enqueued_count,
            replayed_count=len(result.attempts) if result.replayed else 0,
            skipped_count=result.skipped_count,
            attempt_ids=tuple(item.attempt_id for item in result.attempts),
            first_not_before=(min(result.scheduled_at) if result.scheduled_at else None),
            last_not_before=(max(result.scheduled_at) if result.scheduled_at else None),
            replayed=result.replayed,
        )

    def cancel_attempt(
        self,
        *,
        project_id: UUID,
        attempt_id: UUID,
        payload: CancelSamplingAttemptRequest,
    ) -> DurableSamplingAttemptCommandResult:
        result = self._cancellation.cancel_attempt(
            project_id=project_id,
            attempt_id=attempt_id,
            expected_task_version=payload.expected_task_version,
            expected_attempt_version=payload.expected_attempt_version,
            idempotency_key=(
                f"sampling-attempt-cancel:{attempt_id}:"
                f"{payload.expected_task_version}:{payload.expected_attempt_version}"
            ),
            cancelled_at=self._clock(),
        )
        return DurableSamplingAttemptCommandResult(
            attempt=self._attempt(
                project_id=project_id,
                run_id=result.run_id,
                attempt_id=attempt_id,
            )
        )

    def cancel_run(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        idempotency_key: str,
    ) -> BulkSamplingCancelView:
        result = self._cancellation.cancel_run(
            project_id=project_id,
            run_id=run_id,
            idempotency_key=idempotency_key,
            cancelled_at=self._clock(),
        )
        return BulkSamplingCancelView(
            run_id=result.run_id,
            cancel_requested_count=(
                0 if result.replayed else result.cancellation_requested_count
            ),
            replayed_count=(result.cancellation_requested_count if result.replayed else 0),
            skipped_count=result.released_task_count,
            attempt_ids=result.attempt_ids,
            replayed=result.replayed,
        )

    def submit_manual_evidence(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        task_id: UUID,
        actor_id: str,
        idempotency_key: str,
        payload: SubmitManualEvidenceRequest,
    ) -> ManualEvidenceImport:
        return self.manual.submit(
            project_id=project_id,
            run_id=run_id,
            task_id=task_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            payload=payload,
        )

    def get_manual_evidence(self, *, project_id: UUID, import_id: UUID) -> ManualEvidenceImport:
        return self.manual.get(project_id=project_id, import_id=import_id)

    def list_manual_evidence(self, *, project_id: UUID) -> tuple[ManualEvidenceImport, ...]:
        return self.manual.list(project_id=project_id)

    def review_manual_evidence(
        self,
        *,
        project_id: UUID,
        import_id: UUID,
        actor_id: str,
        idempotency_key: str,
        payload: ReviewManualEvidenceRequest,
        approved: bool,
    ) -> ManualEvidenceImport:
        return self.manual.review(
            project_id=project_id,
            import_id=import_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            payload=payload,
            approved=approved,
        )

    def manual_evidence_for_attempt(
        self, *, project_id: UUID, attempt_id: UUID
    ) -> ManualEvidenceImport:
        return self.manual.for_attempt(project_id=project_id, attempt_id=attempt_id)

    def _attempt(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        attempt_id: UUID,
    ) -> SamplingAttempt:
        run = self._runs.get(project_id=project_id, run_id=run_id)
        suite = self.get_suite(project_id=project_id, suite_id=run.suite_id)
        return self._reads.attempt(
            project_id=project_id,
            attempt_id=attempt_id,
            source=suite.source_stratum,
        )


def build_postgres_workflow_c_sampling_runtime(
    *,
    connect: Callable[[], Any],
    artifact_writer: ManualArtifactWriter,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> PostgresWorkflowCSamplingRuntime:
    """Build the complete durable Sampling API vertical from one connection port.

    Keeping this composition local to Sampling prevents a partly persistent
    global Workflow C API from becoming routable while Analysis still lacks its
    own durable command and read controls.
    """
    policies = PostgresWorkflowCSamplingPolicyControl(
        repository=PostgresSamplingAdmissionRepository(connect=connect, clock=clock),
        clock=clock,
    )
    suites_repository = PostgresSamplingSuiteRepository(connect=connect)
    runs_repository = PostgresSamplingRunRepository(connect=connect)
    execution_inputs = PostgresProviderSamplingExecutionInputRepository(connect=connect)
    suites = PostgresWorkflowCSamplingSuiteControl(
        repository=suites_repository,
        execution_inputs=execution_inputs,
        policies=policies,
        clock=clock,
    )
    runs = PostgresWorkflowCSamplingRunControl(
        runs=runs_repository,
        suites=suites_repository,
        policies=policies,
        clock=clock,
    )
    provider_attempts = PostgresWorkflowCProviderSamplingControl(
        runs=runs_repository,
        suites=suites_repository,
        execution_inputs=execution_inputs,
        attempts=PostgresProviderSamplingAttemptRepository(connect=connect),
        policies=policies,
        clock=clock,
    )
    provider_bulk_attempts = PostgresWorkflowCProviderBulkSamplingControl(
        runs=runs_repository,
        suites=suites_repository,
        execution_inputs=execution_inputs,
        attempts=PostgresProviderSamplingBulkAttemptRepository(connect=connect),
        policies=policies,
        clock=clock,
    )
    browser_bulk_attempts = PostgresWorkflowCBrowserBulkSamplingControl(
        runs=runs_repository,
        suites=suites_repository,
        attempts=BrowserCaptureBulkAdmissionService(connect=connect),
        clock=clock,
    )
    manual = PostgresWorkflowCManualEvidenceControl(
        imports=PostgresManualEvidenceRepository(connect=connect),
        runs=runs_repository,
        suites=suites_repository,
        artifact_writer=artifact_writer,
        clock=clock,
    )
    return PostgresWorkflowCSamplingRuntime(
        policies=policies,
        suites=suites,
        runs=runs,
        provider_attempts=provider_attempts,
        provider_bulk_attempts=provider_bulk_attempts,
        browser_bulk_attempts=browser_bulk_attempts,
        manual=manual,
        cancellation=PostgresSamplingCancellationRepository(connect=connect),
        reads=PostgresSamplingReadRepository(connect=connect),
        clock=clock,
    )


__all__ = [
    "DurableSamplingAttemptCommandResult",
    "PostgresWorkflowCSamplingRuntime",
    "build_postgres_workflow_c_sampling_runtime",
]
