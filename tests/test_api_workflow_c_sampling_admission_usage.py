from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from fastapi.testclient import TestClient
import pytest

from geo_api.workflow_c_runtime import WorkflowCApi
from geo_api.workflow_c_sampling_contracts import (
    AdmissionPolicyDecisionRequest,
    AdmissionPolicySubmitRequest,
    CreateAdmissionPolicyRequest,
)
from geo_api.workflow_c_sampling_policy_runtime import SamplingAdmissionRuntimeOption
from geo_core.sampling import CaptureMethod, SamplingRuleViolation
from tests.workflow_c_api_test_support import (
    NOW,
    PROJECT_ID,
    install_provider_policy,
    install_admission_runtime_option,
    install_suite_inputs,
    internal_app,
    provider_suite_payload,
)


def test_manual_ui_runtime_option_cannot_self_declare_controlled_au_location() -> None:
    _, api, _, _ = internal_app()

    with pytest.raises(SamplingRuleViolation, match="cannot claim controlled geography"):
        api.sampling.policies.install_runtime_option(
            project_id=PROJECT_ID,
            option=SamplingAdmissionRuntimeOption(
                option_key="forged-manual-au",
                display_name="Forged manual AU control",
                platform="consumer-ui",
                capture_method=CaptureMethod.MANUAL_UI,
                adapter_release="manual-ui-v1",
                location_control="country",
                location_evidence_hash="a" * 64,
                authorization_reference="manual-authority",
                allowed_purposes=("geo_measurement",),
            ),
        )


def test_run_reservation_is_idempotent_and_cancel_releases_only_unused_quota() -> None:
    app, api, _, _ = internal_app()
    install_provider_policy(api)
    suites = f"/v1/projects/{PROJECT_ID}/sampling/suites"

    with TestClient(app) as client:
        suite = client.post(
            suites,
            headers={"Idempotency-Key": "suite:reservation"},
            json=provider_suite_payload(),
        ).json()
        run_path = f"{suites}/{suite['id']}/runs"
        payload = {
            "purpose": "geo_measurement",
            "requested_not_before": NOW.isoformat(),
        }
        first = client.post(
            run_path,
            headers={"Idempotency-Key": "run:reservation:first"},
            json=payload,
        )
        replay = client.post(
            run_path,
            headers={"Idempotency-Key": "run:reservation:first"},
            json=payload,
        )
        exhausted = client.post(
            run_path,
            headers={"Idempotency-Key": "run:reservation:second"},
            json=payload,
        )
        first_run_id = UUID(first.json()["run"]["id"])
        cancelled = client.post(
            f"/v1/projects/{PROJECT_ID}/sampling/runs/{first_run_id}/cancel",
            headers={"Idempotency-Key": "cancel:reservation:first"},
        )
        admitted_after_release = client.post(
            run_path,
            headers={"Idempotency-Key": "run:reservation:second"},
            json=payload,
        )

    assert first.status_code == replay.status_code == 201
    assert first.json()["run"]["id"] == replay.json()["run"]["id"]
    assert exhausted.status_code == 422
    assert cancelled.status_code == 200
    assert admitted_after_release.status_code == 201
    reservation = api.sampling.policies.reservation(
        project_id=PROJECT_ID,
        run_id=first_run_id,
    )
    assert reservation.reserved_task_count == reservation.released_task_count == 10
    assert reservation.consumed_task_count == reservation.unused_task_count == 0


def test_policy_usage_window_and_claim_gate_apply_across_runs() -> None:
    app, api, clock, _ = internal_app()
    policy_id, _ = _install_provider_policy(
        api,
        key="provider-policy:shared-gate",
        quota_remaining=20,
        daily_task_limit=20,
        minimum_request_interval_seconds=2,
        max_concurrency=1,
    )
    suite_payload = provider_suite_payload(
        admission_policy_id=policy_id,
    )
    suite_payload["max_concurrency"] = 1
    suites = f"/v1/projects/{PROJECT_ID}/sampling/suites"

    with TestClient(app) as client:
        suite = client.post(
            suites,
            headers={"Idempotency-Key": "suite:shared-gate"},
            json=suite_payload,
        ).json()
        runs = []
        for index in (1, 2):
            detail = client.post(
                f"{suites}/{suite['id']}/runs",
                headers={"Idempotency-Key": f"run:shared-gate:{index}"},
                json={
                    "purpose": "geo_measurement",
                    "requested_not_before": NOW.isoformat(),
                },
            ).json()
            task = detail["tasks"][0]
            attempt = client.post(
                f"/v1/projects/{PROJECT_ID}/sampling/runs/{detail['run']['id']}/tasks/"
                f"{task['id']}/attempts",
                headers={"Idempotency-Key": f"attempt:shared-gate:{index}"},
                json={"expected_task_version": 1, "requested_not_before": NOW.isoformat()},
            ).json()
            runs.append((detail["run"], task, attempt))

    first_run, first_task, first_attempt = runs[0]
    second_run, second_task, second_attempt = runs[1]
    api.sampling.execution.claim_attempt(
        project_id=PROJECT_ID,
        run_id=UUID(first_run["id"]),
        task_id=UUID(first_task["id"]),
        attempt_id=UUID(first_attempt["id"]),
        expected_task_version=2,
        expected_attempt_version=1,
        worker_id="sampling-worker-1",
        now=clock(),
        lease_for=timedelta(seconds=10),
    )
    with pytest.raises(SamplingRuleViolation, match="interval"):
        _claim_second(api, clock.advance(seconds=1), second_run, second_task, second_attempt)
    with pytest.raises(SamplingRuleViolation, match="concurrency"):
        _claim_second(api, clock.advance(seconds=1), second_run, second_task, second_attempt)
    claimed = _claim_second(
        api,
        clock.advance(seconds=8),
        second_run,
        second_task,
        second_attempt,
    )
    assert claimed.attempt.job.lease_owner == "sampling-worker-2"


def test_daily_usage_limit_is_shared_and_resets_only_at_utc_window_boundary() -> None:
    app, api, clock, _ = internal_app()
    policy_id, _ = _install_provider_policy(
        api,
        key="provider-policy:daily-window",
        quota_remaining=20,
        daily_task_limit=1,
        minimum_request_interval_seconds=2,
        max_concurrency=1,
    )
    suite_payload = provider_suite_payload(
        admission_policy_id=policy_id,
    )
    suite_payload["max_daily_tasks"] = 1
    suite_payload["max_concurrency"] = 1
    suites = f"/v1/projects/{PROJECT_ID}/sampling/suites"

    with TestClient(app) as client:
        suite = client.post(
            suites,
            headers={"Idempotency-Key": "suite:daily-window"},
            json=suite_payload,
        ).json()
        details = [
            client.post(
                f"{suites}/{suite['id']}/runs",
                headers={"Idempotency-Key": f"run:daily-window:{index}"},
                json={
                    "purpose": "geo_measurement",
                    "requested_not_before": NOW.isoformat(),
                },
            ).json()
            for index in (1, 2)
        ]
        paths = [
            f"/v1/projects/{PROJECT_ID}/sampling/runs/{item['run']['id']}/tasks/"
            f"{item['tasks'][0]['id']}/attempts"
            for item in details
        ]
        body = {"expected_task_version": 1, "requested_not_before": NOW.isoformat()}
        first = client.post(
            paths[0], headers={"Idempotency-Key": "attempt:daily-window:1"}, json=body
        )
        blocked = client.post(
            paths[1], headers={"Idempotency-Key": "attempt:daily-window:2"}, json=body
        )
        clock.advance(days=1)
        next_window = client.post(
            paths[1], headers={"Idempotency-Key": "attempt:daily-window:2"}, json=body
        )

    assert first.status_code == next_window.status_code == 201
    assert blocked.status_code == 422
    windows = api.sampling.policies.usage_windows(project_id=PROJECT_ID, policy_id=policy_id)
    assert [item.consumed_task_count for item in windows] == [1, 1]


def _claim_second(api: WorkflowCApi, now, run, task, attempt):
    return api.sampling.execution.claim_attempt(
        project_id=PROJECT_ID,
        run_id=UUID(run["id"]),
        task_id=UUID(task["id"]),
        attempt_id=UUID(attempt["id"]),
        expected_task_version=2,
        expected_attempt_version=1,
        worker_id="sampling-worker-2",
        now=now,
        lease_for=timedelta(seconds=10),
    )


def _install_provider_policy(
    api: WorkflowCApi,
    *,
    key: str,
    quota_remaining: int,
    daily_task_limit: int,
    minimum_request_interval_seconds: int,
    max_concurrency: int,
) -> tuple[UUID, str]:
    sampling = api.sampling
    runtime_option_key = install_admission_runtime_option(api)
    created = sampling.create_admission_policy(
        project_id=PROJECT_ID,
        actor_id="policy-maker",
        idempotency_key=key,
        payload=CreateAdmissionPolicyRequest(
            runtime_authorization_option_key=runtime_option_key,
            purpose="geo_measurement",
            valid_until=NOW + timedelta(days=30),
            quota_remaining=quota_remaining,
            daily_task_limit=daily_task_limit,
            minimum_request_interval_seconds=minimum_request_interval_seconds,
            max_concurrency=max_concurrency,
        ),
    )
    submitted = sampling.submit_admission_policy(
        project_id=PROJECT_ID,
        policy_id=created.record.id,
        actor_id="policy-maker",
        idempotency_key=f"{key}:submit",
        payload=AdmissionPolicySubmitRequest(expected_version=1),
    )
    approved = sampling.decide_admission_policy(
        project_id=PROJECT_ID,
        policy_id=created.record.id,
        actor_id="policy-checker",
        idempotency_key=f"{key}:approve",
        payload=AdmissionPolicyDecisionRequest(
            expected_version=submitted.record.aggregate_version,
            reason="Independent authorization and operating-limit review completed.",
        ),
        approved=True,
    )
    install_suite_inputs(api, created.record.id, approved.record.definition_hash)
    return created.record.id, approved.record.definition_hash
