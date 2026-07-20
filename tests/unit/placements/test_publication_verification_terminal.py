from __future__ import annotations

from datetime import timedelta
from typing import Mapping
from uuid import UUID, uuid4

import pytest

from geo_core.jobs.postgres import (
    ClaimResult,
    JobCancellationRequested,
    WorkerLease,
)
from geo_core.placements.worker_composition import (
    PlacementWorkerDispatcher,
    PublicationVerificationHandler,
)


class _Store:
    def __init__(self, claim: ClaimResult, *, failure_status: str = "retry_wait") -> None:
        self.claim_result = claim
        self.failure_status = failure_status
        self.cancelled = False

    def claim(self, **values: object) -> ClaimResult:
        del values
        return self.claim_result

    def fail(self, lease: WorkerLease, **values: object) -> str:
        del lease, values
        return self.failure_status

    def cancel(self, lease: WorkerLease) -> None:
        del lease
        self.cancelled = True


class _Handler:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.reconciled: list[tuple[UUID, UUID]] = []

    def handle(self, lease: WorkerLease) -> Mapping[str, object]:
        if self.error is not None:
            raise self.error
        return {"status": "succeeded", "job_id": str(lease.job_id)}

    def reconcile_terminal(self, *, job_id: UUID, project_id: UUID) -> None:
        self.reconciled.append((job_id, project_id))


class _Repository:
    def __init__(self) -> None:
        self.reconciled: list[tuple[UUID, UUID]] = []

    def reconcile_terminal_verification(
        self, *, job_id: UUID, project_id: UUID
    ) -> None:
        self.reconciled.append((job_id, project_id))


def _lease(*, job_id: UUID, project_id: UUID) -> WorkerLease:
    return WorkerLease(
        job_id=job_id,
        project_id=project_id,
        kind="publication.verify",
        worker_id="verification-unit",
        lease_token=uuid4(),
        fencing_generation=1,
        attempt_count=1,
        max_attempts=3,
    )


@pytest.mark.parametrize(
    ("failure_status", "expected_reconciliations"),
    (("retry_wait", 0), ("dead_lettered", 1)),
)
def test_uncaught_verification_failure_reconciles_only_at_true_terminal(
    failure_status: str, expected_reconciliations: int
) -> None:
    job_id, project_id = uuid4(), uuid4()
    lease = _lease(job_id=job_id, project_id=project_id)
    store = _Store(ClaimResult("claimed", lease, lease.kind), failure_status=failure_status)
    handler = _Handler(RuntimeError("unexpected verifier failure"))
    dispatcher = PlacementWorkerDispatcher(
        store=store,  # type: ignore[arg-type]
        handlers={lease.kind: handler},
        worker_id="verification-unit",
    )

    assert dispatcher.process(job_id=job_id, project_id=project_id)["status"] == failure_status
    assert handler.reconciled == [(job_id, project_id)] * expected_reconciliations


def test_cancel_acknowledgement_reconciles_after_job_is_terminal() -> None:
    job_id, project_id = uuid4(), uuid4()
    lease = _lease(job_id=job_id, project_id=project_id)
    store = _Store(ClaimResult("claimed", lease, lease.kind))
    handler = _Handler(JobCancellationRequested("cancel requested"))
    dispatcher = PlacementWorkerDispatcher(
        store=store,  # type: ignore[arg-type]
        handlers={lease.kind: handler},
        worker_id="verification-unit",
    )

    assert dispatcher.process(job_id=job_id, project_id=project_id)["status"] == "cancelled"
    assert store.cancelled is True
    assert handler.reconciled == [(job_id, project_id)]


def test_claim_terminal_budget_reconciles_without_a_lease() -> None:
    job_id, project_id = uuid4(), uuid4()
    store = _Store(ClaimResult("dead_lettered", kind="publication.verify"))
    handler = _Handler()
    dispatcher = PlacementWorkerDispatcher(
        store=store,  # type: ignore[arg-type]
        handlers={"publication.verify": handler},
        worker_id="verification-unit",
    )

    assert dispatcher.process(job_id=job_id, project_id=project_id)["status"] == "dead_lettered"
    assert handler.reconciled == [(job_id, project_id)]


def test_publication_handler_delegates_terminal_reconciliation() -> None:
    job_id, project_id = uuid4(), uuid4()
    repository = _Repository()
    handler = PublicationVerificationHandler(
        store=object(),  # type: ignore[arg-type]
        repository=repository,  # type: ignore[arg-type]
        verifier=object(),  # type: ignore[arg-type]
        lease_for=timedelta(seconds=30),
    )

    handler.reconcile_terminal(job_id=job_id, project_id=project_id)

    assert repository.reconciled == [(job_id, project_id)]
