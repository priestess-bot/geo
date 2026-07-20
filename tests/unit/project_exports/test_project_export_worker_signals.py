from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from geo_core.jobs.postgres import JobCancellationRequested, LostJobLease, WorkerLease
from geo_core.project_exports.worker import ProjectExportHandler


class _RaisingRepository:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def load_claim(self, lease: WorkerLease):
        del lease
        raise self._error


class _NoFailureStore:
    def fail(self, *args: object, **kwargs: object) -> str:
        del args, kwargs
        raise AssertionError("terminal worker signals must reach the dispatcher")


@pytest.mark.parametrize(
    "error",
    [
        JobCancellationRequested("cancel requested"),
        LostJobLease("lease fenced"),
    ],
)
def test_project_export_worker_passes_terminal_signals_to_dispatcher(error: Exception) -> None:
    handler = ProjectExportHandler(
        store=_NoFailureStore(),  # type: ignore[arg-type]
        repository=_RaisingRepository(error),
        source=object(),  # type: ignore[arg-type]
        object_store=object(),  # type: ignore[arg-type]
        lease_for=timedelta(seconds=30),
    )
    lease = WorkerLease(uuid4(), uuid4(), "project.export", "worker", uuid4(), 1, 1, 3)

    with pytest.raises(type(error), match=str(error)):
        handler.handle(lease)
