from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from geo_core.jobs.postgres import WorkerLease
from geo_core.synthetic_lab.artifact_maintenance_contracts import (
    SYNTHETIC_ARTIFACT_MAINTENANCE_JOB_KIND,
    SyntheticArtifactMaintenanceResult,
)
from geo_worker import synthetic_artifact_maintenance as module


class _Store:
    def __init__(self) -> None:
        self.heartbeats: list[WorkerLease] = []
        self.completed: list[tuple[WorkerLease, str, dict[str, int]]] = []
        self.failures: list[tuple[WorkerLease, str, dict[str, str]]] = []

    def heartbeat(self, lease: WorkerLease, *, lease_for: timedelta) -> None:
        assert lease_for == timedelta(seconds=60)
        self.heartbeats.append(lease)

    @contextmanager
    def fenced_transaction(self, lease: WorkerLease):
        assert lease == _lease()
        yield object()

    def complete_in_transaction(
        self,
        _connection: object,
        lease: WorkerLease,
        *,
        result_ref: str,
        details: dict[str, int],
    ) -> None:
        self.completed.append((lease, result_ref, details))

    def fail(
        self,
        lease: WorkerLease,
        *,
        error_code: str,
        details: dict[str, str],
        retry_delay: timedelta,
    ) -> str:
        assert retry_delay == timedelta(seconds=60)
        self.failures.append((lease, error_code, details))
        return "retry_wait"


class _Service:
    def __init__(self, *, fail: bool = False) -> None:
        self.project_ids: list[UUID] = []
        self.fail = fail

    def run_once(self, *, project_id):
        self.project_ids.append(project_id)
        if self.fail:
            raise RuntimeError("object store detail must not reach Job status")
        return SyntheticArtifactMaintenanceResult(
            staged_expiry_count=2,
            claimed_count=3,
            crypto_erased_count=3,
            completed_count=2,
            retry_count=1,
        )


class _Heartbeat:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.checked = 0

    def __enter__(self) -> _Heartbeat:
        return self

    def __exit__(self, *_args: object) -> None:
        pass

    def raise_if_stopped(self) -> None:
        self.checked += 1


_JOB_ID = uuid4()
_PROJECT_ID = uuid4()
_LEASE_TOKEN = uuid4()


def _lease(kind: str = SYNTHETIC_ARTIFACT_MAINTENANCE_JOB_KIND) -> WorkerLease:
    return WorkerLease(
        job_id=_JOB_ID,
        project_id=_PROJECT_ID,
        kind=kind,
        worker_id="synthetic-retention-test",
        lease_token=_LEASE_TOKEN,
        fencing_generation=2,
        attempt_count=1,
        max_attempts=3,
    )


def _operation(store: _Store, service: _Service) -> module.SyntheticArtifactMaintenanceOperation:
    return module.SyntheticArtifactMaintenanceOperation(
        store=store,
        service=service,
        lease_for=timedelta(seconds=60),
    )


def test_operation_completes_only_after_project_scoped_maintenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "LeaseHeartbeat", _Heartbeat)
    store = _Store()
    service = _Service()

    result = _operation(store, service).execute(_lease())

    assert service.project_ids == [_PROJECT_ID]
    assert len(store.heartbeats) == 1
    assert result == {
        "status": "succeeded",
        "job_id": str(_JOB_ID),
        "staged_expiry_count": 2,
        "claimed_count": 3,
        "crypto_erased_count": 3,
        "completed_count": 2,
        "retry_count": 1,
    }
    assert store.completed == [
        (
            _lease(),
            "synthetic-artifact-maintenance://" + f"{_JOB_ID}/2",
            {
                "staged_expiry_count": 2,
                "claimed_count": 3,
                "crypto_erased_count": 3,
                "completed_count": 2,
                "retry_count": 1,
            },
        )
    ]


def test_operation_retries_with_a_stable_error_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "LeaseHeartbeat", _Heartbeat)
    store = _Store()
    service = _Service(fail=True)

    result = _operation(store, service).execute(_lease())

    assert result == {"status": "retry_wait", "job_id": str(_JOB_ID)}
    assert len(store.heartbeats) == 2
    assert store.completed == []
    assert store.failures == [
        (
            _lease(),
            "synthetic_artifact_maintenance_failed",
            {"classification": "RuntimeError"},
        )
    ]


def test_operation_rejects_a_non_maintenance_job() -> None:
    store = _Store()
    service = _Service()

    with pytest.raises(ValueError, match="unsupported Job"):
        _operation(store, service).execute(_lease(kind="synthetic.style.collect"))

    assert service.project_ids == []
