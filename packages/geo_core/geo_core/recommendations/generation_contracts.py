"""Immutable contracts for Recommendation generation Jobs and frozen evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from geo_core.model_gateway.contracts import ModelCaptureMethod, ModelPolicy
from geo_core.model_gateway.releases import ModelRoute
from geo_core.prompts.program_contracts import ProgramKind
from geo_core.recommendations.errors import RecommendationRuleViolation
from geo_core.recommendations.generation_evidence import (
    EvidenceSummary as EvidenceSummary,
    FrozenGenerationEvidence,
    ScopeLocator as ScopeLocator,
)
from geo_core.recommendations.models import Recommendation, require_aware
from geo_core.recommendations.generation_hashing import (
    canonical_hash,
    idempotency_hash as idempotency_hash,
    json_mapping as _json_mapping,
    require_hash as _hash,
    required as _required,
)


RECOMMENDATION_JOB_KIND = "recommendation.generate"


class RecommendationGenerationError(RuntimeError):
    """Base error safe for a Recommendation generation terminal record."""


class RecommendationGenerationConflict(RecommendationGenerationError):
    """A Job idempotency, ownership, budget or terminal write conflicted."""


class RecommendationGenerationStale(RecommendationGenerationError):
    """A frozen Fact or Prompt identity changed before terminal persistence."""


class RecommendationGenerationOutputError(RecommendationGenerationError):
    """Structured model output violated the Recommendation evidence boundary."""


class GenerationJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REJECTED_STALE_INPUT = "rejected_stale_input"


@dataclass(frozen=True)
class FrozenPromptBinding:
    project_id: UUID
    binding_id: UUID
    binding_version: int
    frozen_state_id: UUID
    frozen_state_version: int
    release_id: UUID
    release_version: int
    release_hash: str
    program_kind: ProgramKind
    purpose: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_kind", ProgramKind(self.program_kind))
        if (
            self.binding_version < 1
            or self.release_version < 1
            or self.frozen_state_version < 1
        ):
            raise RecommendationRuleViolation("Prompt binding versions must be positive")
        _hash(self.release_hash, "Prompt Release")
        object.__setattr__(self, "purpose", _required(self.purpose, "Prompt purpose"))
        expected = {
            ProgramKind.RECOMMENDATION: "recommendations.recommendation",
            ProgramKind.ARBITER: "synthetic_lab.arbiter",
        }
        if self.program_kind not in expected:
            raise RecommendationRuleViolation(
                "generation requires recommendation or arbiter Prompt"
            )
        if expected[self.program_kind] != self.purpose:
            raise RecommendationRuleViolation("Prompt kind and purpose are inconsistent")


@dataclass(frozen=True)
class ResolvedGenerationPrompt:
    binding: FrozenPromptBinding
    route: ModelRoute
    configured_model: str
    capture_method: ModelCaptureMethod
    search_mode: str | None
    prompt_bundle_hash: str
    messages: tuple[dict[str, str], ...]
    output_schema: Mapping[str, object]
    application_output_schema: Mapping[str, object]
    policy: ModelPolicy
    structured_input_hash: str

    def __post_init__(self) -> None:
        capture_method, search_mode = _model_execution_identity(
            self.route,
            self.capture_method,
            self.search_mode,
            label="resolved Prompt",
        )
        object.__setattr__(self, "capture_method", capture_method)
        object.__setattr__(self, "search_mode", search_mode)
        _hash(self.prompt_bundle_hash, "prompt bundle")
        _hash(self.structured_input_hash, "structured Prompt input")
        if not self.configured_model.strip() or not self.messages:
            raise RecommendationRuleViolation("resolved Prompt requires model and messages")
        object.__setattr__(self, "output_schema", _json_mapping(self.output_schema))
        object.__setattr__(
            self,
            "application_output_schema",
            _json_mapping(self.application_output_schema),
        )


@dataclass(frozen=True)
class RecommendationGenerationSpec:
    project_id: UUID
    evidence: FrozenGenerationEvidence
    prompt_binding: FrozenPromptBinding
    runtime_selection_id: UUID
    runtime_manifest_id: UUID
    runtime_manifest_hash: str
    runtime_option_id: UUID
    runtime_option_hash: str
    route: ModelRoute
    configured_model: str
    model_policy: ModelPolicy
    capture_method: ModelCaptureMethod
    search_mode: str | None
    valid_until: datetime
    created_by: str
    minimum_real_observations: int = 3
    arbiter_binding: FrozenPromptBinding | None = None
    arbiter_runtime_selection_id: UUID | None = None
    arbiter_runtime_manifest_id: UUID | None = None
    arbiter_runtime_manifest_hash: str | None = None
    arbiter_runtime_option_id: UUID | None = None
    arbiter_runtime_option_hash: str | None = None
    arbiter_route: ModelRoute | None = None
    arbiter_configured_model: str | None = None
    arbiter_model_policy: ModelPolicy | None = None
    arbiter_capture_method: ModelCaptureMethod | None = None
    arbiter_search_mode: str | None = None

    def __post_init__(self) -> None:
        if self.project_id != self.evidence.scope.project_id:
            raise RecommendationRuleViolation("generation spec and evidence Projects differ")
        if self.prompt_binding.project_id != self.project_id:
            raise RecommendationRuleViolation("generation Prompt belongs to another Project")
        if self.prompt_binding.program_kind != ProgramKind.RECOMMENDATION:
            raise RecommendationRuleViolation("primary Prompt must be a recommendation Prompt")
        if self.runtime_selection_id.int == 0:
            raise RecommendationRuleViolation("generation runtime selection is required")
        if self.runtime_manifest_id.int == 0 or self.runtime_option_id.int == 0:
            raise RecommendationRuleViolation("generation runtime lineage is required")
        if self.runtime_selection_id != self.runtime_option_id:
            raise RecommendationRuleViolation(
                "generation runtime selection must identify the frozen option"
            )
        _hash(self.runtime_manifest_hash, "generation runtime manifest")
        _hash(self.runtime_option_hash, "generation runtime option")
        if not 1 <= self.minimum_real_observations <= 1000:
            raise RecommendationRuleViolation("minimum observation count is out of bounds")
        object.__setattr__(self, "configured_model", _required(self.configured_model, "model"))
        capture_method, search_mode = _model_execution_identity(
            self.route,
            self.capture_method,
            self.search_mode,
            label="generation",
        )
        object.__setattr__(self, "capture_method", capture_method)
        object.__setattr__(self, "search_mode", search_mode)
        actor = _required(self.created_by, "generation actor")
        try:
            actor_id = UUID(actor)
        except ValueError as error:
            raise RecommendationRuleViolation("generation actor must be a UUID") from error
        if actor_id.int == 0:
            raise RecommendationRuleViolation("generation actor UUID cannot be zero")
        object.__setattr__(self, "created_by", actor)
        require_aware(self.valid_until, "generated Recommendation validity time")
        arbitration = (
            self.arbiter_binding,
            self.arbiter_runtime_selection_id,
            self.arbiter_runtime_manifest_id,
            self.arbiter_runtime_manifest_hash,
            self.arbiter_runtime_option_id,
            self.arbiter_runtime_option_hash,
            self.arbiter_route,
            self.arbiter_configured_model,
            self.arbiter_model_policy,
            self.arbiter_capture_method,
        )
        if any(item is not None for item in arbitration) and not all(
            item is not None for item in arbitration
        ):
            raise RecommendationRuleViolation(
                "arbiter binding, runtime, route, model and capture method are all required"
            )
        if self.arbiter_binding is None and self.arbiter_search_mode is not None:
            raise RecommendationRuleViolation(
                "arbiter search mode cannot exist without an arbiter"
            )
        if self.arbiter_binding is not None:
            if (
                self.arbiter_binding.project_id != self.project_id
                or self.arbiter_binding.program_kind != ProgramKind.ARBITER
            ):
                raise RecommendationRuleViolation("arbiter Prompt is not valid for this Project")
            assert self.arbiter_runtime_selection_id is not None
            assert self.arbiter_runtime_manifest_id is not None
            assert self.arbiter_runtime_manifest_hash is not None
            assert self.arbiter_runtime_option_id is not None
            assert self.arbiter_runtime_option_hash is not None
            if (
                self.arbiter_runtime_selection_id.int == 0
                or self.arbiter_runtime_manifest_id.int == 0
                or self.arbiter_runtime_option_id.int == 0
            ):
                raise RecommendationRuleViolation("arbiter runtime selection is required")
            if self.arbiter_runtime_selection_id != self.arbiter_runtime_option_id:
                raise RecommendationRuleViolation(
                    "arbiter runtime selection must identify the frozen option"
                )
            _hash(self.arbiter_runtime_manifest_hash, "arbiter runtime manifest")
            _hash(self.arbiter_runtime_option_hash, "arbiter runtime option")
            assert self.arbiter_route is not None
            assert self.arbiter_configured_model is not None
            assert self.arbiter_model_policy is not None
            assert self.arbiter_capture_method is not None
            primary_identity = (self.route.provider, self.route.model_release_id)
            arbiter_identity = (self.arbiter_route.provider, self.arbiter_route.model_release_id)
            if primary_identity == arbiter_identity:
                raise RecommendationRuleViolation("arbiter cannot use the generation model")
            object.__setattr__(
                self,
                "arbiter_configured_model",
                _required(self.arbiter_configured_model, "arbiter model"),
            )
            arbiter_capture_method, arbiter_search_mode = _model_execution_identity(
                self.arbiter_route,
                self.arbiter_capture_method,
                self.arbiter_search_mode,
                label="arbiter",
            )
            object.__setattr__(self, "arbiter_capture_method", arbiter_capture_method)
            object.__setattr__(self, "arbiter_search_mode", arbiter_search_mode)

    @property
    def maximum_model_calls(self) -> int:
        return 2 if self.arbiter_binding is not None else 1

    @property
    def input_hash(self) -> str:
        return canonical_hash(
            {
                "project_id": self.project_id,
                "evidence_input_hash": self.evidence.input_hash,
                "prompt": _binding_value(self.prompt_binding),
                "runtime_selection_id": self.runtime_selection_id,
                "runtime_manifest_id": self.runtime_manifest_id,
                "runtime_manifest_hash": self.runtime_manifest_hash,
                "runtime_option_id": self.runtime_option_id,
                "runtime_option_hash": self.runtime_option_hash,
                "route": _route_value(self.route),
                "configured_model": self.configured_model,
                "model_policy": _policy_value(self.model_policy),
                "capture_method": self.capture_method,
                "search_mode": self.search_mode,
                "valid_until": self.valid_until,
                "created_by": self.created_by,
                "minimum_real_observations": self.minimum_real_observations,
                "arbiter_prompt": (
                    _binding_value(self.arbiter_binding) if self.arbiter_binding else None
                ),
                "arbiter_runtime_selection_id": self.arbiter_runtime_selection_id,
                "arbiter_runtime_manifest_id": self.arbiter_runtime_manifest_id,
                "arbiter_runtime_manifest_hash": self.arbiter_runtime_manifest_hash,
                "arbiter_runtime_option_id": self.arbiter_runtime_option_id,
                "arbiter_runtime_option_hash": self.arbiter_runtime_option_hash,
                "arbiter_route": _route_value(self.arbiter_route) if self.arbiter_route else None,
                "arbiter_model": self.arbiter_configured_model,
                "arbiter_model_policy": (
                    _policy_value(self.arbiter_model_policy)
                    if self.arbiter_model_policy
                    else None
                ),
                "arbiter_capture_method": self.arbiter_capture_method,
                "arbiter_search_mode": self.arbiter_search_mode,
            }
        )


@dataclass(frozen=True)
class GenerationJobOwnership:
    lease_id: UUID
    fencing_token: int

    def __post_init__(self) -> None:
        if self.fencing_token < 1:
            raise RecommendationRuleViolation("generation fencing token must be positive")


@dataclass(frozen=True)
class RecommendationGenerationJob:
    id: UUID
    spec: RecommendationGenerationSpec
    input_hash: str
    idempotency_key_hash: str
    status: GenerationJobStatus = GenerationJobStatus.QUEUED
    version: int = 1
    consumed_model_calls: int = 0
    lease_id: UUID | None = None
    lease_expires_at: datetime | None = None
    fencing_token: int = 0
    cancel_requested: bool = False
    error_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", GenerationJobStatus(self.status))
        _hash(self.input_hash, "generation Job input")
        _hash(self.idempotency_key_hash, "generation Job idempotency key")
        if self.input_hash != self.spec.input_hash:
            raise RecommendationRuleViolation("generation Job input hash changed")
        if self.version < 1 or self.fencing_token < 0:
            raise RecommendationRuleViolation("generation Job version/fence is invalid")
        if not 0 <= self.consumed_model_calls <= self.spec.maximum_model_calls:
            raise RecommendationRuleViolation("generation Job model budget is invalid")
        if self.status == GenerationJobStatus.RUNNING:
            if self.lease_id is None or self.lease_expires_at is None or self.fencing_token < 1:
                raise RecommendationRuleViolation("running generation Job requires an active lease")


@dataclass(frozen=True)
class RecommendationGenerationResult:
    recommendation: Recommendation
    model_call_ids: tuple[UUID, ...]
    insufficient_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.recommendation.status.value != "draft":
            raise RecommendationRuleViolation("generation may only create Recommendation drafts")


@dataclass(frozen=True)
class GenerationExecution:
    job: RecommendationGenerationJob
    result: RecommendationGenerationResult | None
    replayed: bool = False


def _binding_value(value: FrozenPromptBinding) -> Mapping[str, object]:
    return {
        "binding_id": value.binding_id,
        "binding_version": value.binding_version,
        "frozen_state_id": value.frozen_state_id,
        "frozen_state_version": value.frozen_state_version,
        "release_id": value.release_id,
        "release_version": value.release_version,
        "release_hash": value.release_hash,
        "kind": value.program_kind,
        "purpose": value.purpose,
    }


def _route_value(value: ModelRoute) -> Mapping[str, object]:
    return {
        "provider": value.provider,
        "adapter_release_id": value.adapter_release_id,
        "adapter_release_hash": value.adapter_release_hash,
        "model_release_id": value.model_release_id,
        "model_release_hash": value.model_release_hash,
    }


def _policy_value(value: ModelPolicy) -> Mapping[str, object]:
    return {
        **value.canonical_value(),
        "policy_version_id": value.policy_version_id,
        "policy_version_hash": value.policy_version_hash,
    }


def _model_execution_identity(
    route: ModelRoute,
    capture_method: ModelCaptureMethod,
    search_mode: str | None,
    *,
    label: str,
) -> tuple[ModelCaptureMethod, str | None]:
    try:
        normalized_capture = ModelCaptureMethod(capture_method)
    except (TypeError, ValueError) as error:
        raise RecommendationRuleViolation(f"{label} capture method is invalid") from error
    expected_capture = (
        ModelCaptureMethod.PROXY_GROUNDED_API
        if route.provider == "microsoft"
        else ModelCaptureMethod.PROVIDER_API
    )
    if normalized_capture is not expected_capture:
        raise RecommendationRuleViolation(
            f"{label} capture method does not match its frozen Model route"
        )
    normalized_search = (
        _required(search_mode, f"{label} search mode")
        if search_mode is not None
        else None
    )
    return normalized_capture, normalized_search
