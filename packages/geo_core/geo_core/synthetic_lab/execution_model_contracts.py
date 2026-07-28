"""Frozen Prompt and model-call contracts for Synthetic Lab execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias
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


DIFY_SYNTHETIC_PROGRAM_KINDS = frozenset(
    {
        ProgramKind.STYLE_PROFILE,
        ProgramKind.GENERATION,
        ProgramKind.CLAIM_EXTRACTION,
        ProgramKind.CONFLICT_CHECK,
        ProgramKind.REVISION,
    }
)


class SyntheticExecutionBackend(StrEnum):
    MODEL_GATEWAY = "model_gateway"
    DIFY = "dify"


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
    execution_backend: SyntheticExecutionBackend = SyntheticExecutionBackend.MODEL_GATEWAY
    workflow_release_id: UUID | None = None
    workflow_release_hash: str | None = None

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
        object.__setattr__(
            self,
            "execution_backend",
            SyntheticExecutionBackend(self.execution_backend),
        )
        if self.deterministic_seed is not None and not 0 <= self.deterministic_seed < 2**64:
            raise SyntheticLabContractError("deterministic model seed is out of range")
        if self.max_output_tokens < 1:
            raise SyntheticLabContractError("model output token limit must be positive")
        if self.execution_backend is SyntheticExecutionBackend.DIFY:
            if self.prompt.frozen.program_kind not in DIFY_SYNTHETIC_PROGRAM_KINDS:
                raise SyntheticLabContractError("native-only Synthetic Prompt cannot use Dify")
            if self.workflow_release_id is None or self.workflow_release_id.int == 0:
                raise SyntheticLabContractError("Dify invocation requires a Workflow Release")
            _require_hash(self.workflow_release_hash or "", "Dify Workflow Release")
        elif self.workflow_release_id is not None or self.workflow_release_hash is not None:
            raise SyntheticLabContractError("native model invocation cannot carry Dify lineage")


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


@dataclass(frozen=True, kw_only=True)
class SyntheticWorkflowResult:
    workflow_attempt_id: UUID
    workflow_release_id: UUID
    workflow_release_hash: str
    output: Mapping[str, object]
    configured_model: str
    reported_model: str
    model_identity_hash: str
    request_hash: str
    response_hash: str
    published_snapshot_id: UUID | None = None
    published_snapshot_hash: str | None = None
    provider: str = "dify"

    def __post_init__(self) -> None:
        _require_uuid(self.workflow_attempt_id, "workflow attempt")
        _require_uuid(self.workflow_release_id, "Workflow Release")
        object.__setattr__(self, "output", _freeze_mapping(self.output))
        for value, label in (
            (self.provider, "workflow provider"),
            (self.configured_model, "configured model"),
            (self.reported_model, "reported model"),
        ):
            _require_text(value, label)
        if self.provider != "dify":
            raise SyntheticLabContractError("Synthetic workflow result provider must be Dify")
        for value, label in (
            (self.workflow_release_hash, "Workflow Release"),
            (self.model_identity_hash, "workflow model identity"),
            (self.request_hash, "workflow request"),
            (self.response_hash, "workflow response"),
        ):
            _require_hash(value, label)
        if (self.published_snapshot_id is None) != (self.published_snapshot_hash is None):
            raise SyntheticLabContractError(
                "Dify published snapshot requires both identity and hash"
            )
        if self.published_snapshot_id is not None:
            _require_uuid(self.published_snapshot_id, "Dify published snapshot")
            _require_hash(
                self.published_snapshot_hash or "",
                "Dify published snapshot",
            )


SyntheticExecutionResult: TypeAlias = SyntheticModelResult | SyntheticWorkflowResult


_PUBLIC_MODULE = "geo_core.synthetic_lab.execution_contracts"
SyntheticExecutionBackend.__module__ = _PUBLIC_MODULE
for _contract_type in (
    FrozenPromptRef,
    ResolvedSyntheticPrompt,
    SyntheticModelInvocation,
    SyntheticModelResult,
    SyntheticWorkflowResult,
):
    _contract_type.__module__ = _PUBLIC_MODULE


__all__ = [
    "DIFY_SYNTHETIC_PROGRAM_KINDS",
    "FrozenPromptRef",
    "ResolvedSyntheticPrompt",
    "SyntheticExecutionBackend",
    "SyntheticExecutionResult",
    "SyntheticModelInvocation",
    "SyntheticModelResult",
    "SyntheticWorkflowResult",
]
