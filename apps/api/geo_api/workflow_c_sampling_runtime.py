"""Explicit memory runtime for the non-B Sampling Core Internal API."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from uuid import UUID, uuid5

from geo_api.workflow_c_sampling_contracts import (
    AdmissionPolicyDecisionRequest,
    AdmissionPolicySubmitRequest,
    CancelSamplingAttemptRequest,
    CreateAdmissionPolicyRequest,
    CreateSamplingSuiteRequest,
    EnqueueReadySamplingRunRequest,
    EnqueueSamplingAttemptRequest,
    StartSamplingRunRequest,
    ReviewManualEvidenceRequest,
    SubmitManualEvidenceRequest,
)
from geo_api.workflow_c_sampling_ids import SAMPLING_API_NAMESPACE, sampling_command_id
from geo_api.workflow_c_sampling_catalog import ResolvedSamplingSuiteInputs
from geo_api.workflow_c_sampling_execution_runtime import WorkflowCSamplingExecutionControl
from geo_api.workflow_c_sampling_manual_runtime import WorkflowCManualEvidenceControl
from geo_api.workflow_c_manual_artifacts import ManualArtifactWriter
from geo_api.workflow_c_sampling_policy_runtime import (
    SamplingAdmissionPolicyView,
    WorkflowCSamplingPolicyControl,
)
from geo_api.workflow_c_sampling_suite_runtime import WorkflowCSamplingSuiteControl
from geo_core.sampling import (
    CaptureMethod,
    InMemorySamplingStore,
    ManualEvidenceImport,
    SamplingAdmissionCommand,
    SamplingApplication,
    SamplingAttempt,
    SamplingConflict,
    SamplingNotFound,
    SamplingObservation,
    SamplingRun,
    SamplingRunAssessment,
    SamplingSuite,
    SamplingTask,
    SamplingTaskStatus,
    admit_sampling_suite,
)
from geo_core.sampling.lifecycle import AttemptEnqueueResult, AttemptTransitionResult

@dataclass(frozen=True)
class SamplingRunView:
    suite: SamplingSuite
    run: SamplingRun
    tasks: tuple[SamplingTask, ...]
    attempts: tuple[SamplingAttempt, ...]
    observations: tuple[SamplingObservation, ...]
    assessment: SamplingRunAssessment


@dataclass(frozen=True)
class BulkSamplingEnqueueView:
    run_id: UUID
    planned_task_count: int
    enqueued_count: int
    replayed_count: int
    skipped_count: int
    attempt_ids: tuple[UUID, ...]
    first_not_before: datetime | None
    last_not_before: datetime | None
    replayed: bool


@dataclass(frozen=True)
class BulkSamplingCancelView:
    run_id: UUID
    cancel_requested_count: int
    replayed_count: int
    skipped_count: int
    attempt_ids: tuple[UUID, ...]
    replayed: bool


class WorkflowCSamplingRuntime:
    """Memory is explicit: production mounting must inject a durable replacement."""

    def __init__(
        self,
        *,
        store: InMemorySamplingStore | None = None,
        clock: Callable[[], datetime],
        manual_artifact_writer: ManualArtifactWriter | None = None,
    ) -> None:
        self.store = store or InMemorySamplingStore()
        self._clock = clock
        self._lock = RLock()
        self._bulk_commands: dict[
            tuple[UUID, UUID, str],
            tuple[tuple[object, ...], BulkSamplingEnqueueView],
        ] = {}
        self._run_cancel_commands: dict[tuple[UUID, UUID, str], BulkSamplingCancelView] = {}
        self.policies = WorkflowCSamplingPolicyControl(clock=clock)
        self.application = SamplingApplication(
            self.store.unit_of_work_factory(),
            admission_guard=self.policies.require_current,
        )
        self.suite_control = WorkflowCSamplingSuiteControl(
            store=self.store,
            application=self.application,
            policies=self.policies,
            clock=clock,
        )
        self.suite_inputs = self.suite_control.inputs
        self.execution = WorkflowCSamplingExecutionControl(
            store=self.store,
            application=self.application,
            policies=self.policies,
        )
        self.manual = WorkflowCManualEvidenceControl(
            store=self.store,
            application=self.application,
            clock=clock,
            artifact_writer=manual_artifact_writer,
            enqueue_attempt=self._enqueue_approved_manual_attempt,
        )

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
        self.suite_control.install(
            project_id=project_id,
            resolved=resolved,
        )

    def list_suites(self, *, project_id: UUID) -> tuple[SamplingSuite, ...]:
        return self.suite_control.list(project_id=project_id)

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

    def mark_manual_evidence_committed(
        self,
        *,
        project_id: UUID,
        import_id: UUID,
        expected_version: int,
        committed_at: datetime,
    ) -> ManualEvidenceImport:
        return self.manual.mark_committed(
            project_id=project_id,
            import_id=import_id,
            expected_version=expected_version,
            committed_at=committed_at,
        )

    def get_suite(self, *, project_id: UUID, suite_id: UUID) -> SamplingSuite:
        return self.suite_control.get(project_id=project_id, suite_id=suite_id)

    def start_run(
        self,
        *,
        project_id: UUID,
        suite_id: UUID,
        idempotency_key: str,
        payload: StartSamplingRunRequest,
    ) -> tuple[SamplingRun, tuple[SamplingTask, ...]]:
        suite = self.get_suite(project_id=project_id, suite_id=suite_id)
        now = self._clock()
        record = self.policies.record(project_id, suite.admission_policy_id)
        if record.definition_hash != suite.admission_policy_hash:
            raise SamplingConflict("Sampling Suite admission policy definition is stale")
        policy = record.approved_policy(at=now)
        grant = admit_sampling_suite(
            suite,
            policy=policy,
            command=SamplingAdmissionCommand(
                idempotency_key=idempotency_key,
                purpose=payload.purpose,
                requested_at=now,
                requested_not_before=payload.requested_not_before,
            ),
        )
        run_id = sampling_command_id(project_id, "run", idempotency_key)
        existing = self.store.run(project_id=project_id, run_id=run_id)
        result, _, _ = self.policies.create_reserved_run(
            record=record,
            grant=grant,
            run_id=run_id,
            occurred_at=now,
            operation=(
                lambda: (existing, self._tasks(project_id, run_id))
                if existing is not None
                else self.application.create_run(
                    project_id=project_id,
                    suite_id=suite_id,
                    grant=grant,
                    run_id=run_id,
                    created_at=now,
                )
            ),
        )
        return result

    def get_run_view(self, *, project_id: UUID, run_id: UUID) -> SamplingRunView:
        with self.store.unit_of_work_factory()(project_id=project_id) as unit_of_work:
            run = unit_of_work.sampling.get_run(project_id=project_id, run_id=run_id)
            if run is None:
                raise SamplingNotFound("Sampling Run does not exist")
            suite = unit_of_work.sampling.get_suite(project_id=project_id, suite_id=run.suite_id)
            if suite is None:
                raise SamplingNotFound("Sampling Run Suite does not exist")
            tasks = unit_of_work.sampling.list_tasks(project_id=project_id, run_id=run_id)
            observations = unit_of_work.sampling.list_observations(
                project_id=project_id, run_id=run_id
            )
            attempts = tuple(
                attempt
                for task in tasks
                for attempt_id in task.attempt_ids
                if (
                    attempt := unit_of_work.sampling.get_attempt(
                        project_id=project_id, attempt_id=attempt_id
                    )
                )
                is not None
            )
        assessment = self.application.assess_run(project_id=project_id, run_id=run_id)
        return SamplingRunView(
            suite,
            run,
            tuple(sorted(tasks, key=lambda item: item.identity.task_key)),
            tuple(sorted(attempts, key=lambda item: (item.task_key, item.ordinal))),
            tuple(sorted(observations, key=lambda item: item.task_key)),
            assessment,
        )

    def list_runs(self, *, project_id: UUID) -> tuple[SamplingRun, ...]:
        return self.store.runs(project_id=project_id)

    def enqueue_attempt(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        task_id: UUID,
        idempotency_key: str,
        payload: EnqueueSamplingAttemptRequest,
    ) -> AttemptEnqueueResult:
        task = self.store.task(
            project_id=project_id,
            run_id=run_id,
            task_id=task_id,
        )
        if task is None:
            raise SamplingNotFound("Sampling Task does not exist")
        if task.identity.capture_method is CaptureMethod.MANUAL_UI:
            raise SamplingConflict("manual_ui Attempts require approved manual evidence")
        attempt_id = sampling_command_id(project_id, "attempt", idempotency_key)
        now = self._clock()
        return self.policies.consume_and_execute(
            run=self._run(project_id, run_id),
            task_count=(0 if self.store.attempt(project_id=project_id, attempt_id=attempt_id) else 1),
            occurred_at=now,
            operation=lambda: self.application.enqueue_attempt(
                project_id=project_id,
                run_id=run_id,
                task_id=task_id,
                expected_task_version=payload.expected_task_version,
                attempt_id=attempt_id,
                requested_not_before=payload.requested_not_before,
                authorization_checked_at=now,
            ),
        )

    def enqueue_ready_attempts(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        idempotency_key: str,
        payload: EnqueueReadySamplingRunRequest,
    ) -> BulkSamplingEnqueueView:
        command_key = (project_id, run_id, idempotency_key)
        signature = (payload.requested_not_before.isoformat(), payload.max_tasks)
        with self._lock:
            prior = self._bulk_commands.get(command_key)
            if prior is not None:
                if prior[0] != signature:
                    raise SamplingConflict(
                        "bulk enqueue Idempotency-Key was reused with different input"
                    )
                original = prior[1]
                return BulkSamplingEnqueueView(
                    run_id=original.run_id,
                    planned_task_count=original.planned_task_count,
                    enqueued_count=0,
                    replayed_count=len(original.attempt_ids),
                    skipped_count=original.skipped_count,
                    attempt_ids=original.attempt_ids,
                    first_not_before=original.first_not_before,
                    last_not_before=original.last_not_before,
                    replayed=True,
                )
            run = self._run(project_id, run_id)
            suite = self.get_suite(project_id=project_id, suite_id=run.suite_id)
            task_count = min(
                payload.max_tasks,
                suite.max_daily_tasks,
                sum(
                    item.status is SamplingTaskStatus.PLANNED
                    for item in self._tasks(project_id, run_id)
                ),
            )
            now = self._clock()
            result = self.policies.consume_and_execute(
                run=run,
                task_count=task_count,
                occurred_at=now,
                operation=lambda: self.application.enqueue_ready_attempts(
                    project_id=project_id,
                    run_id=run_id,
                    requested_not_before=payload.requested_not_before,
                    authorization_checked_at=now,
                    max_tasks=payload.max_tasks,
                    attempt_id_factory=lambda task: uuid5(
                        SAMPLING_API_NAMESPACE,
                        f"{project_id}:run:{run_id}:task:{task.id}:attempt:1",
                    ),
                ),
            )
            not_before_values = tuple(
                item.job.next_run_at for item in result.attempts if item.job.next_run_at is not None
            )
            view = BulkSamplingEnqueueView(
                run_id=run_id,
                planned_task_count=result.planned_task_count,
                enqueued_count=result.enqueued_count,
                replayed_count=0,
                skipped_count=result.skipped_count,
                attempt_ids=tuple(item.id for item in result.attempts),
                first_not_before=(min(not_before_values) if not_before_values else None),
                last_not_before=(max(not_before_values) if not_before_values else None),
                replayed=False,
            )
            self._bulk_commands[command_key] = (signature, view)
            return view

    def cancel_attempt(
        self,
        *,
        project_id: UUID,
        attempt_id: UUID,
        payload: CancelSamplingAttemptRequest,
    ) -> AttemptTransitionResult:
        attempt = self._attempt(project_id, attempt_id)
        return self.application.request_cancel(
            project_id=project_id,
            run_id=attempt.run_id,
            task_id=attempt.task_id,
            attempt_id=attempt.id,
            expected_task_version=payload.expected_task_version,
            expected_attempt_version=payload.expected_attempt_version,
            now=self._clock(),
        )

    def cancel_run(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        idempotency_key: str,
    ) -> BulkSamplingCancelView:
        command_key = (project_id, run_id, idempotency_key)
        with self._lock:
            prior = self._run_cancel_commands.get(command_key)
            if prior is not None:
                return BulkSamplingCancelView(
                    run_id=prior.run_id,
                    cancel_requested_count=0,
                    replayed_count=len(prior.attempt_ids),
                    skipped_count=prior.skipped_count,
                    attempt_ids=prior.attempt_ids,
                    replayed=True,
                )
            now = self._clock()
            run = self._run(project_id, run_id)
            unused_task_count = sum(
                not item.attempt_ids for item in self._tasks(project_id, run_id)
            )
            result = self.policies.cancel_and_release(
                run=run,
                unused_task_count=unused_task_count,
                occurred_at=now,
                operation=lambda: self.application.request_run_cancel(
                    project_id=project_id,
                    run_id=run_id,
                    now=now,
                ),
            )
            view = BulkSamplingCancelView(
                run_id=run_id,
                cancel_requested_count=result.requested_count,
                replayed_count=0,
                skipped_count=result.skipped_count,
                attempt_ids=tuple(item.id for item in result.attempts),
                replayed=False,
            )
            self._run_cancel_commands[command_key] = view
            return view

    def _attempt(self, project_id: UUID, attempt_id: UUID) -> SamplingAttempt:
        attempt = self.store.attempt(project_id=project_id, attempt_id=attempt_id)
        if attempt is None:
            raise SamplingNotFound("Sampling Attempt does not exist")
        return attempt

    def _run(self, project_id: UUID, run_id: UUID) -> SamplingRun:
        run = self.store.run(project_id=project_id, run_id=run_id)
        if run is None:
            raise SamplingNotFound("Sampling Run does not exist")
        return run

    def _tasks(self, project_id: UUID, run_id: UUID) -> tuple[SamplingTask, ...]:
        with self.store.unit_of_work_factory()(project_id=project_id) as unit_of_work:
            return unit_of_work.sampling.list_tasks(project_id=project_id, run_id=run_id)

    def _enqueue_approved_manual_attempt(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        task_id: UUID,
        expected_task_version: int,
        attempt_id: UUID,
        requested_not_before: datetime,
        authorization_checked_at: datetime,
    ) -> AttemptEnqueueResult:
        return self.policies.consume_and_execute(
            run=self._run(project_id, run_id),
            task_count=(0 if self.store.attempt(project_id=project_id, attempt_id=attempt_id) else 1),
            occurred_at=authorization_checked_at,
            operation=lambda: self.application.enqueue_attempt(
                project_id=project_id,
                run_id=run_id,
                task_id=task_id,
                expected_task_version=expected_task_version,
                attempt_id=attempt_id,
                requested_not_before=requested_not_before,
                authorization_checked_at=authorization_checked_at,
            ),
        )
