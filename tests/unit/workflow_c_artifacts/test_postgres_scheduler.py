from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from geo_core.sampling import SamplingRuleViolation
from geo_core.workflow_c_artifacts.postgres_scheduler import (
    PostgresWorkflowCArtifactMaintenanceSchedulerRepository,
)


NOW = datetime(2026, 7, 23, 11, 0, tzinfo=UTC)
PROJECT_ID = UUID("cc300000-0000-0000-0000-000000000001")
JOB_ID = UUID("cc300000-0000-0000-0000-000000000002")
OUTBOX_ID = UUID("cc300000-0000-0000-0000-000000000003")


class _Result:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, object]]:
        return self._rows


class _Connection:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql: str, values: tuple[object, ...]) -> _Result:
        self.calls.append((sql, values))
        return _Result(self.rows)


def test_seed_uses_the_global_seed_rpc_and_preserves_immutable_ids() -> None:
    connection = _Connection(
        [
            {
                "project_id": PROJECT_ID,
                "job_id": JOB_ID,
                "outbox_id": OUTBOX_ID,
                "inserted": True,
            }
        ]
    )
    repository = PostgresWorkflowCArtifactMaintenanceSchedulerRepository(
        connect=lambda: connection
    )

    result = repository.seed_due(
        now=NOW, staged_grace_seconds=900, max_projects=100
    )

    assert result[0].project_id == PROJECT_ID
    assert result[0].job_id == JOB_ID
    assert result[0].outbox_id == OUTBOX_ID
    assert result[0].inserted is True
    assert "geo_seed_workflow_c_artifact_maintenance" in connection.calls[0][0]
    assert connection.calls[0][1] == (NOW, 900, 100)


def test_seed_rejects_a_malformed_rpc_row() -> None:
    repository = PostgresWorkflowCArtifactMaintenanceSchedulerRepository(
        connect=lambda: _Connection([{"project_id": PROJECT_ID}])
    )

    with pytest.raises(SamplingRuleViolation, match="invalid row"):
        repository.seed_due(now=NOW, staged_grace_seconds=900, max_projects=100)


def test_seed_rejects_naive_time_before_opening_a_connection() -> None:
    repository = PostgresWorkflowCArtifactMaintenanceSchedulerRepository(
        connect=lambda: pytest.fail("connection must not open")
    )

    with pytest.raises(SamplingRuleViolation, match="timezone-aware"):
        repository.seed_due(
            now=NOW.replace(tzinfo=None), staged_grace_seconds=900, max_projects=100
        )
