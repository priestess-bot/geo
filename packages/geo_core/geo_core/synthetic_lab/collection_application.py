"""Atomic admission of an exact, live-canary-approved Style Collection task."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from geo_core.synthetic_lab.application_support import (
    command_identity,
    new_outbox_message,
    new_synthetic_job,
    recover_command,
    require_roles,
    stage_command,
)
from geo_core.synthetic_lab.authorization import recheck_before_navigation
from geo_core.synthetic_lab.collection_execution_contracts import (
    StyleCollectionExecutionError,
    StyleCollectionTask,
)
from geo_core.synthetic_lab.ports import (
    CommandReceipt,
    LabPrincipal,
    LabRole,
    SyntheticCommandOperation,
    SyntheticJob,
    SyntheticLabUnitOfWorkFactory,
)
from geo_core.synthetic_lab.style_browser import StyleAdapterRegistry


class StyleCollectionExecutionApplication:
    def __init__(
        self,
        uow_factory: SyntheticLabUnitOfWorkFactory,
        *,
        registry: StyleAdapterRegistry,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._registry = registry
        self._clock = clock or (lambda: datetime.now(UTC))

    def enqueue(
        self,
        *,
        principal: LabPrincipal,
        task: StyleCollectionTask,
        outbox_id: UUID,
        idempotency_key: str,
    ) -> CommandReceipt:
        require_roles(principal, task.project_id, LabRole.OPERATOR)
        if task.authorization.purpose != "style_collection":
            raise StyleCollectionExecutionError(
                "Style Collection task requires the exact style_collection purpose"
            )
        self._registry.require(task)
        identity = command_identity(
            project_id=task.project_id,
            idempotency_key=idempotency_key,
            operation=SyntheticCommandOperation.ADMIT_COLLECTION,
            request={
                "job_id": task.job_id,
                "collection_run_id": task.collection_run_id,
                "style_source_revision_id": task.style_source_revision_id,
                "task_input_hash": task.input_hash,
                "adapter_registry_hash": self._registry.registry_hash,
                "outbox_id": outbox_id,
            },
        )
        with self._uow_factory(project_id=task.project_id) as uow:
            replay = recover_command(uow, identity, SyntheticJob)
            if replay is not None:
                return replay
            current = uow.authorizations.current(
                project_id=task.project_id,
                channel=task.channel,
                adapter_release=task.adapter_release,
            )
            navigation = recheck_before_navigation(
                task.authorization,
                current.record if current is not None else None,
                at=self._clock(),
            )
            if not navigation.proceed:
                raise StyleCollectionExecutionError(
                    "Style Collection authorization is stale or inactive"
                )
            job = new_synthetic_job(
                job_id=task.job_id,
                project_id=task.project_id,
                kind="style_collection",
                input_hash=task.input_hash,
                idempotency_key_hash=identity.idempotency_key_hash,
                payload={
                    "collection_run_id": task.collection_run_id,
                    "style_source_revision_id": task.style_source_revision_id,
                    "raw_artifact_id": task.raw_artifact_id,
                    "derived_artifact_id": task.derived_artifact_id,
                    "adapter_registry_hash": self._registry.registry_hash,
                },
                runtime_inputs=None,
                authorization_binding=task.authorization,
            )
            uow.jobs.stage(job, expected_version=0)
            uow.style_collection_tasks.stage(
                task,
                expected_job_input_hash=job.input_hash,
            )
            uow.outbox.stage(
                new_outbox_message(
                    message_id=outbox_id,
                    job=job,
                    event_type="synthetic.style.collect.queued",
                )
            )
            return stage_command(uow, identity, job)


__all__ = ["StyleCollectionExecutionApplication"]
