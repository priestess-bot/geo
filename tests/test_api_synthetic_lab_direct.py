from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from test_api_synthetic_lab import (
    PROJECT_ID,
    MemorySyntheticLabApi,
    _app,
    _boundary,
)


def test_job_list_and_review_result_are_project_scoped_safe_reads() -> None:
    app, services, creator = _app(MemorySyntheticLabApi(uuid4()))
    services.principal = creator
    base = f"/v1/projects/{PROJECT_ID}/synthetic-lab"
    with TestClient(app) as client:
        created = client.post(
            f"{base}/jobs/generation",
            headers={"Idempotency-Key": "review-list-result"},
            json={
                "suite_version_id": str(uuid4()),
                "case_id": str(uuid4()),
                "runtime_selection_id": str(uuid4()),
                "style_pass_threshold": 4.2,
            },
        )
        assert created.status_code == 202
        job_id = created.json()["id"]

        listed = client.get(
            f"{base}/jobs",
            params={"kind": "candidate_generation", "status": "queued"},
        )
        assert listed.status_code == 200
        _boundary(listed.json())
        assert listed.json()["total"] == 1
        assert listed.json()["items"][0]["id"] == job_id

        result = client.get(f"{base}/jobs/{job_id}/result")
        assert result.status_code == 200
        body = result.json()
        _boundary(body)
        assert body["final_text"] == "A concise Australian buyer review."
        assert body["status"] == "completed_with_warning"
        assert body["warning_codes"] == ["derived_or_unknown"]
        assert body["batches"][0]["candidate_count"] == 4
        assert body["evaluations"][0]["claim_assessments"][0]["status"] == ("derived_or_unknown")
        assert not {
            "prompt",
            "raw_response",
            "evidence_summary",
            "secret_value",
        }.intersection(body)


def test_direct_generation_options_style_version_and_enqueue_form_a_vertical_path() -> None:
    app, services, creator = _app(MemorySyntheticLabApi(uuid4()))
    services.principal = creator
    base = f"/v1/projects/{PROJECT_ID}/synthetic-lab"
    with TestClient(app) as client:
        initial = client.get(f"{base}/direct-generation/options")
        assert initial.status_code == 200
        assert initial.json()["subjects"][0]["name"] == "ADVINSYS TerraMow V600"
        assert initial.json()["channel_styles"] == []

        style = client.post(
            f"{base}/channel-styles/reddit/versions",
            headers={"Idempotency-Key": "direct-style-create-v1"},
            json={
                "expected_current_version": 0,
                "directive": "Use candid Australian English and only supplied knowledge.",
            },
        )
        assert style.status_code == 201
        assert style.json()["version_number"] == 1
        assert style.json()["calibration_status"] == "pending_sample_calibration"

        options = client.get(f"{base}/direct-generation/options").json()
        subject = options["subjects"][0]
        current_style = options["channel_styles"][0]
        queued = client.post(
            f"{base}/jobs/direct-generation",
            headers={"Idempotency-Key": "direct-generation-v600-reddit"},
            json={
                "channel": "reddit",
                "subject_entity_id": subject["id"],
                "generation_goal": "Write a short review for a medium Australian lawn.",
                "runtime_selection_id": str(uuid4()),
                "channel_style_version_id": current_style["id"],
                "channel_style_hash": current_style["style_hash"],
                "knowledge_snapshot_hash": subject["knowledge_snapshot_hash"],
                "style_pass_threshold": 4.2,
                "include_competitor_context": False,
            },
        )
        assert queued.status_code == 202
        assert queued.json()["kind"] == "candidate_generation"
        assert queued.json()["status"] == "queued"
