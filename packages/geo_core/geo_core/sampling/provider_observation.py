"""Map one successful exact model call into governed Sampling evidence."""

from __future__ import annotations

from geo_core.model_gateway.application_support import ModelCallExecution
from geo_core.model_gateway.contracts import ModelGatewayResult
from geo_core.model_gateway.ports import (
    ModelCallTerminalEvent,
    ModelCallTerminalStatus,
    canonical_json_hash,
)
from geo_core.sampling.contracts import SamplingSuite
from geo_core.sampling.execution import (
    ObservationArtifactKind,
    ObservationArtifactManifest,
    ObservationEvidence,
    SamplingAttempt,
)
from geo_core.sampling.provider_execution_contracts import (
    ExecuteProviderSampling,
    ProviderAttemptObservationLineage,
    ProviderSamplingAdmissionError,
)


def map_provider_success(
    command: ExecuteProviderSampling,
    suite: SamplingSuite,
    attempt: SamplingAttempt,
    execution: ModelCallExecution,
) -> tuple[ProviderAttemptObservationLineage, ObservationEvidence]:
    result = execution.result
    if result is None:
        raise ProviderSamplingAdmissionError("replayed model call has no recoverable output")
    event = execution.terminal_event
    source = suite.source_stratum
    _validate_success_identity(command, result, event, reported_model=source.reported_model)
    requested_location = result.requested_location
    effective_location = result.effective_location
    assert requested_location is not None
    assert effective_location is not None
    answer = result.output.get(command.prompt.answer_field)
    if not isinstance(answer, str) or not answer.strip():
        raise ProviderSamplingAdmissionError("structured result has no non-empty answer field")
    parameters = {
        "sampling_attempt_id": attempt.id,
        "model_call_attempt_id": execution.attempt.spec.id,
        "gateway_call_log_id": result.call_log_id,
        "provider_request_id": result.provider_request_id,
        "provider": command.route.provider,
        "adapter_release_id": command.route.adapter_release_id,
        "adapter_release_hash": command.route.adapter_release_hash,
        "model_release_id": command.route.model_release_id,
        "model_release_hash": command.route.model_release_hash,
        "configured_model": result.configured_model,
        "provider_reported_model": result.provider_reported_model,
        "capture_method": result.capture_method,
        "search_mode": result.search_mode,
        "locale": source.locale,
        "region": source.region,
        "language": source.language,
        "surface": source.surface,
        "citation_count": event.lineage.citation_count,
        "citation_lineage_hash": event.lineage.citation_lineage_hash,
        "search_event_count": event.lineage.search_event_count,
        "search_lineage_hash": event.lineage.search_lineage_hash,
        "paid_call_count": event.paid_call_count,
        "usage_details_hash": event.lineage.usage_details_hash,
        "requested_location": requested_location.canonical_value(),
        "effective_location": effective_location.canonical_value(),
    }
    parameters_hash = canonical_json_hash(parameters)
    assert result.provider is not None
    assert result.provider_reported_model is not None
    assert result.capture_method is not None
    assert result.search_mode is not None
    assert event.output_hash is not None
    raw_artifact, derived_artifact = _artifact_manifests(result)
    if (
        result.raw_artifact_cache_decision is None
        or result.raw_artifact_display_decision is None
        or result.raw_artifact_redistribution_decision is None
        or result.raw_artifact_storage_decision is None
        or result.usage_purpose is None
        or result.usage_audience is None
    ):
        raise ProviderSamplingAdmissionError(
            "provider result has incomplete data-use policy lineage"
        )
    summary = (
        "Governed provider evidence is available to approved viewers."
        if result.raw_artifact_display_decision == "allowed"
        else "Provider response withheld by approved data policy."
    )
    lineage = ProviderAttemptObservationLineage(
        sampling_attempt_id=attempt.id,
        model_call_attempt_id=execution.attempt.spec.id,
        gateway_call_log_id=result.call_log_id,
        provider_request_id=result.provider_request_id,
        response_hash=result.response_hash,
        output_hash=event.output_hash,
        provider=result.provider,
        adapter_release_id=command.route.adapter_release_id,
        adapter_release_hash=command.route.adapter_release_hash,
        model_release_id=command.route.model_release_id,
        model_release_hash=command.route.model_release_hash,
        configured_model=result.configured_model,
        provider_reported_model=result.provider_reported_model,
        capture_method=result.capture_method,
        search_mode=result.search_mode,
        citation_count=event.lineage.citation_count,
        citation_lineage_hash=event.lineage.citation_lineage_hash,
        search_event_count=event.lineage.search_event_count,
        search_lineage_hash=event.lineage.search_lineage_hash,
        raw_artifact_manifest_hash=raw_artifact.manifest_hash,
        derived_artifact_manifest_hash=derived_artifact.manifest_hash,
        result_parameters_hash=parameters_hash,
        location_control=effective_location.control.value,
        location_evidence_hash=effective_location.evidence_hash,
        requested_country=requested_location.country_code,
        requested_region=requested_location.region_code,
        requested_locale=requested_location.locale,
        requested_language=requested_location.language,
        effective_country=effective_location.country_code,
        effective_region=effective_location.region_code,
        effective_locale=effective_location.locale,
        effective_language=effective_location.language,
    )
    evidence = ObservationEvidence(
        raw_artifact=raw_artifact,
        derived_artifact=derived_artifact,
        derived_summary=summary,
        evidence_locator=(f"{derived_artifact.manifest_reference}#/{command.prompt.answer_field}"),
        provider_response_id=result.provider_request_id,
        egress_verification_id=None,
        result_parameters_hash=parameters_hash,
        storage_decision=result.raw_artifact_storage_decision,
        cache_decision=result.raw_artifact_cache_decision,
        display_decision=result.raw_artifact_display_decision,
        redistribution_decision=result.raw_artifact_redistribution_decision,
        usage_purpose=result.usage_purpose,
        usage_audience=result.usage_audience.value,
    )
    return lineage, evidence


def _artifact_manifests(
    result: ModelGatewayResult,
) -> tuple[ObservationArtifactManifest, ObservationArtifactManifest]:
    policy_hash = result.raw_artifact_policy_hash
    decision = result.raw_artifact_storage_decision
    values = (
        result.raw_artifact_manifest_hash,
        result.raw_artifact_content_hash,
        result.raw_artifact_byte_size,
        result.derived_artifact_manifest_hash,
        result.derived_artifact_content_hash,
        result.derived_artifact_byte_size,
    )
    if (
        policy_hash is None
        or decision not in {"allowed", "prohibited"}
        or any(value is None for value in values)
    ):
        raise ProviderSamplingAdmissionError(
            "provider result has incomplete governed artifact lineage"
        )
    raw_hash, raw_content_hash, raw_size, derived_hash, derived_content_hash, derived_size = values
    assert isinstance(raw_hash, str) and isinstance(raw_content_hash, str)
    assert isinstance(derived_hash, str) and isinstance(derived_content_hash, str)
    assert isinstance(raw_size, int) and isinstance(derived_size, int)
    if decision == "allowed":
        if (
            result.raw_artifact_reference is None
            or result.derived_artifact_reference is None
            or raw_size < 1
            or derived_size < 1
        ):
            raise ProviderSamplingAdmissionError("stored provider artifacts are incomplete")
        raw_reference = result.raw_artifact_reference
        derived_reference = result.derived_artifact_reference
    else:
        if (
            result.raw_artifact_reference is not None
            or result.derived_artifact_reference is not None
            or raw_size != 0
            or derived_size != 0
        ):
            raise ProviderSamplingAdmissionError("prohibited provider artifacts were persisted")
        raw_reference = f"withheld://provider-artifact/raw/{raw_hash}"
        derived_reference = f"withheld://provider-artifact/derived/{derived_hash}"
    return (
        ObservationArtifactManifest(
            kind=ObservationArtifactKind.RAW,
            manifest_reference=raw_reference,
            manifest_hash=raw_hash,
            content_hash=raw_content_hash,
            governance_policy_hash=policy_hash,
        ),
        ObservationArtifactManifest(
            kind=ObservationArtifactKind.DERIVED,
            manifest_reference=derived_reference,
            manifest_hash=derived_hash,
            content_hash=derived_content_hash,
            governance_policy_hash=policy_hash,
        ),
    )


def _validate_success_identity(
    command: ExecuteProviderSampling,
    result: ModelGatewayResult,
    event: ModelCallTerminalEvent,
    *,
    reported_model: str,
) -> None:
    if result.requested_location is None or result.effective_location is None:
        raise ProviderSamplingAdmissionError(
            "provider result has no requested/effective location lineage"
        )
    if (
        event.status is not ModelCallTerminalStatus.SUCCEEDED
        or event.gateway_call_log_id != result.call_log_id
        or event.response_hash != result.response_hash
        or event.output_hash != canonical_json_hash(result.output)
        or result.provider != command.route.provider
        or result.adapter_release_id != command.route.adapter_release_id
        or result.adapter_release_hash != command.route.adapter_release_hash
        or result.model_release_id != command.route.model_release_id
        or result.model_release_hash != command.route.model_release_hash
        or result.provider_reported_model != reported_model
    ):
        raise ProviderSamplingAdmissionError(
            "provider result differs from frozen release, model, or call-log identity"
        )


def location_ineligibility(
    suite: SamplingSuite,
    result: ModelGatewayResult,
) -> tuple[str, ...]:
    requested = result.requested_location
    effective = result.effective_location
    source = suite.source_stratum
    if requested is None or effective is None:
        return ("provider_location_lineage_missing",)
    requested_mismatch = (
        requested.country_code != source.requested_country
        or requested.region_code != source.requested_region
        or requested.locale != source.requested_locale
        or requested.language != source.requested_language
    )
    effective_mismatch = (
        effective.control.value != source.location_control.value
        or effective.evidence_hash != source.location_evidence_hash
        or effective.country_code != source.effective_country
        or effective.region_code != source.effective_region
        or effective.locale != source.effective_locale
        or effective.language != source.effective_language
    )
    return ("provider_location_control_mismatch",) if (
        requested_mismatch or effective_mismatch
    ) else ()


__all__ = ["location_ineligibility", "map_provider_success"]
