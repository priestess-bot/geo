from __future__ import annotations

from uuid import UUID, uuid4

from geo_core.synthetic_lab.postgres_child_model_calls import (
    PostgresSyntheticChildCallRepository,
)


PROJECT_ID = UUID("32000000-0000-0000-0000-000000000001")


class _RecordedCursor:
    def fetchone(self) -> dict[str, object]:
        return {"status": "queued"}


class _StateQueryConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.closed = False

    def execute(self, sql: str, parameters: tuple[object, ...]):
        self.calls.append((sql, parameters))
        return _RecordedCursor()

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class _StateQueryRepository(PostgresSyntheticChildCallRepository):
    def __init__(self, connection: _StateQueryConnection) -> None:
        super().__init__(lambda: connection, artifacts=object(), results=object())
        self._connection = connection

    def _open(self, project_id):
        assert project_id == PROJECT_ID
        return self._connection


def test_child_state_query_loads_exact_dify_release_lineage() -> None:
    connection = _StateQueryConnection()
    repository = _StateQueryRepository(connection)
    child_job_id = uuid4()

    assert repository._state_row(PROJECT_ID, child_job_id) == {"status": "queued"}

    assert connection.closed is True
    sql, parameters = connection.calls[0]
    assert parameters == (PROJECT_ID, child_job_id)
    assert "workflow.prompt_release_id AS workflow_prompt_release_id" in sql
    assert "workflow.prompt_release_hash AS workflow_prompt_release_hash" in sql
    assert "workflow.configured_model AS workflow_configured_model" in sql
    assert "workflow.purpose AS workflow_purpose" in sql
    assert "LEFT JOIN dify_workflow_releases AS workflow" in sql
