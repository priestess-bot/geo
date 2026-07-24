"""Application commands for guarded three-arm offline Synthetic Lab experiments."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from geo_core.synthetic_lab.application_support import (
    JobWriteOwnership,
    assert_runtime_current,
    assert_terminal_write,
    canonical_hash,
    command_identity,
    complete_synthetic_job,
    finalization_guard,
    new_outbox_message,
    new_synthetic_job,
    recover_command,
    require_roles,
    stage_command,
)
from geo_core.synthetic_lab.offline_experiment import OfflineExperimentPlan, OfflineSlotResult
from geo_core.synthetic_lab.offline_results import (
    OfflineExperimentResult,
    finalize_offline_experiment,
)
from geo_core.synthetic_lab.ports import (
    CommandReceipt,
    JobTerminalResult,
    LabPrincipal,
    LabRole,
    RuntimeInputPort,
    RuntimeInputSnapshot,
    SyntheticCommandOperation,
    SyntheticLabPersistenceError,
    SyntheticLabUnitOfWorkFactory,
    SyntheticJob,
    VersionedAggregate,
)


OFFLINE_EXPERIMENT_PLAN_KIND = "offline_experiment_plan"
OFFLINE_EXPERIMENT_RESULT_KIND = "offline_experiment_result"


class ExperimentApplication:
    def __init__(self, uow_factory: SyntheticLabUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def enqueue_offline_experiment(
        self,
        *,
        principal: LabPrincipal,
        plan: OfflineExperimentPlan,
        job_id: UUID,
        outbox_id: UUID,
        runtime_inputs: RuntimeInputSnapshot,
        runtime_port: RuntimeInputPort,
        idempotency_key: str,
    ) -> CommandReceipt:
        require_roles(principal, plan.project_id, LabRole.OPERATOR, LabRole.REVIEWER)
        self._assert_plan_runtime(plan, runtime_inputs)
        identity = command_identity(
            project_id=plan.project_id,
            idempotency_key=idempotency_key,
            operation=SyntheticCommandOperation.ENQUEUE_EXPERIMENT,
            request={
                "plan": plan,
                "job_id": job_id,
                "outbox_id": outbox_id,
                "runtime_inputs": runtime_inputs,
            },
        )
        with self._uow_factory(project_id=plan.project_id) as uow:
            replay = recover_command(uow, identity, SyntheticJob)
            if replay is not None:
                return replay
            current = assert_runtime_current(runtime_inputs, runtime_port)
            self._assert_plan_runtime(plan, current)
            job = new_synthetic_job(
                job_id=job_id,
                project_id=plan.project_id,
                kind="offline_experiment",
                input_hash=canonical_hash(
                    {
                        "plan_input_hash": plan.input_hash,
                        "prompt_release_id": current.prompt_release_id,
                        "prompt_release_hash": current.prompt_release_hash,
                    }
                ),
                payload={
                    "offline_experiment_id": plan.id,
                    "offline_experiment_hash": plan.input_hash,
                },
                runtime_inputs=current,
                idempotency_key_hash=identity.idempotency_key_hash,
            )
            uow.aggregates.stage(
                VersionedAggregate(
                    project_id=plan.project_id,
                    kind=OFFLINE_EXPERIMENT_PLAN_KIND,
                    resource_id=plan.id,
                    version=1,
                    submitted_by=principal.actor_id,
                    payload=plan,
                ),
                expected_version=0,
            )
            uow.jobs.stage(job, expected_version=0)
            uow.outbox.stage(
                new_outbox_message(
                    message_id=outbox_id,
                    job=job,
                    event_type="synthetic.offline_experiment.queued",
                )
            )
            return stage_command(uow, identity, job)

    def finalize_offline_experiment(
        self,
        *,
        principal: LabPrincipal,
        job_id: UUID,
        plan_id: UUID,
        result_id: UUID,
        slot_results: tuple[OfflineSlotResult, ...],
        ownership: JobWriteOwnership,
        expected_job_version: int,
        runtime_port: RuntimeInputPort,
        completed_at: datetime,
        idempotency_key: str,
    ) -> CommandReceipt:
        require_roles(principal, principal.project_id, LabRole.WORKER)
        identity = command_identity(
            project_id=principal.project_id,
            idempotency_key=idempotency_key,
            operation=SyntheticCommandOperation.FINALIZE_EXPERIMENT,
            request={
                "job_id": job_id,
                "plan_id": plan_id,
                "result_id": result_id,
                "result_hashes": tuple(item.result_hash for item in slot_results),
                "ownership": ownership,
                "expected_job_version": expected_job_version,
                "completed_at": completed_at,
            },
        )
        with self._uow_factory(project_id=principal.project_id) as uow:
            replay = recover_command(uow, identity, OfflineExperimentResult)
            if replay is not None:
                return replay
            job = uow.jobs.get(project_id=principal.project_id, job_id=job_id)
            plan_record = uow.aggregates.get(
                project_id=principal.project_id,
                kind=OFFLINE_EXPERIMENT_PLAN_KIND,
                resource_id=plan_id,
            )
            if (
                job is None
                or plan_record is None
                or not isinstance(plan_record.payload, OfflineExperimentPlan)
            ):
                raise SyntheticLabPersistenceError("offline Experiment Job or Plan is missing")
            plan = plan_record.payload
            if (
                job.kind != "offline_experiment"
                or job.payload.get("offline_experiment_id") != plan.id
                or job.payload.get("offline_experiment_hash") != plan.input_hash
            ):
                raise SyntheticLabPersistenceError(
                    "offline Experiment Job does not match its frozen Plan"
                )
            current = assert_terminal_write(
                job,
                ownership=ownership,
                runtime_port=runtime_port,
                at=completed_at,
            )
            if current is None:
                raise SyntheticLabPersistenceError(
                    "offline Experiment Job lacks frozen runtime inputs"
                )
            self._assert_plan_runtime(plan, current)
            guard = finalization_guard(
                job,
                resource_id=plan.id,
                ownership=ownership,
                current=current,
            )
            result = finalize_offline_experiment(
                result_id=result_id,
                plan=plan,
                slot_results=slot_results,
                guard=guard,
            )
            terminal = JobTerminalResult(
                project_id=plan.project_id,
                job_id=job.id,
                job_kind=job.kind,
                result=result,
                result_hash=result.result_hash,
            )
            completed = complete_synthetic_job(
                job,
                ownership=ownership,
                at=completed_at,
                result_ref=result.result_hash,
            )
            uow.aggregates.stage(
                VersionedAggregate(
                    project_id=plan.project_id,
                    kind=OFFLINE_EXPERIMENT_RESULT_KIND,
                    resource_id=result.id,
                    version=1,
                    submitted_by=principal.actor_id,
                    payload=result,
                ),
                expected_version=0,
            )
            uow.jobs.stage_terminal(terminal)
            uow.jobs.stage(completed, expected_version=expected_job_version)
            return stage_command(uow, identity, result)

    @staticmethod
    def _assert_plan_runtime(
        plan: OfflineExperimentPlan,
        runtime: RuntimeInputSnapshot,
    ) -> None:
        if (
            runtime.project_id != plan.project_id
            or runtime.fact_snapshot_id != plan.approved_fact_snapshot_id
            or runtime.fact_snapshot_hash != plan.approved_fact_snapshot_hash
            or runtime.profile_version_id != plan.profile_version_id
            or runtime.profile_hash != plan.profile_hash
            or runtime.prompt_release_id != plan.prompt_release_id
            or runtime.prompt_release_hash != plan.prompt_release_hash
        ):
            raise SyntheticLabPersistenceError(
                "offline Experiment Plan does not match frozen Fact/Profile inputs"
            )


__all__ = [
    "ExperimentApplication",
    "OFFLINE_EXPERIMENT_PLAN_KIND",
    "OFFLINE_EXPERIMENT_RESULT_KIND",
]
