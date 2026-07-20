"""Domain views for isolated, non-publishable prompt simulations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import hashlib
from types import MappingProxyType
from typing import Mapping
from uuid import UUID


DEFAULT_SIMULATION_MODEL_POLICY_HASH = hashlib.sha256(
    b'{"external_training_allowed":false,"structured_output_required":true}'
).hexdigest()


class PromptSimulationAuthenticityMode(StrEnum):
    BRAND_AUTHORED = "brand_authored"
    FAKE_PERSONA = "fake_persona"
    SYNTHETIC_TESTIMONIAL = "synthetic_testimonial"


@dataclass(frozen=True)
class PromptSimulation:
    id: UUID
    project_id: UUID
    destination_id: UUID
    destination_policy_version_id: UUID | None
    template_release_id: UUID
    primary_brand_entity_id: UUID
    product_entity_id: UUID
    authenticity_mode: PromptSimulationAuthenticityMode
    requested_by: UUID
    input_hash: str
    test_only: bool
    publication_eligible: bool
    created_at: datetime
    generation_job_id: UUID
    generation_status: str
    configured_model: str
    model_call_budget: int
    artifact_status: str
    artifact_uri: str | None = None
    storage_key: str | None = None
    output_hash: str | None = None
    manifest_hash: str | None = None
    model_response_hash: str | None = None
    input_snapshot: Mapping[str, object] | None = None
    artifact_manifest: Mapping[str, object] | None = None
    campaign_id: UUID | None = None
    opportunity_id: UUID | None = None
    prompt_release_binding_id: UUID | None = None
    prompt_release_binding_version: int | None = None
    skill_version_id: UUID | None = None
    release_version: int | None = None
    release_hash: str | None = None
    simulation_purpose: str = "content_preview"
    question_set_id: UUID | None = None
    question_set_hash: str | None = None
    question_set_item_id: UUID | None = None
    question_candidate_id: UUID | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "authenticity_mode",
            PromptSimulationAuthenticityMode(self.authenticity_mode),
        )
        if not self.test_only or self.publication_eligible:
            raise ValueError("prompt simulations must remain test-only and non-publishable")
        binding_lineage = (
            self.campaign_id,
            self.opportunity_id,
            self.prompt_release_binding_id,
            self.prompt_release_binding_version,
        )
        if any(value is None for value in binding_lineage) and not all(
            value is None for value in binding_lineage
        ):
            raise ValueError("prompt simulation binding lineage must be exact or legacy")
        question_values = (
            self.question_set_id,
            self.question_set_hash,
            self.question_set_item_id,
            self.question_candidate_id,
        )
        if self.simulation_purpose == "content_preview" and any(
            value is not None for value in question_values
        ):
            raise ValueError("content preview cannot claim a QuestionSet binding")
        if self.simulation_purpose == "geo_question_test" and any(
            value is None for value in question_values
        ):
            raise ValueError("GEO question test requires an exact QuestionSet binding")
        if self.simulation_purpose not in {"content_preview", "geo_question_test"}:
            raise ValueError("prompt simulation purpose is unsupported")
        if self.input_snapshot is not None:
            object.__setattr__(
                self, "input_snapshot", MappingProxyType(dict(self.input_snapshot))
            )
        if self.artifact_manifest is not None:
            object.__setattr__(
                self, "artifact_manifest", MappingProxyType(dict(self.artifact_manifest))
            )
