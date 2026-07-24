"""Durable, project-scoped Admin inbox transport for Workflow C alerts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import json
from typing import Any
from uuid import UUID

from geo_core.alerts.notifications import NOTIFICATION_SUMMARY_FIELDS
from geo_core.project_scope import set_project_scope


class WorkflowCAdminInboxError(RuntimeError):
    """The notification summary is not safe or cannot be persisted idempotently."""


class PostgresWorkflowCAdminInboxWriter:
    """Write only the pre-whitelisted alert summary, once per command id."""

    def __init__(self, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def put(
        self,
        *,
        command_id: str,
        idempotency_key: str,
        project_id: str,
        payload: Mapping[str, object],
    ) -> None:
        notification_id = _uuid(command_id, "notification command id")
        scoped_project_id = _uuid(project_id, "notification project id")
        key = _text(idempotency_key, "notification idempotency key")
        safe_payload = {"summary": _summary(payload, project_id=scoped_project_id)}
        payload_hash = _hash(safe_payload)
        connection = self._connect()
        try:
            set_project_scope(connection, scoped_project_id)
            connection.execute(
                """INSERT INTO workflow_c_admin_inbox_notifications(
                       project_id, command_id, idempotency_key, payload, payload_hash, created_at
                   ) VALUES (%s, %s, %s, %s::jsonb, %s, clock_timestamp())
                   ON CONFLICT (project_id, command_id) DO NOTHING""",
                (
                    scoped_project_id,
                    notification_id,
                    key,
                    _json(safe_payload),
                    payload_hash,
                ),
            )
            row = _row(
                connection.execute(
                    """SELECT project_id, idempotency_key, payload, payload_hash
                           FROM workflow_c_admin_inbox_notifications
                          WHERE project_id = %s AND command_id = %s""",
                    (scoped_project_id, notification_id),
                )
            )
            if (
                row is None
                or row.get("project_id") != scoped_project_id
                or row.get("idempotency_key") != key
                or _canonical_json(row.get("payload")) != _canonical_json(safe_payload)
                or row.get("payload_hash") != payload_hash
            ):
                raise WorkflowCAdminInboxError("admin inbox command identity was reused")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


def _summary(payload: Mapping[str, object], *, project_id: UUID) -> dict[str, object]:
    if frozenset(payload) != NOTIFICATION_SUMMARY_FIELDS:
        raise WorkflowCAdminInboxError("admin inbox payload is not the notification summary")
    if payload.get("project_id") != str(project_id):
        raise WorkflowCAdminInboxError("admin inbox payload crosses project scope")
    for key, value in payload.items():
        if not isinstance(key, str) or isinstance(value, (bytes, bytearray)):
            raise WorkflowCAdminInboxError("admin inbox payload contains unsafe data")
    return dict(payload)


def _uuid(value: str, label: str) -> UUID:
    try:
        return UUID(value)
    except (TypeError, ValueError) as error:
        raise WorkflowCAdminInboxError(f"{label} is invalid") from error


def _text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise WorkflowCAdminInboxError(f"{label} is invalid")
    return value


def _row(cursor: Any) -> Mapping[str, object] | None:
    value = cursor.fetchone()
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise WorkflowCAdminInboxError("admin inbox query must use mapping rows")
    return dict(value)


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _hash(value: object) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else _json(value)


__all__ = ["PostgresWorkflowCAdminInboxWriter", "WorkflowCAdminInboxError"]
