"""Persistence-neutral contracts for audited model-call execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
import re
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from geo_core.jobs.lifecycle import JobStatus
from geo_core.model_gateway.contracts import (
    ModelCallBudget,
    ModelAudience,
    ModelCaptureMethod,
    ModelGatewayErrorCode,
    ModelGatewayRequest,
    ModelGatewayResult,
    ModelPolicy,
)
from geo_core.model_gateway.location import (
    EffectiveModelLocation,
    RequestedModelLocation,
)
from geo_core.model_gateway.releases import ModelRoute
from geo_core.model_gateway.identity import (
    canonical_json_hash,
    hash_secret_identifier as hash_secret_identifier,
)
from geo_core.model_gateway.prompt_admission import (
    ModelCallAdmissionMode,
    PromptReleaseAdmission,
    validate_attempt_prompt_shape,
    validate_job_prompt_shape,
)
from geo_core.model_gateway.port_validation import (
    require_aware as _require_aware,
    require_data_decision as _require_data_decision,
    require_hash as _require_hash,
    require_provider_secret_handle as _require_provider_secret_handle,
    require_text as _require_text,
    require_uuid as _require_uuid,
)
from geo_core.secrets.models import SecretVersionHandle


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EVIDENCE_REFERENCE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}:[A-Za-z0-9][A-Za-z0-9._:/-]{0,447}$")


class ModelCallPersistenceError(RuntimeError):
    """Base error for atomic model-call persistence operations."""


class ModelCallVersionConflict(ModelCallPersistenceError):
    """Committed state changed after a unit of work read its snapshot."""


class ModelCallIdempotencyConflict(ModelCallPersistenceError):
    """An attempt idempotency key was reused for a different request."""


class ModelCallAttemptKind(StrEnum):
    INITIAL = "initial"
    RETRY = "retry"
    REPAIR = "repair"


class ModelCallTerminalStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ModelCallFailureClass(StrEnum):
    PROVIDER = "provider"
    APPLICATION_STRUCTURED_OUTPUT = "application_structured_output"
    APPLICATION_RESULT_CONTRACT = "application_result_contract"
    MANUAL_RECONCILIATION = "manual_reconciliation"


@dataclass(frozen=True)
class ModelCallJobAdmission:
    project_id: UUID
    job_id: UUID
    job_kind: str
    job_version: int
    admission_mode: ModelCallAdmissionMode
    status: JobStatus
    lease_token: UUID
    fencing_generation: int
    purpose: str
    usage_audience: ModelAudience
    route: ModelRoute
    provider_secret_handle: SecretVersionHandle
    runtime_manifest_id: UUID
    runtime_manifest_hash: str
    runtime_option_id: UUID
    runtime_option_hash: str
    prompt_binding_id: UUID | None
    prompt_release_id: UUID
    prompt_release_hash: str
    prompt_state_id: UUID
    prompt_state_version: int
    prompt_test_set_hash: str | None
    prompt_bundle_hash: str
    output_schema_hash: str
    application_output_schema_hash: str
    policy_version_id: UUID
    policy_version_hash: str
    maximum_paid_calls: int
    maximum_concurrent_calls: int
    raw_artifact_policy_hash: str
    raw_artifact_storage_decision: str
    raw_artifact_cache_decision: str
    raw_artifact_display_decision: str
    raw_artifact_redistribution_decision: str
    raw_artifact_retention_days: int | None
    paid_calls: int = 0
    reserved_calls: int = 0
    budget_version: int = 0
    next_attempt_number: int = 1

    def __post_init__(self) -> None:
        _require_uuid(self.project_id, "model-call Job project")
        _require_uuid(self.job_id, "model-call Job")
        _require_uuid(self.lease_token, "model-call Job lease")
        _require_uuid(self.prompt_release_id, "model-call Prompt Release")
        _require_uuid(self.prompt_state_id, "model-call Prompt state")
        _require_uuid(self.policy_version_id, "model-call policy version")
        _require_uuid(self.runtime_manifest_id, "model-call runtime manifest")
        _require_uuid(self.runtime_option_id, "model-call runtime option")
        _require_text(self.job_kind, "model-call Job kind")
        _require_text(self.purpose, "model-call purpose")
        object.__setattr__(self, "admission_mode", ModelCallAdmissionMode(self.admission_mode))
        object.__setattr__(self, "usage_audience", ModelAudience(self.usage_audience))
        _require_provider_secret_handle(
            self.provider_secret_handle,
            project_id=self.project_id,
            provider=self.route.provider,
        )
        _require_hash(self.prompt_release_hash, "model-call Prompt Release")
        _require_hash(self.runtime_manifest_hash, "model-call runtime manifest")
        _require_hash(self.runtime_option_hash, "model-call runtime option")
        if self.prompt_test_set_hash is not None:
            _require_hash(self.prompt_test_set_hash, "model-call Prompt test set")
        _require_hash(self.prompt_bundle_hash, "model-call prompt bundle")
        _require_hash(self.output_schema_hash, "model-call output schema")
        _require_hash(
            self.application_output_schema_hash,
            "model-call application output schema",
        )
        _require_hash(self.policy_version_hash, "model-call policy version")
        _require_hash(self.raw_artifact_policy_hash, "model-call raw-artifact policy")
        for decision in (
            self.raw_artifact_storage_decision,
            self.raw_artifact_cache_decision,
            self.raw_artifact_display_decision,
            self.raw_artifact_redistribution_decision,
        ):
            _require_data_decision(decision)
        if self.job_version < 1 or self.fencing_generation < 1 or self.prompt_state_version < 1:
            raise ValueError("model-call Job version and fencing generation must be positive")
        validate_job_prompt_shape(
            admission_mode=self.admission_mode,
            binding_id=self.prompt_binding_id,
            test_set_hash=self.prompt_test_set_hash,
            job_kind=self.job_kind,
            purpose=self.purpose,
        )
        if self.maximum_paid_calls < 1 or self.maximum_concurrent_calls < 1:
            raise ValueError("model-call paid and concurrency budgets must be positive")
        if self.raw_artifact_retention_days is not None and self.raw_artifact_retention_days < 0:
            raise ValueError("model-call raw-artifact retention cannot be negative")
        if min(self.paid_calls, self.reserved_calls, self.budget_version) < 0:
            raise ValueError("model-call budget counters cannot be negative")
        if self.paid_calls + self.reserved_calls > self.maximum_paid_calls:
            raise ValueError("model-call budget is overcommitted")
        if self.next_attempt_number < 1:
            raise ValueError("model-call next attempt number must be positive")
        object.__setattr__(self, "status", JobStatus(self.status))

    @property
    def provider_secret_handle_hash(self) -> str:
        return canonical_json_hash(self.provider_secret_handle.as_job_payload())

    @property
    def portable_output_schema_hash(self) -> str:
        """Explicit domain name for the legacy-compatible physical column."""
        return self.output_schema_hash


@dataclass(frozen=True)
class ModelCallAttemptDraft:
    id: UUID
    project_id: UUID
    job_id: UUID
    job_version: int
    admission_mode: ModelCallAdmissionMode
    lease_token: UUID
    fencing_generation: int
    kind: ModelCallAttemptKind
    parent_attempt_id: UUID | None
    idempotency_key_hash: str
    request_hash: str
    input_hash: str
    purpose: str
    usage_audience: ModelAudience
    route: ModelRoute
    provider_secret_handle: SecretVersionHandle
    runtime_manifest_id: UUID
    runtime_manifest_hash: str
    runtime_option_id: UUID
    runtime_option_hash: str
    prompt_binding_id: UUID | None
    prompt_release_id: UUID
    prompt_release_hash: str
    prompt_state_id: UUID
    prompt_state_version: int
    prompt_test_set_hash: str | None
    prompt_test_case_id: UUID | None
    prompt_test_case_hash: str | None
    prompt_bundle_hash: str
    output_schema_hash: str
    application_output_schema_hash: str
    policy_version_id: UUID
    policy_version_hash: str
    raw_artifact_policy_hash: str
    raw_artifact_storage_decision: str
    raw_artifact_cache_decision: str
    raw_artifact_display_decision: str
    raw_artifact_redistribution_decision: str
    raw_artifact_retention_days: int | None
    configured_model: str
    search_mode: str | None
    capture_method: ModelCaptureMethod | None
    requested_location: RequestedModelLocation | None
    expected_effective_location: EffectiveModelLocation | None

    def __post_init__(self) -> None:
        for uuid_value, label in (
            (self.id, "model-call attempt"),
            (self.project_id, "model-call attempt project"),
            (self.job_id, "model-call attempt Job"),
            (self.lease_token, "model-call attempt lease"),
            (self.prompt_release_id, "model-call attempt Prompt Release"),
            (self.prompt_state_id, "model-call attempt Prompt state"),
            (self.policy_version_id, "model-call attempt policy version"),
            (self.runtime_manifest_id, "model-call attempt runtime manifest"),
            (self.runtime_option_id, "model-call attempt runtime option"),
        ):
            _require_uuid(uuid_value, label)
        object.__setattr__(self, "kind", ModelCallAttemptKind(self.kind))
        object.__setattr__(self, "admission_mode", ModelCallAdmissionMode(self.admission_mode))
        if (self.kind is ModelCallAttemptKind.INITIAL) != (self.parent_attempt_id is None):
            raise ValueError("only retry/repair attempts require a parent attempt")
        if self.parent_attempt_id is not None:
            _require_uuid(self.parent_attempt_id, "parent model-call attempt")
        for hash_value, label in (
            (self.idempotency_key_hash, "attempt idempotency key"),
            (self.request_hash, "attempt request"),
            (self.input_hash, "attempt input"),
            (self.prompt_release_hash, "attempt Prompt Release"),
            (self.prompt_bundle_hash, "attempt prompt bundle"),
            (self.output_schema_hash, "attempt output schema"),
            (
                self.application_output_schema_hash,
                "attempt application output schema",
            ),
            (self.policy_version_hash, "attempt policy version"),
            (self.raw_artifact_policy_hash, "attempt raw-artifact policy"),
            (self.runtime_manifest_hash, "attempt runtime manifest"),
            (self.runtime_option_hash, "attempt runtime option"),
        ):
            _require_hash(hash_value, label)
        for optional_hash, label in (
            (self.prompt_test_set_hash, "attempt Prompt test set"),
            (self.prompt_test_case_hash, "attempt Prompt test case"),
        ):
            if optional_hash is not None:
                _require_hash(optional_hash, label)
        _require_text(self.purpose, "attempt purpose")
        object.__setattr__(self, "usage_audience", ModelAudience(self.usage_audience))
        _require_text(self.configured_model, "attempt configured model")
        _require_provider_secret_handle(
            self.provider_secret_handle,
            project_id=self.project_id,
            provider=self.route.provider,
        )
        for decision in (
            self.raw_artifact_storage_decision,
            self.raw_artifact_cache_decision,
            self.raw_artifact_display_decision,
            self.raw_artifact_redistribution_decision,
        ):
            _require_data_decision(decision)
        if self.raw_artifact_retention_days is not None and self.raw_artifact_retention_days < 0:
            raise ValueError("attempt raw-artifact retention cannot be negative")
        if self.job_version < 1 or self.fencing_generation < 1 or self.prompt_state_version < 1:
            raise ValueError("attempt Job version and fencing generation must be positive")
        validate_attempt_prompt_shape(
            admission_mode=self.admission_mode,
            binding_id=self.prompt_binding_id,
            test_set_hash=self.prompt_test_set_hash,
            test_case_id=self.prompt_test_case_id,
            test_case_hash=self.prompt_test_case_hash,
            purpose=self.purpose,
        )
        if (self.requested_location is None) != (
            self.expected_effective_location is None
        ):
            raise ValueError(
                "attempt requested and expected effective location must be paired"
            )

    @property
    def provider_secret_handle_hash(self) -> str:
        return canonical_json_hash(self.provider_secret_handle.as_job_payload())

    @property
    def portable_output_schema_hash(self) -> str:
        """Explicit domain name for the legacy-compatible physical column."""
        return self.output_schema_hash


@dataclass(frozen=True)
class ModelCallAttempt:
    spec: ModelCallAttemptDraft
    attempt_number: int
    reserved_at: datetime

    def __post_init__(self) -> None:
        if self.attempt_number < 1:
            raise ValueError("model-call attempt number must be positive")
        _require_aware(self.reserved_at, "model-call reservation time")


@dataclass(frozen=True)
class StoredModelCallAttempt:
    attempt: ModelCallAttempt
    replayed: bool


@dataclass(frozen=True)
class ModelCallLineage:
    search_mode: str | None
    capture_method: ModelCaptureMethod | None
    citation_count: int
    citation_lineage_hash: str
    search_event_count: int
    search_lineage_hash: str
    usage_details_hash: str
    raw_artifact_reference_hash: str | None
    raw_artifact_policy_hash: str
    raw_artifact_storage_decision: str
    raw_artifact_cache_decision: str
    raw_artifact_display_decision: str
    raw_artifact_redistribution_decision: str
    raw_artifact_retention_days: int | None
    usage_purpose: str
    usage_audience: ModelAudience
    effective_location: EffectiveModelLocation | None

    def __post_init__(self) -> None:
        if self.citation_count < 0 or self.search_event_count < 0:
            raise ValueError("model-call lineage counts cannot be negative")
        for hash_value, label in (
            (self.citation_lineage_hash, "citation lineage"),
            (self.search_lineage_hash, "search lineage"),
            (self.usage_details_hash, "usage details"),
            (self.raw_artifact_policy_hash, "raw-artifact policy"),
        ):
            _require_hash(hash_value, label)
        if self.raw_artifact_reference_hash is not None:
            _require_hash(self.raw_artifact_reference_hash, "raw-artifact reference")
        for decision in (
            self.raw_artifact_storage_decision,
            self.raw_artifact_cache_decision,
            self.raw_artifact_display_decision,
            self.raw_artifact_redistribution_decision,
        ):
            _require_data_decision(decision)
        _require_text(self.usage_purpose, "model-call lineage usage purpose")
        object.__setattr__(self, "usage_audience", ModelAudience(self.usage_audience))
        if self.raw_artifact_retention_days is not None and self.raw_artifact_retention_days < 0:
            raise ValueError("raw-artifact retention cannot be negative")


@dataclass(frozen=True)
class ModelCallTerminalEvent:
    id: UUID
    project_id: UUID
    job_id: UUID
    attempt_id: UUID
    status: ModelCallTerminalStatus
    occurred_at: datetime
    paid_call_count: int
    gateway_call_log_id: UUID | None
    configured_model: str
    provider_reported_model: str | None
    provider_request_id: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: Decimal | None
    finish_reason: str | None
    input_hash: str
    output_hash: str | None
    response_hash: str | None
    lineage: ModelCallLineage
    error_classification: ModelCallFailureClass | None = None
    error_code: ModelGatewayErrorCode | None = None
    error_retryable: bool | None = None
    reconciled_by: UUID | None = None
    reconciliation_evidence_ref: str | None = None

    def __post_init__(self) -> None:
        for uuid_value, label in (
            (self.id, "model-call event"),
            (self.project_id, "model-call event project"),
            (self.job_id, "model-call event Job"),
            (self.attempt_id, "model-call event attempt"),
        ):
            _require_uuid(uuid_value, label)
        status = ModelCallTerminalStatus(self.status)
        object.__setattr__(self, "status", status)
        _require_aware(self.occurred_at, "model-call event time")
        _require_text(self.configured_model, "model-call configured model")
        _require_hash(self.input_hash, "model-call input")
        if self.paid_call_count not in {0, 1}:
            raise ValueError("a model-call attempt can consume zero or one paid call")
        for count_value, label in (
            (self.prompt_tokens, "prompt token count"),
            (self.completion_tokens, "completion token count"),
        ):
            if count_value is not None and count_value < 0:
                raise ValueError(f"{label} cannot be negative")
        if self.cost_usd is not None and self.cost_usd < 0:
            raise ValueError("model-call cost cannot be negative")
        classification = (
            ModelCallFailureClass(self.error_classification)
            if self.error_classification is not None
            else None
        )
        object.__setattr__(self, "error_classification", classification)
        reconciled = self.reconciled_by is not None or self.reconciliation_evidence_ref is not None
        if reconciled:
            if self.reconciled_by is None or self.reconciliation_evidence_ref is None:
                raise ValueError("manual reconciliation requires actor and evidence")
            _require_uuid(self.reconciled_by, "model-call reconciliation actor")
            if _EVIDENCE_REFERENCE.fullmatch(self.reconciliation_evidence_ref) is None:
                raise ValueError("manual reconciliation evidence must be an opaque reference")
        if (classification is ModelCallFailureClass.MANUAL_RECONCILIATION) != reconciled:
            raise ValueError(
                "manual reconciliation classification requires exact actor and evidence pairing"
            )
        if status is ModelCallTerminalStatus.SUCCEEDED:
            if self.output_hash is None or self.response_hash is None:
                raise ValueError("successful model-call events require output and response hashes")
            if self.paid_call_count != 1:
                raise ValueError("successful model-call events require one paid call")
            if self.error_code is not None or self.error_retryable is not None:
                raise ValueError("successful model-call events cannot contain error details")
        else:
            if classification is None or self.error_code is None:
                raise ValueError("failed model-call events require classified errors")
            if self.error_retryable is None:
                raise ValueError("failed model-call events require retryability")
            object.__setattr__(self, "error_code", ModelGatewayErrorCode(self.error_code))
        for hash_value, label in (
            (self.output_hash, "model-call output"),
            (self.response_hash, "model-call response"),
        ):
            if hash_value is not None:
                _require_hash(hash_value, label)


@dataclass(frozen=True)
class ModelCallOutcome:
    attempt: ModelCallAttempt
    terminal_event: ModelCallTerminalEvent | None


@dataclass(frozen=True)
class ModelCallReconciliationRecord:
    id: UUID
    project_id: UUID
    attempt_id: UUID
    terminal_event_id: UUID
    reconciled_by: UUID
    idempotency_key_hash: str
    request_hash: str
    expected_budget_version: int
    recorded_at: datetime

    def __post_init__(self) -> None:
        for value, label in (
            (self.id, "model-call reconciliation command"),
            (self.project_id, "model-call reconciliation project"),
            (self.attempt_id, "model-call reconciliation attempt"),
            (self.terminal_event_id, "model-call reconciliation terminal event"),
            (self.reconciled_by, "model-call reconciliation actor"),
        ):
            _require_uuid(value, label)
        _require_hash(self.idempotency_key_hash, "reconciliation idempotency key")
        _require_hash(self.request_hash, "reconciliation request")
        if self.expected_budget_version < 0:
            raise ValueError("reconciliation expected budget version cannot be negative")
        _require_aware(self.recorded_at, "reconciliation command time")


class ModelCallRepository(Protocol):
    def get_job(self, *, project_id: UUID, job_id: UUID) -> ModelCallJobAdmission | None: ...

    def get_prompt_release(
        self, *, project_id: UUID, binding_id: UUID, release_id: UUID
    ) -> PromptReleaseAdmission | None: ...

    def get_prompt_test_release(
        self,
        *,
        project_id: UUID,
        release_id: UUID,
        state_id: UUID,
        state_version: int,
        test_set_hash: str,
    ) -> PromptReleaseAdmission | None: ...

    def get_attempt(self, *, project_id: UUID, attempt_id: UUID) -> ModelCallAttempt | None: ...

    def get_attempt_by_idempotency(
        self, *, project_id: UUID, job_id: UUID, idempotency_key_hash: str
    ) -> ModelCallOutcome | None: ...

    def get_terminal_event(
        self, *, project_id: UUID, attempt_id: UUID
    ) -> ModelCallTerminalEvent | None: ...

    def get_reconciliation_command(
        self, *, project_id: UUID, idempotency_key_hash: str
    ) -> ModelCallReconciliationRecord | None: ...

    def reserve_attempt(
        self,
        *,
        draft: ModelCallAttemptDraft,
        expected_job_version: int,
        expected_budget_version: int,
        reserved_at: datetime,
    ) -> StoredModelCallAttempt: ...

    def append_terminal_event(
        self,
        *,
        event: ModelCallTerminalEvent,
        expected_budget_version: int,
    ) -> None: ...

    def add_reconciliation_command(self, command: ModelCallReconciliationRecord) -> None: ...


class ExactModelGatewayPort(Protocol):
    """Invoke one explicit route; implementations must not select a fallback."""

    def generate(
        self,
        route: ModelRoute,
        request: ModelGatewayRequest,
        *,
        policy: ModelPolicy,
        budget: ModelCallBudget,
    ) -> ModelGatewayResult: ...


class ModelCallUnitOfWork(Protocol):
    calls: ModelCallRepository

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

    def commit(self) -> None: ...


class ModelCallUnitOfWorkFactory(Protocol):
    def __call__(self, *, project_id: UUID) -> ModelCallUnitOfWork: ...
