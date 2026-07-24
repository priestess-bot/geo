"""Shared Run status guards and terminal cancellation convergence."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from geo_core.sampling.contracts import (
    SamplingConflict,
    SamplingNotFound,
    SamplingRun,
    SamplingRunStatus,
    SamplingTaskStatus,
)
from geo_core.sampling.ports import SamplingRepository


_TERMINAL_TASK_STATUSES = frozenset(
    {
        SamplingTaskStatus.SUCCEEDED,
        SamplingTaskStatus.FAILED,
        SamplingTaskStatus.CANCELLED,
    }
)


def require_active_run(run: SamplingRun) -> None:
    if run.status not in {SamplingRunStatus.PLANNED, SamplingRunStatus.RUNNING}:
        raise SamplingConflict("Sampling Run is not accepting new work")


def close_cancelled_run_if_terminal(
    repository: SamplingRepository,
    *,
    project_id: UUID,
    run_id: UUID,
) -> None:
    run = repository.get_run(project_id=project_id, run_id=run_id)
    if run is None:
        raise SamplingNotFound("Sampling Run does not exist")
    if run.status is not SamplingRunStatus.CANCEL_REQUESTED:
        return
    tasks = repository.list_tasks(project_id=project_id, run_id=run_id)
    if not all(task.status in _TERMINAL_TASK_STATUSES for task in tasks):
        return
    repository.save_run(
        replace(
            run,
            status=SamplingRunStatus.CANCELLED,
            version=run.version + 1,
        ),
        expected_version=run.version,
    )
