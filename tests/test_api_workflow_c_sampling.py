from __future__ import annotations

import base64
from copy import deepcopy
from datetime import timedelta
import hashlib
from uuid import UUID

from fastapi.testclient import TestClient
import pytest

from geo_core.sampling import EvidenceStatus, SamplingRuleViolation

from tests.unit.sampling.factories import make_evidence
from tests.workflow_c_api_test_support import (
    NOW,
    PROJECT_ID,
    digest,
    install_admission_runtime_option,
    install_manual_policy,
    install_provider_policy,
    install_suite_inputs,
    internal_app,
    principal,
    provider_admission_policy_payload,
    provider_suite_payload,
)


def test_sampling_internal_api_runs_fenced_observation_and_fixed_denominator() -> None:
    app, api, clock, _ = internal_app()
    install_provider_policy(api)
    collection = f"/v1/projects/{PROJECT_ID}/sampling/suites"

    with TestClient(app) as client:
        options = client.get(f"/v1/projects/{PROJECT_ID}/sampling/suite-input-options")
        created = client.post(
            collection,
            headers={"Idempotency-Key": "sampling-suite:one"},
            json=provider_suite_payload(),
        )
        assert created.status_code == 201, created.text
        suite = created.json()
        assert suite["planned_task_count"] == 10
        assert suite["minimum_valid_repeats"] == 8
        assert suite["source_stratum"]["capture_method"] == "provider_api"
        inventory = client.get(collection)

        started = client.post(
            f"{collection}/{suite['id']}/runs",
            headers={"Idempotency-Key": "sampling-run:one"},
            json={
                "purpose": "geo_measurement",
                "requested_not_before": NOW.isoformat(),
            },
        )
        assert started.status_code == 201, started.text
        detail = started.json()
        run = detail["run"]
        task = detail["tasks"][0]
        denominator = tuple(run["planned_task_keys"])
        assert len(denominator) == 10
        assert detail["assessment"]["status"] == "insufficient_evidence"
        assert detail["assessment"]["missing_task_count"] == 10

        enqueued = client.post(
            f"/v1/projects/{PROJECT_ID}/sampling/runs/{run['id']}/tasks/{task['id']}/attempts",
            headers={"Idempotency-Key": "sampling-attempt:one"},
            json={
                "expected_task_version": 1,
                "requested_not_before": NOW.isoformat(),
            },
        )
        assert enqueued.status_code == 201, enqueued.text
        attempt = enqueued.json()
        assert attempt["job_status"] == "queued"

        clock.advance(seconds=1)
        claimed = api.sampling.execution.claim_attempt(
            project_id=PROJECT_ID,
            run_id=UUID(run["id"]),
            task_id=UUID(task["id"]),
            attempt_id=UUID(attempt["id"]),
            expected_task_version=2,
            expected_attempt_version=1,
            worker_id="sampling-worker-1",
            now=clock(),
            lease_for=timedelta(seconds=120),
        )
        token = claimed.attempt.job.lease_token
        assert token is not None
        completed = api.sampling.execution.finalize_observation(
            project_id=PROJECT_ID,
            run_id=UUID(run["id"]),
            task_id=UUID(task["id"]),
            attempt_id=UUID(attempt["id"]),
            expected_task_version=claimed.task.version,
            expected_attempt_version=claimed.attempt.record_version,
            token=token,
            generation=claimed.attempt.job.fencing_generation,
            now=clock.advance(seconds=1),
            evidence_status=EvidenceStatus.COMPLETE,
            ineligible_reasons=(),
            evidence=make_evidence(
                claimed.task,
                provider_response_id="provider-response-42",
            ),
        )
        assert completed.observation.evidence_status is EvidenceStatus.COMPLETE

        refreshed = client.get(f"/v1/projects/{PROJECT_ID}/sampling/runs/{run['id']}")
        assert refreshed.status_code == 200, refreshed.text
        final_detail = refreshed.json()
        assert tuple(final_detail["run"]["planned_task_keys"]) == denominator
        assert final_detail["tasks"][0]["task_key"] == task["task_key"]
        assert "provider-response-42" not in final_detail["tasks"][0].values()
        assert final_detail["assessment"]["planned_task_count"] == 10
        assert final_detail["assessment"]["valid_task_count"] == 1
        assert final_detail["assessment"]["missing_task_count"] == 9
        assert final_detail["assessment"]["status"] == "insufficient_evidence"
        public_attempt = final_detail["attempts"][0]
        assert not {
            "lease_token",
            "lease_owner",
            "lease_expires_at",
            "fencing_generation",
        }.intersection(public_attempt)
        public_evidence = final_detail["observations"][0]["evidence"]
        assert public_evidence["derived_summary"]
        assert public_evidence["evidence_locator"]
        assert not {
            "answer_text",
            "raw_artifact_uri",
            "manifest_reference",
        }.intersection(public_evidence)

    assert options.status_code == 200
    assert options.json()["total"] == 1
    assert options.json()["items"][0]["question_count"] == 1
    assert inventory.status_code == 200
    assert inventory.json()["total"] == 1
    request_fields = app.openapi()["components"]["schemas"]["CreateSamplingSuiteRequest"][
        "properties"
    ]
    assert "questions" not in request_fields
    assert "source_stratum" not in request_fields


def test_worker_private_attempt_transitions_are_not_http_routes() -> None:
    app, _, _, _ = internal_app()
    attempt_id = "60000000-0000-4000-8000-000000000006"
    worker_commands = ("claim", "heartbeat", "finalize", "fail", "acknowledge-cancel")

    with TestClient(app) as client:
        responses = [
            client.post(
                f"/v1/projects/{PROJECT_ID}/sampling/attempts/{attempt_id}/{command}",
                json={},
            )
            for command in worker_commands
        ]

    assert all(response.status_code == 404 for response in responses)
    paths = set(app.openapi()["paths"])
    assert not any(
        path.endswith(tuple(f"/{command}" for command in worker_commands))
        for path in paths
        if path.startswith("/v1/projects/{project_id}/sampling/")
    )


def test_bulk_enqueue_ready_is_atomic_rate_scheduled_and_idempotent() -> None:
    app, api, _, _ = internal_app()
    install_provider_policy(api)
    suites = f"/v1/projects/{PROJECT_ID}/sampling/suites"

    with TestClient(app) as client:
        suite_response = client.post(
            suites,
            headers={"Idempotency-Key": "suite:bulk"},
            json=provider_suite_payload(),
        )
        suite = suite_response.json()
        run_response = client.post(
            f"{suites}/{suite['id']}/runs",
            headers={"Idempotency-Key": "run:bulk"},
            json={
                "purpose": "geo_measurement",
                "requested_not_before": NOW.isoformat(),
            },
        )
        run = run_response.json()["run"]
        path = f"/v1/projects/{PROJECT_ID}/sampling/runs/{run['id']}/enqueue-ready"
        payload = {"requested_not_before": NOW.isoformat(), "max_tasks": 100}
        first = client.post(
            path,
            headers={"Idempotency-Key": "bulk-enqueue:one"},
            json=payload,
        )
        replay = client.post(
            path,
            headers={"Idempotency-Key": "bulk-enqueue:one"},
            json=payload,
        )
        conflict = client.post(
            path,
            headers={"Idempotency-Key": "bulk-enqueue:one"},
            json={**payload, "max_tasks": 9},
        )
        cancelled = client.post(
            f"/v1/projects/{PROJECT_ID}/sampling/runs/{run['id']}/cancel",
            headers={"Idempotency-Key": "bulk-cancel:one"},
        )
        cancel_replay = client.post(
            f"/v1/projects/{PROJECT_ID}/sampling/runs/{run['id']}/cancel",
            headers={"Idempotency-Key": "bulk-cancel:one"},
        )
        progress = client.get(f"/v1/projects/{PROJECT_ID}/sampling/runs/{run['id']}")

    assert first.status_code == replay.status_code == 201, first.text
    assert conflict.status_code == 409
    body = first.json()
    assert body["planned_task_count"] == body["enqueued_count"] == 10
    assert body["replayed_count"] == body["skipped_count"] == 0
    assert len(set(body["attempt_ids"])) == 10
    assert body["first_not_before"] == NOW.isoformat().replace("+00:00", "Z")
    assert body["last_not_before"] == (NOW + timedelta(seconds=18)).isoformat().replace(
        "+00:00", "Z"
    )
    replay_body = replay.json()
    assert replay_body["enqueued_count"] == 0
    assert replay_body["replayed_count"] == 10
    assert replay_body["replayed"] is True
    assert replay_body["attempt_ids"] == body["attempt_ids"]
    assert len(api.sampling.store.outbox_messages(project_id=PROJECT_ID)) == 10
    assert cancelled.status_code == cancel_replay.status_code == 200
    assert cancelled.json()["cancel_requested_count"] == 10
    assert cancel_replay.json()["replayed_count"] == 10
    assert progress.json()["run"]["status"] == "cancelled"
    assert all(item["status"] == "cancelled" for item in progress.json()["tasks"])


def test_admission_policy_requires_maker_checker_and_rechecks_revoke() -> None:
    app, api, clock, services = internal_app(role="admin")
    install_admission_runtime_option(api)
    policy_collection = f"/v1/projects/{PROJECT_ID}/sampling/admission-policies"
    suite_collection = f"/v1/projects/{PROJECT_ID}/sampling/suites"

    with TestClient(app) as client:
        created_response = client.post(
            policy_collection,
            headers={"Idempotency-Key": "policy:guarded"},
            json=provider_admission_policy_payload(),
        )
        assert created_response.status_code == 201, created_response.text
        created = created_response.json()
        policy_id = created["id"]
        assert created["status"] == "draft"
        assert created["effective_authorization_state"] == "not_assessed"

        submitted_response = client.post(
            f"{policy_collection}/{policy_id}/submit",
            headers={"Idempotency-Key": "policy:guarded:submit"},
            json={"expected_version": 1},
        )
        assert submitted_response.status_code == 200, submitted_response.text
        submitted = submitted_response.json()
        assert submitted["status"] == "pending_review"

        self_approval = client.post(
            f"{policy_collection}/{policy_id}/approve",
            headers={"Idempotency-Key": "policy:guarded:self-approve"},
            json={
                "expected_version": 2,
                "reason": "A maker cannot approve this policy.",
            },
        )
        assert self_approval.status_code == 422

        services.principal = principal("owner")
        approved_response = client.post(
            f"{policy_collection}/{policy_id}/approve",
            headers={"Idempotency-Key": "policy:guarded:approve"},
            json={
                "expected_version": 2,
                "reason": "Independent terms and budget review completed.",
            },
        )
        assert approved_response.status_code == 200, approved_response.text
        approved = approved_response.json()
        assert approved["status"] == "approved"
        assert approved["decided_by"] == "workflow-c-owner"
        guarded_policy_id = UUID(policy_id)
        install_suite_inputs(api, guarded_policy_id, approved["definition_hash"])

        suite_response = client.post(
            suite_collection,
            headers={"Idempotency-Key": "suite:guarded"},
            json=provider_suite_payload(
                admission_policy_id=guarded_policy_id,
            ),
        )
        suite = suite_response.json()
        run_response = client.post(
            f"{suite_collection}/{suite['id']}/runs",
            headers={"Idempotency-Key": "run:guarded"},
            json={
                "purpose": "geo_measurement",
                "requested_not_before": NOW.isoformat(),
            },
        )
        assert run_response.status_code == 201, run_response.text
        detail = run_response.json()
        run = detail["run"]
        assert run["admission_policy_id"] == policy_id
        assert run["admission_policy_hash"]

        first_task = detail["tasks"][0]
        enqueued_response = client.post(
            f"/v1/projects/{PROJECT_ID}/sampling/runs/{run['id']}/tasks/{first_task['id']}/attempts",
            headers={"Idempotency-Key": "attempt:before-revoke"},
            json={
                "expected_task_version": 1,
                "requested_not_before": NOW.isoformat(),
            },
        )
        assert enqueued_response.status_code == 201, enqueued_response.text
        enqueued = enqueued_response.json()
        outbox_count = len(api.sampling.store.outbox_messages(project_id=PROJECT_ID))

        revoked_response = client.post(
            f"{policy_collection}/{policy_id}/revoke",
            headers={"Idempotency-Key": "policy:guarded:revoke"},
            json={
                "expected_version": 3,
                "reason": "Authorization was withdrawn.",
            },
        )
        assert revoked_response.status_code == 200, revoked_response.text
        assert revoked_response.json()["effective_authorization_state"] == "revoked"

        second_task = detail["tasks"][1]
        blocked_enqueue = client.post(
            f"/v1/projects/{PROJECT_ID}/sampling/runs/{run['id']}/tasks/{second_task['id']}/attempts",
            headers={"Idempotency-Key": "attempt:after-revoke"},
            json={
                "expected_task_version": 1,
                "requested_not_before": NOW.isoformat(),
            },
        )
        assert blocked_enqueue.status_code == 422
        assert len(api.sampling.store.outbox_messages(project_id=PROJECT_ID)) == outbox_count

    with pytest.raises(SamplingRuleViolation, match="revoked"):
        api.sampling.execution.claim_attempt(
            project_id=PROJECT_ID,
            run_id=UUID(run["id"]),
            task_id=UUID(first_task["id"]),
            attempt_id=UUID(enqueued["id"]),
            expected_task_version=2,
            expected_attempt_version=1,
            worker_id="sampling-worker-1",
            now=clock.advance(seconds=1),
            lease_for=timedelta(seconds=120),
        )

    stored = api.sampling.store.attempt(project_id=PROJECT_ID, attempt_id=UUID(enqueued["id"]))
    assert stored is not None and stored.job.status.value == "queued"


def test_manual_evidence_requires_independent_review_before_job_creation() -> None:
    app, api, _, services = internal_app(role="admin")
    install_manual_policy(api)
    suites = f"/v1/projects/{PROJECT_ID}/sampling/suites"

    with TestClient(app) as client:
        suite_response = client.post(
            suites,
            headers={"Idempotency-Key": "suite:manual"},
            json=provider_suite_payload(capture_method="manual_ui"),
        )
        assert suite_response.status_code == 201, suite_response.text
        suite = suite_response.json()
        run_response = client.post(
            f"{suites}/{suite['id']}/runs",
            headers={"Idempotency-Key": "run:manual"},
            json={
                "purpose": "geo_measurement",
                "requested_not_before": NOW.isoformat(),
            },
        )
        detail = run_response.json()
        run = detail["run"]
        task = detail["tasks"][0]
        bulk = client.post(
            f"/v1/projects/{PROJECT_ID}/sampling/runs/{run['id']}/enqueue-ready",
            headers={"Idempotency-Key": "bulk:manual-forbidden"},
            json={"requested_not_before": NOW.isoformat()},
        )
        diagnostic = client.post(
            f"/v1/projects/{PROJECT_ID}/sampling/runs/{run['id']}/tasks/{task['id']}/attempts",
            headers={"Idempotency-Key": "attempt:manual-forbidden"},
            json={
                "expected_task_version": 1,
                "requested_not_before": NOW.isoformat(),
            },
        )
        assert bulk.status_code == diagnostic.status_code == 409

        submit_path = (
            f"/v1/projects/{PROJECT_ID}/sampling/runs/{run['id']}/tasks/"
            f"{task['id']}/manual-evidence"
        )
        manual_payload = {
            "expected_task_version": 1,
            "content_base64": base64.b64encode(b"\x89PNG\r\n\x1a\nmanual-evidence").decode("ascii"),
            "content_type": "image/png",
            "governance_policy_option_key": "manual-evidence-redaction-v1",
            "evidence_kind": "screenshot",
            "pre_redacted_attestation": True,
            "device": "desktop",
            "locale": "en-AU",
            "captured_at": NOW.isoformat(),
        }
        submitted_response = client.post(
            submit_path,
            headers={"Idempotency-Key": "manual-evidence:one"},
            json=manual_payload,
        )
        replay = client.post(
            submit_path,
            headers={"Idempotency-Key": "manual-evidence:one"},
            json=manual_payload,
        )
        forged = client.post(
            submit_path,
            headers={"Idempotency-Key": "manual-evidence:forged"},
            json={**manual_payload, "answer_text": "must not enter transport"},
        )
        forged_lineage = client.post(
            submit_path,
            headers={"Idempotency-Key": "manual-evidence:forged-lineage"},
            json={
                **manual_payload,
                "artifact_manifest_hash": digest("client-controlled-manifest"),
            },
        )
        assert submitted_response.status_code == 201, submitted_response.text
        assert replay.status_code == 201
        assert replay.json() == submitted_response.json()
        assert forged.status_code == forged_lineage.status_code == 422
        submitted = submitted_response.json()
        assert submitted["status"] == "pending_review"
        assert "answer_text" not in submitted
        assert (
            submitted["artifact_content_hash"]
            == hashlib.sha256(b"\x89PNG\r\n\x1a\nmanual-evidence").hexdigest()
        )
        assert len(api.sampling.store.outbox_messages(project_id=PROJECT_ID)) == 0

        self_review = client.post(
            f"/v1/projects/{PROJECT_ID}/sampling/manual-evidence-imports/{submitted['id']}/approve",
            headers={"Idempotency-Key": "manual-review:self"},
            json={"expected_version": 1, "reason": "Self review is forbidden."},
        )
        assert self_review.status_code == 422

        services.principal = principal("owner")
        approved_response = client.post(
            f"/v1/projects/{PROJECT_ID}/sampling/manual-evidence-imports/{submitted['id']}/approve",
            headers={"Idempotency-Key": "manual-review:approve"},
            json={
                "expected_version": 1,
                "reason": "Artifact identity and capture metadata reviewed.",
            },
        )
        assert approved_response.status_code == 200, approved_response.text
        approved = approved_response.json()
        assert approved["status"] == "approved"
        assert approved["reviewed_by"] == "workflow-c-owner"

    assert len(api.sampling.store.outbox_messages(project_id=PROJECT_ID)) == 1
    attempt = api.sampling.store.attempt(
        project_id=PROJECT_ID,
        attempt_id=UUID(approved["attempt_id"]),
    )
    assert attempt is not None
    assert attempt.job.spec.kind == "sampling.manual_import"
    assert "answer_text" not in attempt.job.spec.payload


def test_sampling_contract_rejects_automated_ui_unknown_fields_and_bad_manual_floor() -> None:
    app, api, _, _ = internal_app()
    install_manual_policy(api)
    path = f"/v1/projects/{PROJECT_ID}/sampling/suites"
    automated = provider_suite_payload()
    automated["capture_method"] = "automated_ui"
    unknown = deepcopy(provider_suite_payload())
    unknown["browser_profile"] = {"stealth": True}
    manual = provider_suite_payload(capture_method="manual_ui")
    manual["repetitions"] = 2

    with TestClient(app) as client:
        automated_result = client.post(
            path,
            headers={"Idempotency-Key": "sampling-suite:automated"},
            json=automated,
        )
        unknown_result = client.post(
            path,
            headers={"Idempotency-Key": "sampling-suite:unknown"},
            json=unknown,
        )
        manual_result = client.post(
            path,
            headers={"Idempotency-Key": "sampling-suite:manual-low"},
            json=manual,
        )

    assert automated_result.status_code == 422
    assert unknown_result.status_code == 422
    assert manual_result.status_code == 422


def test_sampling_write_requires_contributor_role() -> None:
    app, _, _, _ = internal_app(role="viewer")

    with TestClient(app) as client:
        response = client.post(
            f"/v1/projects/{PROJECT_ID}/sampling/suites",
            headers={"Idempotency-Key": "sampling-suite:viewer"},
            json=provider_suite_payload(),
        )

    assert response.status_code == 403


def test_analyst_cannot_install_an_admission_policy() -> None:
    app, _, _, _ = internal_app(role="analyst")

    with TestClient(app) as client:
        response = client.post(
            f"/v1/projects/{PROJECT_ID}/sampling/admission-policies",
            headers={"Idempotency-Key": "policy:analyst"},
            json=provider_admission_policy_payload(),
        )

        assert response.status_code == 403
