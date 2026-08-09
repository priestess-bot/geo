"""Strict PostgreSQL row mappings for Model Gateway persistence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from geo_core.jobs.lifecycle import JobStatus
from geo_core.model_gateway.contracts import (
    CapabilityVerification,
    ModelAudience,
    ModelCaptureMethod,
    ModelGatewayErrorCode,
    ModelPolicy,
    ProviderCapabilities,
)
from geo_core.model_gateway.ports import (
    ModelCallAttempt,
    ModelCallAttemptDraft,
    ModelCallAttemptKind,
    ModelCallFailureClass,
    ModelCallJobAdmission,
    ModelCallLineage,
    ModelCallReconciliationRecord,
    ModelCallTerminalEvent,
    ModelCallTerminalStatus,
    PromptReleaseAdmission,
    canonical_json_hash,
)
from geo_core.model_gateway.location import (
    EffectiveModelLocation,
    ModelLocationControl,
    RequestedModelLocation,
)
from geo_core.model_gateway.prompt_admission import ModelCallAdmissionMode
from geo_core.model_gateway.releases import (
    AdapterRelease,
    DataUseDecision,
    ModelRelease,
    ModelRoute,
    ProviderDataPolicy,
    ReleaseState,
    ReportedModelPolicy,
    provider_secret_purpose,
)
from geo_core.secrets import SecretVersionHandle


Row = Mapping[str, Any]


def adapter_release_from_row(row: Row) -> AdapterRelease:
    data_policy = ProviderDataPolicy(
        storage=DataUseDecision(row["data_storage_decision"]),
        cache=DataUseDecision(row["data_cache_decision"]),
        display=DataUseDecision(row["data_display_decision"]),
        redistribution=DataUseDecision(row["data_redistribution_decision"]),
        retention_days=row["data_policy_retention_days"],
        terms_reference=row["terms_reference"],
        terms_sha256=row["terms_sha256"],
    )
    if data_policy.data_policy_hash != row["data_policy_hash"]:
        raise ValueError("stored Model Gateway Adapter Release data-policy hash is invalid")
    return AdapterRelease(
        provider=row["provider"],
        adapter_release_id=row["adapter_release_id"],
        release_hash=row["release_hash"],
        interface_contract_version=row["interface_contract_version"],
        expected_capture_method=ModelCaptureMethod(row["expected_capture_method"]),
        capabilities=ProviderCapabilities(
            provider=row["provider"],
            external_training_allowed=row["external_training_allowed"],
            structured_output=row["structured_output"],
            data_retention_days=row["capability_data_retention_days"],
            policy_reference=row["capability_policy_reference"],
            supports_seed=row["supports_seed"],
            supports_tools=row["supports_tools"],
            supports_search=row["supports_search"],
            supports_citations=row["supports_citations"],
            supports_idempotency=row["supports_idempotency"],
            supports_structured_output_with_tools=row[
                "supports_structured_output_with_tools"
            ],
            verification=CapabilityVerification(row["capability_verification"]),
        ),
        data_policy=data_policy,
        state=ReleaseState(row["state"]),
        capability_evidence_reference=row["capability_evidence_reference"],
        capability_evidence_sha256=row["capability_evidence_sha256"],
    )


def model_release_from_row(row: Row) -> ModelRelease:
    return ModelRelease(
        provider=row["provider"],
        adapter_release_id=row["adapter_release_id"],
        model_release_id=row["model_release_id"],
        release_hash=row["release_hash"],
        configured_model=row["configured_model"],
        state=ReleaseState(row["state"]),
        reported_model_policy=ReportedModelPolicy(row["reported_model_policy"]),
        allowed_reported_models=tuple(row["allowed_reported_models"]),
    )


def project_policy_from_row(row: Row) -> ModelPolicy:
    policy = ModelPolicy(
        external_training_allowed=row["external_training_allowed"],
        structured_output_required=row["structured_output_required"],
        allowed_providers=frozenset(row["allowed_providers"]),
        allowed_adapter_release_ids=frozenset(row["allowed_adapter_release_ids"]),
        policy_version_id=row["id"],
        maximum_paid_calls=row["maximum_paid_calls_default"],
        maximum_concurrent_calls=row["maximum_concurrent_calls"],
    )
    if policy.policy_version_hash != row["policy_hash"]:
        raise ValueError("stored Model Gateway project policy hash is invalid")
    return policy


def prompt_admission_from_row(row: Row) -> PromptReleaseAdmission:
    return PromptReleaseAdmission(
        project_id=row["project_id"],
        admission_mode=ModelCallAdmissionMode(row["admission_mode"]),
        binding_id=row["binding_id"],
        state_id=row["state_id"],
        state_version=row["state_version"],
        release_id=row["release_id"],
        release_hash=row["release_hash"],
        purpose=row["purpose"],
        output_schema_hash=row["output_schema_hash"],
        application_output_schema_hash=row["application_output_schema_hash"],
        test_set_hash=row["test_set_hash"],
        state_status=row["state_status"],
        current=row["current"],
    )


def job_admission_from_row(row: Row) -> ModelCallJobAdmission:
    return ModelCallJobAdmission(
        project_id=row["project_id"],
        job_id=row["job_id"],
        job_kind=row["job_kind"],
        job_version=row["job_version"],
        runtime_manifest_id=row["runtime_manifest_id"],
        runtime_manifest_hash=row["runtime_manifest_hash"],
        runtime_option_id=row["runtime_option_id"],
        runtime_option_hash=row["runtime_option_hash"],
        admission_mode=ModelCallAdmissionMode(row["admission_mode"]),
        status=JobStatus(row["durable_status"]),
        lease_token=row["lease_token"],
        fencing_generation=row["fencing_generation"],
        purpose=row["purpose"],
        usage_audience=ModelAudience(row["usage_audience"]),
        route=_route(row),
        provider_secret_handle=_secret_handle(row),
        prompt_binding_id=row["prompt_binding_id"],
        prompt_release_id=row["prompt_release_id"],
        prompt_release_hash=row["prompt_release_hash"],
        prompt_state_id=row["prompt_frozen_state_id"],
        prompt_state_version=row["prompt_state_version"],
        prompt_test_set_hash=row["prompt_test_set_hash"],
        prompt_bundle_hash=row["prompt_bundle_hash"],
        output_schema_hash=row["output_schema_hash"],
        application_output_schema_hash=row["application_output_schema_hash"],
        policy_version_id=row["policy_version_id"],
        policy_version_hash=row["policy_version_hash"],
        maximum_paid_calls=row["maximum_paid_calls"],
        maximum_concurrent_calls=row["maximum_concurrent_calls"],
        raw_artifact_policy_hash=row["raw_artifact_policy_hash"],
        raw_artifact_storage_decision=row["raw_artifact_storage_decision"],
        raw_artifact_cache_decision=row["raw_artifact_cache_decision"],
        raw_artifact_display_decision=row["raw_artifact_display_decision"],
        raw_artifact_redistribution_decision=row[
            "raw_artifact_redistribution_decision"
        ],
        raw_artifact_retention_days=row["raw_artifact_retention_days"],
        paid_calls=row["paid_calls"],
        reserved_calls=row["reserved_calls"],
        budget_version=row["budget_version"],
        next_attempt_number=row["next_attempt_number"],
    )


def attempt_from_row(row: Row) -> ModelCallAttempt:
    capture_method = row["capture_method"]
    return ModelCallAttempt(
        spec=ModelCallAttemptDraft(
            id=row["id"],
            project_id=row["project_id"],
            job_id=row["job_id"],
            job_version=row["job_version"],
            runtime_manifest_id=row["runtime_manifest_id"],
            runtime_manifest_hash=row["runtime_manifest_hash"],
            runtime_option_id=row["runtime_option_id"],
            runtime_option_hash=row["runtime_option_hash"],
            admission_mode=ModelCallAdmissionMode(row["admission_mode"]),
            lease_token=row["lease_token"],
            fencing_generation=row["fencing_generation"],
            kind=ModelCallAttemptKind(row["kind"]),
            parent_attempt_id=row["parent_attempt_id"],
            idempotency_key_hash=row["idempotency_key_hash"],
            request_hash=row["request_hash"],
            input_hash=row["input_hash"],
            purpose=row["purpose"],
            usage_audience=ModelAudience(row["usage_audience"]),
            route=_route(row),
            provider_secret_handle=_secret_handle(row),
            prompt_binding_id=row["prompt_binding_id"],
            prompt_release_id=row["prompt_release_id"],
            prompt_release_hash=row["prompt_release_hash"],
            prompt_state_id=row["prompt_state_id"],
            prompt_state_version=row["prompt_state_version"],
            prompt_test_set_hash=row["prompt_test_set_hash"],
            prompt_test_case_id=row["prompt_test_case_id"],
            prompt_test_case_hash=row["prompt_test_case_hash"],
            prompt_bundle_hash=row["prompt_bundle_hash"],
            output_schema_hash=row["output_schema_hash"],
            application_output_schema_hash=row["application_output_schema_hash"],
            policy_version_id=row["policy_version_id"],
            policy_version_hash=row["policy_version_hash"],
            raw_artifact_policy_hash=row["raw_artifact_policy_hash"],
            raw_artifact_storage_decision=row["raw_artifact_storage_decision"],
            raw_artifact_cache_decision=row["raw_artifact_cache_decision"],
            raw_artifact_display_decision=row["raw_artifact_display_decision"],
            raw_artifact_redistribution_decision=row[
                "raw_artifact_redistribution_decision"
            ],
            raw_artifact_retention_days=row["raw_artifact_retention_days"],
            configured_model=row["configured_model"],
            search_mode=row["search_mode"],
            capture_method=(
                ModelCaptureMethod(capture_method) if capture_method is not None else None
            ),
            requested_location=_requested_location(row),
            expected_effective_location=_effective_location(row, prefix="expected_location"),
        ),
        attempt_number=row["attempt_number"],
        reserved_at=row["reserved_at"],
    )


def terminal_event_from_row(row: Row) -> ModelCallTerminalEvent:
    capture_method = row["capture_method"]
    return ModelCallTerminalEvent(
        id=row["id"],
        project_id=row["project_id"],
        job_id=row["job_id"],
        attempt_id=row["attempt_id"],
        status=ModelCallTerminalStatus(row["status"]),
        occurred_at=row["occurred_at"],
        paid_call_count=row["paid_call_count"],
        gateway_call_log_id=row["gateway_call_log_id"],
        configured_model=row["configured_model"],
        provider_reported_model=row["provider_reported_model"],
        provider_request_id=row["provider_request_id"],
        prompt_tokens=row["prompt_tokens"],
        completion_tokens=row["completion_tokens"],
        cost_usd=row["cost_usd"],
        finish_reason=row["finish_reason"],
        input_hash=row["input_hash"],
        output_hash=row["output_hash"],
        response_hash=row["response_hash"],
        lineage=ModelCallLineage(
            search_mode=row["search_mode"],
            capture_method=(
                ModelCaptureMethod(capture_method) if capture_method is not None else None
            ),
            citation_count=row["citation_count"],
            citation_lineage_hash=row["citation_lineage_hash"],
            search_event_count=row["search_event_count"],
            search_lineage_hash=row["search_lineage_hash"],
            usage_details_hash=row["usage_details_hash"],
            raw_artifact_reference_hash=row["raw_artifact_reference_hash"],
            raw_artifact_policy_hash=row["raw_artifact_policy_hash"],
            raw_artifact_storage_decision=row["raw_artifact_storage_decision"],
            raw_artifact_cache_decision=row["raw_artifact_cache_decision"],
            raw_artifact_display_decision=row["raw_artifact_display_decision"],
            raw_artifact_redistribution_decision=row[
                "raw_artifact_redistribution_decision"
            ],
            raw_artifact_retention_days=row["raw_artifact_retention_days"],
            usage_purpose=row["usage_purpose"],
            usage_audience=ModelAudience(row["usage_audience"]),
            effective_location=_effective_location(row, prefix="effective_location"),
        ),
        error_classification=(
            ModelCallFailureClass(row["error_classification"])
            if row["error_classification"] is not None
            else None
        ),
        error_code=(
            ModelGatewayErrorCode(row["error_code"])
            if row["error_code"] is not None
            else None
        ),
        error_retryable=row["error_retryable"],
        reconciled_by=row["reconciled_by"],
        reconciliation_evidence_ref=row["reconciliation_evidence_ref"],
    )


def reconciliation_record_from_row(row: Row) -> ModelCallReconciliationRecord:
    return ModelCallReconciliationRecord(
        id=row["id"],
        project_id=row["project_id"],
        attempt_id=row["attempt_id"],
        terminal_event_id=row["terminal_event_id"],
        reconciled_by=row["reconciled_by"],
        idempotency_key_hash=row["idempotency_key_hash"],
        request_hash=row["request_hash"],
        expected_budget_version=row["expected_budget_version"],
        recorded_at=row["recorded_at"],
    )


def _route(row: Row) -> ModelRoute:
    return ModelRoute(
        provider=row["provider"],
        adapter_release_id=row["adapter_release_id"],
        adapter_release_hash=row["adapter_release_hash"],
        model_release_id=row["model_release_id"],
        model_release_hash=row["model_release_hash"],
    )


def _secret_handle(row: Row) -> SecretVersionHandle:
    handle = SecretVersionHandle(
        reference_id=row["provider_secret_reference_id"],
        project_id=row["project_id"],
        purpose=provider_secret_purpose(row["provider"]),
        version=row["provider_secret_version"],
    )
    if canonical_json_hash(handle.as_job_payload()) != row["provider_secret_handle_hash"]:
        raise ValueError("stored Model Gateway Provider Secret handle hash is invalid")
    return handle


def _requested_location(row: Row) -> RequestedModelLocation | None:
    if row["requested_location_locale"] is None:
        return None
    return RequestedModelLocation(
        country_code=row["requested_location_country"],
        region_code=row["requested_location_region"],
        locale=row["requested_location_locale"],
        language=row["requested_location_language"],
    )


def _effective_location(row: Row, *, prefix: str) -> EffectiveModelLocation | None:
    control = row[f"{prefix}_control"]
    if control is None:
        return None
    return EffectiveModelLocation(
        control=ModelLocationControl(control),
        country_code=row[f"{prefix}_country"],
        region_code=row[f"{prefix}_region"],
        locale=row[f"{prefix}_locale"],
        language=row[f"{prefix}_language"],
        evidence_hash=row[f"{prefix}_evidence_hash"],
    )


__all__ = [
    "adapter_release_from_row",
    "attempt_from_row",
    "job_admission_from_row",
    "model_release_from_row",
    "project_policy_from_row",
    "prompt_admission_from_row",
    "reconciliation_record_from_row",
    "terminal_event_from_row",
]
