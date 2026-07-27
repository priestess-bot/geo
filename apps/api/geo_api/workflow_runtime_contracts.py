"""Stable HTTP projections for the Dify workflow runtime catalog."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WorkflowRuntimeContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkflowRuntimeCardResponse(WorkflowRuntimeContract):
    purpose: Literal[
        "knowledge.question_generation",
        "knowledge.rag_grounding",
        "placements.generation",
        "placements.simulation",
    ]
    backend: Literal["native", "dify"]
    activation_status: Literal[
        "not_configured",
        "active",
        "blocked_secret",
        "blocked_prompt_retired",
        "stale_prompt",
    ]
    release_id: UUID | None = None
    release_version: int | None = None
    release_hash: str | None = None
    prompt_program_id: UUID | None = None
    prompt_release_id: UUID | None = None
    prompt_release_hash: str | None = None
    prompt_system_template: str | None = None
    prompt_user_template: str | None = None
    dify_app_id: str | None = None
    dify_workflow_id: str | None = None
    dsl_hash: str | None = None
    configured_model: str | None = None
    model_provider: str | None = None
    binding_version: int | None = None
    activated_at: datetime | None = None
    last_attempt_status: str | None = None
    last_attempt_kind: str | None = None
    last_attempt_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    console_url: str | None = None
    published_workflow_hash: str | None = None
    published_snapshot_hash: str | None = None
    published_prompt_nodes: list[dict[str, Any]] = Field(default_factory=list)
    published_input_variables: list[dict[str, Any]] = Field(default_factory=list)
    published_graph_nodes: list[dict[str, Any]] = Field(default_factory=list)
    published_at: datetime | None = None
    observed_at: datetime | None = None
    sync_status: Literal["not_observed", "cached", "current", "unreachable"]
    sync_error: str | None = None


class WorkflowRuntimePageResponse(WorkflowRuntimeContract):
    runtime_backend: Literal["native", "dify"]
    items: list[WorkflowRuntimeCardResponse]
    total: int
