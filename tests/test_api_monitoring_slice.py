from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from geo_api.app_factory import create_api_app
from geo_core.access.models import AccessForbidden, AccessPrincipal, MembershipRecord
from geo_core.monitoring.application import MonitoringApplication
from geo_core.monitoring.domain import (
    REPORT_METHODOLOGY,
    Device,
    MeasurementWindow,
    MetricSnapshot,
    MonitoringProtocol,
    MonitoringReport,
    Platform,
    ProtocolStatus,
    VerifiedUrl,
)


NOW = datetime(2026, 7, 16, tzinfo=UTC)


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


class ReadModelApplication(MonitoringApplication):
    def __init__(self, project_id: UUID) -> None:
        self.project_id = project_id
        self.metric = MetricSnapshot(
            uuid4(), project_id, uuid4(), uuid4(), MeasurementWindow.T28, 10, 8,
            Decimal("0.5"), Decimal("0.5"), Decimal("0.25"), Decimal("0.5"),
            Decimal("0.25"), Decimal("0.1"), "confounded", ("failed_samples",),
            "a" * 64, "geo-observational-v1", NOW,
        )

    def list_metrics(self, principal: AccessPrincipal, *, project_id: UUID):
        del principal
        assert project_id == self.project_id
        return (self.metric,)

    def list_verified_urls(self, principal: AccessPrincipal, *, project_id: UUID):
        del principal
        assert project_id == self.project_id
        return (
            VerifiedUrl(
                self.metric.campaign_id, (self.metric.protocol_id,),
                "https://example.com/review", "Review", uuid4(), NOW, 3,
            ),
        )

    def list_reports(
        self, principal: AccessPrincipal, *, project_id: UUID, approved_only: bool
    ):
        del principal
        assert project_id == self.project_id
        assert approved_only
        return (
            MonitoringReport(
                uuid4(), project_id, self.metric.protocol_id, self.metric.campaign_id,
                self.metric.id,
                "Approved report", "Public aggregate only", REPORT_METHODOLOGY,
                "b" * 64, "approved", NOW, NOW,
            ),
        )

    def list_protocols(self, principal: AccessPrincipal, *, project_id: UUID):
        del principal
        return (
            MonitoringProtocol(
                uuid4(), project_id, self.metric.campaign_id, uuid4(), "Frozen",
                Platform.CHATGPT_SEARCH,
                "en-AU", Device.DESKTOP, 10, 28, ProtocolStatus.FROZEN,
                "c" * 64, NOW, NOW, NOW,
            ),
        )


def _app(surface: str = "customer") -> tuple[object, AccessPrincipal]:
    tenant_id, identity_id, project_id = uuid4(), uuid4(), uuid4()
    principal = AccessPrincipal(
        identity_id, "customer-subject", tenant_id,
        (MembershipRecord(project_id, tenant_id, "customer"),), "session",
    )
    return (
        create_api_app(
            surface=surface,  # type: ignore[arg-type]
            services=PrincipalServices(principal),  # type: ignore[arg-type]
            monitoring_application=ReadModelApplication(project_id),
        ),
        principal,
    )


def test_customer_surface_is_read_only_and_never_exposes_raw_observations() -> None:
    app, principal = _app()
    project_id = principal.project_ids[0]
    with TestClient(app) as client:  # type: ignore[arg-type]
        metrics = client.get(f"/v1/projects/{project_id}/geo/metrics")
        reports = client.get(f"/v1/projects/{project_id}/geo/reports")
        summary = client.get(f"/v1/projects/{project_id}/geo/summary")

    assert metrics.status_code == reports.status_code == summary.status_code == 200
    serialized = str(metrics.json()) + str(reports.json()) + str(summary.json())
    assert "raw_answer" not in serialized
    assert "raw_result" not in serialized
    assert reports.json()[0]["status"] == "approved"
    assert reports.json()[0]["methodology_statement"] == REPORT_METHODOLOGY


def test_customer_openapi_has_only_read_operations_for_geo_routes() -> None:
    app, _ = _app()
    paths = app.openapi()["paths"]  # type: ignore[union-attr]
    geo_paths = {path: item for path, item in paths.items() if "/geo/" in path}

    assert len(geo_paths) == 5
    assert all(set(item) & {"post", "put", "patch", "delete"} == set() for item in geo_paths.values())
    assert not any("observation" in path for path in paths)


def test_customer_project_scope_is_enforced_before_read_model_access() -> None:
    app, _ = _app()
    with TestClient(app) as client:  # type: ignore[arg-type]
        response = client.get(f"/v1/projects/{uuid4()}/geo/metrics")

    assert response.status_code == 403


def test_internal_monitoring_dto_rejects_actor_and_tenant_fields() -> None:
    app, principal = _app("internal")
    with TestClient(app) as client:  # type: ignore[arg-type]
        response = client.post(
            f"/v1/projects/{principal.project_ids[0]}/monitoring-protocols",
            json={
                "market_profile_id": str(uuid4()), "name": "Protocol",
                "campaign_id": str(uuid4()),
                "platform": "chatgpt_search", "locale": "en-AU", "device": "desktop",
                "sample_size": 10, "window_days": 28,
                "actor_id": str(uuid4()), "tenant_id": str(uuid4()),
            },
        )

    assert response.status_code == 422
