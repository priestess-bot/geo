from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest

from geo_core.jobs.postgres import WorkerLease
from geo_core.synthetic_lab.application_support import new_synthetic_job
from geo_core.synthetic_lab.execution_contracts import (
    StyleProfileBuildOutput,
    SyntheticExecutionError,
)
from geo_core.synthetic_lab.postgres_execution import (
    PostgresSyntheticExecutionRepository,
)
from geo_core.synthetic_lab.postgres_repository import PostgresSyntheticJobRepository
from tests.unit.synthetic_lab.test_execution_worker import _hash, _task


class _RecordingConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def execute(self, statement: str, parameters: object = None) -> object:
        self.calls.append((statement, parameters))
        return object()


@pytest.mark.parametrize("mismatch", ("profile_version_id", "profile_hash"))
def test_style_profile_finalizer_rejects_output_for_another_frozen_target(
    mismatch: str,
) -> None:
    task = _task()
    lease = WorkerLease(
        job_id=task.job_id,
        project_id=task.project_id,
        kind="style.profile.build",
        worker_id="style-profile-identity-test",
        lease_token=uuid4(),
        fencing_generation=1,
        attempt_count=1,
        max_attempts=3,
    )
    output = StyleProfileBuildOutput(
        project_id=task.project_id,
        profile_version_id=task.profile_version_id,
        profile_hash=task.runtime_inputs.profile_hash,
        artifact_hash=_hash("style-profile-output-artifact"),
        model_call_ids=(uuid4(),),
    )
    if mismatch == "profile_version_id":
        output = replace(output, profile_version_id=uuid4())
    else:
        output = replace(output, profile_hash=_hash("another-profile"))

    repository = PostgresSyntheticExecutionRepository(lambda: None)
    with pytest.raises(SyntheticExecutionError, match="frozen build target"):
        repository.finalize(
            connection=object(),
            lease=lease,
            task=task,
            output=output,
            runtime=task.runtime_inputs,
        )


def test_style_profile_parent_job_locks_the_dify_binding_before_insert() -> None:
    task = _task()
    job = new_synthetic_job(
        job_id=task.job_id,
        project_id=task.project_id,
        kind="style_profile_build",
        input_hash=task.input_hash,
        idempotency_key_hash=_hash("style-profile-parent-admission"),
        payload={"profile_version_id": task.profile_version_id},
        runtime_inputs=task.runtime_inputs,
    )
    connection = _RecordingConnection()

    PostgresSyntheticJobRepository(connection, task.project_id)._insert_job(job)

    first_statement, first_parameters = connection.calls[0]
    assert "pg_advisory_xact_lock(hashtextextended(%s, 0))" in first_statement
    assert first_parameters == (
        f"dify-binding:{task.project_id}:synthetic_lab.style_profile",
    )
    assert "INSERT INTO durable_jobs" in connection.calls[1][0]
