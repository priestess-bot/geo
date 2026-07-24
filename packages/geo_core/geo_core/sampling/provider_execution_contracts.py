"""Immutable commands and lineage for Provider Sampling execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
import re
from types import MappingProxyType
from uuid import UUID

from geo_core.model_gateway import ModelCaptureMethod, ModelRoute, canonical_json_hash
from geo_core.model_gateway.schema_validation import validate_output_schema_pair
from geo_core.secrets import SecretVersionHandle
from geo_core.sampling.contracts import SamplingRuleViolation


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ProviderSamplingAdmissionError(SamplingRuleViolation):
    """The runtime command differs from the admitted immutable Sampling identity."""


@dataclass(frozen=True)
class ProviderSamplingPrompt:
    """Ephemeral rendering inputs bound to one frozen Prompt Release."""

    binding_id: UUID
    release_id: UUID
    release_hash: str
    bundle_hash: str
    system_message: str
    output_schema: Mapping[str, object]
    application_output_schema: Mapping[str, object]
    answer_field: str = "answer"
    temperature: float = 0.2
    max_output_tokens: int = 4096
    seed: int | None = None
    tool_mode: str | None = None
    output_schema_hash: str = field(init=False)
    application_output_schema_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for uuid_value, label in (
            (self.binding_id, "Prompt binding"),
            (self.release_id, "Prompt Release"),
        ):
            if uuid_value.int == 0:
                raise ValueError(f"{label} ID cannot be zero")
        for hash_value, label in (
            (self.release_hash, "Prompt Release"),
            (self.bundle_hash, "Prompt bundle"),
        ):
            if _SHA256.fullmatch(hash_value) is None:
                raise ValueError(f"{label} hash must be lowercase SHA-256")
        if not self.system_message.strip() or not self.answer_field.strip():
            raise ValueError("Prompt system message and answer field cannot be empty")
        if self.max_output_tokens < 1:
            raise ValueError("Prompt max output tokens must be positive")
        schema = MappingProxyType(dict(self.output_schema))
        application_schema = MappingProxyType(dict(self.application_output_schema))
        validate_output_schema_pair(schema, application_schema)
        object.__setattr__(self, "output_schema", schema)
        object.__setattr__(self, "application_output_schema", application_schema)
        object.__setattr__(self, "output_schema_hash", canonical_json_hash(schema))
        object.__setattr__(
            self,
            "application_output_schema_hash",
            canonical_json_hash(application_schema),
        )

    @property
    def portable_output_schema_hash(self) -> str:
        return self.output_schema_hash


@dataclass(frozen=True)
class ExecuteProviderSampling:
    project_id: UUID
    run_id: UUID
    task_id: UUID
    attempt_id: UUID
    expected_task_version: int
    expected_attempt_version: int
    lease_token: UUID
    fencing_generation: int
    route: ModelRoute
    provider_secret_handle: SecretVersionHandle
    prompt: ProviderSamplingPrompt
    question_text: str
    deadline_at: datetime | None = None

    def __post_init__(self) -> None:
        for value in (
            self.project_id,
            self.run_id,
            self.task_id,
            self.attempt_id,
            self.lease_token,
        ):
            if value.int == 0:
                raise ValueError("Provider Sampling command UUIDs cannot be zero")
        if (
            min(
                self.expected_task_version,
                self.expected_attempt_version,
                self.fencing_generation,
            )
            < 1
        ):
            raise ValueError("Provider Sampling versions and fencing generation must be positive")
        if not self.question_text.strip():
            raise ValueError("Provider Sampling question text cannot be empty")
        if (
            self.provider_secret_handle.project_id != self.project_id
            or self.provider_secret_handle.purpose != f"model_provider.{self.route.provider}"
        ):
            raise ValueError("Provider Sampling secret handle does not match project/provider")


@dataclass(frozen=True)
class ProviderAttemptObservationLineage:
    """Attempt-scoped view; citation/search payloads stay out of Observation."""

    sampling_attempt_id: UUID
    model_call_attempt_id: UUID
    gateway_call_log_id: UUID
    provider_request_id: str | None
    response_hash: str
    output_hash: str
    provider: str
    adapter_release_id: str
    adapter_release_hash: str
    model_release_id: str
    model_release_hash: str
    configured_model: str
    provider_reported_model: str
    capture_method: ModelCaptureMethod
    search_mode: str
    citation_count: int
    citation_lineage_hash: str
    search_event_count: int
    search_lineage_hash: str
    raw_artifact_manifest_hash: str
    derived_artifact_manifest_hash: str
    result_parameters_hash: str
    location_control: str
    location_evidence_hash: str
    requested_country: str | None
    requested_region: str | None
    requested_locale: str
    requested_language: str
    effective_country: str | None
    effective_region: str | None
    effective_locale: str | None
    effective_language: str | None


__all__ = [
    "ExecuteProviderSampling",
    "ProviderAttemptObservationLineage",
    "ProviderSamplingAdmissionError",
    "ProviderSamplingPrompt",
]
