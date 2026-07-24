"""Policy-global execution gate around the Sampling application service."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from geo_api.workflow_c_sampling_policy_runtime import WorkflowCSamplingPolicyControl
from geo_core.sampling import (
    EvidenceStatus,
    InMemorySamplingStore,
    ObservationCommitResult,
    ObservationEvidence,
    SamplingApplication,
    SamplingAttempt,
    SamplingNotFound,
)
from geo_core.sampling.lifecycle import AttemptTransitionResult


class WorkflowCSamplingExecutionControl:
    def __init__(
        self,
        *,
        store: InMemorySamplingStore,
        application: SamplingApplication,
        policies: WorkflowCSamplingPolicyControl,
    ) -> None:
        self._store = store
        self._application = application
        self._policies = policies

    def claim_attempt(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        task_id: UUID,
        attempt_id: UUID,
        expected_task_version: int,
        expected_attempt_version: int,
        worker_id: str,
        now: datetime,
        lease_for: timedelta,
    ) -> AttemptTransitionResult:
        run = self._run(project_id, run_id)
        return self._policies.claim_and_execute(
            run=run,
            attempt_id=attempt_id,
            now=now,
            lease_for=lease_for,
            operation=lambda: self._application.claim_attempt(
                project_id=project_id,
                run_id=run_id,
                task_id=task_id,
                attempt_id=attempt_id,
                expected_task_version=expected_task_version,
                expected_attempt_version=expected_attempt_version,
                worker_id=worker_id,
                now=now,
                lease_for=lease_for,
            ),
        )

    def heartbeat_attempt(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        attempt_id: UUID,
        expected_attempt_version: int,
        token: UUID,
        generation: int,
        now: datetime,
        lease_for: timedelta,
    ) -> SamplingAttempt:
        updated = self._application.heartbeat_attempt(
            project_id=project_id,
            attempt_id=attempt_id,
            expected_attempt_version=expected_attempt_version,
            token=token,
            generation=generation,
            now=now,
            lease_for=lease_for,
        )
        assert updated.job.lease_expires_at is not None
        self._policies.update_execution_lease(
            run=self._run(project_id, run_id),
            attempt_id=attempt_id,
            expires_at=updated.job.lease_expires_at,
        )
        return updated

    def finalize_observation(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        task_id: UUID,
        attempt_id: UUID,
        expected_task_version: int,
        expected_attempt_version: int,
        token: UUID,
        generation: int,
        now: datetime,
        evidence_status: EvidenceStatus,
        ineligible_reasons: tuple[str, ...],
        evidence: ObservationEvidence,
    ) -> ObservationCommitResult:
        result = self._application.finalize_observation(
            project_id=project_id,
            run_id=run_id,
            task_id=task_id,
            attempt_id=attempt_id,
            expected_task_version=expected_task_version,
            expected_attempt_version=expected_attempt_version,
            token=token,
            generation=generation,
            now=now,
            evidence_status=evidence_status,
            ineligible_reasons=ineligible_reasons,
            evidence=evidence,
        )
        self._policies.release_execution(
            run=self._run(project_id, run_id),
            attempt_id=attempt_id,
        )
        return result

    def fail_attempt(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        task_id: UUID,
        attempt_id: UUID,
        expected_task_version: int,
        expected_attempt_version: int,
        token: UUID,
        generation: int,
        now: datetime,
        error_code: str,
    ) -> AttemptTransitionResult:
        result = self._application.fail_attempt(
            project_id=project_id,
            run_id=run_id,
            task_id=task_id,
            attempt_id=attempt_id,
            expected_task_version=expected_task_version,
            expected_attempt_version=expected_attempt_version,
            token=token,
            generation=generation,
            now=now,
            error_code=error_code,
        )
        self._policies.release_execution(
            run=self._run(project_id, run_id),
            attempt_id=attempt_id,
        )
        return result

    def acknowledge_cancel(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        task_id: UUID,
        attempt_id: UUID,
        expected_task_version: int,
        expected_attempt_version: int,
        token: UUID,
        generation: int,
        now: datetime,
    ) -> AttemptTransitionResult:
        result = self._application.acknowledge_cancel(
            project_id=project_id,
            run_id=run_id,
            task_id=task_id,
            attempt_id=attempt_id,
            expected_task_version=expected_task_version,
            expected_attempt_version=expected_attempt_version,
            token=token,
            generation=generation,
            now=now,
        )
        self._policies.release_execution(
            run=self._run(project_id, run_id),
            attempt_id=attempt_id,
        )
        return result

    def _run(self, project_id: UUID, run_id: UUID):
        run = self._store.run(project_id=project_id, run_id=run_id)
        if run is None:
            raise SamplingNotFound("Sampling Run does not exist")
        return run
