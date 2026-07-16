"""Transport contracts for internal prompt simulations."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from geo_api.contracts import JobState
from geo_api.placement_contracts import PlacementContract
from geo_core.placements.simulation import DEFAULT_SIMULATION_MODEL_POLICY_HASH


class PromptSimulationCreate(PlacementContract):
    destination_id: UUID
    template_release_id: UUID
    primary_brand_entity_id: UUID
    product_entity_id: UUID
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


class PromptSimulationView(PlacementContract):
    id: UUID
    project_id: UUID
    destination_id: UUID
    destination_policy_version_id: UUID | None
    template_release_id: UUID
    primary_brand_entity_id: UUID
    product_entity_id: UUID
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


class PromptSimulationCreated(PlacementContract):
    simulation: PromptSimulationView
    job_id: UUID
    status: JobState
    status_url: str
