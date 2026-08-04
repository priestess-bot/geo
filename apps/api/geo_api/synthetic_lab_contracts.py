"""Strict, redacted Internal API contracts for the Synthetic Lab."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Generic, Literal, TypeVar
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Channel = Literal[
    "owned_site",
    "amazon",
    "youtube",
    "tiktok",
    "instagram",
    "productreview",
    "reddit",
    "ozbargain",
    "quora",
]
AuthorizationState = Literal[
    "not_assessed", "assessed_no_basis", "approved", "expired", "revoked"
]
JobKind = Literal[
    "style_collection",
    "style_profile_build",
    "candidate_generation",
    "candidate_revision",
    "corpus_finalize",
    "offline_experiment",
]
SyntheticJobStatus = Literal[
    "queued",
    "running",
    "finalizing",
    "retry_wait",
    "succeeded",
    "failed",
    "dead_lettered",
    "cancelled",
]
AuthorizationPurpose = Literal["style_collection"]
_ItemT = TypeVar("_ItemT")


class SyntheticContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SyntheticBoundaryResponse(SyntheticContract):
    synthetic: Literal[True] = True
    test_only: Literal[True] = True
    publication_eligible: Literal[False] = False


class SyntheticMutationResponse(SyntheticBoundaryResponse):
    replayed: bool = False


class SyntheticPageResponse(SyntheticBoundaryResponse, Generic[_ItemT]):
    items: list[_ItemT]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class DecideAuthorizationRequest(SyntheticContract):
    expected_version: int = Field(ge=0)
    decision: Literal["approved", "assessed_no_basis"]
    evidence_reference: str | None = Field(default=None, min_length=1, max_length=2000)
    allowed_purposes: list[AuthorizationPurpose] = Field(default_factory=list, max_length=1)
    max_requests_per_period: int | None = Field(default=None, ge=1)
    period_seconds: int | None = Field(default=None, ge=1)
    max_concurrency: int | None = Field(default=None, ge=1)
    expires_at: datetime | None = None
    decision_reason: str = Field(min_length=1, max_length=2000)


class CreateAuthorizationRequest(SyntheticContract):
    expected_version: Literal[0]
    channel: Channel
    adapter_release: str = Field(min_length=1, max_length=200)


class RevokeAuthorizationRequest(SyntheticContract):
    expected_version: int = Field(ge=1)
    decision_reason: str = Field(min_length=1, max_length=2000)


class ReassessAuthorizationRequest(SyntheticContract):
    expected_version: int = Field(ge=1)
    opened_at: datetime
    reassessment_reason: str = Field(min_length=1, max_length=2000)


class CreateStyleSourceRequest(SyntheticContract):
    expected_version: int = Field(ge=0)
    channel: Channel
    access_mode: Literal["public", "authenticated", "manual_import"]
    locale: Literal["en-AU"] = "en-AU"
    source_url: str | None = Field(default=None, min_length=9, max_length=2048)
    source_label: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("source_url")
    @classmethod
    def safe_source_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Style Source URL must be credential-free HTTPS")
        return value

    @model_validator(mode="after")
    def source_mode_matches_url(self) -> "CreateStyleSourceRequest":
        manual = self.access_mode == "manual_import"
        if manual != (self.source_label is not None) or manual == (self.source_url is not None):
            raise ValueError("manual sources require a label; live sources require an HTTPS URL")
        return self


class EnqueueStyleCollectionRequest(SyntheticContract):
    style_source_revision_id: UUID
    adapter_release: str = Field(min_length=1, max_length=200)
    login_secret_reference_id: UUID | None = None


class CreateManualImportPreviewRequest(SyntheticContract):
    expected_version: Literal[0]
    style_source_revision_id: UUID
    import_format: Literal["text", "csv", "jsonl"]
    filename: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1, max_length=7_100_000)
    default_source_rights: Literal[
        "owned", "licensed", "public_reference", "authorized_manual_capture"
    ]
    rights_evidence_reference: str = Field(min_length=1, max_length=2000)

    @field_validator("filename")
    @classmethod
    def safe_filename(cls, value: str) -> str:
        stripped = value.strip()
        if stripped in {".", ".."} or "/" in stripped or "\\" in stripped or "\x00" in stripped:
            raise ValueError("filename must not contain a path")
        return stripped

    @field_validator("content_base64")
    @classmethod
    def strict_base64_shape(cls, value: str) -> str:
        if any(character.isspace() for character in value):
            raise ValueError("base64 upload must not contain whitespace")
        return value


class ApproveManualImportPreviewRequest(SyntheticContract):
    expected_version: Literal[1]
    selected_row_numbers: list[int] = Field(min_length=1, max_length=2000)
    au_english_verified: Literal[True]
    anonymization_verified: Literal[True]

    @field_validator("selected_row_numbers")
    @classmethod
    def unique_rows(cls, values: list[int]) -> list[int]:
        if any(value < 1 for value in values) or len(values) != len(set(values)):
            raise ValueError("selected rows must be unique positive integers")
        return values


class RejectManualImportPreviewRequest(SyntheticContract):
    expected_version: Literal[1]
    reason: str = Field(min_length=1, max_length=2000)


class CreateStyleProfileRequest(SyntheticContract):
    expected_version: Literal[0]
    channel: Channel
    locale: Literal["en-AU"] = "en-AU"
    prompt_binding_id: UUID
    approved_sample_ids: list[UUID] = Field(min_length=200, max_length=10_000)

    @field_validator("approved_sample_ids")
    @classmethod
    def unique_profile_samples(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("Style Profile sample IDs must be unique")
        return values


class FreezeStyleProfileRequest(SyntheticContract):
    expected_version: int = Field(ge=1)
    approved_sample_ids: list[UUID] = Field(default_factory=list, max_length=10_000)

    @field_validator("approved_sample_ids")
    @classmethod
    def legacy_samples_are_valid(cls, values: list[UUID]) -> list[UUID]:
        if values and (len(values) < 200 or len(values) != len(set(values))):
            raise ValueError("legacy Style Profile sample manifest is invalid")
        return values


class SubmitStyleProfileRequest(SyntheticContract):
    expected_version: int = Field(ge=1)


class DecideStyleProfileRequest(SyntheticContract):
    expected_version: int = Field(ge=1)
    decision: Literal["approve", "reject"]


class CreateReviewSuiteRequest(SyntheticContract):
    expected_version: Literal[0]
    channel: Channel
    suite_name: str = Field(min_length=1, max_length=200)


class CreateReviewCaseRequest(SyntheticContract):
    expected_version: int = Field(ge=0)
    case_key: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{1,200}$")
    ordinal: int = Field(ge=1)
    mode: Literal["autonomous_scenario", "guided_scenario"]
    channel: Channel
    persona: str = Field(min_length=1, max_length=4000)
    use_case: str = Field(min_length=1, max_length=4000)
    subject: str = Field(min_length=1, max_length=1000)
    question_set_version_id: UUID
    fact_snapshot_id: UUID
    profile_version_id: UUID
    competitor_scenario: bool
    expected_risks: list[str] = Field(default_factory=list, max_length=100)
    creative_reference: str | None = Field(default=None, max_length=4000)


class FreezeReviewSuiteRequest(SyntheticContract):
    expected_version: int = Field(ge=1)


class SyntheticResourceOptionResponse(SyntheticContract):
    id: UUID
    label: str
    kind: Literal[
        "sample",
        "prompt_binding",
        "question_set",
        "fact_snapshot",
        "profile",
        "review_job",
        "corpus_candidate",
        "corpus_approved",
    ]
    status: str
    channel: Channel | None = None


class SyntheticResourceInventoryResponse(SyntheticBoundaryResponse):
    samples: list[SyntheticResourceOptionResponse]
    prompt_bindings: list[SyntheticResourceOptionResponse]
    question_sets: list[SyntheticResourceOptionResponse]
    fact_snapshots: list[SyntheticResourceOptionResponse]
    profiles: list[SyntheticResourceOptionResponse]
    review_jobs: list[SyntheticResourceOptionResponse]
    candidate_corpora: list[SyntheticResourceOptionResponse]
    approved_corpora: list[SyntheticResourceOptionResponse]


class FrozenRuntimeInputRequest(SyntheticContract):
    fact_snapshot_id: UUID
    fact_snapshot_hash: Sha256
    profile_version_id: UUID
    profile_hash: Sha256
    prompt_release_id: UUID
    prompt_release_hash: Sha256


class EnqueueStyleProfileBuildRequest(SyntheticContract):
    profile_version_id: UUID
    fact_snapshot_id: UUID
    approved_sample_ids: list[UUID] = Field(default_factory=list, max_length=10_000)
    runtime_selection_id: UUID
    recovery_of_attempt_id: UUID | None = None
    dify_reconciliation_token: Sha256 | None = None

    @field_validator("approved_sample_ids")
    @classmethod
    def unique_profile_samples(cls, values: list[UUID]) -> list[UUID]:
        if values and len(values) < 200:
            raise ValueError("legacy Style Profile sample manifest requires at least 200 IDs")
        if len(values) != len(set(values)):
            raise ValueError("approved Style Profile sample IDs must be unique")
        return values

    @model_validator(mode="after")
    def complete_dify_recovery_identity(self) -> "EnqueueStyleProfileBuildRequest":
        if (self.recovery_of_attempt_id is None) != (
            self.dify_reconciliation_token is None
        ):
            raise ValueError(
                "Dify recovery requires both the old attempt ID and reconciliation token"
            )
        return self


class EnqueueReviewCaseRunRequest(SyntheticContract):
    suite_version_id: UUID
    case_id: UUID
    runtime_selection_id: UUID
    style_pass_threshold: float = Field(default=4.2, ge=0, le=5)


class EnqueueCorpusFinalizeRequest(SyntheticContract):
    role: Literal["new_candidate_corpus", "current_approved_corpus"]
    review_job_ids: list[UUID] = Field(default_factory=list, max_length=5000)
    source_corpus_job_id: UUID | None = None

    @model_validator(mode="after")
    def exact_source_shape(self) -> "EnqueueCorpusFinalizeRequest":
        if len(self.review_job_ids) != len(set(self.review_job_ids)):
            raise ValueError("Corpus Review Job selectors must be unique")
        candidate = self.role == "new_candidate_corpus"
        if candidate != bool(self.review_job_ids) or candidate == (
            self.source_corpus_job_id is not None
        ):
            raise ValueError(
                "candidate Corpus requires Review Jobs; approved Corpus requires one source Corpus"
            )
        return self


class EnqueueOfflineExperimentRequest(SyntheticContract):
    question_set_id: UUID
    current_corpus_job_id: UUID
    candidate_corpus_job_id: UUID
    runtime_selection_id: UUID
    minimum_valid_pair_ratio: float = Field(default=0.8, gt=0, le=1)

    @model_validator(mode="after")
    def distinct_corpora(self) -> "EnqueueOfflineExperimentRequest":
        if self.current_corpus_job_id == self.candidate_corpus_job_id:
            raise ValueError("Offline Experiment Corpus selectors must be distinct")
        return self


class EnqueueSyntheticJobRequest(SyntheticContract):
    expected_version: int = Field(ge=0)
    job_id: UUID
    outbox_id: UUID
    resource_id: UUID
    resource_hash: Sha256
    runtime_inputs: FrozenRuntimeInputRequest


class CancelSyntheticJobRequest(SyntheticContract):
    expected_version: int = Field(ge=1)


class FinalizeSyntheticJobRequest(SyntheticContract):
    expected_version: int = Field(ge=1)
    lease_id: UUID
    fencing_token: int = Field(ge=1)
    completed_at: datetime
    result_artifact_id: UUID
    result_hash: Sha256


class AuthorizationResponse(SyntheticMutationResponse):
    id: UUID
    project_id: UUID
    channel: Channel
    adapter_release: str
    version_number: int = Field(ge=1)
    state: AuthorizationState
    effective_state: AuthorizationState
    evidence_reference_hash: Sha256 | None
    allowed_purposes: list[str]
    max_requests_per_period: int | None
    period_seconds: int | None
    max_concurrency: int | None
    expires_at: datetime | None
    record_hash: Sha256


class StyleSourceResponse(SyntheticMutationResponse):
    id: UUID
    project_id: UUID
    source_id: UUID
    revision_number: int = Field(ge=1)
    channel: Channel
    access_mode: Literal["public", "authenticated", "manual_import"]
    locale: Literal["en-AU"]
    source_locator_hash: Sha256
    status: Literal["draft", "active", "suspended", "retired"]


class ManualImportPreviewRowResponse(SyntheticContract):
    row_number: int = Field(ge=1)
    redacted_text: str = Field(min_length=1, max_length=100_000)
    source_rights: Literal[
        "owned", "licensed", "public_reference", "authorized_manual_capture"
    ]
    detected_codes: list[str]
    blocking_codes: list[str]
    disposition: Literal["ready_for_review", "blocked", "duplicate"]
    selectable: bool


class ManualImportPreviewSummaryResponse(SyntheticMutationResponse):
    id: UUID
    project_id: UUID
    style_source_revision_id: UUID
    channel: Channel
    filename: str
    import_format: Literal["text", "csv", "jsonl"]
    status: Literal["pending", "approved", "rejected", "expired"]
    version: int = Field(ge=1)
    submitted_by: UUID
    submitted_at: datetime
    expires_at: datetime
    row_count: int = Field(ge=1)
    selectable_count: int = Field(ge=0)
    blocked_count: int = Field(ge=0)
    preview_manifest_hash: Sha256


class ManualImportPreviewResponse(ManualImportPreviewSummaryResponse):
    rows: list[ManualImportPreviewRowResponse]


class ImportedSampleOptionResponse(SyntheticContract):
    id: UUID
    channel: Channel
    source_rights: Literal[
        "owned", "licensed", "public_reference", "authorized_manual_capture"
    ]
    short_example_eligible: bool
    created_at: datetime
    display_label: str


class ManualImportRowErrorResponse(SyntheticContract):
    row_number: int = Field(ge=1)
    code: str
    message: str
    evidence_hash: Sha256


class ManualSampleImportResponse(SyntheticMutationResponse):
    id: UUID
    project_id: UUID
    request_id: UUID
    channel: Channel
    locale: Literal["en-AU"]
    row_count: int = Field(ge=1)
    accepted_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    duplicate_row_count: int = Field(ge=0)
    input_hash: Sha256
    manifest_hash: Sha256
    row_errors: list[ManualImportRowErrorResponse]


class StyleProfileResponse(SyntheticMutationResponse):
    id: UUID
    project_id: UUID
    profile_id: UUID
    version_number: int = Field(ge=1)
    state_version: int = Field(ge=1)
    channel: Channel
    locale: Literal["en-AU"]
    corpus_hash: Sha256
    profile_hash: Sha256
    prompt_release_id: UUID
    prompt_release_hash: Sha256
    approved_sample_count: int = Field(ge=0)
    status: Literal["draft", "in_review", "approved", "frozen", "rejected", "superseded"]
    build_verification_status: Literal["verified", "legacy_unverified"] | None = None
    rebuild_required: bool = False


class ReviewSuiteResponse(SyntheticMutationResponse):
    id: UUID
    project_id: UUID
    suite_id: UUID
    version_number: int = Field(ge=1)
    state_version: int = Field(ge=1)
    channel: Channel
    case_count: int = Field(ge=0)
    case_set_hash: Sha256
    status: Literal["draft", "frozen", "retired"]


class ReviewCaseResponse(SyntheticMutationResponse):
    id: UUID
    project_id: UUID
    review_suite_version_id: UUID
    review_suite_version_number: int = Field(ge=1)
    state_version: int = Field(ge=1)
    case_key: str
    ordinal: int = Field(ge=1)
    mode: Literal["autonomous_scenario", "guided_scenario"]
    channel: Channel
    competitor_scenario: bool
    content_hash: Sha256


class SyntheticWarningSummaryResponse(SyntheticContract):
    warning_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    warning_ratio: float = Field(ge=0, le=1)
    by_code: dict[str, int]
    by_channel: dict[str, int]
    by_scenario_mode: dict[str, int]
    by_competitor: dict[str, int]
    by_model: dict[str, int]
    by_question_cluster: dict[str, int]


class SyntheticJobResponse(SyntheticMutationResponse):
    id: UUID
    project_id: UUID
    kind: JobKind
    status: SyntheticJobStatus
    version: int = Field(ge=1)
    input_hash: Sha256
    fencing_generation: int = Field(ge=0)
    cancel_requested: bool
    result_hash: Sha256 | None = None
    warning_summary: SyntheticWarningSummaryResponse | None = None


class StyleCollectionAdmissionResponse(SyntheticBoundaryResponse):
    disposition: Literal["accepted", "b_track", "rejected"]
    reason_code: str
    may_issue_network_request: bool
    job: SyntheticJobResponse | None = None


AuthorizationPageResponse = SyntheticPageResponse[AuthorizationResponse]
StyleSourcePageResponse = SyntheticPageResponse[StyleSourceResponse]
ManualImportPreviewPageResponse = SyntheticPageResponse[ManualImportPreviewSummaryResponse]
ImportedSampleOptionPageResponse = SyntheticPageResponse[ImportedSampleOptionResponse]
StyleProfilePageResponse = SyntheticPageResponse[StyleProfileResponse]
ReviewSuitePageResponse = SyntheticPageResponse[ReviewSuiteResponse]
ReviewCasePageResponse = SyntheticPageResponse[ReviewCaseResponse]
SyntheticJobPageResponse = SyntheticPageResponse[SyntheticJobResponse]
