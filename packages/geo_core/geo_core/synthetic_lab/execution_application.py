"""Atomic admission of exact frozen Synthetic Lab execution tasks."""

from __future__ import annotations

from uuid import UUID

from geo_core.synthetic_lab.application_support import (
    assert_runtime_current,
    command_identity,
    new_outbox_message,
    new_synthetic_job,
    recover_command,
    require_roles,
    stage_command,
)
from geo_core.synthetic_lab.execution_contracts import (
    CorpusFinalizeTask,
    OfflineExperimentRunTask,
    ReviewCaseRunTask,
    StyleProfileBuildTask,
    SyntheticExecutionError,
    SyntheticExecutionTask,
    SyntheticPromptResolverPort,
    prompt_refs,
)
from geo_core.synthetic_lab.ports import (
    CommandReceipt,
    LabPrincipal,
    LabRole,
    RuntimeInputPort,
    SyntheticCommandOperation,
    SyntheticJob,
    SyntheticLabUnitOfWorkFactory,
)


class SyntheticExecutionApplication:
    def __init__(self, uow_factory: SyntheticLabUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def enqueue(
        self,
        *,
        principal: LabPrincipal,
        task: SyntheticExecutionTask,
        outbox_id: UUID,
        runtime_inputs: RuntimeInputPort,
        prompts: SyntheticPromptResolverPort,
        idempotency_key: str,
        recovery_of_attempt_id: UUID | None = None,
        dify_reconciliation_token: str | None = None,
    ) -> CommandReceipt:
        require_roles(principal, task.project_id, LabRole.OPERATOR, LabRole.REVIEWER)
        if (recovery_of_attempt_id is None) != (dify_reconciliation_token is None):
            raise SyntheticExecutionError(
                "Dify recovery requires both the old attempt ID and reconciliation token"
            )
        if recovery_of_attempt_id is not None and not isinstance(
            task, StyleProfileBuildTask
        ):
            raise SyntheticExecutionError(
                "Dify recovery is supported only for Style Profile build tasks"
            )
        if task.requested_by != principal.actor_id:
            raise SyntheticExecutionError(
                "Synthetic execution task requester must match the admitting principal"
            )
        current = assert_runtime_current(
            task.runtime_inputs,
            runtime_inputs,
            require_frozen_profile=not isinstance(task, StyleProfileBuildTask),
        )
        for prompt in prompt_refs(task):
            prompts.assert_current(prompt)
        kind, event_type = _task_kind(task)
        request: dict[str, object] = {
            "task_type": type(task).__name__,
            "task_input_hash": task.input_hash,
            "outbox_id": outbox_id,
        }
        if recovery_of_attempt_id is not None:
            request["recovery_of_attempt_id"] = recovery_of_attempt_id
        identity = command_identity(
            project_id=task.project_id,
            idempotency_key=idempotency_key,
            operation=SyntheticCommandOperation.ENQUEUE_EXECUTION,
            request=request,
        )
        with self._uow_factory(project_id=task.project_id) as uow:
            replay = recover_command(uow, identity, SyntheticJob)
            if replay is not None:
                if isinstance(task, StyleProfileBuildTask):
                    uow.dify_reconciliation.bind_resubmission(
                        project_id=task.project_id,
                        new_parent_job_id=task.job_id,
                        actor_id=principal.actor_id,
                        recovery_of_attempt_id=recovery_of_attempt_id,
                        token=dify_reconciliation_token,
                    )
                    uow.commit()
                return replay
            job = new_synthetic_job(
                job_id=task.job_id,
                project_id=task.project_id,
                kind=kind,
                input_hash=task.input_hash,
                idempotency_key_hash=identity.idempotency_key_hash,
                payload={
                    "execution_task_id": task.job_id,
                    "execution_task_hash": task.input_hash,
                },
                runtime_inputs=current,
            )
            uow.jobs.stage(job, expected_version=0)
            uow.execution_tasks.stage(task, expected_job_input_hash=job.input_hash)
            uow.outbox.stage(
                new_outbox_message(
                    message_id=outbox_id,
                    job=job,
                    event_type=event_type,
                )
            )
            if isinstance(task, StyleProfileBuildTask):
                uow.dify_reconciliation.bind_resubmission(
                    project_id=task.project_id,
                    new_parent_job_id=task.job_id,
                    actor_id=principal.actor_id,
                    recovery_of_attempt_id=recovery_of_attempt_id,
                    token=dify_reconciliation_token,
                )
            return stage_command(uow, identity, job)


def _task_kind(task: SyntheticExecutionTask) -> tuple[str, str]:
    if isinstance(task, StyleProfileBuildTask):
        return "style.profile.build", "synthetic.style.profile.build.queued"
    if isinstance(task, ReviewCaseRunTask):
        return "review.case.run", "synthetic.review.case.run.queued"
    if isinstance(task, CorpusFinalizeTask):
        return "corpus.finalize", "synthetic.corpus.finalize.queued"
    if isinstance(task, OfflineExperimentRunTask):
        return "offline_experiment.run", "synthetic.offline_experiment.run.queued"
    raise TypeError("unsupported Synthetic execution task")


__all__ = ["SyntheticExecutionApplication"]
