"""Read models and projection mapping for the Dify operator catalog."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
from uuid import UUID


@dataclass(frozen=True)
class WorkflowRuntimeCard:
    purpose: str
    backend: str
    activation_status: str
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
    published_workflow_hash: str | None = None
    published_snapshot_hash: str | None = None
    published_prompt_nodes: tuple[Mapping[str, object], ...] = ()
    published_input_variables: tuple[Mapping[str, object], ...] = ()
    published_graph_nodes: tuple[Mapping[str, object], ...] = ()
    published_at: datetime | None = None
    observed_at: datetime | None = None
    sync_status: str = "not_observed"
    sync_error: str | None = None


@dataclass(frozen=True)
class DifyUnresolvedAttempt:
    attempt_id: UUID
    parent_job_id: UUID
    child_job_id: UUID
    flow_kind: str
    purpose: str
    status: str
    child_job_status: str
    lease_state: str
    required_action: str
    provider_run_id: str | None
    error_code: str | None
    error_message: str | None
    started_at: datetime


def workflow_runtime_card(purpose: str, row: Mapping[str, Any] | None) -> WorkflowRuntimeCard:
    if row is None:
        return WorkflowRuntimeCard(purpose, "native", "not_configured")
    status = "active"
    if row["secret_status"] != "active":
        status = "blocked_secret"
    return WorkflowRuntimeCard(
        purpose=purpose,
        backend="dify",
        activation_status=status,
        release_id=row["id"],
        release_version=int(row["version"]),
        release_hash=str(row["release_hash"]),
        prompt_program_id=row["prompt_program_id"],
        prompt_release_id=row["prompt_release_id"],
        prompt_release_hash=str(row["prompt_release_hash"]),
        prompt_system_template=None,
        prompt_user_template=None,
        dify_app_id=str(row["dify_app_id"]),
        dify_workflow_id=str(row["published_workflow_id"] or row["dify_workflow_id"]),
        dsl_hash=str(row["dsl_hash"]),
        configured_model=str(row["configured_model"]),
        model_provider=str(row["model_provider"]),
        binding_version=int(row["binding_version"]),
        activated_at=row["activated_at"],
        last_attempt_status=row["last_attempt_status"],
        last_attempt_kind=row["last_attempt_kind"],
        last_attempt_at=row["last_attempt_at"],
        last_error_code=row["last_error_code"],
        last_error_message=row["last_error_message"],
        published_workflow_hash=row["published_workflow_hash"],
        published_snapshot_hash=row["published_snapshot_hash"],
        published_prompt_nodes=tuple(row["published_prompt_nodes"] or ()),
        published_input_variables=tuple(row["published_input_variables"] or ()),
        published_graph_nodes=tuple(row["published_graph_nodes"] or ()),
        published_at=row["published_at"],
        observed_at=row["observed_at"],
        sync_status="cached" if row["published_snapshot_hash"] else "not_observed",
    )
