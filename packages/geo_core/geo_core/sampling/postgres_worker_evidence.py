"""Text-free observation evidence assembled after governed sampling execution."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID, uuid5

from geo_core.model_gateway import canonical_json_hash
from geo_core.model_gateway.contracts import ModelCaptureMethod, ModelGatewayResult
from geo_core.sampling.contracts import CaptureMethod, LocationControl
from geo_core.sampling.execution import SAMPLING_OBSERVATION_NAMESPACE
from geo_core.sampling.postgres_worker_contracts import (
    ManualSamplingCommit,
    ManualSamplingWorkerSpec,
    ProviderSamplingCommit,
    ProviderSamplingWorkerSpec,
    SamplingWorkerSource,
    WorkflowCSamplingSpecError,
)


def build_provider_commit(
    *,
    project_id: UUID,
    spec: ProviderSamplingWorkerSpec,
    task_key: str,
    question_id: str,
    question_version: str,
    source: SamplingWorkerSource,
    result: ModelGatewayResult,
    model_attempt_id: UUID,
    output_hash: str,
    observed_at: datetime,
) -> ProviderSamplingCommit:
    """Validate a structured Provider result and emit a text-free observation."""

    _require_aware(observed_at, "provider observation time")
    source_stratum = source.source
    if source_stratum.capture_method not in {
        CaptureMethod.PROVIDER_API,
        CaptureMethod.PROXY_GROUNDED_API,
    }:
        raise WorkflowCSamplingSpecError("provider Job has a non-provider source stratum")
    if source.questions.get((question_id, question_version)) != spec.question_hash:
        raise WorkflowCSamplingSpecError("provider question differs from frozen Suite")
    prompt = spec.prompt.as_provider_prompt()
    answer = result.output.get(prompt.answer_field)
    if not isinstance(answer, str) or not answer.strip():
        raise WorkflowCSamplingSpecError("provider structured result has no answer")
    if canonical_json_hash(result.output) != output_hash:
        raise WorkflowCSamplingSpecError("provider output differs from terminal event")
    if (
        result.provider != source_stratum.platform
        or result.capture_method is not ModelCaptureMethod(source_stratum.capture_method.value)
        or result.search_mode != source_stratum.search_mode
        or result.configured_model != source_stratum.configured_model
        or result.provider_reported_model != source_stratum.reported_model
        or result.requested_location is None
        or result.effective_location is None
        or result.usage_purpose != spec.prompt.purpose
        or result.usage_audience is None
    ):
        raise WorkflowCSamplingSpecError("provider result differs from frozen source identity")
    requested = result.requested_location.canonical_value()
    effective = result.effective_location.canonical_value()
    expected_requested = {
        "country_code": source_stratum.requested_country,
        "region_code": source_stratum.requested_region,
        "locale": source_stratum.requested_locale,
        "language": source_stratum.requested_language,
    }
    expected_effective = {
        "control": source_stratum.location_control.value,
        "country_code": source_stratum.effective_country,
        "region_code": source_stratum.effective_region,
        "locale": source_stratum.effective_locale,
        "language": source_stratum.effective_language,
        "evidence_hash": source_stratum.location_evidence_hash,
    }
    ineligible = () if requested == expected_requested and effective == expected_effective else (
        "provider_location_control_mismatch",
    )
    actual_location = {
        "location_control": effective["control"],
        "location_evidence_hash": effective["evidence_hash"],
        "requested_country": requested["country_code"],
        "requested_region": requested["region_code"],
        "requested_locale": requested["locale"],
        "requested_language": requested["language"],
        "effective_country": effective["country_code"],
        "effective_region": effective["region_code"],
        "effective_locale": effective["locale"],
        "effective_language": effective["language"],
    }
    artifacts = _provider_artifacts(result)
    evidence = {
        "schema_version": 1,
        "kind": "provider_api",
        "raw_artifact": artifacts["raw_artifact"],
        "derived_artifact": artifacts["derived_artifact"],
        "derived_summary": "Governed provider evidence is available to approved viewers.",
        "evidence_locator": (
            f"{artifacts['derived_artifact']['manifest_reference']}#/{prompt.answer_field}"
        ),
        "provider_response_id": result.provider_request_id,
        "egress_verification_id": None,
        "result_parameters_hash": canonical_json_hash(
            {
                "sampling_attempt_id": str(spec.attempt_id),
                "model_call_attempt_id": str(model_attempt_id),
                "gateway_call_log_id": str(result.call_log_id),
                "provider": result.provider,
                "configured_model": result.configured_model,
                "provider_reported_model": result.provider_reported_model,
                "capture_method": result.capture_method.value,
                "search_mode": result.search_mode,
                "requested_location": requested,
                "effective_location": effective,
            }
        ),
        "storage_decision": result.raw_artifact_storage_decision,
        "cache_decision": result.raw_artifact_cache_decision,
        "display_decision": result.raw_artifact_display_decision,
        "redistribution_decision": result.raw_artifact_redistribution_decision,
        "usage_purpose": result.usage_purpose,
        "usage_audience": result.usage_audience.value,
    }
    actual_hash = canonical_json_hash(actual_location)
    observation_id = _observation_id(task_key, spec.attempt_id, evidence, actual_location)
    return ProviderSamplingCommit(
        observation_id=observation_id,
        observation_hash=_observation_hash(
            project_id=project_id,
            run_id=spec.run_id,
            task_id=spec.task_id,
            attempt_id=spec.attempt_id,
            task_key=task_key,
            evidence_status="ineligible" if ineligible else "complete",
            ineligible_reasons=ineligible,
            actual_location=actual_location,
            evidence=evidence,
            observed_at=observed_at,
        ),
        evidence_status="ineligible" if ineligible else "complete",
        ineligible_reasons=ineligible,
        actual_location=actual_location,
        actual_location_hash=actual_hash,
        evidence=evidence,
        provider_attempt_id=model_attempt_id,
        provider_response_hash=result.response_hash,
        output_hash=output_hash,
        observed_at=observed_at,
    )


def build_manual_commit(
    *,
    project_id: UUID,
    spec: ManualSamplingWorkerSpec,
    task_key: str,
    source: SamplingWorkerSource,
    manifest_uri: str,
    observed_at: datetime,
) -> ManualSamplingCommit:
    _require_aware(observed_at, "manual observation time")
    if source.source.capture_method is not CaptureMethod.MANUAL_UI:
        raise WorkflowCSamplingSpecError("manual Job has a non-manual source stratum")
    if source.source.location_control is not LocationControl.NOT_CONTROLLED:
        raise WorkflowCSamplingSpecError("manual evidence cannot claim controlled geography")
    reference = _manifest_reference(manifest_uri)
    actual_location = {
        "location_control": LocationControl.NOT_CONTROLLED.value,
        "location_evidence_hash": source.source.location_evidence_hash,
        "requested_country": source.source.requested_country,
        "requested_region": source.source.requested_region,
        "requested_locale": source.source.requested_locale,
        "requested_language": source.source.requested_language,
        "effective_country": None,
        "effective_region": None,
        "effective_locale": None,
        "effective_language": None,
    }
    evidence = {
        "schema_version": 1,
        "kind": "manual_import",
        "raw_artifact": {
            "kind": "raw",
            "manifest_reference": f"withheld://manual-evidence/raw/{spec.artifact_content_hash}",
            "manifest_hash": spec.artifact_manifest_hash,
            "content_hash": spec.artifact_content_hash,
            "governance_policy_hash": spec.governance_policy_hash,
        },
        "derived_artifact": {
            "kind": "derived",
            "manifest_reference": reference,
            "manifest_hash": spec.artifact_manifest_hash,
            "content_hash": spec.artifact_content_hash,
            "governance_policy_hash": spec.governance_policy_hash,
        },
        "derived_summary": "Approved restricted manual evidence was committed.",
        "evidence_locator": f"{reference}#/redacted-evidence",
        "provider_response_id": None,
        "egress_verification_id": None,
        "result_parameters_hash": canonical_json_hash(
            {
                "manual_import_id": str(spec.manual_import_id),
                "capture_session_id": str(spec.capture_session_id),
                "artifact_manifest_id": str(spec.artifact_manifest_id),
            }
        ),
        "storage_decision": "prohibited",
        "cache_decision": "prohibited",
        "display_decision": "prohibited",
        "redistribution_decision": "prohibited",
        "usage_purpose": "sampling.manual_import",
        "usage_audience": "internal_worker",
    }
    observation_id = _observation_id(task_key, spec.attempt_id, evidence, actual_location)
    return ManualSamplingCommit(
        observation_id=observation_id,
        observation_hash=_observation_hash(
            project_id=project_id,
            run_id=spec.run_id,
            task_id=spec.task_id,
            attempt_id=spec.attempt_id,
            task_key=task_key,
            evidence_status="complete",
            ineligible_reasons=(),
            actual_location=actual_location,
            evidence=evidence,
            observed_at=observed_at,
        ),
        actual_location=actual_location,
        actual_location_hash=canonical_json_hash(actual_location),
        evidence=evidence,
        observed_at=observed_at,
    )


def _provider_artifacts(result: ModelGatewayResult) -> dict[str, Mapping[str, object]]:
    required = (
        result.raw_artifact_manifest_hash,
        result.raw_artifact_content_hash,
        result.raw_artifact_byte_size,
        result.derived_artifact_manifest_hash,
        result.derived_artifact_content_hash,
        result.derived_artifact_byte_size,
        result.raw_artifact_policy_hash,
        result.raw_artifact_storage_decision,
        result.raw_artifact_cache_decision,
        result.raw_artifact_display_decision,
        result.raw_artifact_redistribution_decision,
    )
    if any(value is None for value in required):
        raise WorkflowCSamplingSpecError("provider result artifact lineage is incomplete")
    assert result.raw_artifact_manifest_hash is not None
    assert result.raw_artifact_content_hash is not None
    assert result.raw_artifact_byte_size is not None
    assert result.derived_artifact_manifest_hash is not None
    assert result.derived_artifact_content_hash is not None
    assert result.derived_artifact_byte_size is not None
    assert result.raw_artifact_policy_hash is not None
    assert result.raw_artifact_storage_decision is not None
    if result.raw_artifact_storage_decision == "allowed":
        if (
            result.raw_artifact_reference is None
            or result.derived_artifact_reference is None
            or result.raw_artifact_byte_size < 1
            or result.derived_artifact_byte_size < 1
        ):
            raise WorkflowCSamplingSpecError("allowed provider artifacts are incomplete")
        raw_reference = result.raw_artifact_reference
        derived_reference = result.derived_artifact_reference
    else:
        if (
            result.raw_artifact_storage_decision != "prohibited"
            or result.raw_artifact_reference is not None
            or result.derived_artifact_reference is not None
            or result.raw_artifact_byte_size != 0
            or result.derived_artifact_byte_size != 0
        ):
            raise WorkflowCSamplingSpecError("prohibited provider artifacts were persisted")
        raw_reference = f"withheld://provider-artifact/raw/{result.raw_artifact_manifest_hash}"
        derived_reference = (
            f"withheld://provider-artifact/derived/{result.derived_artifact_manifest_hash}"
        )
    return {
        "raw_artifact": {
            "kind": "raw",
            "manifest_reference": raw_reference,
            "manifest_hash": result.raw_artifact_manifest_hash,
            "content_hash": result.raw_artifact_content_hash,
            "governance_policy_hash": result.raw_artifact_policy_hash,
        },
        "derived_artifact": {
            "kind": "derived",
            "manifest_reference": derived_reference,
            "manifest_hash": result.derived_artifact_manifest_hash,
            "content_hash": result.derived_artifact_content_hash,
            "governance_policy_hash": result.raw_artifact_policy_hash,
        },
    }


def _observation_id(
    task_key: str,
    attempt_id: UUID,
    evidence: Mapping[str, object],
    actual_location: Mapping[str, object],
) -> UUID:
    return uuid5(
        SAMPLING_OBSERVATION_NAMESPACE,
        canonical_json_hash(
            {
                "task_key": task_key,
                "attempt_id": str(attempt_id),
                "evidence": evidence,
                "actual_location": actual_location,
            }
        ),
    )


def _observation_hash(
    *,
    project_id: UUID,
    run_id: UUID,
    task_id: UUID,
    attempt_id: UUID,
    task_key: str,
    evidence_status: str,
    ineligible_reasons: tuple[str, ...],
    actual_location: Mapping[str, object],
    evidence: Mapping[str, object],
    observed_at: datetime,
) -> str:
    return canonical_json_hash(
        {
            "project_id": str(project_id),
            "run_id": str(run_id),
            "task_id": str(task_id),
            "attempt_id": str(attempt_id),
            "task_key": task_key,
            "evidence_status": evidence_status,
            "ineligible_reasons": list(ineligible_reasons),
            "actual_location": actual_location,
            "evidence": evidence,
            "observed_at": observed_at.isoformat(),
        }
    )


def _manifest_reference(value: str) -> str:
    reference = value.strip()
    if not reference or len(reference) > 2_000:
        raise WorkflowCSamplingSpecError("manual artifact manifest URI is invalid")
    return reference


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise WorkflowCSamplingSpecError(f"{label} must be timezone-aware")


__all__ = ["build_manual_commit", "build_provider_commit"]
