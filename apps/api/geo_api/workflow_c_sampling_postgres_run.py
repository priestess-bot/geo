"""Durable Internal API control for Workflow C Sampling Run admission."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from geo_api.workflow_c_sampling_contracts import StartSamplingRunRequest
from geo_api.workflow_c_sampling_ids import sampling_command_id
from geo_api.workflow_c_sampling_postgres_policy import (
    PostgresWorkflowCSamplingPolicyControl,
)
from geo_core.sampling import (
    PostgresSamplingRunRepository,
    PostgresSamplingSuiteRepository,
    SamplingAdmissionCommand,
    SamplingConflict,
    SamplingRun,
    SamplingSuite,
    SamplingTask,
    admit_sampling_suite,
)


class PostgresWorkflowCSamplingRunControl:
    """Create a durable Run only after rechecking its frozen admission policy."""

    persistence = "durable"

    def __init__(
        self,
        *,
        runs: PostgresSamplingRunRepository,
        suites: PostgresSamplingSuiteRepository,
        policies: PostgresWorkflowCSamplingPolicyControl,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._runs = runs
        self._suites = suites
        self._policies = policies
        self._clock = clock

    def start_run(
        self,
        *,
        project_id: UUID,
        suite_id: UUID,
        idempotency_key: str,
        payload: StartSamplingRunRequest,
    ) -> tuple[SamplingRun, tuple[SamplingTask, ...]]:
        suite = self._suites.get_suite(project_id=project_id, suite_id=suite_id)
        now = self._clock()
        record = self._policies.record(project_id, suite.admission_policy_id)
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
        return self._runs.create_run(
            suite=suite,
            grant=grant,
            run_id=sampling_command_id(project_id, "run", idempotency_key),
            idempotency_key=idempotency_key,
            created_at=now,
        )

    def get(self, *, project_id: UUID, run_id: UUID) -> SamplingRun:
        return self._runs.get_run(project_id=project_id, run_id=run_id)

    def list(self, *, project_id: UUID) -> tuple[SamplingRun, ...]:
        return self._runs.list_runs(project_id=project_id)

    def list_tasks(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        suite: SamplingSuite,
    ) -> tuple[SamplingTask, ...]:
        """Return the persisted Run denominator under the frozen Suite contract."""
        return self._runs.list_tasks(project_id=project_id, run_id=run_id, suite=suite)


__all__ = ["PostgresWorkflowCSamplingRunControl"]
