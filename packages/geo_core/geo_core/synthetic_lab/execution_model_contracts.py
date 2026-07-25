"""Frozen Prompt and model-call contracts for Synthetic Lab execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from geo_core.jobs.postgres import WorkerLease
from geo_core.model_gateway.contracts import ModelPolicy
from geo_core.model_gateway.releases import ModelRoute
from geo_core.prompts.bootstrap_templates import bootstrap_template
from geo_core.prompts.program_contracts import ProgramKind
from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.domain import (
    SyntheticLabContractError,
    _require_hash,
    _require_text,
    _require_uuid,
)
from geo_core.synthetic_lab.execution_json import freeze_execution_mapping as _freeze_mapping
from geo_core.synthetic_lab.ports import RuntimeInputSnapshot


@dataclass(frozen=True, kw_only=True)
class FrozenPromptRef:
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
    route: ModelRoute
    configured_model: str
    runtime_manifest_id: UUID
    runtime_manifest_hash: str
    runtime_option_id: UUID
    runtime_option_hash: str
    model_policy: ModelPolicy
    model_policy_hash: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.project_id, "Prompt project"),
            (self.binding_id, "Prompt binding"),
            (self.frozen_state_id, "Prompt frozen state"),
            (self.release_id, "Prompt Release"),
            (self.runtime_manifest_id, "runtime manifest"),
            (self.runtime_option_id, "runtime option"),
        ):
            _require_uuid(value, label)
        if self.binding_version < 1 or self.frozen_state_version < 1 or self.release_version < 1:
            raise SyntheticLabContractError(
                "Prompt binding, frozen-state and Release versions must be positive"
            )
        object.__setattr__(self, "program_kind", ProgramKind(self.program_kind))
        _require_hash(self.release_hash, "Prompt Release")
        _require_hash(self.runtime_manifest_hash, "runtime manifest")
        _require_hash(self.runtime_option_hash, "runtime option")
        _require_hash(self.model_policy_hash, "Prompt model policy")
        _require_text(self.purpose, "Prompt purpose")
        if self.purpose != bootstrap_template(self.program_kind).purpose:
            raise SyntheticLabContractError(
                "Prompt purpose must match the exact governed Program kind"
            )
        _require_text(self.configured_model, "configured model")
        if self.route.provider.strip() == "":
            raise SyntheticLabContractError("Prompt route provider is required")

    @property
    def identity_hash(self) -> str:
        return canonical_hash(
            {
                "project_id": self.project_id,
                "binding_id": self.binding_id,
                "binding_version": self.binding_version,
                "frozen_state_id": self.frozen_state_id,
                "frozen_state_version": self.frozen_state_version,
                "release_id": self.release_id,
                "release_version": self.release_version,
                "release_hash": self.release_hash,
                "program_kind": self.program_kind,
                "purpose": self.purpose,
                "route": self.route,
                "configured_model": self.configured_model,
                "runtime_manifest_id": self.runtime_manifest_id,
                "runtime_manifest_hash": self.runtime_manifest_hash,
                "runtime_option_id": self.runtime_option_id,
                "runtime_option_hash": self.runtime_option_hash,
                "model_policy_hash": self.model_policy_hash,
            }
        )


@dataclass(frozen=True, kw_only=True)
class ResolvedSyntheticPrompt:
    frozen: FrozenPromptRef
    messages: tuple[dict[str, str], ...]
    output_schema: Mapping[str, object]
    application_output_schema: Mapping[str, object]
    prompt_bundle_hash: str
    structured_input_hash: str

    def __post_init__(self) -> None:
        if not self.messages or any(
            set(message) != {"role", "content"}
            or not message["role"].strip()
            or not message["content"].strip()
            for message in self.messages
        ):
            raise SyntheticLabContractError("resolved Prompt messages are invalid")
        object.__setattr__(self, "output_schema", _freeze_mapping(self.output_schema))
        object.__setattr__(
            self,
            "application_output_schema",
            _freeze_mapping(self.application_output_schema),
        )
        _require_hash(self.prompt_bundle_hash, "Prompt bundle")
        _require_hash(self.structured_input_hash, "Prompt structured input")


@dataclass(frozen=True, kw_only=True)
class SyntheticModelInvocation:
    lease: WorkerLease
    expected_job_version: int
    parent_task_input_hash: str
    runtime_inputs: RuntimeInputSnapshot
    prompt: ResolvedSyntheticPrompt
    admitted_by: UUID
    step_key: str
    structured_input: Mapping[str, object]
    deterministic_seed: int | None = None
    max_output_tokens: int = 4096

    def __post_init__(self) -> None:
        if self.expected_job_version < 1:
            raise SyntheticLabContractError("model-call Job version must be positive")
        if self.prompt.frozen.project_id != self.lease.project_id:
            raise SyntheticLabContractError("model Prompt and Job belong to different Projects")
        if self.runtime_inputs.project_id != self.lease.project_id:
            raise SyntheticLabContractError(
                "model runtime inputs and Job belong to different Projects"
            )
        _require_uuid(self.admitted_by, "model-call admission actor")
        _require_hash(self.parent_task_input_hash, "parent Synthetic task input")
        _require_text(self.step_key, "deterministic model step key")
        object.__setattr__(self, "structured_input", _freeze_mapping(self.structured_input))
        if self.deterministic_seed is not None and not 0 <= self.deterministic_seed < 2**64:
            raise SyntheticLabContractError("deterministic model seed is out of range")
        if self.max_output_tokens < 1:
            raise SyntheticLabContractError("model output token limit must be positive")


@dataclass(frozen=True, kw_only=True)
class SyntheticModelResult:
    model_attempt_id: UUID
    model_call_id: UUID
    output: Mapping[str, object]
    provider: str
    configured_model: str
    reported_model: str
    model_identity_hash: str
    request_hash: str
    response_hash: str

    def __post_init__(self) -> None:
        _require_uuid(self.model_attempt_id, "model-call attempt")
        _require_uuid(self.model_call_id, "model call")
        object.__setattr__(self, "output", _freeze_mapping(self.output))
        for value, label in (
            (self.provider, "model provider"),
            (self.configured_model, "configured model"),
            (self.reported_model, "reported model"),
        ):
            _require_text(value, label)
        for value, label in (
            (self.model_identity_hash, "model identity"),
            (self.request_hash, "model request"),
            (self.response_hash, "model response"),
        ):
            _require_hash(value, label)


_PUBLIC_MODULE = "geo_core.synthetic_lab.execution_contracts"
for _contract_type in (
    FrozenPromptRef,
    ResolvedSyntheticPrompt,
    SyntheticModelInvocation,
    SyntheticModelResult,
):
    _contract_type.__module__ = _PUBLIC_MODULE


__all__ = [
    "FrozenPromptRef",
    "ResolvedSyntheticPrompt",
    "SyntheticModelInvocation",
    "SyntheticModelResult",
]
