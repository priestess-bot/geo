from __future__ import annotations

from datetime import UTC, datetime
from types import TracebackType
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest

from geo_api.app_factory import create_api_app
from geo_core.access.models import AccessForbidden, AccessPrincipal, MembershipRecord
from geo_core.monitoring.application import MonitoringApplication
from geo_core.monitoring.domain import (
    Device,
    MonitoringProtocol,
    MonitoringRuleViolation,
    Platform,
    ProtocolStatus,
    QuerySuggestion,
    SuggestionStatus,
)


NOW = datetime(2026, 7, 19, tzinfo=UTC)


class _Repository:
    def __init__(self, protocol: MonitoringProtocol, suggestion: QuerySuggestion) -> None:
        self.protocol = protocol
        self.suggestion = suggestion
        self.approve_calls = 0

    def get_protocol(self, **values: object) -> MonitoringProtocol:
        del values
        return self.protocol

    def list_suggestions(self, **values: object) -> tuple[QuerySuggestion, ...]:
        del values
        return (self.suggestion,)

    def approve_suggestion(self, **values: object) -> None:
        del values
        self.approve_calls += 1
        raise AssertionError("legacy suggestion must be rejected before repository writes")


class _UnitOfWork:
    def __init__(self, repository: _Repository) -> None:
        self.monitoring = repository
        self.committed = False

    def __enter__(self) -> "_UnitOfWork":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback

    def commit(self) -> None:
        self.committed = True


class _PrincipalServices:
    def __init__(self, principal: AccessPrincipal) -> None:
        self.principal = principal

    def require_project_role(
        self,
        authentication: object,
        *,
        project_id: UUID,
        allowed_roles: frozenset[str],
    ) -> AccessPrincipal:
        del authentication
        membership = next(
            (item for item in self.principal.memberships if item.project_id == project_id),
            None,
        )
        if membership is None or membership.role not in allowed_roles:
            raise AccessForbidden("project membership is required")
        return self.principal


def test_legacy_suggestion_without_cluster_is_rejected_before_repository_write() -> None:
    values = _fixture()

    with pytest.raises(MonitoringRuleViolation, match="explicit cluster key"):
        values["application"].approve_suggestion(
            values["principal"],
            project_id=values["project_id"],
            campaign_id=values["campaign_id"],
            protocol_id=values["protocol_id"],
            suggestion_id=values["suggestion_id"],
        )

    assert values["repository"].approve_calls == 0
    assert values["unit_of_work"].committed is False


def test_legacy_suggestion_approval_maps_to_monitoring_rule_problem() -> None:
    values = _fixture()
    app = create_api_app(
        surface="internal",
        services=_PrincipalServices(values["principal"]),  # type: ignore[arg-type]
        monitoring_application=values["application"],
    )
    path = (
        f"/v1/projects/{values['project_id']}/monitoring-protocols/"
        f"{values['protocol_id']}/query-suggestions/{values['suggestion_id']}/approve"
        f"?campaign_id={values['campaign_id']}"
    )

    with TestClient(app) as client:
        response = client.post(path)

    assert response.status_code == 422
    assert response.json()["type"] == "urn:geo:problem:monitoring-rule-violation"
    assert "explicit cluster key" in response.json()["detail"]
    assert values["repository"].approve_calls == 0


def _fixture() -> dict[str, object]:
    project_id = uuid4()
    campaign_id = uuid4()
    protocol_id = uuid4()
    suggestion_id = uuid4()
    tenant_id = uuid4()
    principal = AccessPrincipal(
        identity_id=uuid4(),
        actor_id="legacy-suggestion-test",
        tenant_id=tenant_id,
        memberships=(MembershipRecord(project_id, tenant_id, "owner"),),
        auth_method="test",
    )
    protocol = MonitoringProtocol(
        id=protocol_id,
        project_id=project_id,
        campaign_id=campaign_id,
        market_profile_id=uuid4(),
        name="Legacy draft",
        platform=Platform.CHATGPT_SEARCH,
        locale="en-AU",
        device=Device.DESKTOP,
        sample_size=1,
        window_days=28,
        status=ProtocolStatus.DRAFT,
        protocol_hash=None,
        created_at=NOW,
    )
    suggestion = QuerySuggestion(
        id=suggestion_id,
        project_id=project_id,
        protocol_id=protocol_id,
        query_text="Which product?",
        query_kind="recommendation",
        rationale="Legacy suggestion",
        status=SuggestionStatus.SUGGESTED,
        created_at=NOW,
        query_cluster_key=None,
    )
    repository = _Repository(protocol, suggestion)
    unit_of_work = _UnitOfWork(repository)
    application = MonitoringApplication(
        lambda principal: unit_of_work  # type: ignore[arg-type]
    )
    return {
        "application": application,
        "principal": principal,
        "project_id": project_id,
        "campaign_id": campaign_id,
        "protocol_id": protocol_id,
        "suggestion_id": suggestion_id,
        "repository": repository,
        "unit_of_work": unit_of_work,
    }
