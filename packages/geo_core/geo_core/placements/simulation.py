"""Domain views for isolated, non-publishable prompt simulations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
from types import MappingProxyType
from typing import Mapping
from uuid import UUID


DEFAULT_SIMULATION_MODEL_POLICY_HASH = hashlib.sha256(
    b'{"external_training_allowed":false,"structured_output_required":true}'
).hexdigest()


@dataclass(frozen=True)
class PromptSimulation:
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

    def __post_init__(self) -> None:
        if not self.test_only or self.publication_eligible:
            raise ValueError("prompt simulations must remain test-only and non-publishable")
        if self.input_snapshot is not None:
            object.__setattr__(
                self, "input_snapshot", MappingProxyType(dict(self.input_snapshot))
            )
        if self.artifact_manifest is not None:
            object.__setattr__(
                self, "artifact_manifest", MappingProxyType(dict(self.artifact_manifest))
            )
