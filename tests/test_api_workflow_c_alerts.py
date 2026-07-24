from __future__ import annotations

from datetime import timedelta
import json
from uuid import UUID

from fastapi.testclient import TestClient
from geo_api.workflow_c_runtime import WorkflowCApi
from geo_core.alerts import (
    AlertCommandResult,
    AlertEvidenceReference,
    AlertRuleKind,
    AlertRuleVersion,
    AlertScope,
    AlertSeverity,
    NotificationChannel,
)

from tests.workflow_c_api_test_support import NOW, PROJECT_ID, digest, internal_app


def test_alert_lifecycle_is_versioned_idempotent_and_projects_safe_notifications() -> None:
    app, api, _, _ = internal_app()
    collection = f"/v1/projects/{PROJECT_ID}/alerts"
    opened = _seed_alert(api, key="alert-open:one")
    replayed = _seed_alert(api, key="alert-open:one")

    alert_id = str(opened.alert.id)
    assert opened.alert.status.value == "open"
    assert opened.replayed is False
    assert len(opened.notification_commands) == 3
    assert replayed.replayed is True
    assert replayed.notification_commands == ()

    with TestClient(app) as client:
        acknowledged = _transition(
            client,
            f"{collection}/{alert_id}/acknowledge",
            key="alert-ack:one",
            expected_version=1,
            occurred_at=NOW + timedelta(minutes=1),
            reason="Operations accepted ownership.",
        )
        assert acknowledged["alert"]["status"] == "acknowledged"
        assert acknowledged["alert"]["version"] == 2
        acknowledged_replay = _transition(
            client,
            f"{collection}/{alert_id}/acknowledge",
            key="alert-ack:one",
            expected_version=1,
            occurred_at=NOW + timedelta(minutes=1),
            reason="Operations accepted ownership.",
        )
        assert acknowledged_replay["replayed"] is True
        assert acknowledged_replay["notifications"] == []

        suppressed_response = client.post(
            f"{collection}/{alert_id}/suppress",
            headers={"Idempotency-Key": "alert-suppress:one"},
            json={
                "expected_version": 2,
                "reason": "Known provider maintenance window.",
                "suppressed_until": (NOW + timedelta(hours=1)).isoformat(),
            },
        )
        assert suppressed_response.status_code == 200, suppressed_response.text
        suppressed = suppressed_response.json()
        assert suppressed["alert"]["status"] == "suppressed"
        assert suppressed["alert"]["suppressed_until"]

        unsuppressed = _transition(
            client,
            f"{collection}/{alert_id}/unsuppress",
            key="alert-unsuppress:one",
            expected_version=3,
            occurred_at=NOW + timedelta(minutes=3),
            reason="Provider maintenance ended early.",
        )
        assert unsuppressed["alert"]["status"] == "open"

        resolved = _transition(
            client,
            f"{collection}/{alert_id}/resolve",
            key="alert-resolve:one",
            expected_version=4,
            occurred_at=NOW + timedelta(minutes=4),
            reason="Metrics returned to the frozen baseline.",
        )
        assert resolved["alert"]["status"] == "resolved"
        assert len(resolved["alert"]["dispositions"]) == 4

        listed = client.get(collection)
        fetched = client.get(f"{collection}/{alert_id}")
        projected = client.get(f"{collection}/{alert_id}/notifications")
        assert listed.status_code == fetched.status_code == projected.status_code == 200
        assert listed.json()["total"] == 1
        assert fetched.json()["version"] == 5
        notifications = projected.json()
        assert len(notifications) == 15
        expected_summary = {
            "alert_id",
            "project_id",
            "rule_key",
            "rule_version",
            "rule_kind",
            "severity",
            "status",
            "event_type",
            "occurred_at",
            "detail_link",
        }
        assert all(set(item["summary"]) == expected_summary for item in notifications)
        serialized = json.dumps(notifications).lower()
        assert "must-not-leave-trigger-snapshot" not in serialized
        assert "authorization" not in serialized
        assert "credential" not in serialized


def test_alert_transition_conflict_maps_to_409_without_extra_notification() -> None:
    app, api, _, _ = internal_app()
    collection = f"/v1/projects/{PROJECT_ID}/alerts"
    opened = _seed_alert(api, key="alert-open:conflict")
    alert_id = str(opened.alert.id)

    with TestClient(app) as client:
        conflict = client.post(
            f"{collection}/{alert_id}/resolve",
            headers={"Idempotency-Key": "alert-resolve:stale"},
            json={
                "expected_version": 99,
                "reason": "Stale operator screen.",
            },
        )
        projected = client.get(f"{collection}/{alert_id}/notifications")

    assert conflict.status_code == 409
    assert len(projected.json()) == 3


def test_alert_trigger_is_worker_private_and_absent_from_internal_http_contract() -> None:
    app, _, _, _ = internal_app()
    schema = app.openapi()

    assert "/v1/projects/{project_id}/alerts/triggers" not in schema["paths"]
    assert "RecordAlertTriggerRequest" not in schema["components"]["schemas"]

    with TestClient(app) as client:
        response = client.post(
            f"/v1/projects/{PROJECT_ID}/alerts/triggers",
            headers={"Idempotency-Key": "alert-open:secret"},
            json={"api_key": "must-never-enter-alert-state"},
        )

    assert response.status_code == 405
    assert "must-never-enter-alert-state" not in response.text


def _seed_alert(api: WorkflowCApi, *, key: str) -> AlertCommandResult:
    rule = AlertRuleVersion(
        id=UUID("61000000-0000-4000-8000-000000000001"),
        project_id=PROJECT_ID,
        rule_key="recommendation-rate-drop",
        version=1,
        kind=AlertRuleKind.BASELINE_DELTA,
        severity=AlertSeverity.CRITICAL,
        parameters={
            "schema_version": "alert-rule-baseline-delta-v1",
            "metric_key": "recommendation_rate",
            "direction": "decrease",
            "minimum_delta": "0.2",
        },
        frozen_by="workflow-c-worker",
        frozen_at=NOW - timedelta(days=1),
    )
    scope = AlertScope(
        project_id=PROJECT_ID,
        resource_kind="sampling_run",
        resource_key="run-42",
        dimensions=(("capture_method", "provider_api"), ("region", "AU")),
    )
    result = api.alerts.evaluate_rule(
        project_id=PROJECT_ID,
        idempotency_key=key,
        rule_version=rule,
        scope=scope,
        input_values={
            "schema_version": "alert-input-baseline-delta-v1",
            "metric_key": "recommendation_rate",
            "baseline_value": "0.55",
            "current_value": "0.30",
        },
        evidence=(
            AlertEvidenceReference(
                kind="comparison_result",
                resource_id="comparison-42",
                version="v1",
                sha256=digest("comparison-42"),
                locator="/admin/comparisons/comparison-42",
            ),
        ),
        evaluated_at=NOW,
        channels=tuple(NotificationChannel),
    )
    assert result.evaluation.matched is True
    assert result.command is not None
    return result.command


def _transition(
    client: TestClient,
    path: str,
    *,
    key: str,
    expected_version: int,
    occurred_at,
    reason: str,
) -> dict[str, object]:
    response = client.post(
        path,
        headers={"Idempotency-Key": key},
        json={
            "expected_version": expected_version,
            "reason": reason,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()
