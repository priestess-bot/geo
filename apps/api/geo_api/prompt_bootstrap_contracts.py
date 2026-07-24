"""Strict Internal API contracts for governed Prompt bootstrap operations."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from geo_api.prompt_program_contracts import (
    PromptProgramReleaseResponse,
    PromptProgramSummaryResponse,
)


BootstrapKindValue = Literal[
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
]


class PromptBootstrapContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BootstrapRubricCriterionResponse(PromptBootstrapContract):
    code: str
    description: str
    weight: int = Field(ge=1, le=100)
    blocking: bool


class BootstrapFixturePreviewResponse(PromptBootstrapContract):
    fixture_id: str
    scenario: Literal[
        "positive",
        "negative",
        "prompt_injection",
        "subject_mixup",
        "fabricated_citation",
    ]
    description: str
    input_value: dict[str, object]


class BootstrapKindPreviewResponse(PromptBootstrapContract):
    program_kind: BootstrapKindValue
    purpose: str
    spec_version: str
    spec_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    test_set_id: UUID
    test_set_version: int = Field(ge=1)
    test_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    variable_schema_version: str
    variable_schema: dict[str, object]
    input_schema_version: str
    input_schema: dict[str, object]
    output_schema_version: str
    output_schema: dict[str, object]
    output_schema_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    application_output_schema_version: str
    application_output_schema: dict[str, object]
    application_output_schema_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_policy_version: str
    model_policy: dict[str, object]
    model_policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    application_rules: list[str]
    rubric: list[BootstrapRubricCriterionResponse]
    minimum_score: int = Field(ge=1, le=100)
    fixtures: list[BootstrapFixturePreviewResponse] = Field(min_length=5, max_length=5)


class BootstrapCatalogPreviewResponse(PromptBootstrapContract):
    catalog_version: str
    catalog_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    items: list[BootstrapKindPreviewResponse] = Field(min_length=10, max_length=10)
    external_model_calls: Literal[0] = 0
    automatic_transitions: Literal[False] = False
    batch_atomicity: Literal["per_item"] = "per_item"
    action_boundary: Literal["draft_only_manual_test"] = "draft_only_manual_test"


class BootstrapEvaluationRequest(PromptBootstrapContract):
    program_kind: BootstrapKindValue
    catalog_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    spec_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    test_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    outputs: dict[str, dict[str, object]] = Field(min_length=5, max_length=5)


class BootstrapCaseEvaluationResponse(PromptBootstrapContract):
    fixture_id: str
    scenario: Literal[
        "positive",
        "negative",
        "prompt_injection",
        "subject_mixup",
        "fabricated_citation",
    ]
    output_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    score: int = Field(ge=0, le=100)
    passed: bool
    error_code: str | None
    failed_criteria: list[str]
    blocking_failure: bool


class BootstrapEvaluationResponse(PromptBootstrapContract):
    catalog_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    program_kind: BootstrapKindValue
    spec_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    test_set_id: UUID
    test_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    rubric: list[BootstrapRubricCriterionResponse]
    minimum_score: int = Field(ge=1, le=100)
    case_results: list[BootstrapCaseEvaluationResponse] = Field(min_length=5, max_length=5)
    score: float = Field(ge=0, le=100)
    passed: bool
    result_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    external_model_calls: Literal[0] = 0
    automatic_transitions: Literal[False] = False


class BootstrapCreateDraftsRequest(PromptBootstrapContract):
    catalog_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class BootstrapDraftFailureResponse(PromptBootstrapContract):
    code: Literal[
        "idempotency_conflict",
        "version_conflict",
        "persistence_unavailable",
        "forbidden",
        "not_found",
        "rule_violation",
        "application_unavailable",
    ]
    detail: str
    retryable: bool


class BootstrapDraftItemResponse(PromptBootstrapContract):
    program_kind: BootstrapKindValue
    spec_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    test_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["created", "replayed", "failed"]
    program: PromptProgramSummaryResponse | None
    release: PromptProgramReleaseResponse | None
    failure: BootstrapDraftFailureResponse | None


class BootstrapCreateDraftsResponse(PromptBootstrapContract):
    catalog_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    completion_status: Literal["completed", "partial_failure", "failed"]
    items: list[BootstrapDraftItemResponse] = Field(min_length=10, max_length=10)
    created_count: int = Field(ge=0, le=10)
    replayed_count: int = Field(ge=0, le=10)
    failed_count: int = Field(ge=0, le=10)
    atomic: Literal[False] = False
    safe_to_retry: Literal[True] = True
    action_boundary: Literal[
        "draft_only_no_approval_freeze_binding"
    ] = "draft_only_no_approval_freeze_binding"
