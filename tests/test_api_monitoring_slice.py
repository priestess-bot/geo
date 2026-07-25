from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from geo_api.app_factory import create_api_app
from geo_api.monitoring_contracts import SourceStratumContract
from geo_api.monitoring_source_adapters import source_stratum
from geo_core.access.models import AccessForbidden, AccessPrincipal, MembershipRecord
from geo_core.monitoring.application import MonitoringApplication
from geo_core.monitoring.customer_projection import ApprovedReportSnapshot, CustomerCampaign
from geo_core.monitoring.domain import (
    REPORT_METHODOLOGY,
    Device,
    MeasurementWindow,
    MetricSnapshot,
    MonitoringNotFound,
    MonitoringProtocol,
    MonitoringReport,
    Platform,
    ProtocolQuery,
    ProtocolStatus,
    VerifiedCitationTarget,
    VerifiedUrl,
    source_strata_inventory_hash,
)
from geo_core.monitoring.source_contract import (
    CaptureMethod,
    ClientKind,
    ModelIdentity,
    ModelIdentityState,
    ObservationDevice,
    ObservationPlatform,
    ObservationSurface,
    SearchMode,
    SourceStratumKey,
    SurfaceKind,
    RawEvidence,
)
from geo_core.workflow_c_reports import WorkflowCCustomerApprovedReport, WorkflowCCustomerReportReader


NOW = datetime(2026, 7, 16, tzinfo=UTC)
SOURCE_STRATUM = SourceStratumKey(
    capture_method=CaptureMethod.MANUAL_UI,
    platform=ObservationPlatform.OPENAI,
    surface=ObservationSurface.CHATGPT_SEARCH,
    surface_kind=SurfaceKind.CONSUMER_UI,
    engine="chatgpt",
    configured_model=ModelIdentity(ModelIdentityState.DISCLOSED, "model-v1"),
    reported_model=ModelIdentity(ModelIdentityState.DISCLOSED, "model-v1"),
    locale="en-AU",
    region="AU",
    language="en",
    device=ObservationDevice.DESKTOP,
    client_kind=ClientKind.BROWSER,
    search_enabled=True,
    search_mode=SearchMode.LIVE_WEB,
)


class PrincipalServices:
    def __init__(self, principal: AccessPrincipal) -> None:
        self.principal = principal

    def require_project_role(
        self, authentication: object, *, project_id: UUID, allowed_roles: frozenset[str]
    ) -> AccessPrincipal:
        del authentication
        membership = next(
            (item for item in self.principal.memberships if item.project_id == project_id), None
        )
        if membership is None or membership.role not in allowed_roles:
            raise AccessForbidden("project membership is required")
        return self.principal


class WorkflowCCustomerReaderStub:
    persistence: Literal["durable"] = "durable"

    def __init__(self, report: WorkflowCCustomerApprovedReport) -> None:
        self.report = report
        self.calls: list[tuple[UUID, UUID]] = []

    def list_approved_reports(
        self, *, project_id: UUID, campaign_id: UUID
    ) -> tuple[WorkflowCCustomerApprovedReport, ...]:
        self.calls.append((project_id, campaign_id))
        if project_id != self.report.project_id or campaign_id != self.report.campaign_id:
            return ()
        return (self.report,)


class ReadModelApplication(MonitoringApplication):
    def __init__(self, project_id: UUID) -> None:
        self.project_id = project_id
        self.metric = MetricSnapshot(
            id=uuid4(),
            project_id=project_id,
            protocol_id=uuid4(),
            campaign_id=uuid4(),
            measurement_window=MeasurementWindow.T28,
            source_stratum=SOURCE_STRATUM,
            source_stratum_hash=SOURCE_STRATUM.canonical_hash(),
            expected_sample_count=10,
            eligible_sample_count=8,
            recommendation_share=Decimal("0.5"),
            product_mention_share=Decimal("0.5"),
            placement_citation_share=Decimal("0.25"),
            qualified_destination_coverage=Decimal("0.5"),
            verified_placement_coverage=Decimal("0.25"),
            competitive_delta=Decimal("0.1"),
            status="confounded",
            confounded_reasons=("failed_samples",),
            input_hash="a" * 64,
            method_version="geo-observational-source-separated-v1",
            computed_at=NOW,
        )
        self.report = MonitoringReport(
            uuid4(),
            project_id,
            self.metric.protocol_id,
            self.metric.campaign_id,
            self.metric.id,
            "Approved report",
            "Public aggregate only",
            REPORT_METHODOLOGY,
            "b" * 64,
            "approved",
            NOW,
            NOW,
        )
        self.campaign = CustomerCampaign(
            self.metric.campaign_id,
            project_id,
            "Customer Campaign",
            "recommendation_influence",
            "active",
            1,
            NOW,
        )

    def list_customer_campaigns(self, principal: AccessPrincipal, *, project_id: UUID):
        del principal
        assert project_id == self.project_id
        return (self.campaign,)

    def get_customer_campaign(
        self, principal: AccessPrincipal, *, project_id: UUID, campaign_id: UUID
    ):
        del principal
        assert project_id == self.project_id
        if campaign_id != self.campaign.id:
            raise MonitoringNotFound("Campaign is outside the authenticated project scope.")
        return self.campaign

    def list_customer_approved_report_snapshots(
        self, principal: AccessPrincipal, *, project_id: UUID, campaign_id: UUID
    ):
        del principal
        assert project_id == self.project_id
        assert campaign_id == self.metric.campaign_id
        return (ApprovedReportSnapshot(self.report, self.metric),)

    def verify_raw_evidence(
        self,
        *,
        project_id: UUID,
        capture_method: CaptureMethod,
        evidence: RawEvidence,
    ) -> RawEvidence:
        del project_id, capture_method
        return replace(evidence, artifact_verified=True)

    def list_metrics(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID | None = None,
    ):
        del principal
        assert project_id == self.project_id
        assert campaign_id is None or campaign_id == self.metric.campaign_id
        return (self.metric,)

    def list_verified_urls(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID | None = None,
    ):
        del principal
        assert project_id == self.project_id
        assert campaign_id is None or campaign_id == self.metric.campaign_id
        return (
            VerifiedUrl(
                self.metric.campaign_id,
                (self.metric.protocol_id,),
                "https://example.com/review",
                "Review",
                uuid4(),
                NOW,
                3,
            ),
        )

    def list_customer_approved_verified_urls(
        self, principal: AccessPrincipal, *, project_id: UUID, campaign_id: UUID
    ):
        del principal
        assert project_id == self.project_id
        assert campaign_id == self.metric.campaign_id
        return ()

    def list_reports(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        approved_only: bool,
        campaign_id: UUID | None = None,
    ):
        del principal
        assert project_id == self.project_id
        assert campaign_id is None or campaign_id == self.metric.campaign_id
        assert approved_only
        return (self.report,)

    def list_protocols(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID | None = None,
    ):
        del principal
        assert campaign_id is None or campaign_id == self.metric.campaign_id
        return (
            MonitoringProtocol(
                uuid4(),
                project_id,
                self.metric.campaign_id,
                uuid4(),
                "Frozen",
                Platform.CHATGPT_SEARCH,
                "en-AU",
                Device.DESKTOP,
                10,
                28,
                ProtocolStatus.FROZEN,
                "c" * 64,
                NOW,
                NOW,
                NOW,
                (SOURCE_STRATUM,),
                source_strata_inventory_hash((SOURCE_STRATUM,)),
            ),
        )

    def list_protocol_queries(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        protocol_id: UUID,
    ):
        del principal, campaign_id
        return (
            ProtocolQuery(
                uuid4(),
                project_id,
                protocol_id,
                uuid4(),
                "best robot vacuum",
                "recommendation",
                "en-AU",
                1,
            ),
        )

    def list_citation_targets(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        protocol_id: UUID,
    ):
        del principal, project_id, campaign_id, protocol_id
        return (
            VerifiedCitationTarget(
                uuid4(),
                uuid4(),
                "owned-au",
                "owned_site",
                "https://example.com/verified",
                NOW,
            ),
        )


def _app(
    surface: str = "customer",
    role: str = "customer",
    workflow_c_customer_reader: WorkflowCCustomerReportReader | None = None,
    project_id: UUID | None = None,
) -> tuple[FastAPI, AccessPrincipal]:
    tenant_id, identity_id = uuid4(), uuid4()
    resolved_project_id = project_id or uuid4()
    principal = AccessPrincipal(
        identity_id,
        "customer-subject",
        tenant_id,
        (MembershipRecord(resolved_project_id, tenant_id, role),),
        "session",
    )
    return (
        create_api_app(
            surface=surface,  # type: ignore[arg-type]
            services=PrincipalServices(principal),  # type: ignore[arg-type]
            monitoring_application=ReadModelApplication(resolved_project_id),
            workflow_c_customer_reader=workflow_c_customer_reader,
        ),
        principal,
    )


def test_customer_surface_is_read_only_and_never_exposes_raw_observations() -> None:
    app, principal = _app()
    project_id = principal.project_ids[0]
    campaign_id = app.state.monitoring_application.metric.campaign_id
    with TestClient(app) as client:
        query = {"campaign_id": str(campaign_id)}
        metrics = client.get(f"/v1/projects/{project_id}/geo/metrics", params=query)
        reports = client.get(f"/v1/projects/{project_id}/geo/reports", params=query)
        summary = client.get(f"/v1/projects/{project_id}/geo/summary", params=query)
        read_model = client.get(f"/v1/projects/{project_id}/geo/campaigns/{campaign_id}/read-model")

    assert metrics.status_code == reports.status_code == summary.status_code == 200
    assert read_model.status_code == 200
    serialized = str(metrics.json()) + str(reports.json()) + str(summary.json())
    assert "raw_answer" not in serialized
    assert "raw_result" not in serialized
    assert reports.json()[0]["status"] == "approved"
    assert reports.json()[0]["methodology_statement"] == REPORT_METHODOLOGY
    approved = read_model.json()["approved_measurements"][0]
    assert approved["report"]["metric_snapshot_id"] == approved["snapshot"]["id"]
    assert approved["snapshot_contract"] == "legacy_unknown"
    assert read_model.json()["verified_urls"] == []


def test_customer_openapi_has_only_read_operations_for_geo_routes() -> None:
    app, _ = _app()
    paths = app.openapi()["paths"]
    geo_paths = {path: item for path, item in paths.items() if "/geo/" in path}

    # Legacy monitoring has seven read routes.  The eighth is the separate,
    # independently-approved Workflow C report projection, which is likewise
    # Customer-read-only and never exposes a raw observation.
    assert len(geo_paths) == 8
    assert "/v1/projects/{project_id}/geo/workflow-c-reports" in geo_paths
    assert all(
        set(item) & {"post", "put", "patch", "delete"} == set() for item in geo_paths.values()
    )
    assert not any("observation" in path for path in paths)


def test_customer_workflow_c_reports_use_only_the_durable_approved_reader() -> None:
    project_id, campaign_id = uuid4(), uuid4()
    report = WorkflowCCustomerApprovedReport(
        id=uuid4(),
        project_id=project_id,
        campaign_id=campaign_id,
        semantic_snapshot_hash="a" * 64,
        report_hash="b" * 64,
        source_kind="provider_api",
        approved_safe_payload={
            "headline": "Approved aggregate",
            "summary": "Approved aggregate",
            "mention_rate": "0.5",
        },
        approved_at=NOW,
    )
    reader = WorkflowCCustomerReaderStub(report)
    app, principal = _app(
        workflow_c_customer_reader=reader,
        project_id=project_id,
    )
    requested_project = principal.project_ids[0]
    foreign_campaign_id = uuid4()

    with TestClient(app) as client:
        allowed = client.get(
            f"/v1/projects/{requested_project}/geo/workflow-c-reports",
            params={"campaign_id": str(campaign_id)},
        )
        foreign = client.get(
            f"/v1/projects/{requested_project}/geo/workflow-c-reports",
            params={"campaign_id": str(foreign_campaign_id)},
        )

    assert allowed.status_code == foreign.status_code == 200
    assert allowed.json() == {
        "items": [
            {
                "id": str(report.id),
                "project_id": str(project_id),
                "campaign_id": str(campaign_id),
                "semantic_snapshot_hash": "a" * 64,
                "report_hash": "b" * 64,
                "source_kind": "provider_api",
                "approved_safe_payload": {
                    "headline": "Approved aggregate",
                    "summary": "Approved aggregate",
                    "mention_rate": "0.5",
                },
                "approved_at": "2026-07-16T00:00:00Z",
            }
        ],
        "total": 1,
    }
    assert foreign.json() == {"items": [], "total": 0}
    assert reader.calls == [
        (requested_project, campaign_id),
        (requested_project, foreign_campaign_id),
    ]


def test_customer_project_scope_is_enforced_before_read_model_access() -> None:
    app, _ = _app()
    campaign_id = app.state.monitoring_application.metric.campaign_id
    with TestClient(app) as client:
        response = client.get(
            f"/v1/projects/{uuid4()}/geo/metrics",
            params={"campaign_id": str(campaign_id)},
        )

    assert response.status_code == 403


def test_customer_analytics_require_an_explicit_campaign() -> None:
    app, principal = _app()
    project_id = principal.project_ids[0]
    with TestClient(app) as client:
        responses = [
            client.get(f"/v1/projects/{project_id}/geo/{resource}")
            for resource in (
                "metrics",
                "measurement-windows",
                "verified-urls",
                "reports",
                "summary",
            )
        ]

    assert {response.status_code for response in responses} == {422}


def test_customer_invalid_campaign_is_a_404_and_never_falls_back() -> None:
    app, principal = _app()
    project_id = principal.project_ids[0]
    requested_campaign = uuid4()
    with TestClient(app) as client:
        campaigns = client.get(f"/v1/projects/{project_id}/geo/campaigns")
        response = client.get(
            f"/v1/projects/{project_id}/geo/campaigns/{requested_campaign}/read-model"
        )

    assert campaigns.status_code == 200
    assert len(campaigns.json()) == 1
    assert response.status_code == 404
    assert response.json()["type"] == "urn:geo:problem:monitoring-not-found"


def test_internal_monitoring_dto_rejects_actor_and_tenant_fields() -> None:
    app, principal = _app("internal")
    with TestClient(app) as client:
        response = client.post(
            f"/v1/projects/{principal.project_ids[0]}/monitoring-protocols",
            json={
                "market_profile_id": str(uuid4()),
                "name": "Protocol",
                "campaign_id": str(uuid4()),
                "platform": "chatgpt_search",
                "locale": "en-AU",
                "device": "desktop",
                "sample_size": 10,
                "window_days": 28,
                "actor_id": str(uuid4()),
                "tenant_id": str(uuid4()),
            },
        )

    assert response.status_code == 422


def test_internal_monitoring_exposes_frozen_queries_and_verified_citation_targets() -> None:
    app, principal = _app("internal", "owner")
    application = app.state.monitoring_application
    campaign_id = application.metric.campaign_id
    project_id, protocol_id = principal.project_ids[0], uuid4()
    with TestClient(app) as client:
        queries = client.get(
            f"/v1/projects/{project_id}/monitoring-protocols/{protocol_id}/queries",
            params={"campaign_id": str(campaign_id)},
        )
        targets = client.get(
            f"/v1/projects/{project_id}/monitoring-protocols/{protocol_id}/citation-targets",
            params={"campaign_id": str(campaign_id)},
        )

    assert queries.status_code == targets.status_code == 200
    assert queries.json()[0]["protocol_id"] == str(protocol_id)
    assert targets.json()[0]["url"] == "https://example.com/verified"
    assert targets.json()[0]["publication_channel"] == "owned_site"


def test_citation_verification_fields_are_server_authoritative() -> None:
    app, _ = _app("internal", "owner")
    properties = app.openapi()["components"]["schemas"]["ObservationCitationRequest"]["properties"]

    assert set(properties) == {"url", "title", "submission_id"}


def test_public_observation_contract_rejects_non_observational_capture_methods() -> None:
    app, _ = _app("internal", "owner")
    schema = app.openapi()["components"]["schemas"]
    observation = schema["ImportObservationRequest"]

    assert observation["properties"]["capture_method"]["enum"] == [
        "manual_ui",
        "provider_api",
        "proxy_grounded_api",
    ]
    assert "citations" in observation["required"]
    assert set(schema["ObservationSourceRequest"]["properties"]["surface"]["enum"]) >= {
        "bing_search",
        "bing_copilot",
        "claude_ai",
    }


def test_source_stratum_transport_enforces_v3_other_details() -> None:
    payload = {
        **SOURCE_STRATUM.canonical_value(),
        "platform": "other",
        "surface": "other",
        "surface_kind": "consumer_ui",
        "platform_detail": "answer-engine-a",
        "surface_detail": "consumer-surface-a",
    }
    first = source_stratum(SourceStratumContract.model_validate(payload))
    second = source_stratum(
        SourceStratumContract.model_validate(
            {
                **payload,
                "platform_detail": "answer-engine-b",
                "surface_detail": "consumer-surface-b",
            }
        )
    )

    assert first.canonical_hash() != second.canonical_hash()
    assert first.canonical_value()["platform_detail"] == "answer-engine-a"
    with pytest.raises(ValidationError, match="platform_detail"):
        SourceStratumContract.model_validate({**payload, "platform_detail": None})
    with pytest.raises(ValidationError, match="exactly for OTHER"):
        SourceStratumContract.model_validate(
            {
                **SOURCE_STRATUM.canonical_value(),
                "platform_detail": "unexpected",
            }
        )


def test_statistics_v2_transport_exposes_strata_completion_uncertainty_and_queries() -> None:
    app, _ = _app("internal", "owner")
    schema = app.openapi()["components"]["schemas"]
    metric = schema["MetricResponse"]
    query_result = schema["QueryMetricResultResponse"]
    compute = schema["ComputeMetricsRequest"]

    assert {
        "statistics_contract_version",
        "query_cluster_key",
        "analysis_stratum_hash",
        "minimum_valid_repeats",
        "sampled_sample_count",
        "invalid_sample_count",
        "missing_sample_count",
        "sampling_completion_ratio",
        "valid_completion_ratio",
        "invalid_reason_counts",
        "query_results",
        "recommendation_ci_low",
        "recommendation_ci_high",
        "worst_query_id",
        "result_hash",
        "observation_membership_version",
        "observation_membership_hash",
        "observation_membership_count",
    } <= set(metric["properties"])
    assert set(query_result["properties"]) == {
        "monitoring_query_id",
        "query_text_snapshot",
        "query_cluster_key",
        "expected_sample_count",
        "sampled_sample_count",
        "valid_sample_count",
        "invalid_sample_count",
        "missing_sample_count",
        "meets_threshold",
        "invalid_reason_counts",
        "confounding_factors",
        "recommendation",
        "product_mention",
        "placement_citation",
        "competitor",
        "competitive_delta",
    }
    assert "query_cluster_key" in compute["required"]
    assert metric["properties"]["status"]["enum"] == [
        "complete",
        "confounded",
        "insufficient_evidence",
    ]


def test_official_reports_and_csv_have_dedicated_internal_routes() -> None:
    app, _ = _app("internal", "owner")
    paths = app.openapi()["paths"]

    official = "/v1/projects/{project_id}/monitoring-official-report-imports"
    export = "/v1/projects/{project_id}/geo/campaigns/{campaign_id}/" "monitoring-observations.csv"
    assert set(paths[official]) >= {"get", "post"}
    assert set(paths[export]) >= {"get"}
    assert paths[official]["post"]["operationId"] == "importMonitoringOfficialReport"


def test_invalid_official_report_row_is_a_422_not_an_internal_error() -> None:
    app, principal = _app("internal", "owner")
    project_id = principal.project_ids[0]
    application = app.state.monitoring_application
    with TestClient(app) as client:
        response = client.post(
            f"/v1/projects/{project_id}/monitoring-official-report-imports",
            headers={"Idempotency-Key": "official-row-validation"},
            json={
                "campaign_id": str(application.metric.campaign_id),
                "platform": "google",
                "surface": "google_generative_ai_performance_report",
                "artifact": {
                    "kind": "artifact",
                    "artifact_uri": (
                        f"s3://geo-artifacts/observation-artifacts/{project_id}/report.csv"
                    ),
                    "artifact_hash": "a" * 64,
                },
                "parser_name": "google-ai-performance-csv",
                "parser_version": "1.0.0",
                "report_period_start": "2026-06-01",
                "report_period_end": "2026-06-30",
                "account_ref": "account-1",
                "rows": [
                    {
                        "row_index": 0,
                        "row_data": {"query": "robot vacuum"},
                        "requested_eligible": True,
                        "operator_ineligible_reasons": ["cannot-coexist"],
                    }
                ],
            },
        )

    assert response.status_code == 422
    assert "eligible report row cannot carry reasons" in response.json()["detail"]
