from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from geo_api.app_factory import create_api_app
from geo_api.workflow_c_routes import mount_workflow_c_internal

from tests.workflow_c_api_test_support import PROJECT_ID, PrincipalServices, internal_app, principal


def test_workflow_c_internal_control_plane_is_internal_only() -> None:
    internal, _, _, _ = internal_app()
    customer = create_api_app(
        surface="customer", services=PrincipalServices(principal("customer"))
    )
    internal_paths = set(internal.openapi()["paths"])
    customer_paths = set(customer.openapi()["paths"])
    owned_prefixes = (
        "/v1/projects/{project_id}/sampling",
        "/v1/projects/{project_id}/analysis",
        "/v1/projects/{project_id}/alerts",
    )

    assert any(path.startswith(owned_prefixes) for path in internal_paths)
    assert not any(path.startswith(owned_prefixes) for path in customer_paths)
    assert "/v1/projects/{project_id}/geo/workflow-c-reports" in customer_paths
    with pytest.raises(ValueError, match="Internal API"):
        mount_workflow_c_internal(customer, api=internal.state.workflow_c_api)

    with TestClient(customer) as client:
        sampling = client.get(f"/v1/projects/{PROJECT_ID}/sampling/runs/{PROJECT_ID}")
        alerts = client.get(f"/v1/projects/{PROJECT_ID}/alerts")
        trigger = client.post(f"/v1/projects/{PROJECT_ID}/alerts/triggers", json={})
        metrics = client.post(
            f"/v1/projects/{PROJECT_ID}/analysis/semantic-metrics/compute", json={}
        )
        reports = client.get(
            f"/v1/projects/{PROJECT_ID}/geo/workflow-c-reports",
            params={"campaign_id": str(PROJECT_ID)},
        )
    assert sampling.status_code == alerts.status_code == trigger.status_code == metrics.status_code == 404
    assert reports.status_code == 503
    assert reports.json()["type"] == "urn:geo:problem:workflow-c-customer-unavailable"


def test_customer_mounts_only_the_durable_workflow_c_report_reader() -> None:
    customer = create_api_app(
        surface="customer",
        services=PrincipalServices(principal("customer")),
        workflow_c_customer_reader=_DurableCustomerReader(),
    )

    paths = set(customer.openapi()["paths"])

    assert "/v1/projects/{project_id}/geo/workflow-c-reports" in paths
    assert not any(path.startswith("/v1/projects/{project_id}/sampling") for path in paths)
    with TestClient(customer) as client:
        response = client.get(
            f"/v1/projects/{PROJECT_ID}/geo/workflow-c-reports",
            params={"campaign_id": str(PROJECT_ID)},
        )
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}


class _DurableCustomerReader:
    persistence = "durable"

    def list_approved_reports(self, *, project_id, campaign_id):
        del project_id, campaign_id
        return ()


def test_default_internal_mount_is_discoverable_but_fails_closed_without_durable_runtime() -> None:
    internal = create_api_app(
        surface="internal", services=PrincipalServices(principal("admin"))
    )

    assert "/v1/projects/{project_id}/alerts" in internal.openapi()["paths"]
    with TestClient(internal) as client:
        response = client.get(f"/v1/projects/{PROJECT_ID}/alerts")

    assert response.status_code == 503
    assert response.headers["retry-after"] == "30"
    assert response.json()["type"] == "urn:geo:problem:workflow-c-unavailable"


def test_workflow_c_openapi_excludes_automated_ui_and_b_workflow_commands() -> None:
    internal, api, _, _ = internal_app()
    schema = internal.openapi()
    capture_schema = schema["components"]["schemas"]["SamplingSourceStratumContract"]
    capture_property = capture_schema["properties"]["capture_method"]
    operation_ids = {
        operation["operationId"]
        for path, path_item in schema["paths"].items()
        if path.startswith(
            (
                "/v1/projects/{project_id}/sampling",
                "/v1/projects/{project_id}/analysis",
                "/v1/projects/{project_id}/alerts",
            )
        )
        for method, operation in path_item.items()
        if method in {"get", "post"}
    }

    assert set(capture_property["enum"]) == {
        "provider_api",
        "proxy_grounded_api",
        "manual_ui",
    }
    assert api.persistence == "memory_test_only"
    assert {
        "createMetricProtocol",
        "listMetricProtocols",
        "getMetricProtocol",
        "submitMetricProtocol",
        "approveMetricProtocol",
        "retireMetricProtocol",
        "enqueueSemanticMetricJob",
    }.issubset(operation_ids)
    assert not {
        "claimSamplingAttempt",
        "heartbeatSamplingAttempt",
        "finalizeSamplingObservation",
        "failSamplingAttempt",
        "acknowledgeSamplingCancellation",
    }.intersection(operation_ids)
    forbidden = ("browser", "egress", "connector", "attribution", "automated")
    assert not any(term in operation.lower() for operation in operation_ids for term in forbidden)
    assert "/v1/projects/{project_id}/alerts/triggers" not in schema["paths"]
    assert schema["components"]["schemas"]["CreateSamplingSuiteRequest"][
        "additionalProperties"
    ] is False
    suite_request = schema["components"]["schemas"]["CreateSamplingSuiteRequest"][
        "properties"
    ]
    assert not {"questions", "source_stratum", "configured_model"}.intersection(
        suite_request
    )
    assert set(suite_request) == {
        "suite_input_option_key",
        "repetitions",
        "statistics_method_version",
        "max_planned_tasks",
        "max_daily_tasks",
        "minimum_request_interval_seconds",
        "max_concurrency",
    }
    admission_request = schema["components"]["schemas"][
        "CreateAdmissionPolicyRequest"
    ]["properties"]
    assert not {
        "adapter_release",
        "location_evidence_hash",
        "authorization_reference",
        "next_allowed_at",
    }.intersection(admission_request)
    assert "RecordAlertTriggerRequest" not in schema["components"]["schemas"]
    attempt = schema["components"]["schemas"]["SamplingAttemptResponse"]
    assert not {
        "lease_token",
        "lease_owner",
        "lease_expires_at",
        "fencing_generation",
    }.intersection(attempt["properties"])
    evidence = schema["components"]["schemas"]["ObservationEvidenceSummaryResponse"]
    assert not {"answer_text", "raw_artifact_uri", "manifest_reference"}.intersection(
        evidence["properties"]
    )
    semantic_request = schema["components"]["schemas"][
        "ComputeSemanticMetricsRequest"
    ]["properties"]
    comparison_request = schema["components"]["schemas"][
        "AnalyzeComparisonFamilyRequest"
    ]["properties"]
    drift_request = schema["components"]["schemas"]["ComputeDriftRequest"][
        "properties"
    ]
    forbidden_analysis_truth = {
        "observations",
        "observation_artifacts",
        "planned_slots",
        "comparisons",
        "pairs",
        "baseline",
        "current",
        "effect",
        "p_value",
        "computed_at",
    }
    assert not forbidden_analysis_truth.intersection(semantic_request)
    assert not forbidden_analysis_truth.intersection(comparison_request)
    assert not forbidden_analysis_truth.intersection(drift_request)


def test_workflow_c_customer_report_payload_is_typed_in_input_and_output_openapi() -> None:
    internal, _, _, _ = internal_app()
    schemas = internal.openapi()["components"]["schemas"]
    input_payload = schemas["WorkflowCCustomerSafePayload-Input"]
    output_payload = schemas["WorkflowCCustomerSafePayloadSerialized"]

    assert input_payload["additionalProperties"] is False
    assert output_payload["additionalProperties"] is False
    assert input_payload["required"] == output_payload["required"] == ["headline"]
    assert set(input_payload["properties"]) == set(output_payload["properties"]) == {
        "headline",
        "summary",
        "methodology",
        "warnings",
        "metrics",
        "mention_rate",
        "recommendation_rate",
    }
    metric_object = input_payload["properties"]["metrics"]["anyOf"][0]
    assert metric_object["minProperties"] == 1
    assert "access_token" not in metric_object["propertyNames"]["enum"]
