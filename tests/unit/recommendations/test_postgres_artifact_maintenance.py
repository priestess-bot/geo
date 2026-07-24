from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from geo_core.recommendations.postgres.artifact_maintenance import (
    PostgresRecommendationArtifactDeletionRepository,
)
from geo_core.recommendations.postgres.artifact_maintenance_scheduler import (
    PostgresRecommendationArtifactMaintenanceSchedulerRepository,
)


NOW = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
PROJECT_ID = UUID("ab200000-0000-0000-0000-000000000001")
JOB_ID = UUID("ab200000-0000-0000-0000-000000000002")
OUTBOX_ID = UUID("ab200000-0000-0000-0000-000000000003")


class _Result:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self._rows = [] if rows is None else rows

    def fetchone(self) -> dict[str, object]:
        return {"ok": True}

    def fetchall(self) -> list[dict[str, object]]:
        return self._rows


class _Connection:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.committed = False
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement: str, values: tuple[object, ...]) -> _Result:
        self.calls.append((statement, values))
        return _Result(self.rows)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def test_deletion_repository_uses_only_project_scoped_enqueue_and_claim_rpcs() -> None:
    connection = _Connection()
    repository = PostgresRecommendationArtifactDeletionRepository(
        lambda: connection
    )

    repository.enqueue_due(project_id=PROJECT_ID, now=NOW)
    repository.claim(project_id=PROJECT_ID, worker_id="maintainer-1", now=NOW, limit=5)

    enqueue_statement, enqueue_values = connection.calls[0]
    claim_statement, claim_values = connection.calls[1]
    assert "geo_enqueue_recommendation_artifact_maintenance(%s, %s)" in enqueue_statement
    assert enqueue_values == (PROJECT_ID, NOW)
    assert "geo_claim_recommendation_artifact_deletion(\n                   %s, %s, %s, %s, %s" in claim_statement
    assert claim_values == (PROJECT_ID, "maintainer-1", NOW, 120, 5)


def test_scheduler_uses_global_control_plane_rpc_and_validates_returned_ids() -> None:
    connection = _Connection(
        [
            {
                "project_id": PROJECT_ID,
                "job_id": JOB_ID,
                "outbox_id": OUTBOX_ID,
                "inserted": False,
            }
        ]
    )
    repository = PostgresRecommendationArtifactMaintenanceSchedulerRepository(
        connect=lambda: connection
    )

    result = repository.schedule_due(now=NOW)

    assert result[0].project_id == PROJECT_ID
    assert result[0].inserted is False
    assert "geo_schedule_recommendation_artifact_maintenance" in connection.calls[0][0]
    assert connection.calls[0][1] == (NOW,)


def test_scheduler_rejects_naive_time_before_opening_connection() -> None:
    repository = PostgresRecommendationArtifactMaintenanceSchedulerRepository(
        connect=lambda: pytest.fail("connection must not open")
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        repository.schedule_due(now=NOW.replace(tzinfo=None))
