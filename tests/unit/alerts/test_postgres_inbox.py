from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest

from geo_core.alerts.postgres_inbox import (
    PostgresWorkflowCAdminInboxWriter,
    WorkflowCAdminInboxError,
)


def test_postgres_admin_inbox_persists_only_whitelisted_summary_idempotently() -> None:
    project_id, command_id = uuid4(), uuid4()
    connection = _Connection(project_id, command_id)
    payload = _payload(project_id)

    PostgresWorkflowCAdminInboxWriter(lambda: connection).put(
        command_id=str(command_id),
        idempotency_key="alert-notification:example:v1:opened:admin_inbox",
        project_id=str(project_id),
        payload=payload,
    )

    assert connection.committed is True
    assert any("INSERT INTO workflow_c_admin_inbox_notifications" in item for item in connection.queries)


def test_postgres_admin_inbox_rejects_raw_or_cross_project_payload() -> None:
    project_id, command_id = uuid4(), uuid4()
    payload = _payload(project_id)
    payload["raw_body"] = "not allowed"

    with pytest.raises(WorkflowCAdminInboxError, match="notification summary"):
        PostgresWorkflowCAdminInboxWriter(lambda: _Connection(project_id, command_id)).put(
            command_id=str(command_id),
            idempotency_key="alert-notification:example:v1:opened:admin_inbox",
            project_id=str(project_id),
            payload=payload,
        )


def _payload(project_id: UUID) -> dict[str, object]:
    return {
        "alert_id": str(uuid4()),
        "project_id": str(project_id),
        "rule_key": "completion_freshness",
        "rule_version": 1,
        "rule_kind": "completion_freshness",
        "severity": "warning",
        "status": "open",
        "event_type": "opened",
        "occurred_at": "2026-07-23T10:00:00+00:00",
        "detail_link": "/admin/projects/example/alerts/example",
    }


class _Cursor:
    def __init__(self, row: dict[str, object] | None = None) -> None:
        self._row = row

    def fetchone(self) -> dict[str, object] | None:
        return self._row


class _Connection:
    def __init__(self, project_id: UUID, command_id: UUID) -> None:
        self.project_id = project_id
        self.command_id = command_id
        self.queries: list[str] = []
        self.committed = False
        self.payload: object | None = None
        self.payload_hash: str | None = None

    def execute(self, query: str, params: object = None) -> _Cursor:
        self.queries.append(query)
        if "INSERT INTO workflow_c_admin_inbox_notifications" in query:
            assert isinstance(params, tuple)
            self.payload = json.loads(params[3])
            self.payload_hash = params[4]
        if "SELECT project_id, idempotency_key, payload, payload_hash" in query:
            assert isinstance(params, tuple)
            return _Cursor(
                {
                    "project_id": self.project_id,
                    "idempotency_key": "alert-notification:example:v1:opened:admin_inbox",
                    "payload": self.payload,
                    "payload_hash": self.payload_hash,
                }
            )
        return _Cursor()

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass
