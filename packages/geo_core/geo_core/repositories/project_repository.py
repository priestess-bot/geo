from __future__ import annotations

from typing import Any, Protocol


class ProjectRepository(Protocol):
    """Project repository boundary for Production v1."""

    def list_runtime_projects(
        self,
        *,
        actor_id: str,
        limit: int,
        offset: int,
        status: str | None = None,
        market_code: str | None = None,
    ) -> Any: ...

    def update_runtime_project(self, update: Any) -> Any: ...

    def apply_runtime_project_action(self, action_input: Any) -> Any: ...

    def save_project_bootstrap(self, bootstrap: Any) -> None: ...

    def list_runtime_project_lifecycle_events(
        self,
        *,
        project_id: str,
        limit: int,
        offset: int,
        event_type: str | None = None,
    ) -> Any: ...

    def export_runtime_project_lifecycle_events_csv(
        self,
        *,
        project_id: str,
        event_type: str | None = None,
    ) -> Any: ...


__all__ = ["ProjectRepository"]
