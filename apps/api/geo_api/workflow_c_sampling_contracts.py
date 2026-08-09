"""Strict Internal API contracts for the non-B Sampling Core vertical."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


SamplingCaptureMethod = Literal[
    "provider_api",
    "proxy_grounded_api",
    "manual_ui",
    "automated_ui",
]
SamplingLocationControl = Literal[
    "country",
    "market_language",
    "language_only",
    "not_controlled",
]
EvidenceStatusValue = Literal["complete", "ineligible"]
AdmissionPolicyStatusValue = Literal[
    "draft",
    "pending_review",
    "approved",
    "assessed_no_basis",
    "revoked",
]
AuthorizationStateValue = Literal[
    "approved",
    "not_assessed",
    "assessed_no_basis",
    "expired",
    "revoked",
]


class SamplingQuestionContract(StrictModel):
    question_id: str = Field(min_length=1, max_length=200)
    question_version: str = Field(min_length=1, max_length=200)
    text_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class SamplingSourceStratumContract(StrictModel):
    platform: str = Field(min_length=1, max_length=200)
    surface: str = Field(min_length=1, max_length=200)
    configured_model: str = Field(min_length=1, max_length=200)
    reported_model: str = Field(min_length=1, max_length=200)
    capture_method: SamplingCaptureMethod
    adapter_release: str = Field(min_length=1, max_length=200)
    locale: str = Field(min_length=1, max_length=100)
    region: str = Field(min_length=1, max_length=100)
    language: str = Field(min_length=1, max_length=100)
    search_mode: str = Field(min_length=1, max_length=100)
    account_cohort: str = Field(min_length=1, max_length=200)
    egress_policy_category: str = Field(min_length=1, max_length=200)
    location_control: SamplingLocationControl
    location_evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    requested_country: str | None = Field(default=None, max_length=100)
    requested_region: str | None = Field(default=None, max_length=100)
    requested_locale: str = Field(min_length=1, max_length=100)
    requested_language: str = Field(min_length=1, max_length=100)
    effective_country: str | None = Field(default=None, max_length=100)
    effective_region: str | None = Field(default=None, max_length=100)
    effective_locale: str | None = Field(default=None, max_length=100)
    effective_language: str | None = Field(default=None, max_length=100)
    stratum_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class CreateAdmissionPolicyRequest(StrictModel):
    supersedes_policy_id: UUID | None = None
    runtime_authorization_option_key: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=200)
    valid_until: datetime
    quota_remaining: int = Field(ge=1, le=10_000_000)
    daily_task_limit: int = Field(ge=1, le=1_000_000)
    minimum_request_interval_seconds: int = Field(ge=0, le=86_400)
    max_concurrency: int = Field(ge=1, le=10_000)


class AdmissionPolicySubmitRequest(StrictModel):
    expected_version: int = Field(ge=1)


class AdmissionPolicyDecisionRequest(AdmissionPolicySubmitRequest):
    reason: str = Field(min_length=1, max_length=1000)


class AdmissionPolicyResponse(StrictModel):
    id: UUID
    project_id: UUID
    revision: int
    supersedes_policy_id: UUID | None
    platform: str
    capture_method: SamplingCaptureMethod
    adapter_release: str
    location_control: SamplingLocationControl
    location_evidence_hash: str
    authorization_reference: str
    authorized_purposes: list[str]
    valid_until: datetime
    quota_remaining: int
    daily_task_limit: int
    minimum_request_interval_seconds: int
    max_concurrency: int
    next_allowed_at: datetime
    status: AdmissionPolicyStatusValue
    effective_authorization_state: AuthorizationStateValue
    definition_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_version: str
    created_by: str
    created_at: datetime
    submitted_by: str | None
    submitted_at: datetime | None
    decided_by: str | None
    decided_at: datetime | None
    decision_reason: str | None
    revoked_by: str | None
    revoked_at: datetime | None
    revocation_reason: str | None
    aggregate_version: int


class AdmissionPolicyPageResponse(StrictModel):
    items: list[AdmissionPolicyResponse]
    total: int


class AdmissionRuntimeOptionResponse(StrictModel):
    option_key: str
    display_name: str
    platform: str
    capture_method: SamplingCaptureMethod
    adapter_release: str
    location_control: SamplingLocationControl
    location_evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    authorization_reference: str
    allowed_purposes: list[str]


class AdmissionRuntimeOptionPageResponse(StrictModel):
    items: list[AdmissionRuntimeOptionResponse]
    total: int


class CreateSamplingSuiteRequest(StrictModel):
    suite_input_option_key: str = Field(min_length=1, max_length=200)
    # A production Suite is a ten-question pilot selected from the frozen
    # QuestionSet input.  Keep this optional only for legacy fixtures whose
    # frozen input contains fewer than ten questions; production inputs with
    # more than ten questions must provide the explicit selection.
    question_set_item_ids: list[str] | None = Field(
        default=None,
        min_length=10,
        max_length=10,
    )
    repetitions: int = Field(ge=1, le=100)
    statistics_method_version: str = Field(min_length=1, max_length=200)
    max_planned_tasks: int = Field(ge=1, le=100_000)
    max_daily_tasks: int = Field(ge=1, le=100_000)
    minimum_request_interval_seconds: int = Field(ge=0, le=86_400)
    max_concurrency: int = Field(ge=1, le=1000)


class SamplingSuiteResponse(StrictModel):
    id: UUID
    project_id: UUID
    question_set_id: UUID
    question_set_version: str
    question_set_hash: str
    adapter_release_id: UUID
    adapter_release_hash: str
    model_release_id: UUID
    model_release_hash: str
    route_policy_id: UUID
    route_policy_hash: str
    runtime_manifest_id: UUID
    runtime_manifest_hash: str
    runtime_option_id: UUID
    runtime_option_hash: str
    admission_policy_id: UUID
    admission_policy_hash: str
    questions: list[SamplingQuestionContract]
    question_set_item_ids: list[str]
    source_stratum: SamplingSourceStratumContract
    repetitions: int
    statistics_method_version: str
    max_planned_tasks: int
    max_daily_tasks: int
    minimum_request_interval_seconds: int
    max_concurrency: int
    minimum_valid_repeats: int
    planned_task_count: int
    frozen_by: str
    frozen_at: datetime
    suite_hash: str


class SamplingSuitePageResponse(StrictModel):
    items: list[SamplingSuiteResponse]
    total: int


class SamplingSuiteInputOptionResponse(StrictModel):
    option_key: str
    display_name: str
    question_set_id: UUID
    question_set_version: str
    question_set_hash: str
    question_count: int
    question_set_item_ids: list[str]
    adapter_release_id: UUID
    adapter_release_hash: str
    model_release_id: UUID
    model_release_hash: str
    route_policy_id: UUID
    route_policy_hash: str
    runtime_manifest_id: UUID
    runtime_manifest_hash: str
    runtime_option_id: UUID
    runtime_option_hash: str
    admission_policy_id: UUID
    admission_policy_hash: str
    source_stratum: SamplingSourceStratumContract


class SamplingSuiteInputOptionPageResponse(StrictModel):
    items: list[SamplingSuiteInputOptionResponse]
    total: int


class StartSamplingRunRequest(StrictModel):
    purpose: str = Field(min_length=1, max_length=200)
    requested_not_before: datetime


class SamplingRunResponse(StrictModel):
    id: UUID
    project_id: UUID
    suite_id: UUID
    suite_hash: str
    admission_policy_id: UUID
    admission_policy_hash: str
    admission_grant_hash: str
    purpose: str
    authorization_reference: str
    authorization_valid_until: datetime
    admission_policy_version: str
    reserved_task_count: int
    planned_task_keys: list[str]
    status: Literal[
        "planned",
        "running",
        "cancel_requested",
        "completed",
        "cancelled",
        "failed",
    ]
    admitted_not_before: datetime
    created_at: datetime
    version: int


class SamplingRunPageResponse(StrictModel):
    items: list[SamplingRunResponse]
    total: int


class SamplingTaskResponse(StrictModel):
    id: UUID
    project_id: UUID
    run_id: UUID
    task_key: str
    question_id: str
    question_version: str
    repetition: int
    capture_method: SamplingCaptureMethod
    source_stratum_hash: str
    status: Literal[
        "planned",
        "queued",
        "running",
        "finalizing",
        "retry_ready",
        "succeeded",
        "failed",
        "cancel_requested",
        "cancelled",
    ]
    attempt_ids: list[UUID]
    max_attempts: int
    version: int


class EnqueueSamplingAttemptRequest(StrictModel):
    expected_task_version: int = Field(ge=1)
    requested_not_before: datetime


class EnqueueReadySamplingRunRequest(StrictModel):
    requested_not_before: datetime
    max_tasks: int = Field(default=100_000, ge=1, le=100_000)


class EnqueueReadySamplingRunResponse(StrictModel):
    run_id: UUID
    planned_task_count: int
    enqueued_count: int
    replayed_count: int
    skipped_count: int
    attempt_ids: list[UUID]
    first_not_before: datetime | None
    last_not_before: datetime | None
    replayed: bool


class CancelSamplingRunResponse(StrictModel):
    run_id: UUID
    cancel_requested_count: int
    replayed_count: int
    skipped_count: int
    attempt_ids: list[UUID]
    replayed: bool


class SubmitManualEvidenceRequest(StrictModel):
    expected_task_version: int = Field(ge=1)
    content_base64: SecretStr = Field(min_length=1, max_length=14_000_000)
    content_type: Literal[
        "application/json",
        "image/jpeg",
        "image/png",
        "image/webp",
        "text/html",
        "text/plain",
    ]
    governance_policy_option_key: Literal["manual-evidence-redaction-v1"]
    evidence_kind: Literal["screenshot", "html_export", "transcript_export"]
    pre_redacted_attestation: bool = False
    device: Literal["desktop", "mobile", "tablet"]
    locale: str = Field(min_length=1, max_length=100)
    captured_at: datetime
    surface_parser_release_id: UUID | None = None


class ReviewManualEvidenceRequest(StrictModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class SurfaceParserReleaseResponse(StrictModel):
    id: UUID
    release_key: str
    release_version: str
    release_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    platform: str
    surface: Literal[
        "google_ai_overviews",
        "google_ai_mode",
        "bing_copilot",
    ]
    artifact_schema_version: str
    parser_engine_version: str
    status: Literal["candidate", "fixture_ready"]
    automated_capture_eligible: Literal[False]
    evidence_scope: Literal["fixture_or_manual_non_live"]


class SurfaceParserReleasePageResponse(StrictModel):
    items: list[SurfaceParserReleaseResponse]
    total: int


class SurfaceParseSummaryResponse(StrictModel):
    parser_release_id: UUID
    parser_release_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    platform: str
    surface: Literal[
        "google_ai_overviews",
        "google_ai_mode",
        "bing_copilot",
    ]
    capture_kind: Literal["manual_ui"]
    outcome: Literal[
        "captured",
        "surface_not_present",
        "consent_required",
        "login_required",
        "access_blocked",
        "geo_mismatch",
        "egress_changed",
        "parser_failed",
        "timeout",
    ]
    block_reason: Literal[
        "consent",
        "login",
        "captcha",
        "rate_limit",
        "ban",
        "geo_mismatch",
        "egress_changed",
        "timeout",
        "selector_drift",
        "page_incomplete",
        "invalid_artifact",
        "wrong_surface",
    ] | None
    content_eligible: bool
    automated_capture: Literal[False]
    live_capture_eligible: Literal[False]
    answer_text_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    answer_character_count: int = Field(ge=0)
    citation_count: int = Field(ge=0)
    citation_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_result_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    summary_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ManualEvidenceImportResponse(StrictModel):
    id: UUID
    project_id: UUID
    run_id: UUID
    task_id: UUID
    task_key: str
    attempt_id: UUID
    expected_task_version: int
    artifact_manifest_id: UUID
    artifact_manifest_hash: str
    artifact_content_hash: str
    governance_policy_hash: str
    capture_session_id: UUID
    evidence_kind: Literal["screenshot", "html_export", "transcript_export"]
    device: Literal["desktop", "mobile", "tablet"]
    locale: str
    captured_at: datetime
    submitted_by: str
    submitted_at: datetime
    status: Literal["pending_review", "approved", "rejected", "committed"]
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_reason: str | None
    committed_at: datetime | None
    aggregate_version: int
    definition_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    surface_parse: SurfaceParseSummaryResponse | None


class ManualEvidenceImportPageResponse(StrictModel):
    items: list[ManualEvidenceImportResponse]
    total: int


class ObservationEvidenceSummaryResponse(StrictModel):
    raw_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    derived_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    derived_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    governance_policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    derived_summary: str = Field(min_length=1, max_length=280)
    evidence_locator: str = Field(min_length=1, max_length=500)
    provider_response_id: str | None = Field(default=None, max_length=500)
    egress_verification_id: str | None = Field(default=None, max_length=500)
    result_parameters_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class CancelSamplingAttemptRequest(StrictModel):
    expected_task_version: int = Field(ge=1)
    expected_attempt_version: int = Field(ge=1)


class SamplingActualLocationResponse(StrictModel):
    location_control: SamplingLocationControl
    location_evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    requested_country: str | None
    requested_region: str | None
    requested_locale: str
    requested_language: str
    effective_country: str | None
    effective_region: str | None
    effective_locale: str | None
    effective_language: str | None


class SamplingAttemptResponse(StrictModel):
    id: UUID
    project_id: UUID
    run_id: UUID
    task_id: UUID
    task_key: str
    ordinal: int
    job_status: str
    record_version: int
    attempt_count: int
    provider_response_id: str | None
    egress_verification_id: str | None
    raw_artifact_hash: str | None
    actual_location: SamplingActualLocationResponse | None
    terminal_status: str | None


class SamplingObservationResponse(StrictModel):
    id: UUID
    project_id: UUID
    run_id: UUID
    task_id: UUID
    task_key: str
    winning_attempt_id: UUID
    source_stratum_hash: str
    actual_location: SamplingActualLocationResponse | None
    evidence_status: EvidenceStatusValue
    ineligible_reasons: list[str]
    evidence: ObservationEvidenceSummaryResponse
    observed_at: datetime
    observation_hash: str


class SamplingAssessmentResponse(StrictModel):
    run_id: UUID
    planned_task_count: int
    valid_task_count: int
    invalid_task_count: int
    missing_task_count: int
    valid_completion_ratio: str
    sufficient_question_count: int
    question_count: int
    status: Literal["complete", "insufficient_evidence"]
    denominator_hash: str


class SamplingRunDetailResponse(StrictModel):
    run: SamplingRunResponse
    suite: SamplingSuiteResponse
    tasks: list[SamplingTaskResponse]
    attempts: list[SamplingAttemptResponse]
    observations: list[SamplingObservationResponse]
    assessment: SamplingAssessmentResponse
