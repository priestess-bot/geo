"""Transport adapters for monitoring source provenance."""

from __future__ import annotations

from typing import Any, cast

from geo_api.monitoring_contracts import (
    ModelIdentityContract,
    ObservationRunParametersContract,
    ObservationSourceResponse,
    RawEvidenceRequest,
    RawEvidenceResponse,
    SourceStratumContract,
)
from geo_core.monitoring.domain import MonitoringRuleViolation
from geo_core.monitoring.source_contract import (
    CaptureMethod,
    ClientKind,
    SOURCE_CONTRACT_VERSION,
    ModelIdentity,
    ModelIdentityState,
    ObservationDevice,
    ObservationPlatform,
    ObservationRunParameters,
    ObservationSource,
    ObservationSurface,
    RawEvidence,
    RawEvidenceKind,
    SearchMode,
    SourceStratumKey,
    SurfaceKind,
)


SOURCE_BADGES = {
    CaptureMethod.OFFICIAL_REPORT_IMPORT: "Official report import",
    CaptureMethod.MANUAL_UI: "Manual consumer UI",
    CaptureMethod.PROVIDER_API: "Provider API",
    CaptureMethod.PROXY_GROUNDED_API: "Proxy grounded API",
    CaptureMethod.SYNTHETIC: "Synthetic benchmark - test only",
    CaptureMethod.UNKNOWN: "Legacy unknown - ineligible",
}


def model_identity(value: ModelIdentityContract) -> ModelIdentity:
    return ModelIdentity(ModelIdentityState(value.state), value.value)


def run_parameters(value: ObservationRunParametersContract) -> ObservationRunParameters:
    return ObservationRunParameters(
        engine=value.engine,
        locale=value.locale,
        region=value.region,
        language=value.language,
        device=ObservationDevice(value.device) if value.device else None,
        client_kind=ClientKind(value.client_kind) if value.client_kind else None,
        search_enabled=value.search_enabled,
        search_mode=SearchMode(value.search_mode) if value.search_mode else None,
        prompt_text=value.prompt_text,
        follow_up_prompts=tuple(value.follow_up_prompts),
        adapter_name=value.adapter_name,
        adapter_version=value.adapter_version,
        provider_request_id=value.provider_request_id,
    )


def raw_evidence(value: RawEvidenceRequest) -> RawEvidence:
    if value.kind == "answer":
        return RawEvidence(RawEvidenceKind.ANSWER, answer=value.answer)
    if value.kind == "inline_response":
        return RawEvidence(
            RawEvidenceKind.INLINE_RESPONSE, inline_response=value.inline_response
        )
    return RawEvidence(
        RawEvidenceKind.ARTIFACT,
        artifact_uri=value.artifact_uri,
        artifact_hash=value.artifact_hash,
    )


def source_stratum(value: SourceStratumContract) -> SourceStratumKey:
    if value.source_contract_version != SOURCE_CONTRACT_VERSION:
        raise MonitoringRuleViolation("new protocols require source stratum contract v3")
    return SourceStratumKey(
        capture_method=CaptureMethod(value.capture_method),
        platform=ObservationPlatform(value.platform),
        surface=ObservationSurface(value.surface),
        surface_kind=SurfaceKind(value.surface_kind),
        engine=value.engine,
        configured_model=model_identity(value.configured_model),
        reported_model=model_identity(value.reported_model),
        locale=value.locale,
        region=value.region,
        language=value.language,
        device=ObservationDevice(value.device),
        client_kind=ClientKind(value.client_kind),
        search_enabled=value.search_enabled,
        search_mode=SearchMode(value.search_mode),
        platform_detail=value.platform_detail,
        surface_detail=value.surface_detail,
        source_contract_version=value.source_contract_version,
    )


def source_stratum_contract(value: SourceStratumKey) -> SourceStratumContract:
    payload = value.canonical_value()
    payload["source_contract_version"] = value.source_contract_version
    return SourceStratumContract.model_validate(payload)


def source_response(value: ObservationSource) -> ObservationSourceResponse:
    evidence = value.raw_evidence
    run = value.run
    return ObservationSourceResponse(
        capture_method=cast(Any, value.capture_method.value),
        platform=cast(Any, value.platform.value),
        surface=cast(Any, value.surface.value),
        surface_kind=cast(Any, value.surface_kind.value),
        platform_detail=value.platform_detail,
        surface_detail=value.surface_detail,
        configured_model=ModelIdentityContract(
            state=cast(Any, value.configured_model.state.value),
            value=value.configured_model.value,
        ),
        reported_model=ModelIdentityContract(
            state=cast(Any, value.reported_model.state.value),
            value=value.reported_model.value,
        ),
        run=ObservationRunParametersContract(
            engine=run.engine,
            locale=run.locale,
            region=run.region,
            language=run.language,
            device=cast(Any, run.device.value if run.device else None),
            client_kind=cast(
                Any, run.client_kind.value if run.client_kind else None
            ),
            search_enabled=run.search_enabled,
            search_mode=cast(
                Any, run.search_mode.value if run.search_mode else None
            ),
            prompt_text=run.prompt_text,
            follow_up_prompts=list(run.follow_up_prompts),
            adapter_name=run.adapter_name,
            adapter_version=run.adapter_version,
            provider_request_id=run.provider_request_id,
        ),
        raw_evidence=RawEvidenceResponse(
            kind=cast(Any, evidence.kind.value),
            answer=evidence.answer,
            inline_response=(
                dict(evidence.inline_response)
                if evidence.inline_response is not None
                else None
            ),
            artifact_uri=evidence.artifact_uri,
            artifact_hash=evidence.artifact_hash,
            artifact_verified=evidence.artifact_verified,
        ),
        source_contract_version=value.source_contract_version,
        citations_captured=value.citations_captured,
        source_job_id=value.source_job_id,
        model_call_log_id=value.model_call_log_id,
        test_only=value.test_only,
        publication_eligible=value.publication_eligible,
        source_badge=SOURCE_BADGES[value.capture_method],
    )
