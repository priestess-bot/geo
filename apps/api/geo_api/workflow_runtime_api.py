"""Internal API composition for read-only Dify runtime status."""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Protocol
from uuid import UUID

from geo_core.workflow_runtime import (
    DifyPublishedWorkflowReader,
    PostgresWorkflowRuntimeCatalog,
    WorkflowRuntimeCard,
)


class WorkflowRuntimeApi(Protocol):
    persistence: str

    def list_cards(self, *, project_id: UUID) -> tuple[WorkflowRuntimeCard, ...]: ...


def build_workflow_runtime_api() -> WorkflowRuntimeApi | None:
    database_url = os.getenv("GEO_DATABASE_URL", "").strip()
    if not database_url:
        return None
    catalog = PostgresWorkflowRuntimeCatalog(database_url)
    state_file = os.getenv("GEO_DIFY_STATE_FILE", "").strip()
    if not state_file:
        return catalog
    reader = DifyPublishedWorkflowReader(
        base_url=os.getenv(
            "GEO_DIFY_CONSOLE_INTERNAL_URL",
            os.getenv("GEO_DIFY_API_URL", "http://dify-api:5001"),
        ),
        state_file=state_file,
    )
    return RefreshingWorkflowRuntimeApi(catalog=catalog, reader=reader)


class RefreshingWorkflowRuntimeApi:
    persistence = "durable"

    def __init__(
        self,
        *,
        catalog: PostgresWorkflowRuntimeCatalog,
        reader: DifyPublishedWorkflowReader,
    ) -> None:
        self._catalog = catalog
        self._reader = reader

    def list_cards(self, *, project_id: UUID) -> tuple[WorkflowRuntimeCard, ...]:
        cards = self._catalog.list_cards(project_id=project_id)
        refreshed: list[WorkflowRuntimeCard] = []
        for card in cards:
            if card.release_id is None or card.dify_app_id is None:
                refreshed.append(card)
                continue
            try:
                snapshot = self._reader.read(
                    purpose=card.purpose,
                    app_id=card.dify_app_id,
                )
                self._catalog.record_published_snapshot(
                    project_id=project_id,
                    release_id=card.release_id,
                    snapshot=snapshot,
                )
                model = snapshot.prompt_nodes[0] if snapshot.prompt_nodes else {}
                refreshed.append(
                    replace(
                        card,
                        dify_workflow_id=snapshot.workflow_id,
                        configured_model=str(model.get("model_name") or "") or None,
                        model_provider=str(model.get("model_provider") or "") or None,
                        published_workflow_hash=snapshot.workflow_hash,
                        published_snapshot_hash=snapshot.snapshot_hash,
                        published_prompt_nodes=snapshot.prompt_nodes,
                        published_input_variables=snapshot.input_variables,
                        published_graph_nodes=snapshot.graph_nodes,
                        published_at=snapshot.published_at,
                        observed_at=snapshot.observed_at,
                        sync_status="current",
                        sync_error=None,
                    )
                )
            except Exception as exc:
                refreshed.append(
                    replace(
                        card,
                        sync_status="unreachable",
                        sync_error=_safe_sync_error(exc),
                    )
                )
        return tuple(refreshed)


def _safe_sync_error(error: Exception) -> str:
    message = str(error).strip() or type(error).__name__
    return message[:500]


__all__ = [
    "RefreshingWorkflowRuntimeApi",
    "WorkflowRuntimeApi",
    "build_workflow_runtime_api",
]
