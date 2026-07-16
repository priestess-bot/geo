"""Small immutable records shared by placement worker adapters."""

from dataclasses import dataclass
from typing import Mapping
from uuid import UUID

from geo_core.placements.simulation import PromptSimulationAuthenticityMode


@dataclass(frozen=True)
class VerificationSnapshot:
    submission_id: UUID
    publication_request_id: UUID
    submitted_url: str
    expected_text_fragments: tuple[str, ...]
    required_disclosures: tuple[str, ...]
    expected_links: tuple[str, ...]
    allowed_hosts: tuple[str, ...]


@dataclass(frozen=True)
class ModelCallReservation:
    call_number: int
    request_hash: str
    provider: str


@dataclass(frozen=True)
class PromptSimulationClaim:
    simulation_id: UUID
    project_id: UUID
    input_hash: str
    input_snapshot: Mapping[str, object]
    authenticity_mode: PromptSimulationAuthenticityMode
    system_prompt: str
    rendered_prompt: str
    configured_model: str
    model_call_budget: int
    evidence_item_ids: tuple[UUID, ...]
    public_citation_item_ids: tuple[UUID, ...]
    output_schema: Mapping[str, object]

    @property
    def prompt_input_hash(self) -> str:
        return self.input_hash
