from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
import json
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from geo_core.sampling.provider_canary import (
    ProviderCanaryAttemptEvidence,
    ProviderCanaryAttemptStatus,
    ProviderCanaryError,
    ProviderCanaryPlannedTask,
    ProviderCanaryRunEvidence,
    build_provider_canary_manifest,
    verify_provider_canary_manifest,
)
from geo_core.sampling.provider_release import (
    ProviderReportedModelPolicy,
    ProviderSamplingRelease,
    ProviderSamplingReleaseError,
    ProviderSamplingReleaseState,
    provider_sampling_release_from_value,
)
from geo_core.sampling.provider_sources import canonical_provider_source


NOW = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("provider", "search_mode"),
    (
        ("openai", "web"),
        ("gemini", "google_search"),
        ("perplexity", "web"),
        ("microsoft", "bing_grounding"),
        ("kimi", "disabled"),
    ),
)
def test_five_provider_canaries_produce_replayable_redacted_manifests(
    provider: str, search_mode: str
) -> None:
    release = _release(provider, search_mode=search_mode)
    run = _run(release)

    first = build_provider_canary_manifest(release, run, generated_at=run.completed_at)
    second = build_provider_canary_manifest(release, run, generated_at=run.completed_at)

    assert first == second
    assert first.manifest_hash == second.manifest_hash
    assert first.valid_task_count == 10
    assert verify_provider_canary_manifest(first.value(), release) == first.manifest_hash
    serialized = repr(first.value()).lower()
    for prohibited in ("answer", "prompt", "authorization", "api_key", "s3://"):
        assert prohibited not in serialized
    assert provider_sampling_release_from_value(release.value()) == release


def test_gemini_canary_uses_google_metric_identity_and_gemini_gateway_route() -> None:
    release = _release("gemini", search_mode="google_search")
    manifest = build_provider_canary_manifest(
        release, _run(release), generated_at=NOW + timedelta(minutes=2)
    )

    assert manifest.platform == "google"
    assert manifest.surface == "google_gemini_api"
    assert {call["provider"] for call in manifest.calls} == {"gemini"}


def test_kimi_search_must_remain_disabled_without_native_capability_evidence() -> None:
    with pytest.raises(ProviderSamplingReleaseError, match="search_mode=disabled"):
        _release("kimi", search_mode="web")


def test_live_release_state_requires_canary_and_publisher_evidence() -> None:
    release = _release("openai", search_mode="web")

    with pytest.raises(ProviderSamplingReleaseError, match="real live canary"):
        replace(release, state=ProviderSamplingReleaseState.APPROVED)


def test_canary_rejects_insufficient_completion_without_rewriting_denominator() -> None:
    release = _release("openai", search_mode="web")
    run = _run(release)
    calls = tuple(
        replace(
            item,
            status=ProviderCanaryAttemptStatus.FAILED,
            provider_reported_model=None,
            provider_request_id=None,
            response_hash=None,
            output_hash=None,
            observation_id=None,
            observation_hash=None,
            raw_artifact_manifest_hash=None,
            derived_artifact_manifest_hash=None,
            evidence_status=None,
            location_evidence_hash=None,
            error_code="quota",
            error_retryable=False,
        )
        if item.repetition >= 8
        else item
        for item in run.calls
    )
    run = replace(run, run_status="completed", calls=calls)

    assert len(run.planned_task_keys) == 10
    assert run.valid_task_count == 7
    with pytest.raises(ProviderCanaryError, match="80%"):
        build_provider_canary_manifest(release, run, generated_at=run.completed_at)


def test_canary_detects_silent_model_change_and_missing_search_tool() -> None:
    release = _release("openai", search_mode="web")
    run = _run(release)

    changed_model = replace(
        run,
        calls=(
            replace(run.calls[0], provider_reported_model="silent-model-change"),
            *run.calls[1:],
        ),
    )
    with pytest.raises(ProviderCanaryError, match="reported model"):
        build_provider_canary_manifest(
            release, changed_model, generated_at=changed_model.completed_at
        )

    no_search = replace(
        run,
        calls=(
            replace(run.calls[0], search_event_count=0),
            *run.calls[1:],
        ),
    )
    with pytest.raises(ProviderCanaryError, match="search/citation"):
        build_provider_canary_manifest(
            release, no_search, generated_at=no_search.completed_at
        )


def test_manifest_and_release_reject_unknown_or_tampered_fields() -> None:
    release = _release("kimi", search_mode="disabled")
    release_value = release.value()
    release_value["secret"] = "must-not-fit"
    with pytest.raises(ProviderSamplingReleaseError, match="allowlisted"):
        provider_sampling_release_from_value(release_value)

    manifest = build_provider_canary_manifest(
        release, _run(release), generated_at=NOW + timedelta(minutes=2)
    ).value()
    manifest["valid_task_count"] = 9
    with pytest.raises(ProviderCanaryError, match="hash does not match"):
        verify_provider_canary_manifest(manifest, release)


def test_verifier_rejects_semantic_forgery_even_with_recalculated_hash() -> None:
    release = _release("openai", search_mode="web")
    manifest = build_provider_canary_manifest(
        release, _run(release), generated_at=NOW + timedelta(minutes=2)
    ).value()
    manifest["valid_task_count"] = 9
    manifest["manifest_hash"] = _value_hash(
        {key: value for key, value in manifest.items() if key != "manifest_hash"}
    )

    with pytest.raises(ProviderCanaryError, match="canonical or coherent"):
        verify_provider_canary_manifest(manifest, release)


def test_release_rejects_credential_urls_and_contradictory_raw_policy() -> None:
    release = _release("openai", search_mode="web")

    with pytest.raises(ProviderSamplingReleaseError, match="credential-free HTTPS"):
        replace(
            release,
            documentation_references=("https://docs.example.test/api?token=secret",),
        )
    with pytest.raises(ProviderSamplingReleaseError, match="zero retention"):
        replace(
            release,
            raw_storage_decision="prohibited",
            raw_display_decision="allowed",
        )
    with pytest.raises(ProviderSamplingReleaseError, match="full Git object ID"):
        replace(release, source_commit="main")


def _release(provider: str, *, search_mode: str) -> ProviderSamplingRelease:
    source = canonical_provider_source(provider)
    return ProviderSamplingRelease(
        release_id=f"{provider}-provider-sampling-v1",
        gateway_provider=provider,
        platform=source.platform,
        surface=source.surface,
        capture_method=source.capture_method,
        adapter_release_id=f"{provider}-adapter-v1",
        adapter_release_hash=_hash(f"{provider}:adapter"),
        model_release_id=f"{provider}-model-v1",
        model_release_hash=_hash(f"{provider}:model"),
        configured_model=f"{provider}-configured-model",
        reported_model_policy=ProviderReportedModelPolicy.EXACT,
        allowed_reported_models=(f"{provider}-reported-model",),
        search_mode=search_mode,
        native_search_verified=provider != "kimi",
        request_contract_hash=_hash(f"{provider}:request"),
        result_contract_hash=_hash(f"{provider}:result"),
        error_contract_hash=_hash(f"{provider}:error"),
        citation_contract_hash=_hash(f"{provider}:citation"),
        location_contract_hash=_hash(f"{provider}:location"),
        fixture_corpus_hash=_hash(f"{provider}:fixtures"),
        contract_test_result_hash=_hash(f"{provider}:tests"),
        dependency_lock_hash=_hash("uv.lock"),
        data_policy_hash=_hash(f"{provider}:policy"),
        raw_storage_decision="allowed",
        raw_display_decision="allowed",
        raw_retention_days=30,
        documentation_references=(f"https://docs.example.test/{provider}",),
        owner="geo-platform",
        source_commit="a" * 40,
        state=ProviderSamplingReleaseState.FIXTURE_READY,
    )


def _run(release: ProviderSamplingRelease) -> ProviderCanaryRunEvidence:
    tasks = tuple(
        ProviderCanaryPlannedTask(
            task_key=_hash(f"{release.gateway_provider}:task:{repetition}"),
            task_id=_uuid(f"{release.gateway_provider}:task:{repetition}"),
            question_id="provider-canary-question",
            question_version="v1",
            repetition=repetition,
        )
        for repetition in range(1, 11)
    )
    calls = tuple(_call(release, task) for task in tasks)
    return ProviderCanaryRunEvidence(
        project_id=_uuid("project"),
        suite_id=_uuid(f"{release.gateway_provider}:suite"),
        suite_hash=_hash(f"{release.gateway_provider}:suite"),
        run_id=_uuid(f"{release.gateway_provider}:run"),
        run_status="completed",
        purpose="provider_live_canary",
        platform=release.platform,
        surface=release.surface,
        capture_method=release.capture_method,
        source_stratum_hash=_hash(f"{release.gateway_provider}:source"),
        adapter_release_id=release.adapter_release_id,
        adapter_release_hash=release.adapter_release_hash,
        model_release_id=release.model_release_id,
        model_release_hash=release.model_release_hash,
        planned_tasks=tasks,
        calls=calls,
        started_at=NOW,
        completed_at=NOW + timedelta(minutes=1),
    )


def _call(
    release: ProviderSamplingRelease, task: ProviderCanaryPlannedTask
) -> ProviderCanaryAttemptEvidence:
    provider = release.gateway_provider
    citations = 0 if release.search_mode == "disabled" else (2 if provider == "microsoft" else 1)
    searches = 0 if release.search_mode == "disabled" else 1
    return ProviderCanaryAttemptEvidence(
        sampling_attempt_id=_uuid(f"{task.task_key}:sampling"),
        durable_job_id=_uuid(f"{task.task_key}:job"),
        model_call_attempt_id=_uuid(f"{task.task_key}:model"),
        task_id=task.task_id,
        task_key=task.task_key,
        question_id=task.question_id,
        question_version=task.question_version,
        repetition=task.repetition,
        status=ProviderCanaryAttemptStatus.SUCCEEDED,
        provider=provider,
        adapter_release_id=release.adapter_release_id,
        adapter_release_hash=release.adapter_release_hash,
        model_release_id=release.model_release_id,
        model_release_hash=release.model_release_hash,
        configured_model=release.configured_model,
        provider_reported_model=release.allowed_reported_models[0],
        provider_request_id=f"{provider}-request-{task.repetition}",
        capture_method=release.capture_method,
        search_mode=release.search_mode,
        citation_count=citations,
        citation_lineage_hash=_hash(f"{task.task_key}:citations"),
        search_event_count=searches,
        search_lineage_hash=_hash(f"{task.task_key}:search"),
        usage_details_hash=_hash(f"{task.task_key}:usage"),
        raw_artifact_policy_hash=release.data_policy_hash,
        raw_storage_decision=release.raw_storage_decision,
        raw_display_decision=release.raw_display_decision,
        raw_retention_days=release.raw_retention_days,
        response_hash=_hash(f"{task.task_key}:response"),
        output_hash=_hash(f"{task.task_key}:output"),
        observation_id=_uuid(f"{task.task_key}:observation"),
        observation_hash=_hash(f"{task.task_key}:observation"),
        raw_artifact_manifest_hash=_hash(f"{task.task_key}:raw"),
        derived_artifact_manifest_hash=_hash(f"{task.task_key}:derived"),
        evidence_status="complete",
        location_evidence_hash=_hash(f"{task.task_key}:location"),
        error_code=None,
        error_retryable=None,
        occurred_at=NOW + timedelta(seconds=task.repetition),
    )


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _value_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _uuid(value: str) -> UUID:
    return uuid5(NAMESPACE_URL, value)
