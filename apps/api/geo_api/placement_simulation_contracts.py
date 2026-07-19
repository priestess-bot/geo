"""Transport contracts for internal prompt simulations."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from geo_api.contracts import JobState
from geo_api.placement_contracts import PlacementContract
from geo_core.placements.simulation import (
    DEFAULT_SIMULATION_MODEL_POLICY_HASH,
    PromptSimulationAuthenticityMode,
)


class PromptSimulationCreate(PlacementContract):
    campaign_id: UUID
    opportunity_id: UUID
    destination_id: UUID
    prompt_release_binding_id: UUID
    confirmed_release_hash: str = Field(pattern="^[0-9a-f]{64}$")
    primary_brand_entity_id: UUID
    product_entity_id: UUID
    authenticity_mode: PromptSimulationAuthenticityMode = (
        PromptSimulationAuthenticityMode.SYNTHETIC_TESTIMONIAL
    )
    evidence_item_ids: list[UUID] = Field(min_length=1)
    goals: dict[str, object]
    constraints: dict[str, object] = Field(default_factory=dict)
    variables: dict[str, object] = Field(default_factory=dict)
    model_policy_hash: str = Field(
        default=DEFAULT_SIMULATION_MODEL_POLICY_HASH,
        pattern="^[0-9a-f]{64}$",
    )
    configured_model: str = Field(
        default="deepseek-v4-flash", min_length=1, max_length=200
    )
    model_call_budget: int = Field(default=2, ge=1, le=5)
    simulation_purpose: Literal["content_preview", "geo_question_test"] = "content_preview"
    question_set_id: UUID | None = None
    confirmed_question_set_hash: str | None = Field(
        default=None, pattern="^[0-9a-f]{64}$"
    )
    question_set_item_id: UUID | None = None

    @model_validator(mode="after")
    def question_binding_shape(self) -> "PromptSimulationCreate":
        values = (
            self.question_set_id,
            self.confirmed_question_set_hash,
            self.question_set_item_id,
        )
        if self.simulation_purpose == "content_preview" and any(
            value is not None for value in values
        ):
            raise ValueError("content preview cannot bind a QuestionSet")
        if self.simulation_purpose == "geo_question_test" and any(
            value is None for value in values
        ):
            raise ValueError("GEO question test requires an exact QuestionSet item")
        return self


class PromptSimulationView(PlacementContract):
    id: UUID
    project_id: UUID
    campaign_id: UUID
    opportunity_id: UUID
    destination_id: UUID
    destination_policy_version_id: UUID | None
    template_release_id: UUID
    prompt_release_binding_id: UUID
    prompt_release_binding_version: int
    skill_version_id: UUID
    release_version: int
    release_hash: str
    primary_brand_entity_id: UUID
    product_entity_id: UUID
    authenticity_mode: PromptSimulationAuthenticityMode
    requested_by: UUID
    input_hash: str
    test_only: bool
    publication_eligible: bool
    created_at: datetime
    generation_job_id: UUID
    generation_status: JobState
    configured_model: str
    model_call_budget: int
    artifact_status: str
    artifact_uri: str | None
    storage_key: str | None
    output_hash: str | None
    manifest_hash: str | None
    model_response_hash: str | None
    input_snapshot: dict[str, object] | None
    artifact_manifest: dict[str, object] | None
    simulation_purpose: Literal["content_preview", "geo_question_test"]
    question_set_id: UUID | None
    question_set_hash: str | None
    question_set_item_id: UUID | None
    question_candidate_id: UUID | None


class PromptSimulationCreated(PlacementContract):
    simulation: PromptSimulationView
    job_id: UUID
    status: JobState
    status_url: str
