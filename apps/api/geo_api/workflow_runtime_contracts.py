"""Stable HTTP projections for the Dify workflow runtime catalog."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WorkflowRuntimeContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkflowRuntimeCardResponse(WorkflowRuntimeContract):
    purpose: Literal[
        "knowledge.question_generation",
        "knowledge.rag_grounding",
        "placements.generation",
        "placements.simulation",
        "synthetic_lab.generation",
        "synthetic_lab.claim_extraction",
        "synthetic_lab.conflict_check",
        "synthetic_lab.revision",
        "synthetic_lab.style_profile",
        "recommendations.recommendation",
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
    sync_status: Literal["not_observed", "cached", "current", "drifted", "unreachable"]
    sync_error: str | None = None


class WorkflowRuntimePageResponse(WorkflowRuntimeContract):
    runtime_backend: Literal["native", "dify"]
    items: list[WorkflowRuntimeCardResponse]
    total: int


class DifyUnresolvedAttemptResponse(WorkflowRuntimeContract):
    attempt_id: UUID
    parent_job_id: UUID
    child_job_id: UUID
    flow_kind: Literal["style_profile", "recommendation"]
    purpose: Literal["synthetic_lab.style_profile", "recommendations.recommendation"]
    status: Literal["running", "failed"]
    child_job_status: str
    lease_state: Literal["active", "not_leased", "lease_expired", "terminal"]
    provider_run_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime
    required_action: Literal["wait_for_lease_expiry", "verify_provider_then_issue_new_parent_token"]


class DifyUnresolvedAttemptPageResponse(WorkflowRuntimeContract):
    items: list[DifyUnresolvedAttemptResponse]
    total: int


class IssueDifyResubmissionTokenRequest(WorkflowRuntimeContract):
    provider_outcome: Literal[
        "not_found", "failed_without_output", "succeeded_output_unrecoverable"
    ]
    provider_run_id: str | None = Field(default=None, max_length=500)
    evidence_reference: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_provider_run(self) -> IssueDifyResubmissionTokenRequest:
        if self.provider_outcome == "not_found":
            if self.provider_run_id is not None:
                raise ValueError("not_found must not include provider_run_id")
        elif not (self.provider_run_id or "").strip():
            raise ValueError("provider_run_id is required for this provider outcome")
        return self


class DifyResubmissionTokenResponse(WorkflowRuntimeContract):
    attempt_id: UUID
    recovery_of_attempt_id: UUID
    dify_reconciliation_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    required_action: Literal["enqueue_new_parent_once"] = "enqueue_new_parent_once"
