"""End-to-end Internal API workflows for governed Synthetic Lab resources."""

from __future__ import annotations

import base64
from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from geo_api.app_factory import create_api_app
from synthetic_lab_api_test_support import (
    case_payload as _case_payload,
    import_payload as _import_payload,
    job_payload as _job_payload,
    manual_source_payload as _manual_source_payload,
    source_payload as _source_payload,
)
from test_api_synthetic_lab import (
    AUTHORIZATION_ID,
    NOW,
    PROJECT_ID,
    MemorySyntheticLabApi,
    _app,
    _boundary,
    _hash,
    _principal,
)


def test_memory_api_assets_authorization_and_safe_manual_errors() -> None:
    creator = _principal("admin")
    api = MemorySyntheticLabApi(creator.identity_id)
    app, services, _ = _app(api)
    prefix = f"/v1/projects/{PROJECT_ID}/synthetic-lab"
    headers = {"Idempotency-Key": "synthetic:asset:command"}
    with TestClient(app) as client:
        authorization = client.post(
            f"{prefix}/authorizations/{AUTHORIZATION_ID}/decision",
            headers=headers,
            json={
                "expected_version": 1,
                "decision": "approved",
                "evidence_reference": "legal-review:terms-2026-07",
                "allowed_purposes": ["style_collection"],
                "max_requests_per_period": 10,
                "period_seconds": 60,
                "max_concurrency": 2,
                "expires_at": (NOW + timedelta(days=30)).isoformat(),
                "decision_reason": "Approved after terms review.",
            },
        )
        assert authorization.status_code == 200, authorization.text
        _boundary(authorization.json())
        assert authorization.json()["state"] == "approved"
        invalid_purpose = client.post(
            f"{prefix}/authorizations/{AUTHORIZATION_ID}/decision",
            headers={"Idempotency-Key": "synthetic:invalid-purpose"},
            json={
                "expected_version": 2,
                "decision": "approved",
                "evidence_reference": "legal-review:terms-2026-07",
                "allowed_purposes": ["unreviewed_collection"],
                "max_requests_per_period": 10,
                "period_seconds": 60,
                "max_concurrency": 2,
                "expires_at": (NOW + timedelta(days=30)).isoformat(),
                "decision_reason": "This purpose is outside the catalog.",
            },
        )
        assert invalid_purpose.status_code == 422

        source = client.post(f"{prefix}/style-sources", headers=headers, json=_source_payload())
        assert source.status_code == 201, source.text
        source_id = source.json()["id"]
        _boundary(source.json())
        listed = client.get(f"{prefix}/style-sources")
        assert listed.status_code == 200
        _boundary(listed.json())
        assert listed.json()["items"][0]["id"] == source_id

        admitted = client.post(
            f"{prefix}/jobs/style-collection",
            headers={"Idempotency-Key": "synthetic:style-collection:admit"},
            json={
                "style_source_revision_id": source_id,
                "adapter_release": "reddit-style-v1",
                "login_secret_reference_id": None,
            },
        )
        assert admitted.status_code == 202, admitted.text
        _boundary(admitted.json())
        assert admitted.json()["disposition"] == "accepted"
        assert admitted.json()["job"]["kind"] == "style_collection"

        manual_source = client.post(
            f"{prefix}/style-sources", headers=headers, json=_manual_source_payload()
        )
        assert manual_source.status_code == 201, manual_source.text
        preview = client.post(
            f"{prefix}/sample-import-previews",
            headers={"Idempotency-Key": "synthetic:manual-preview"},
            json=_import_payload(manual_source.json()["id"]),
        )
        assert preview.status_code == 201, preview.text
        body = preview.json()
        _boundary(body)
        assert body["selectable_count"] == 1
        assert "content_base64" not in preview.text
        assert "raw_text" not in preview.text

        services.principal = _principal("admin")
        approved = client.post(
            f"{prefix}/sample-import-previews/{body['id']}/approve",
            headers={"Idempotency-Key": "synthetic:manual-approve"},
            json={
                "expected_version": 1,
                "selected_row_numbers": [1],
                "au_english_verified": True,
                "anonymization_verified": True,
            },
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["accepted_count"] == 1

        credential_schema = _import_payload()
        credential_schema["content_base64"] = base64.b64encode(
            b"password=do-not-store"
        ).decode()
        rejected_schema = client.post(
            f"{prefix}/sample-import-previews",
            headers={"Idempotency-Key": "synthetic:credential-field"},
            json=credential_schema,
        )
        assert rejected_schema.status_code == 422

        services.principal = creator
        blocked = client.post(
            f"{prefix}/authorizations/{AUTHORIZATION_ID}/decision",
            headers={"Idempotency-Key": "synthetic:self:approval"},
            json={
                "expected_version": 2,
                "decision": "approved",
                "evidence_reference": "legal-review:terms-2026-07",
                "allowed_purposes": ["style_collection"],
                "max_requests_per_period": 10,
                "period_seconds": 60,
                "max_concurrency": 2,
                "expires_at": (NOW + timedelta(days=30)).isoformat(),
                "decision_reason": "Self approval must fail.",
            },
        )
        assert blocked.status_code == 403


def test_authorization_reassessment_opens_blank_next_version() -> None:
    creator = _principal("admin")
    api = MemorySyntheticLabApi(creator.identity_id)
    previous = api.authorizations[AUTHORIZATION_ID]
    previous.update(
        version_number=2,
        state="revoked",
        evidence_reference_hash=_hash("old-evidence"),
        allowed_purposes=("style_collection",),
        max_requests_per_period=10,
        period_seconds=60,
        max_concurrency=1,
        expires_at=NOW + timedelta(days=1),
    )
    app, _, _ = _app(api)
    path = (
        f"/v1/projects/{PROJECT_ID}/synthetic-lab/authorizations/"
        f"{AUTHORIZATION_ID}/reassess"
    )
    with TestClient(app) as client:
        response = client.post(
            path,
            headers={"Idempotency-Key": "synthetic:authorization:reassess"},
            json={
                "expected_version": 2,
                "opened_at": NOW.isoformat(),
                "reassessment_reason": "New terms evidence is ready for independent review.",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    _boundary(body)
    assert body["id"] != str(AUTHORIZATION_ID)
    assert body["version_number"] == 3
    assert body["state"] == "not_assessed"
    assert body["evidence_reference_hash"] is None
    assert body["allowed_purposes"] == []
    assert body["max_requests_per_period"] is None


def test_memory_api_profile_suite_case_and_all_job_routes() -> None:
    api = MemorySyntheticLabApi(uuid4())
    app, _, _ = _app(api)
    prefix = f"/v1/projects/{PROJECT_ID}/synthetic-lab"
    headers = {"Idempotency-Key": "synthetic:workflow:command"}
    sample_ids = [str(uuid4()) for _ in range(200)]
    with TestClient(app) as client:
        profile = client.post(
            f"{prefix}/style-profiles",
            headers=headers,
            json={
                "expected_version": 0,
                "channel": "reddit",
                "locale": "en-AU",
                "prompt_binding_id": str(uuid4()),
                "approved_sample_ids": sample_ids,
            },
        )
        assert profile.status_code == 201, profile.text
        profile_id = profile.json()["id"]
        runtime_selection_id = str(uuid4())
        profile_build = client.post(
            f"{prefix}/jobs/profile-build",
            headers={"Idempotency-Key": "synthetic:profile:build"},
            json={
                "profile_version_id": profile_id,
                "fact_snapshot_id": str(uuid4()),
                "approved_sample_ids": sample_ids,
                "runtime_selection_id": runtime_selection_id,
            },
        )
        assert profile_build.status_code == 202, profile_build.text
        assert profile_build.json()["kind"] == "style_profile_build"
        incomplete_recovery = client.post(
            f"{prefix}/jobs/profile-build",
            headers={"Idempotency-Key": "synthetic:profile:incomplete-recovery"},
            json={
                "profile_version_id": profile_id,
                "fact_snapshot_id": str(uuid4()),
                "approved_sample_ids": sample_ids,
                "runtime_selection_id": runtime_selection_id,
                "recovery_of_attempt_id": str(uuid4()),
            },
        )
        assert incomplete_recovery.status_code == 422
        submitted = client.post(
            f"{prefix}/style-profiles/{profile_id}/submit",
            headers={"Idempotency-Key": "synthetic:profile:submit"},
            json={"expected_version": 1},
        )
        assert submitted.json()["status"] == "in_review"
        decided = client.post(
            f"{prefix}/style-profiles/{profile_id}/decision",
            headers={"Idempotency-Key": "synthetic:profile:approve"},
            json={"expected_version": submitted.json()["state_version"], "decision": "approve"},
        )
        assert decided.json()["status"] == "approved"
        frozen_profile = client.post(
            f"{prefix}/style-profiles/{profile_id}/freeze",
            headers=headers,
            json={"expected_version": decided.json()["state_version"]},
        )
        assert frozen_profile.json()["status"] == "frozen"

        suite = client.post(
            f"{prefix}/review-suites",
            headers=headers,
            json={
                "expected_version": 0,
                "channel": "reddit",
                "suite_name": "Reddit regression suite",
            },
        )
        assert suite.status_code == 201, suite.text
        suite_id = suite.json()["id"]
        case = client.post(
            f"{prefix}/review-suites/{suite_id}/cases",
            headers=headers,
            json=_case_payload(),
        )
        assert case.status_code == 201, case.text
        frozen_suite = client.post(
            f"{prefix}/review-suites/{suite_id}/freeze",
            headers=headers,
            json={"expected_version": suite.json()["state_version"]},
        )
        assert frozen_suite.json()["status"] == "frozen"

        generation = client.post(
            f"{prefix}/jobs/generation",
            headers={"Idempotency-Key": "synthetic:review:run"},
            json={
                "suite_version_id": suite_id,
                "case_id": case.json()["id"],
                "runtime_selection_id": runtime_selection_id,
                "style_pass_threshold": 4.2,
            },
        )
        assert generation.status_code == 202, generation.text
        assert generation.json()["kind"] == "candidate_generation"
        job_ids = [generation.json()["id"]]
        revision = client.post(
            f"{prefix}/jobs/revision", headers=headers, json=_job_payload()
        )
        assert revision.status_code == 202, revision.text
        job_ids.append(revision.json()["id"])
        corpus = client.post(
            f"{prefix}/jobs/corpus",
            headers={"Idempotency-Key": "synthetic:corpus:candidate"},
            json={
                "role": "new_candidate_corpus",
                "review_job_ids": [generation.json()["id"]],
                "source_corpus_job_id": None,
            },
        )
        assert corpus.status_code == 202, corpus.text
        _boundary(corpus.json())
        job_ids.append(corpus.json()["id"])
        experiment = client.post(
            f"{prefix}/jobs/offline-experiment",
            headers={"Idempotency-Key": "synthetic:offline:experiment"},
            json={
                "question_set_id": str(uuid4()),
                "current_corpus_job_id": str(uuid4()),
                "candidate_corpus_job_id": corpus.json()["id"],
                "runtime_selection_id": runtime_selection_id,
                "minimum_valid_pair_ratio": 0.8,
            },
        )
        assert experiment.status_code == 202, experiment.text
        _boundary(experiment.json())
        job_ids.append(experiment.json()["id"])
        fetched = client.get(f"{prefix}/jobs/{job_ids[0]}")
        assert fetched.status_code == 200
        cancelled = client.post(
            f"{prefix}/jobs/{job_ids[0]}/cancel",
            headers=headers,
            json={"expected_version": 1},
        )
        assert cancelled.json()["status"] == "cancelled"
        finalized = client.post(
            f"{prefix}/jobs/{job_ids[1]}/finalize",
            headers=headers,
            json={
                "expected_version": 1,
                "lease_id": str(uuid4()),
                "fencing_token": 4,
                "completed_at": NOW.isoformat(),
                "result_artifact_id": str(uuid4()),
                "result_hash": _hash("final-result"),
            },
        )
        assert finalized.status_code == 200, finalized.text
        assert finalized.json()["status"] == "succeeded"
        assert finalized.json()["result_hash"] == _hash("final-result")

    customer = create_api_app(surface="customer", synthetic_lab_api=api)
    with TestClient(customer) as client:
        assert client.get(f"{prefix}/jobs/{job_ids[0]}").status_code == 404
