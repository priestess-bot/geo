from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import hashlib
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from geo_core.sampling.provider_canary import ProviderCanaryError
from geo_core.sampling.provider_release import (
    ProviderReportedModelPolicy,
    ProviderSamplingRelease,
    ProviderSamplingReleaseState,
)
from geo_core.sampling.provider_sources import canonical_provider_source
from scripts.workflow_c_provider_canary import (
    HttpCanaryApi,
    execute_provider_canary,
)


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
PROJECT_ID = uuid5(NAMESPACE_URL, "provider-canary-project")
SUITE_ID = uuid5(NAMESPACE_URL, "provider-canary-suite")
RUN_ID = uuid5(NAMESPACE_URL, "provider-canary-run")


def test_execute_verifies_suite_and_idempotent_start_and_enqueue() -> None:
    release = _release()
    api = FakeCanaryApi(release)

    result = execute_provider_canary(
        api,
        release=release,
        project_id=PROJECT_ID,
        suite_id=SUITE_ID,
        requested_not_before=NOW,
        idempotency_prefix="openai-canary-20260724",
        poll_interval_seconds=0.01,
        timeout_seconds=1,
        sleep=lambda _: None,
    )

    assert result == RUN_ID
    assert [item[3] for item in api.calls if item[0] == "POST"] == [
        "openai-canary-20260724:start",
        "openai-canary-20260724:start",
        "openai-canary-20260724:enqueue",
        "openai-canary-20260724:enqueue",
    ]
    start = api.calls[1][2]
    assert start == {
        "purpose": "provider_live_canary",
        "requested_not_before": NOW.isoformat(),
    }
    assert "prompt" not in repr(api.calls).lower()


def test_execute_fails_before_start_for_mismatched_release_lineage() -> None:
    release = _release()
    api = FakeCanaryApi(release)
    api.suite["adapter_release_hash"] = _hash("forged")

    with pytest.raises(ProviderCanaryError, match="release lineage differs"):
        execute_provider_canary(
            api,
            release=release,
            project_id=PROJECT_ID,
            suite_id=SUITE_ID,
            requested_not_before=NOW,
            idempotency_prefix="canary",
            poll_interval_seconds=0.01,
            timeout_seconds=1,
            sleep=lambda _: None,
        )

    assert [item[0] for item in api.calls] == ["GET"]


def test_execute_rejects_non_replayable_enqueue_and_terminal_failure() -> None:
    release = _release()
    api = FakeCanaryApi(release, corrupt_enqueue_replay=True)
    with pytest.raises(ProviderCanaryError, match="did not replay exactly"):
        _execute(api, release)

    failed = FakeCanaryApi(release, final_status="failed")
    with pytest.raises(ProviderCanaryError, match="ended as failed"):
        _execute(failed, release)


def test_execute_times_out_without_rewriting_the_run() -> None:
    release = _release()
    api = FakeCanaryApi(release, final_status="running")
    ticks = iter((0.0, 2.0))

    with pytest.raises(ProviderCanaryError, match="before timeout"):
        execute_provider_canary(
            api,
            release=release,
            project_id=PROJECT_ID,
            suite_id=SUITE_ID,
            requested_not_before=NOW,
            idempotency_prefix="canary",
            poll_interval_seconds=0.01,
            timeout_seconds=1,
            sleep=lambda _: None,
            monotonic=lambda: next(ticks),
        )


def test_http_client_reads_auth_only_from_environment_and_requires_tls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOKEN", "secret-token")
    client = HttpCanaryApi.from_environment(
        base_url="https://internal.example.test",
        request_timeout_seconds=30,
        authorization_env="TOKEN",
        actor_id_env="ACTOR",
        tenant_id_env="TENANT",
    )
    assert client.headers == {"Authorization": "Bearer secret-token"}

    monkeypatch.delenv("TOKEN")
    monkeypatch.setenv("ACTOR", "canary-operator")
    monkeypatch.setenv("TENANT", str(uuid5(NAMESPACE_URL, "tenant")))
    development = HttpCanaryApi.from_environment(
        base_url="http://127.0.0.1:18000",
        request_timeout_seconds=30,
        authorization_env="TOKEN",
        actor_id_env="ACTOR",
        tenant_id_env="TENANT",
    )
    assert set(development.headers) == {"X-GEO-Actor-ID", "X-GEO-Tenant-ID"}

    with pytest.raises(ProviderCanaryError, match="requires HTTPS"):
        HttpCanaryApi(
            base_url="http://internal.example.test",
            headers={},
            request_timeout_seconds=30,
        )


def _execute(api: "FakeCanaryApi", release: ProviderSamplingRelease) -> UUID:
    return execute_provider_canary(
        api,
        release=release,
        project_id=PROJECT_ID,
        suite_id=SUITE_ID,
        requested_not_before=NOW,
        idempotency_prefix="canary",
        poll_interval_seconds=0.01,
        timeout_seconds=1,
        sleep=lambda _: None,
    )


class FakeCanaryApi:
    def __init__(
        self,
        release: ProviderSamplingRelease,
        *,
        corrupt_enqueue_replay: bool = False,
        final_status: str = "completed",
    ) -> None:
        self.release = release
        self.corrupt_enqueue_replay = corrupt_enqueue_replay
        self.final_status = final_status
        self.calls: list[
            tuple[str, str, Mapping[str, object] | None, str | None]
        ] = []
        self.suite = _suite(release)
        self.post_count = 0

    def request(
        self,
        method: str,
        path: str,
        body: Mapping[str, object] | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> Mapping[str, object]:
        self.calls.append((method, path, body, idempotency_key))
        if method == "GET" and path.endswith(f"/suites/{SUITE_ID}"):
            return self.suite
        if method == "POST" and path.endswith(f"/suites/{SUITE_ID}/runs"):
            self.post_count += 1
            return {"run": _run("planned"), "suite": self.suite}
        if method == "POST" and path.endswith(f"/runs/{RUN_ID}/enqueue-ready"):
            self.post_count += 1
            attempt_ids = [str(uuid5(NAMESPACE_URL, f"attempt:{index}")) for index in range(10)]
            is_replay = self.post_count == 4
            if is_replay and self.corrupt_enqueue_replay:
                attempt_ids[-1] = str(uuid5(NAMESPACE_URL, "forged-attempt"))
            return {
                "run_id": str(RUN_ID),
                "planned_task_count": 10,
                "enqueued_count": 0 if is_replay else 10,
                "replayed_count": 10 if is_replay else 0,
                "skipped_count": 0,
                "attempt_ids": attempt_ids,
                "first_not_before": NOW.isoformat(),
                "last_not_before": NOW.isoformat(),
                "replayed": is_replay,
            }
        if method == "GET" and path.endswith(f"/runs/{RUN_ID}"):
            return {
                "run": _run(self.final_status),
                "suite": self.suite,
                "tasks": [],
                "attempts": [],
                "observations": [],
                "assessment": {},
            }
        raise AssertionError((method, path))


def _suite(release: ProviderSamplingRelease) -> dict[str, object]:
    return {
        "id": str(SUITE_ID),
        "project_id": str(PROJECT_ID),
        "question_set_id": str(uuid5(NAMESPACE_URL, "question-set")),
        "question_set_version": "v1",
        "question_set_hash": _hash("question-set"),
        "adapter_release_id": release.adapter_release_id,
        "adapter_release_hash": release.adapter_release_hash,
        "model_release_id": release.model_release_id,
        "model_release_hash": release.model_release_hash,
        "questions": [
            {
                "question_id": "provider-canary-question",
                "question_version": "v1",
                "text_hash": _hash("question"),
            }
        ],
        "source_stratum": {
            "platform": release.platform,
            "surface": release.surface,
            "capture_method": release.capture_method.value,
            "configured_model": release.configured_model,
            "reported_model": release.allowed_reported_models[0],
            "adapter_release": release.adapter_release_id,
            "search_mode": release.search_mode,
        },
        "repetitions": 10,
        "planned_task_count": 10,
        "suite_hash": _hash("suite"),
    }


def _run(status: str) -> dict[str, object]:
    return {
        "id": str(RUN_ID),
        "project_id": str(PROJECT_ID),
        "suite_id": str(SUITE_ID),
        "suite_hash": _hash("suite"),
        "admission_policy_id": str(uuid5(NAMESPACE_URL, "policy")),
        "admission_policy_hash": _hash("policy"),
        "admission_grant_hash": _hash("grant"),
        "purpose": "provider_live_canary",
        "authorization_reference": "provider-terms-v1",
        "authorization_valid_until": "2026-08-24T12:00:00+00:00",
        "admission_policy_version": "v1",
        "reserved_task_count": 10,
        "planned_task_keys": [_hash(f"task:{index}") for index in range(10)],
        "status": status,
        "admitted_not_before": NOW.isoformat(),
        "created_at": NOW.isoformat(),
        "version": 1,
    }


def _release() -> ProviderSamplingRelease:
    provider = "openai"
    source = canonical_provider_source(provider)
    return ProviderSamplingRelease(
        release_id="openai-provider-sampling-v1",
        gateway_provider=provider,
        platform=source.platform,
        surface=source.surface,
        capture_method=source.capture_method,
        adapter_release_id=str(uuid5(NAMESPACE_URL, "adapter")),
        adapter_release_hash=_hash("adapter"),
        model_release_id=str(uuid5(NAMESPACE_URL, "model")),
        model_release_hash=_hash("model"),
        configured_model="openai-configured-model",
        reported_model_policy=ProviderReportedModelPolicy.EXACT,
        allowed_reported_models=("openai-reported-model",),
        search_mode="web",
        native_search_verified=True,
        request_contract_hash=_hash("request"),
        result_contract_hash=_hash("result"),
        error_contract_hash=_hash("error"),
        citation_contract_hash=_hash("citation"),
        location_contract_hash=_hash("location"),
        fixture_corpus_hash=_hash("fixtures"),
        contract_test_result_hash=_hash("tests"),
        dependency_lock_hash=_hash("lock"),
        data_policy_hash=_hash("policy"),
        raw_storage_decision="allowed",
        raw_display_decision="allowed",
        raw_retention_days=30,
        documentation_references=("https://example.test/openai",),
        owner="geo-platform",
        source_commit="a" * 40,
        state=ProviderSamplingReleaseState.FIXTURE_READY,
    )


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
