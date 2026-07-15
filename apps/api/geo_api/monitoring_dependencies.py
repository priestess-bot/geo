"""Shared authorization and error mapping for monitoring API adapters."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from fastapi import Request

from geo_api.foundation_services import AuthenticationInput, FoundationServiceUnavailable
from geo_api.problems import ApiProblem
from geo_core.access.models import AccessPrincipal
from geo_core.monitoring.application import MonitoringApplication
from geo_core.monitoring.domain import (
    MonitoringConflict,
    MonitoringForbidden,
    MonitoringNotFound,
    MonitoringPersistenceUnavailable,
    MonitoringRuleViolation,
)


def authorize_monitoring_project(
    request: Request,
    authorization: str | None,
    project_id: UUID,
    allowed_roles: frozenset[str],
) -> AccessPrincipal:
    authentication = AuthenticationInput(
        authorization=authorization,
        customer_session=request.cookies.get(request.app.state.customer_session_cookie_name),
        development_actor_id=request.headers.get("X-GEO-Actor-ID"),
        development_tenant_id=request.headers.get("X-GEO-Tenant-ID"),
    )
    operation = getattr(request.app.state.services, "require_project_role", None)
    if not callable(operation):
        raise FoundationServiceUnavailable("Project authorization is not connected.")
    return cast(
        AccessPrincipal,
        operation(authentication, project_id=project_id, allowed_roles=allowed_roles),
    )


def monitoring_application(request: Request) -> MonitoringApplication:
    application = request.app.state.monitoring_application
    if not isinstance(application, MonitoringApplication):
        raise FoundationServiceUnavailable("The Monitoring application is not configured.")
    return application


def monitoring_call(operation: Any) -> Any:
    try:
        return operation()
    except MonitoringRuleViolation as error:
        raise _problem(422, "Unprocessable Content", error, "rule-violation") from error
    except MonitoringForbidden as error:
        raise _problem(403, "Forbidden", error, "forbidden") from error
    except MonitoringNotFound as error:
        raise _problem(404, "Not Found", error, "not-found") from error
    except MonitoringConflict as error:
        raise _problem(409, "Conflict", error, "conflict") from error
    except MonitoringPersistenceUnavailable as error:
        raise _problem(503, "Service Unavailable", error, "persistence-unavailable") from error


def _problem(status: int, title: str, error: Exception, suffix: str) -> ApiProblem:
    return ApiProblem(
        status=status,
        title=title,
        detail=str(error),
        type_uri=f"urn:geo:problem:monitoring-{suffix}",
    )
