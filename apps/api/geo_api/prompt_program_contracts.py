"""Strict Internal API contracts for governed Prompt Programs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


ProgramKindValue = Literal[
    "generation",
    "claim_extraction",
    "conflict_check",
    "revision",
    "style_judge",
    "arbiter",
    "metric_judge",
    "recommendation",
    "style_profile",
    "offline_answer",
    "reference_translation",
]
ReleaseStatusValue = Literal["draft", "tested", "approved", "frozen"]


class PromptProgramContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProgramSchemaRequest(PromptProgramContract):
    variable_schema_version: str = Field(min_length=1, max_length=100)
    variable_schema: dict[str, object]
    input_schema_version: str = Field(min_length=1, max_length=100)
    input_schema: dict[str, object]
    output_schema_version: str = Field(min_length=1, max_length=100)
    output_schema: dict[str, object]
    application_output_schema_version: str = Field(min_length=1, max_length=100)
    application_output_schema: dict[str, object]


class ModelPolicyRequest(PromptProgramContract):
    version: str = Field(min_length=1, max_length=100)
    policy: dict[str, object]


class CreatePromptProgramRequest(PromptProgramContract):
    program_kind: ProgramKindValue
    purpose: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,127}$")
    system_template: str = Field(min_length=1, max_length=100_000)
    user_template: str = Field(min_length=1, max_length=100_000)
    schemas: ProgramSchemaRequest
    model_policy: ModelPolicyRequest
    test_set_id: UUID
    test_set_version: int = Field(ge=1)
    test_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    compiler_version: str = Field(min_length=1, max_length=100)
    expected_version: int = Field(ge=0)


class CreatePromptProgramReleaseRequest(PromptProgramContract):
    system_template: str = Field(min_length=1, max_length=100_000)
    user_template: str = Field(min_length=1, max_length=100_000)
    schemas: ProgramSchemaRequest
    model_policy: ModelPolicyRequest
    test_set_id: UUID
    test_set_version: int = Field(ge=1)
    test_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    compiler_version: str = Field(min_length=1, max_length=100)
    expected_version: int = Field(ge=1)


class TestPromptProgramReleaseRequest(PromptProgramContract):
    test_set_id: UUID
    test_set_version: int = Field(ge=1)
    test_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_selection_id: UUID
    expected_version: int = Field(ge=1)


class PromptTestRuntimeOptionResponse(PromptProgramContract):
    runtime_selection_id: UUID
    runtime_selection_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_manifest_id: UUID
    runtime_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: str
    adapter_release_id: str
    adapter_release_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_release_id: str
    model_release_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    configured_model: str
    capture_method: Literal["provider_api", "proxy_grounded_api"]
    policy_version_id: UUID
    policy_version_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class PromptTestRuntimeOptionPage(PromptProgramContract):
    items: list[PromptTestRuntimeOptionResponse]
    total: int = Field(ge=0)


class TransitionPromptProgramReleaseRequest(PromptProgramContract):
    expected_version: int = Field(ge=1)


class DiffPromptProgramReleaseRequest(PromptProgramContract):
    baseline_release_id: UUID
    fixed_variables: dict[str, object]
    expected_version: int = Field(ge=1)


class BindPromptProgramReleaseRequest(PromptProgramContract):
    program_id: UUID
    release_id: UUID
    purpose: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,127}$")
    expected_version: int = Field(ge=0)


class PromptProgramSummaryResponse(PromptProgramContract):
    id: UUID
    project_id: UUID
    program_kind: ProgramKindValue
    purpose: str
    owner_id: UUID


class PromptReleaseStateResponse(PromptProgramContract):
    id: UUID
    version: int
    status: ReleaseStatusValue
    acted_by: UUID
    acted_at: datetime
    evidence_ref: str | None


class PromptProgramReleaseResponse(PromptProgramContract):
    id: UUID
    project_id: UUID
    program_id: UUID
    program_kind: ProgramKindValue
    purpose: str
    version: int
    owner_id: UUID
    release_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    system_template_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    user_template_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    variable_schema_version: str
    input_schema_version: str
    output_schema_version: str
    output_schema_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    application_output_schema_version: str
    application_output_schema_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_policy_version: str
    model_policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    test_set_id: UUID
    test_set_version: int
    test_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    compiler_version: str
    state: PromptReleaseStateResponse


class CreatedPromptProgramResponse(PromptProgramContract):
    program: PromptProgramSummaryResponse
    release: PromptProgramReleaseResponse
    replayed: bool


class CreatedPromptProgramReleaseResponse(PromptProgramContract):
    release: PromptProgramReleaseResponse
    replayed: bool


class PromptProgramPage(PromptProgramContract):
    items: list[PromptProgramSummaryResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class PromptProgramReleasePage(PromptProgramContract):
    items: list[PromptProgramReleaseResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class PromptTestEvidenceResponse(PromptProgramContract):
    id: UUID
    test_set_id: UUID
    test_set_version: int
    evidence_ref: str
    output_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    tested_by: UUID
    tested_at: datetime


class TestedPromptProgramResponse(PromptProgramContract):
    release: PromptProgramReleaseResponse
    evidence: PromptTestEvidenceResponse
    replayed: bool


class PromptTestJobResponse(PromptProgramContract):
    job_id: UUID
    project_id: UUID
    release_id: UUID
    release_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    test_set_id: UUID
    test_set_version: int = Field(ge=1)
    test_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal[
        "queued",
        "running",
        "finalizing",
        "retry_wait",
        "succeeded",
        "failed",
        "dead_lettered",
        "cancelled",
    ]
    replayed: bool


class TransitionedPromptProgramResponse(PromptProgramContract):
    release: PromptProgramReleaseResponse
    admitted_test_evidence_hash: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    replayed: bool


class PromptProgramDiffResponse(PromptProgramContract):
    base_release_id: UUID
    base_release_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_release_id: UUID
    candidate_release_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    changed_fields: list[str]
    fixed_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_system_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_system_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_user_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_user_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    replayed: bool


class PromptProgramBindingResponse(PromptProgramContract):
    id: UUID
    project_id: UUID
    purpose: str
    program_kind: ProgramKindValue
    program_id: UUID
    release_id: UUID
    release_version: int
    release_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_state_id: UUID
    binding_version: int
    bound_by: UUID
    bound_at: datetime
    replayed: bool


class PromptProgramBindingOptionResponse(PromptProgramContract):
    id: UUID
    project_id: UUID
    purpose: str
    program_kind: ProgramKindValue
    program_id: UUID
    release_id: UUID
    release_version: int = Field(ge=1)
    release_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_state_id: UUID
    binding_version: int = Field(ge=1)
    bound_by: UUID
    bound_at: datetime


class PromptProgramBindingOptionPage(PromptProgramContract):
    items: list[PromptProgramBindingOptionResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
