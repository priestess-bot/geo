"""Transactional PostgreSQL admission for Recommendation generation selections."""

from __future__ import annotations

import hashlib
from typing import Any, TypeVar
from uuid import UUID

import psycopg

from geo_core.model_gateway.runtime_catalog import (
    ApprovedRuntimeCatalog,
    NewModelCallJobSelection,
    select_approved_runtime,
)
from geo_core.prompts.program_contracts import ProgramKind
from geo_core.recommendations.errors import RecommendationRuleViolation
from geo_core.recommendations.evidence import (
    AttributionRef,
    ContentRef,
    EvidenceRef,
    FactRef,
    MetricComparisonRef,
    ObservationRef,
    QuestionRef,
    RuleRef,
    SurfaceRef,
)
from geo_core.recommendations.generation_admission import (
    GenerationModelSelector,
    RecommendationGenerationSelection,
)
from geo_core.recommendations.generation_contracts import (
    EvidenceSummary,
    FrozenGenerationEvidence,
    FrozenPromptBinding,
    RecommendationGenerationSpec,
    ScopeLocator,
)
from geo_core.recommendations.generation_ports import (
    RECOMMENDATION_DIFY_CONTEXT_MAX_BYTES,
    recommendation_context_size_bytes,
    structured_generation_input,
)
from geo_core.recommendations.postgres.evidence import (
    PostgresRecommendationEvidenceResolver,
)
from geo_core.recommendations.resolution import RecommendationEvidenceKind


class PostgresRecommendationGenerationAdmission:
    """Resolve all source state on the same project-scoped enqueue transaction."""

    def __init__(
        self,
        connection: Any,
        project_id: UUID,
        *,
        runtime_catalog: ApprovedRuntimeCatalog,
    ) -> None:
        self._connection = connection
        self._project_id = project_id
        self._evidence = PostgresRecommendationEvidenceResolver(connection, project_id)
        self._runtime_catalog = runtime_catalog

    def resolve(
        self,
        *,
        selection: RecommendationGenerationSelection,
        created_by: str,
    ) -> RecommendationGenerationSpec:
        self._require_scope(selection.project_id)
        forbidden = {
            RecommendationEvidenceKind.PROMPT_RELEASE,
            RecommendationEvidenceKind.MODEL_CALL,
        }
        if any(item.kind in forbidden for item in selection.evidence_selectors):
            raise RecommendationRuleViolation(
                "generation Prompt and model lineage must use catalog selectors"
            )
        evidence = self._frozen_evidence(selection)
        context_size = recommendation_context_size_bytes(
            structured_generation_input(
                evidence,
                minimum_real_observations=selection.minimum_real_observations,
            )
        )
        if context_size > RECOMMENDATION_DIFY_CONTEXT_MAX_BYTES:
            raise RecommendationRuleViolation(
                "Recommendation Dify context is "
                f"{context_size} bytes and exceeds the 100KB admission limit; "
                "select fewer or shorter evidence summaries and retry"
            )
        prompt = self._prompt(selection.prompt_binding_id, ProgramKind.RECOMMENDATION)
        model = self._model(selection.model, purpose=prompt.purpose)
        arbiter_prompt = (
            self._prompt(selection.arbiter_prompt_binding_id, ProgramKind.ARBITER)
            if selection.arbiter_prompt_binding_id
            else None
        )
        arbiter_model = (
            self._model(selection.arbiter_model, purpose=arbiter_prompt.purpose)
            if selection.arbiter_model and arbiter_prompt
            else None
        )
        return RecommendationGenerationSpec(
            project_id=selection.project_id,
            evidence=evidence,
            prompt_binding=prompt,
            runtime_selection_id=selection.model.runtime_selection_id,
            runtime_manifest_id=model.runtime_manifest_id,
            runtime_manifest_hash=model.runtime_manifest_hash,
            runtime_option_id=model.runtime_option_id,
            runtime_option_hash=model.runtime_option_hash,
            route=model.route,
            configured_model=model.configured_model,
            model_policy=model.policy,
            capture_method=model.adapter_release.expected_capture_method,
            search_mode=selection.model.search_mode,
            valid_until=selection.valid_until,
            created_by=created_by,
            minimum_real_observations=selection.minimum_real_observations,
            arbiter_binding=arbiter_prompt,
            arbiter_runtime_selection_id=(
                selection.arbiter_model.runtime_selection_id if selection.arbiter_model else None
            ),
            arbiter_runtime_manifest_id=(
                arbiter_model.runtime_manifest_id if arbiter_model else None
            ),
            arbiter_runtime_manifest_hash=(
                arbiter_model.runtime_manifest_hash if arbiter_model else None
            ),
            arbiter_runtime_option_id=(arbiter_model.runtime_option_id if arbiter_model else None),
            arbiter_runtime_option_hash=(
                arbiter_model.runtime_option_hash if arbiter_model else None
            ),
            arbiter_route=arbiter_model.route if arbiter_model else None,
            arbiter_configured_model=(arbiter_model.configured_model if arbiter_model else None),
            arbiter_model_policy=arbiter_model.policy if arbiter_model else None,
            arbiter_capture_method=(
                arbiter_model.adapter_release.expected_capture_method if arbiter_model else None
            ),
            arbiter_search_mode=(
                selection.arbiter_model.search_mode if selection.arbiter_model else None
            ),
        )

    def _frozen_evidence(
        self, selection: RecommendationGenerationSelection
    ) -> FrozenGenerationEvidence:
        resolved = self._evidence.resolve_with_summaries(
            project_id=selection.project_id,
            selectors=selection.evidence_selectors,
        )
        refs = tuple(item[0] for item in resolved)
        summaries = tuple(
            EvidenceSummary(
                ref_kind=ref.ref_kind,
                resource_id=ref.resource_id,
                summary=_required_summary(summary, ref.ref_kind),
                summary_hash=hashlib.sha256(
                    _required_summary(summary, ref.ref_kind).encode()
                ).hexdigest(),
            )
            for ref, summary in resolved
            if ref.ref_kind in {"observation", "metric_comparison", "fact", "rule"}
        )
        return FrozenGenerationEvidence(
            scope=selection.scope,
            observations=_typed(refs, ObservationRef),
            metric_comparisons=_typed(refs, MetricComparisonRef),
            facts=_typed(refs, FactRef),
            rules=_typed(refs, RuleRef),
            questions=_typed(refs, QuestionRef),
            surfaces=_typed(refs, SurfaceRef),
            contents=_typed(refs, ContentRef),
            summaries=summaries,
            scope_locators=self._scope_locators(selection, refs),
            attributions=_typed(refs, AttributionRef),
        )

    def _scope_locators(
        self,
        selection: RecommendationGenerationSelection,
        refs: tuple[EvidenceRef, ...],
    ) -> tuple[ScopeLocator, ...]:
        scope = selection.scope
        values: list[ScopeLocator] = []
        if scope.campaign_id is not None:
            row = self._connection.execute(
                "SELECT id FROM geo_campaigns WHERE project_id = %s AND id = %s",
                (selection.project_id, scope.campaign_id),
            ).fetchone()
            if row is None:
                raise RecommendationRuleViolation(
                    "generation Campaign scope is not current in this Project"
                )
            values.append(
                ScopeLocator(
                    "campaign_id",
                    str(scope.campaign_id),
                    {"campaign_id": str(scope.campaign_id)},
                )
            )
        expected_kinds = {
            "question_or_cluster_ref": "question",
            "surface_ref": "surface",
            "content_asset_ref": "content",
        }
        for field_name, kind in expected_kinds.items():
            resource_id = getattr(scope, field_name)
            if resource_id is None:
                continue
            match = next(
                (
                    ref
                    for ref in refs
                    if getattr(ref, "ref_kind", None) == kind
                    and getattr(ref, "resource_id", None) == resource_id
                ),
                None,
            )
            if match is None:
                raise RecommendationRuleViolation(
                    f"generation {field_name} must reference selected current evidence"
                )
            values.append(ScopeLocator(field_name, resource_id, match.locator))
        if scope.url_ref is not None:
            content = next(
                (
                    ref
                    for ref in refs
                    if getattr(ref, "ref_kind", None) == "content"
                    and scope.url_ref in getattr(ref, "locator", {}).values()
                ),
                None,
            )
            if content is None:
                raise RecommendationRuleViolation(
                    "generation URL scope must be proven by selected Content lineage"
                )
            values.append(ScopeLocator("url_ref", scope.url_ref, content.locator))
        return tuple(values)

    def _prompt(self, binding_id: UUID, kind: ProgramKind) -> FrozenPromptBinding:
        try:
            row = self._connection.execute(
                """SELECT binding.*, state.version AS frozen_state_version
                   FROM prompt_program_bindings AS binding
                   JOIN prompt_program_release_states AS state
                     ON state.id = binding.frozen_state_id
                    AND state.project_id = binding.project_id
                    AND state.release_id = binding.release_id
                    AND state.release_hash = binding.release_hash
                   WHERE binding.id = %s AND binding.project_id = %s
                     AND binding.program_kind = %s AND state.status = 'frozen'
                     AND NOT EXISTS (
                         SELECT 1 FROM prompt_program_bindings AS newer
                         WHERE newer.project_id = binding.project_id
                           AND newer.purpose = binding.purpose
                           AND newer.binding_version > binding.binding_version
                     )""",
                (binding_id, self._project_id, kind.value),
            ).fetchone()
        except psycopg.Error as error:
            raise RecommendationRuleViolation(
                "generation Prompt binding could not be resolved"
            ) from error
        if row is None:
            raise RecommendationRuleViolation("generation requires a current frozen Prompt binding")
        return FrozenPromptBinding(
            project_id=row["project_id"],
            binding_id=row["id"],
            binding_version=row["binding_version"],
            frozen_state_id=row["frozen_state_id"],
            frozen_state_version=row["frozen_state_version"],
            release_id=row["release_id"],
            release_version=row["release_version"],
            release_hash=row["release_hash"],
            program_kind=ProgramKind(row["program_kind"]),
            purpose=row["purpose"],
        )

    def _model(
        self,
        selector: GenerationModelSelector,
        *,
        purpose: str,
    ) -> NewModelCallJobSelection:
        return select_approved_runtime(
            catalog=self._runtime_catalog,
            project_id=self._project_id,
            runtime_selection_id=selector.runtime_selection_id,
            required_purpose=purpose,
            search_mode=selector.search_mode,
        )

    def _require_scope(self, project_id: UUID) -> None:
        if project_id != self._project_id:
            raise RecommendationRuleViolation("generation admission Project scope mismatch")


def _required_summary(value: str | None, kind: str) -> str:
    if value is None or not value.strip():
        raise RecommendationRuleViolation(
            f"generation {kind} requires a server-resolved evidence summary"
        )
    return value.strip()


_EvidenceT = TypeVar("_EvidenceT", bound=EvidenceRef)


def _typed(values: tuple[EvidenceRef, ...], expected: type[_EvidenceT]) -> tuple[_EvidenceT, ...]:
    return tuple(value for value in values if isinstance(value, expected))


__all__ = [
    "PostgresRecommendationGenerationAdmission",
]
