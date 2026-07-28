"""Framework-neutral contracts for frozen Dify workflows."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import math
from types import MappingProxyType
from typing import Callable, Mapping, Protocol
from uuid import UUID

from geo_core.jobs.postgres import WorkerLease
from geo_core.model_gateway import ModelGatewayResult
from geo_core.secrets import SecretVersionHandle

from .errors import WorkflowContractError


DIFY_WORKFLOW_PURPOSES = frozenset(
    {
        "knowledge.question_generation",
        "knowledge.rag_grounding",
        "placements.generation",
        "placements.simulation",
        "synthetic_lab.generation",
        "synthetic_lab.claim_extraction",
        "synthetic_lab.conflict_check",
        "synthetic_lab.revision",
        "synthetic_lab.style_profile",
        "recommendations.recommendation",
    }
)
CONTEXT_CONTRACT_VERSION = "geo-dify-context-v1"
DYNAMIC_JSON_OUTPUT_SCHEMA: Mapping[str, object] = MappingProxyType(
    {
        "type": "object",
        "x-geo-runtime-contract": "application-validated-json-object-v1",
    }
)


def canonical_json_hash(value: object) -> str:
    return hashlib.sha256(canonical_json_text(value).encode("utf-8")).hexdigest()


def canonical_json_text(value: object) -> str:
    return _canonical_json_text(canonical_json_value(value))


def _canonical_json_text(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise WorkflowContractError("workflow hash input contains non-finite number")
        number = Decimal(str(value))
        if number == 0:
            return "0"
        rendered = format(number, "f")
        return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, list):
        return "[" + ",".join(_canonical_json_text(item) for item in value) + "]"
    if isinstance(value, dict):
        return (
            "{"
            + ",".join(
                json.dumps(key, ensure_ascii=False, separators=(",", ":"))
                + ":"
                + _canonical_json_text(value[key])
                for key in sorted(value)
            )
            + "}"
        )
    raise WorkflowContractError(
        f"workflow hash input contains unsupported value: {type(value).__name__}"
    )


def canonical_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): canonical_json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [canonical_json_value(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise WorkflowContractError(
        f"workflow hash input contains unsupported value: {type(value).__name__}"
    )


@dataclass(frozen=True)
class WorkflowRuntimeRelease:
    id: UUID
    project_id: UUID
    purpose: str
    version: int
    prompt_program_id: UUID
    prompt_release_id: UUID
    prompt_release_hash: str
    prompt_system_template: str
    prompt_user_template: str
    dify_app_id: str
    dify_workflow_id: str
    dsl_hash: str
    registered_workflow_hash: str
    registered_snapshot_hash: str
    registered_identity_source: str
    context_contract_version: str
    input_schema: Mapping[str, object]
    input_schema_hash: str
    output_schema: Mapping[str, object]
    output_schema_hash: str
    configured_model: str
    model_provider: str
    api_secret_handle: SecretVersionHandle
    release_hash: str
    binding_version: int

    def __post_init__(self) -> None:
        if self.purpose not in DIFY_WORKFLOW_PURPOSES:
            raise WorkflowContractError("Dify release purpose is not supported")
        if self.project_id != self.api_secret_handle.project_id:
            raise WorkflowContractError("Dify secret handle crossed its project boundary")
        if self.api_secret_handle.purpose != "workflow_runtime.dify":
            raise WorkflowContractError("Dify release uses the wrong Secret Store purpose")
        if self.context_contract_version != CONTEXT_CONTRACT_VERSION:
            raise WorkflowConfigurationError(
                "Dify context contract is not installed in this Worker",
                code="dify_context_contract_unavailable",
            )
        for label, value in (
            ("prompt release hash", self.prompt_release_hash),
            ("DSL hash", self.dsl_hash),
            ("registered workflow hash", self.registered_workflow_hash),
            ("registered snapshot hash", self.registered_snapshot_hash),
            ("input schema hash", self.input_schema_hash),
            ("output schema hash", self.output_schema_hash),
            ("release hash", self.release_hash),
        ):
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise WorkflowContractError(f"{label} must be lowercase SHA-256")
        if self.registered_identity_source not in {
            "migration_backfill",
            "runtime_enrollment",
        }:
            raise WorkflowContractError("registered Dify identity source is invalid")
        if not self.prompt_system_template.strip() or not self.prompt_user_template.strip():
            raise WorkflowContractError("Dify release Prompt templates cannot be empty")


@dataclass(frozen=True)
class WorkflowExecutionRequest:
    project_id: UUID
    purpose: str
    context: Mapping[str, object]
    input_hash: str
    output_schema: Mapping[str, object]
    system_prompt: str = ""
    user_prompt: str = ""

    def __post_init__(self) -> None:
        if self.purpose not in DIFY_WORKFLOW_PURPOSES:
            raise WorkflowContractError("workflow request purpose is not supported")
        if not self.context:
            raise WorkflowContractError("workflow context cannot be empty")
        if len(self.input_hash) != 64 or any(
            char not in "0123456789abcdef" for char in self.input_hash
        ):
            raise WorkflowContractError("workflow input hash must be SHA-256")
        object.__setattr__(self, "context", MappingProxyType(dict(self.context)))
        object.__setattr__(self, "output_schema", MappingProxyType(dict(self.output_schema)))

    @property
    def context_hash(self) -> str:
        return canonical_json_hash(self.context)


@dataclass(frozen=True)
class WorkflowExecutionResult:
    output: Mapping[str, object]
    attempt_id: UUID
    runtime_release_id: UUID
    runtime_release_hash: str
    dify_task_id: str | None
    dify_run_id: str
    configured_model: str
    provider_reported_model: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_steps: int | None
    elapsed_seconds: Decimal | None
    response_hash: str
    published_snapshot_id: UUID | None = None
    published_snapshot_hash: str | None = None
    published_workflow_id: str | None = None
    request_hash: str | None = None

    def __post_init__(self) -> None:
        if (self.published_snapshot_id is None) != (self.published_snapshot_hash is None):
            raise WorkflowContractError(
                "Dify result published snapshot ID and hash must be frozen together"
            )
        if self.published_snapshot_hash is not None and (
            len(self.published_snapshot_hash) != 64
            or any(char not in "0123456789abcdef" for char in self.published_snapshot_hash)
        ):
            raise WorkflowContractError("Dify result published snapshot hash must be SHA-256")
        if self.published_workflow_id is not None and not self.published_workflow_id.strip():
            raise WorkflowContractError("Dify result published workflow ID cannot be empty")
        if self.request_hash is not None and (
            len(self.request_hash) != 64
            or any(char not in "0123456789abcdef" for char in self.request_hash)
        ):
            raise WorkflowContractError("Dify result request hash must be SHA-256")

    def as_model_gateway_result(self) -> ModelGatewayResult:
        """Bridge existing business finalizers without recording a fake model call."""

        return ModelGatewayResult(
            output=dict(self.output),
            call_log_id=self.attempt_id,
            provider_request_id=self.dify_run_id,
            configured_model=self.configured_model,
            provider_reported_model=self.provider_reported_model,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            cost_usd=None,
            finish_reason="workflow_succeeded",
            response_hash=self.response_hash,
            provider="dify",
            adapter_release_id="dify-workflow-api-v1",
            adapter_release_hash=self.runtime_release_hash,
            model_release_id=str(self.runtime_release_id),
            model_release_hash=self.runtime_release_hash,
            usage_details={
                "workflow_runtime": "dify",
                "workflow_attempt_id": str(self.attempt_id),
                "workflow_run_id": self.dify_run_id,
                "published_snapshot_id": (
                    str(self.published_snapshot_id)
                    if self.published_snapshot_id is not None
                    else None
                ),
                "published_snapshot_hash": self.published_snapshot_hash,
                "published_workflow_id": self.published_workflow_id,
                "total_steps": self.total_steps,
                "elapsed_seconds": (
                    str(self.elapsed_seconds) if self.elapsed_seconds is not None else None
                ),
            },
        )


class WorkflowExecutor(Protocol):
    def execute_optional(
        self,
        lease: WorkerLease,
        request: WorkflowExecutionRequest,
        *,
        validate_output: Callable[[Mapping[str, object]], None] | None = None,
    ) -> WorkflowExecutionResult | None: ...

    def execute_frozen(
        self,
        lease: WorkerLease,
        request: WorkflowExecutionRequest,
        *,
        release_id: UUID,
        release_hash: str,
        validate_output: Callable[[Mapping[str, object]], None] | None = None,
    ) -> WorkflowExecutionResult: ...


# Avoid a circular import in the validation branch above.
from .errors import WorkflowConfigurationError  # noqa: E402
