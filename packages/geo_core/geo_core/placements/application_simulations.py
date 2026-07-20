"""Application commands and queries for internal prompt simulations."""

from __future__ import annotations

from typing import Any, Mapping, cast
from uuid import UUID

from geo_core.object_store import RetrievedObject
from geo_core.placements.campaign_context import require_campaign_resource
from geo_core.placements.domain import (
    CampaignContextMismatch,
    CampaignResourceKind,
    CampaignScope,
    JobReference,
    PlacementRuleViolation,
)
from geo_core.placements.ports import UnitOfWorkFactory
from geo_core.placements.simulation import (
    PromptSimulation,
    PromptSimulationAuthenticityMode,
)


class PlacementSimulationApplicationMixin:
    _uow_factory: UnitOfWorkFactory
    _artifact_reader: Any | None

    def create_prompt_simulation(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        opportunity_id: UUID,
        destination_id: UUID,
        prompt_release_binding_id: UUID,
        confirmed_release_hash: str,
        primary_brand_entity_id: UUID,
        product_entity_id: UUID,
        authenticity_mode: PromptSimulationAuthenticityMode | str,
        evidence_item_ids: tuple[UUID, ...],
        goals: Mapping[str, object],
        constraints: Mapping[str, object],
        variables: Mapping[str, object],
        model_policy_hash: str,
        configured_model: str,
        model_call_budget: int,
        requested_by: UUID,
        idempotency_key: str,
        simulation_purpose: str = "content_preview",
        question_set_id: UUID | None = None,
        confirmed_question_set_hash: str | None = None,
        question_set_item_id: UUID | None = None,
    ) -> tuple[PromptSimulation, JobReference]:
        if not evidence_item_ids:
            raise PlacementRuleViolation("prompt simulation requires governed evidence")
        if len(set(evidence_item_ids)) != len(evidence_item_ids):
            raise PlacementRuleViolation("prompt simulation evidence must be unique")
        try:
            normalized_authenticity_mode = PromptSimulationAuthenticityMode(
                authenticity_mode
            )
        except ValueError as exc:
            raise PlacementRuleViolation(
                "prompt simulation authenticity mode is invalid"
            ) from exc
        if not configured_model.strip():
            raise PlacementRuleViolation("configured model is required")
        if len(confirmed_release_hash) != 64 or any(
            character not in "0123456789abcdef" for character in confirmed_release_hash
        ):
            raise PlacementRuleViolation("confirmed Prompt Release hash must be SHA-256")
        if len(model_policy_hash) != 64 or any(
            character not in "0123456789abcdef" for character in model_policy_hash
        ):
            raise PlacementRuleViolation("model policy hash must be lowercase SHA-256")
        if not 1 <= model_call_budget <= 5:
            raise PlacementRuleViolation("model call budget must be between 1 and 5")
        question_values = (
            question_set_id,
            confirmed_question_set_hash,
            question_set_item_id,
        )
        if simulation_purpose == "content_preview" and any(
            value is not None for value in question_values
        ):
            raise PlacementRuleViolation("content preview cannot bind a QuestionSet")
        if simulation_purpose == "geo_question_test" and any(
            value is None for value in question_values
        ):
            raise PlacementRuleViolation(
                "GEO question test requires QuestionSet, hash, and item"
            )
        if simulation_purpose not in {"content_preview", "geo_question_test"}:
            raise PlacementRuleViolation("prompt simulation purpose is unsupported")
        scope = CampaignScope(project_id, campaign_id)
        with self._uow_factory(project_id) as uow:
            context = require_campaign_resource(
                uow.placements,
                scope=scope,
                kind=CampaignResourceKind.OPPORTUNITY,
                resource_id=opportunity_id,
                lock=True,
            )
            if context.destination_id != destination_id:
                raise CampaignContextMismatch(
                    "simulation Destination does not match the Opportunity"
                )
            result = uow.placements.create_prompt_simulation(
                project_id=project_id,
                campaign_id=campaign_id,
                opportunity_id=opportunity_id,
                destination_id=destination_id,
                prompt_release_binding_id=prompt_release_binding_id,
                confirmed_release_hash=confirmed_release_hash,
                primary_brand_entity_id=primary_brand_entity_id,
                product_entity_id=product_entity_id,
                authenticity_mode=normalized_authenticity_mode.value,
                evidence_item_ids=evidence_item_ids,
                goals=goals,
                constraints=constraints,
                variables=variables,
                model_policy_hash=model_policy_hash,
                configured_model=configured_model.strip(),
                model_call_budget=model_call_budget,
                requested_by=requested_by,
                idempotency_key=idempotency_key,
                simulation_purpose=simulation_purpose,
                question_set_id=question_set_id,
                confirmed_question_set_hash=confirmed_question_set_hash,
                question_set_item_id=question_set_item_id,
            )
            uow.commit()
            return result

    def list_prompt_simulations(
        self, *, project_id: UUID, campaign_id: UUID | None = None
    ) -> tuple[PromptSimulation, ...]:
        with self._uow_factory(project_id) as uow:
            return uow.placements.list_prompt_simulations(
                project_id=project_id, campaign_id=campaign_id
            )

    def get_prompt_simulation(
        self,
        *,
        project_id: UUID,
        simulation_id: UUID,
        campaign_id: UUID | None = None,
    ) -> PromptSimulation | None:
        with self._uow_factory(project_id) as uow:
            if campaign_id is not None:
                require_campaign_resource(
                    uow.placements,
                    scope=CampaignScope(project_id, campaign_id),
                    kind=CampaignResourceKind.SIMULATION,
                    resource_id=simulation_id,
                )
            return uow.placements.get_prompt_simulation(
                project_id=project_id,
                campaign_id=campaign_id,
                simulation_id=simulation_id,
            )

    def download_prompt_simulation_artifact(
        self,
        *,
        project_id: UUID,
        simulation_id: UUID,
        campaign_id: UUID | None = None,
    ) -> RetrievedObject:
        simulation = self.get_prompt_simulation(
            project_id=project_id, campaign_id=campaign_id, simulation_id=simulation_id
        )
        if simulation is None:
            raise PlacementRuleViolation("prompt simulation does not exist")
        if (
            simulation.artifact_status != "finalized"
            or simulation.artifact_uri is None
            or simulation.storage_key is None
            or simulation.manifest_hash is None
        ):
            raise PlacementRuleViolation("prompt simulation artifact is not finalized")
        if self._artifact_reader is None:
            raise PlacementRuleViolation("prompt simulation artifact storage is not configured")
        getter = getattr(self._artifact_reader, "get_object", None)
        if getter is None:
            raise PlacementRuleViolation("prompt simulation artifact reader is invalid")
        return cast(
            RetrievedObject,
            getter(key=simulation.storage_key, expected_hash=simulation.manifest_hash),
        )
