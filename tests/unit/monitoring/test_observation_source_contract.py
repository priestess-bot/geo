from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from typing import Any, cast
from uuid import uuid4

import pytest

from geo_core.monitoring.source_contract import (
    CaptureMethod,
    ClientKind,
    ModelIdentity,
    ModelIdentityState,
    ObservationDevice,
    ObservationPlatform,
    ObservationRunParameters,
    ObservationSource,
    ObservationSurface,
    LEGACY_SOURCE_STRATUM_CONTRACT_VERSION,
    RawEvidence,
    RawEvidenceKind,
    SearchMode,
    SurfaceKind,
)
from geo_core.monitoring.postgres_mappers import source_stratum_from_value


def test_f009_domain_01_all_public_capture_methods_build_separate_strata() -> None:
    sources = (
        _source(CaptureMethod.MANUAL_UI),
        _source(CaptureMethod.PROVIDER_API),
        _source(CaptureMethod.PROXY_GROUNDED_API),
        _source(CaptureMethod.SYNTHETIC),
    )

    assert all(
        not item.eligibility_reasons(result_succeeded=True)
        for item in sources
        if item.capture_method != CaptureMethod.SYNTHETIC
    )
    assert sources[-1].eligibility_reasons(result_succeeded=True) == (
        "synthetic_test_only",
    )
    assert len({item.stratum_key().canonical_hash() for item in sources}) == len(sources)


def test_kimi_api_has_a_first_class_provider_source_identity() -> None:
    source = replace(
        _source(CaptureMethod.PROVIDER_API),
        platform=ObservationPlatform.KIMI,
        surface=ObservationSurface.KIMI_API,
        run=replace(
            _source(CaptureMethod.PROVIDER_API).run,
            engine="kimi",
            search_enabled=False,
            search_mode=SearchMode.DISABLED,
            adapter_name="kimi",
        ),
    )

    assert not source.hard_violations()
    assert source.stratum_key().platform is ObservationPlatform.KIMI
    assert source.stratum_key().surface is ObservationSurface.KIMI_API


@pytest.mark.parametrize(
    ("method", "surface", "kind"),
    [
        (CaptureMethod.PROVIDER_API, ObservationSurface.CHATGPT_SEARCH, SurfaceKind.CONSUMER_UI),
        (CaptureMethod.PROXY_GROUNDED_API, ObservationSurface.CLAUDE_AI, SurfaceKind.CONSUMER_UI),
        (CaptureMethod.MANUAL_UI, ObservationSurface.OPENAI_API, SurfaceKind.PROVIDER_API),
        (
            CaptureMethod.PROVIDER_API,
            ObservationSurface.BING_COPILOT,
            SurfaceKind.CONSUMER_UI,
        ),
    ],
)
def test_f009_domain_01_api_and_proxy_cannot_claim_consumer_ui(
    method: CaptureMethod, surface: ObservationSurface, kind: SurfaceKind
) -> None:
    source = replace(
        _source(method),
        surface=surface,
        surface_kind=kind,
        platform=_platform(surface),
    )

    assert "capture_surface_kind_mismatch" in source.hard_violations()


@pytest.mark.parametrize("missing", ["engine", "locale", "region", "language"])
def test_f009_domain_01_key_runtime_parameters_are_required(missing: str) -> None:
    source = _source(CaptureMethod.MANUAL_UI)
    source = replace(
        source, run=replace(source.run, **cast(Any, {missing: None}))
    )

    assert f"missing_{missing}" in source.eligibility_reasons(result_succeeded=True)


def test_f009_domain_01_citation_capture_must_be_explicit_even_when_empty() -> None:
    source = replace(_source(CaptureMethod.MANUAL_UI), citations_captured=False)

    assert "citation_capture_not_confirmed" in source.eligibility_reasons(
        result_succeeded=True
    )


def test_f009_domain_01_artifact_must_be_server_verified() -> None:
    source = _source(CaptureMethod.MANUAL_UI)
    source = replace(
        source,
        raw_evidence=RawEvidence(
            RawEvidenceKind.ARTIFACT,
            artifact_uri="s3://geo/observation-artifacts/project/raw.json",
            artifact_hash="a" * 64,
        ),
    )

    assert "missing_or_unverified_raw_evidence" in source.eligibility_reasons(
        result_succeeded=True
    )
    verified = replace(
        source,
        raw_evidence=replace(source.raw_evidence, artifact_verified=True),
    )
    assert not verified.eligibility_reasons(result_succeeded=True)


def test_f009_domain_01_other_platform_and_surface_require_details() -> None:
    source = replace(
        _source(CaptureMethod.MANUAL_UI),
        platform=ObservationPlatform.OTHER,
        surface=ObservationSurface.OTHER,
        surface_kind=SurfaceKind.CONSUMER_UI,
        platform_detail=None,
        surface_detail=None,
    )

    assert set(source.hard_violations()) >= {
        "missing_platform_detail",
        "missing_surface_detail",
    }
    with pytest.raises(ValueError, match="platform detail"):
        source.stratum_key()


def test_source_stratum_v3_details_have_distinct_canonical_hashes() -> None:
    first_source = replace(
        _source(CaptureMethod.MANUAL_UI),
        platform=ObservationPlatform.OTHER,
        surface=ObservationSurface.OTHER,
        surface_kind=SurfaceKind.CONSUMER_UI,
        platform_detail="answer-engine-a",
        surface_detail="consumer-surface-a",
    )
    second_source = replace(
        first_source,
        platform_detail="answer-engine-b",
        surface_detail="consumer-surface-b",
    )

    first = first_source.stratum_key()
    second = second_source.stratum_key()

    assert first.canonical_value()["platform_detail"] == "answer-engine-a"
    assert first.canonical_value()["surface_detail"] == "consumer-surface-a"
    assert first.canonical_hash() != second.canonical_hash()
    assert first_source.source_identity_hash() == first.canonical_hash()


def test_known_source_enums_reject_non_null_details() -> None:
    source = replace(
        _source(CaptureMethod.MANUAL_UI),
        platform_detail="must-not-be-present",
    )

    assert "unexpected_platform_detail" in source.hard_violations()
    with pytest.raises(ValueError, match="exactly for OTHER"):
        source.stratum_key()


def test_legacy_source_stratum_json_preserves_its_v2_hash() -> None:
    current_value = _source(CaptureMethod.MANUAL_UI).stratum_key().canonical_value()
    legacy_value = {
        key: value
        for key, value in current_value.items()
        if key not in {"platform_detail", "surface_detail"}
    }
    expected = hashlib.sha256(
        json.dumps(
            legacy_value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()

    restored = source_stratum_from_value(legacy_value)

    assert restored.source_contract_version == LEGACY_SOURCE_STRATUM_CONTRACT_VERSION
    assert restored.canonical_value() == legacy_value
    assert restored.canonical_hash() == expected


def test_f009_domain_01_unknown_is_history_only_and_never_eligible() -> None:
    source = ObservationSource.legacy_unknown(
        raw_evidence=RawEvidence(RawEvidenceKind.LEGACY_UNKNOWN),
        configured_model="legacy-model",
        reported_model=None,
    )

    assert "legacy_unknown_capture_method" in source.eligibility_reasons(
        result_succeeded=True
    )


def test_f009_domain_01_synthetic_requires_controlled_lineage_and_flags() -> None:
    source = _source(CaptureMethod.SYNTHETIC)
    invalid = replace(source, source_job_id=None, publication_eligible=True)

    assert "invalid_synthetic_lineage" in invalid.hard_violations()
    assert source.test_only
    assert not source.publication_eligible


def test_f009_domain_01_model_disclosure_never_uses_fake_unknown_value() -> None:
    undisclosed = ModelIdentity(ModelIdentityState.NOT_DISCLOSED)

    assert undisclosed.value is None
    with pytest.raises(ValueError, match="cannot carry"):
        ModelIdentity(ModelIdentityState.NOT_DISCLOSED, "unknown")


def _source(method: CaptureMethod) -> ObservationSource:
    configured = ModelIdentity(ModelIdentityState.DISCLOSED, "model-v1")
    reported = ModelIdentity(ModelIdentityState.NOT_DISCLOSED)
    source_job_id = model_call_log_id = None
    test_only = False
    publication_eligible = True
    if method == CaptureMethod.MANUAL_UI:
        platform = ObservationPlatform.OPENAI
        surface = ObservationSurface.CHATGPT_SEARCH
        kind = SurfaceKind.CONSUMER_UI
        device = ObservationDevice.DESKTOP
        client = ClientKind.BROWSER
        adapter_name = adapter_version = provider_request_id = None
        mode = SearchMode.LIVE_WEB
    elif method == CaptureMethod.PROVIDER_API:
        platform = ObservationPlatform.OPENAI
        surface = ObservationSurface.OPENAI_API
        kind = SurfaceKind.PROVIDER_API
        device = ObservationDevice.API
        client = ClientKind.API
        adapter_name, adapter_version, provider_request_id = "openai", "1", "req-1"
        mode = SearchMode.LIVE_WEB
    elif method == CaptureMethod.PROXY_GROUNDED_API:
        platform = ObservationPlatform.MICROSOFT
        surface = ObservationSurface.MICROSOFT_FOUNDRY_BING_GROUNDING
        kind = SurfaceKind.GROUNDED_PROXY
        device = ObservationDevice.API
        client = ClientKind.API
        adapter_name, adapter_version, provider_request_id = "foundry", "1", "req-2"
        mode = SearchMode.GROUNDED_WEB
    elif method == CaptureMethod.SYNTHETIC:
        platform = ObservationPlatform.OTHER
        surface = ObservationSurface.INTERNAL_BENCHMARK
        kind = SurfaceKind.INTERNAL_BENCHMARK
        device = ObservationDevice.INTERNAL_WORKER
        client = ClientKind.INTERNAL_WORKER
        adapter_name, adapter_version, provider_request_id = "controlled", "1", None
        mode = SearchMode.DISABLED
        source_job_id, model_call_log_id = uuid4(), uuid4()
        test_only, publication_eligible = True, False
    else:
        raise AssertionError(f"unsupported fixture method: {method}")
    return ObservationSource(
        capture_method=method,
        platform=platform,
        surface=surface,
        surface_kind=kind,
        platform_detail="deepseek" if platform == ObservationPlatform.OTHER else None,
        surface_detail=None,
        configured_model=configured,
        reported_model=reported,
        run=ObservationRunParameters(
            engine=platform.value,
            locale="en-AU",
            region="AU",
            language="en",
            device=device,
            client_kind=client,
            search_enabled=mode != SearchMode.DISABLED,
            search_mode=mode,
            prompt_text="Which product should I choose?",
            adapter_name=adapter_name,
            adapter_version=adapter_version,
            provider_request_id=provider_request_id,
        ),
        raw_evidence=RawEvidence(RawEvidenceKind.ANSWER, answer="A complete answer."),
        citations_captured=True,
        source_job_id=source_job_id,
        model_call_log_id=model_call_log_id,
        test_only=test_only,
        publication_eligible=publication_eligible,
    )


def _platform(surface: ObservationSurface) -> ObservationPlatform:
    if surface in {ObservationSurface.CHATGPT_SEARCH, ObservationSurface.OPENAI_API}:
        return ObservationPlatform.OPENAI
    if surface == ObservationSurface.CLAUDE_AI:
        return ObservationPlatform.ANTHROPIC
    if surface == ObservationSurface.BING_COPILOT:
        return ObservationPlatform.MICROSOFT
    raise AssertionError(surface)
