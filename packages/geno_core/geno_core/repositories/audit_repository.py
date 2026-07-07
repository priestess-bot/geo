from __future__ import annotations

from typing import Any, Protocol


class AuditRepository(Protocol):
    """Audit read/write repository boundary for Production v1."""

    def save_audit_events(self, events: object, *, cursor: Any | None = None) -> None: ...

    def list_runtime_audit_events(
        self,
        *,
        project_id: str,
        limit: int,
        offset: int,
        event_type: str | None = None,
        actor_id: str | None = None,
    ) -> Any: ...

    def export_runtime_audit_events_csv(
        self,
        *,
        project_id: str,
        event_type: str | None = None,
        actor_id: str | None = None,
    ) -> Any: ...


__all__ = ["AuditRepository"]
