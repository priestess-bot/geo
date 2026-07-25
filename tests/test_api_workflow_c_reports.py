from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from fastapi.testclient import TestClient
import pytest

from tests.workflow_c_api_test_support import PROJECT_ID, digest, internal_app, principal


CAMPAIGN_ID = UUID("81000000-0000-4000-8000-000000000001")
MONITORING_REPORT_ID = UUID("81000000-0000-4000-8000-000000000002")


def test_report_publication_is_maker_checker_and_latest_state_is_explicit() -> None:
    app, _, _, services = internal_app()
    collection = f"/v1/projects/{PROJECT_ID}/analysis/reports"
    with TestClient(app) as client:
        created = client.post(
            collection,
            headers={"Idempotency-Key": "report:create"},
            json={
                "campaign_id": str(CAMPAIGN_ID),
                "monitoring_report_id": str(MONITORING_REPORT_ID),
                "monitoring_report_hash": digest("monitoring-report"),
                "semantic_snapshot_hash": digest("semantic-snapshot"),
                "source_kind": "provider_api",
                "approved_safe_payload": {
                    "headline": "Approved Australian evidence",
                    "recommendation_rate": "0.8",
                },
            },
        )
        report_id = created.json()["report_id"]
        submitted = client.post(
            f"{collection}/{report_id}/submit",
            headers={"Idempotency-Key": "report:submit"},
            json={"expected_version": 1},
        )
        self_approval = client.post(
            f"{collection}/{report_id}/approve",
            headers={"Idempotency-Key": "report:self-approve"},
            json={"expected_version": 2},
        )
        services.principal = replace(
            principal("owner"),
            identity_id=UUID("40000000-0000-0000-0000-000000000005"),
        )
        approved = client.post(
            f"{collection}/{report_id}/approve",
            headers={"Idempotency-Key": "report:approve"},
            json={"expected_version": 2},
        )
        stale = client.post(
            f"{collection}/{report_id}/stale",
            headers={"Idempotency-Key": "report:stale"},
            json={"expected_version": 3, "reason": "source_snapshot_replaced"},
        )
        listed = client.get(collection)

    assert created.status_code == 201
    assert submitted.status_code == 200
    assert self_approval.status_code == 422
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert stale.status_code == 200
    assert stale.json()["status"] == "stale"
    assert listed.json()["items"] == [stale.json()]


def test_report_draft_rejects_manual_or_unclassified_customer_sources() -> None:
    app, _, _, _ = internal_app()
    with TestClient(app) as client:
        response = client.post(
            f"/v1/projects/{PROJECT_ID}/analysis/reports",
            headers={"Idempotency-Key": "report:manual"},
            json={
                "campaign_id": str(CAMPAIGN_ID),
                "monitoring_report_id": str(MONITORING_REPORT_ID),
                "monitoring_report_hash": digest("monitoring-report"),
                "semantic_snapshot_hash": digest("semantic-snapshot"),
                "source_kind": "manual_ui",
                "approved_safe_payload": {"headline": "Not customer eligible"},
            },
        )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "approved_safe_payload",
    [
        {"headline": "Result", "access_token": "private"},
        {"headline": "Result", "raw_text": "private"},
        {"headline": "Result", "system_prompt": "private"},
        {"headline": "Result", "unknown": "private"},
        {"summary": {"text": "nested"}},
        {"metrics": {"mention": {"value": "0.8"}}},
        {"metrics": {"unknown_metric": "0.8"}},
    ],
)
def test_report_draft_rejects_payloads_outside_the_customer_allowlist(
    approved_safe_payload: object,
) -> None:
    app, _, _, _ = internal_app()
    with TestClient(app) as client:
        response = client.post(
            f"/v1/projects/{PROJECT_ID}/analysis/reports",
            headers={"Idempotency-Key": "report:unsafe"},
            json={
                "campaign_id": str(CAMPAIGN_ID),
                "monitoring_report_id": str(MONITORING_REPORT_ID),
                "monitoring_report_hash": digest("monitoring-report"),
                "semantic_snapshot_hash": digest("semantic-snapshot"),
                "source_kind": "provider_api",
                "approved_safe_payload": approved_safe_payload,
            },
        )

    assert response.status_code == 422


def test_report_command_receipts_replay_the_exact_lost_response_after_later_changes() -> None:
    app, _, clock, services = internal_app()
    maker = services.principal
    collection = f"/v1/projects/{PROJECT_ID}/analysis/reports"
    with TestClient(app) as client:
        created = client.post(
            collection,
            headers={"Idempotency-Key": "report:lost:create"},
            json=_report_payload("Lost response report"),
        )
        report_id = created.json()["report_id"]
        submitted = client.post(
            f"{collection}/{report_id}/submit",
            headers={"Idempotency-Key": "report:lost:submit"},
            json={"expected_version": 1},
        )
        services.principal = replace(
            maker,
            identity_id=UUID("40000000-0000-0000-0000-000000000005"),
        )
        approved = client.post(
            f"{collection}/{report_id}/approve",
            headers={"Idempotency-Key": "report:lost:approve"},
            json={"expected_version": 2},
        )
        clock.advance(seconds=30)
        services.principal = maker
        replayed_create = client.post(
            collection,
            headers={"Idempotency-Key": "report:lost:create"},
            json=_report_payload("Lost response report"),
        )
        replayed_submit = client.post(
            f"{collection}/{report_id}/submit",
            headers={"Idempotency-Key": "report:lost:submit"},
            json={"expected_version": 1},
        )

    assert approved.status_code == 200
    assert replayed_create.status_code == 201
    assert replayed_submit.status_code == 200
    assert replayed_create.json() == created.json()
    assert replayed_submit.json() == submitted.json()


def test_report_idempotency_key_reuse_and_stale_versions_are_conflicts() -> None:
    app, _, _, services = internal_app()
    collection = f"/v1/projects/{PROJECT_ID}/analysis/reports"
    with TestClient(app) as client:
        first = client.post(
            collection,
            headers={"Idempotency-Key": "report:conflict:first"},
            json=_report_payload("First report"),
        )
        second = client.post(
            collection,
            headers={"Idempotency-Key": "report:conflict:second"},
            json=_report_payload("Second report"),
        )
        first_id, second_id = first.json()["report_id"], second.json()["report_id"]
        submitted = client.post(
            f"{collection}/{first_id}/submit",
            headers={"Idempotency-Key": "report:shared-submit"},
            json={"expected_version": 1},
        )
        changed_input = client.post(
            f"{collection}/{first_id}/submit",
            headers={"Idempotency-Key": "report:shared-submit"},
            json={"expected_version": 2},
        )
        changed_resource = client.post(
            f"{collection}/{second_id}/submit",
            headers={"Idempotency-Key": "report:shared-submit"},
            json={"expected_version": 1},
        )
        services.principal = replace(
            services.principal,
            identity_id=UUID("40000000-0000-0000-0000-000000000005"),
        )
        stale_version = client.post(
            f"{collection}/{first_id}/approve",
            headers={"Idempotency-Key": "report:stale-version"},
            json={"expected_version": 1},
        )

    assert submitted.status_code == 200
    assert changed_input.status_code == 409
    assert changed_resource.status_code == 409
    assert stale_version.status_code == 409


def test_report_missing_resources_are_404_and_lifecycle_rules_remain_422() -> None:
    app, _, _, services = internal_app()
    collection = f"/v1/projects/{PROJECT_ID}/analysis/reports"
    missing = UUID("81000000-0000-4000-8000-000000000099")
    with TestClient(app) as client:
        missing_get = client.get(f"{collection}/{missing}")
        missing_submit = client.post(
            f"{collection}/{missing}/submit",
            headers={"Idempotency-Key": "report:missing"},
            json={"expected_version": 1},
        )
        created = client.post(
            collection,
            headers={"Idempotency-Key": "report:illegal:create"},
            json=_report_payload("Illegal transition report"),
        )
        services.principal = replace(
            services.principal,
            identity_id=UUID("40000000-0000-0000-0000-000000000005"),
        )
        illegal_transition = client.post(
            f"{collection}/{created.json()['report_id']}/approve",
            headers={"Idempotency-Key": "report:illegal:approve"},
            json={"expected_version": 1},
        )

    assert missing_get.status_code == 404
    assert missing_submit.status_code == 404
    assert illegal_transition.status_code == 422


def _report_payload(headline: str) -> dict[str, object]:
    return {
        "campaign_id": str(CAMPAIGN_ID),
        "monitoring_report_id": str(MONITORING_REPORT_ID),
        "monitoring_report_hash": digest("monitoring-report"),
        "semantic_snapshot_hash": digest("semantic-snapshot"),
        "source_kind": "provider_api",
        "approved_safe_payload": {
            "headline": headline,
            "warnings": ["Small sample"],
            "metrics": {"mention": 0.8, "sentiment": "-0.2"},
        },
    }
