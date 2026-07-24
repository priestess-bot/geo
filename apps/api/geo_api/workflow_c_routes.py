"""Shared authorization, error mapping, aggregation and mount for workflow C."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, TypeVar, cast
from uuid import UUID

from fastapi import APIRouter, FastAPI, Header, Request

from geo_api.foundation_services import AuthenticationInput, FoundationServiceUnavailable
from geo_api.problems import ApiProblem
from geo_api.workflow_c_analysis_runtime import WorkflowCAnalysisNotFound
from geo_api.workflow_c_runtime import WorkflowCApi, WorkflowCUnavailable
from geo_core.access.models import AccessPrincipal
from geo_core.alerts import AlertConflict, AlertNotFound, AlertRuleViolation
from geo_core.jobs import LeaseConflict
from geo_core.jobs.lifecycle import InvalidTransition
from geo_core.sampling import SamplingConflict, SamplingNotFound, SamplingRuleViolation
from geo_core.semantic_metrics import SemanticMetricRuleViolation
from geo_core.statistical_methods import StatisticalRuleViolation


AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]
IdempotencyHeader = Annotated[
    str, Header(alias="Idempotency-Key", min_length=1, max_length=200)
]
READ_ROLES = frozenset({"owner", "admin", "analyst", "viewer"})
WRITE_ROLES = frozenset({"owner", "admin", "analyst"})
MANAGE_ROLES = frozenset({"owner", "admin"})
T = TypeVar("T")


def workflow_c_router() -> APIRouter:
    from geo_api.workflow_c_alert_routes import workflow_c_alert_router
    from geo_api.workflow_c_analysis_routes import workflow_c_analysis_router
    from geo_api.workflow_c_sampling_routes import workflow_c_sampling_router

    router = APIRouter()
    router.include_router(workflow_c_sampling_router())
    router.include_router(workflow_c_analysis_router())
    router.include_router(workflow_c_alert_router())
    return router


def mount_workflow_c_internal(app: FastAPI, *, api: WorkflowCApi | None) -> None:
    """Mount only on Internal API; a missing durable adapter remains fail-closed."""
    if getattr(app.state, "surface", None) != "internal":
        raise ValueError("workflow C routes can only mount on the Internal API")
    if getattr(app.state, "workflow_c_mounted", False):
        raise ValueError("workflow C routes are already mounted")
    app.state.workflow_c_api = api
    app.state.workflow_c_mounted = True
    app.include_router(workflow_c_router())


def authorize_workflow_c(
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


def workflow_c_api(request: Request) -> WorkflowCApi:
    api = getattr(request.app.state, "workflow_c_api", None)
    if not isinstance(api, WorkflowCApi):
        raise WorkflowCUnavailable("workflow C durable runtime is not configured")
    return api


def workflow_c_call(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except (
        SamplingRuleViolation,
        SemanticMetricRuleViolation,
        StatisticalRuleViolation,
        AlertRuleViolation,
    ) as error:
        raise _problem(422, "Unprocessable Content", error, "rule-violation") from error
    except (SamplingNotFound, AlertNotFound, WorkflowCAnalysisNotFound) as error:
        raise _problem(404, "Not Found", error, "not-found") from error
    except (
        SamplingConflict,
        AlertConflict,
        LeaseConflict,
        InvalidTransition,
    ) as error:
        raise _problem(409, "Conflict", error, "conflict") from error
    except WorkflowCUnavailable as error:
        raise _problem(503, "Service Unavailable", error, "unavailable") from error


def _problem(status: int, title: str, error: Exception, suffix: str) -> ApiProblem:
    return ApiProblem(
        status=status,
        title=title,
        detail=str(error),
        type_uri=f"urn:geo:problem:workflow-c-{suffix}",
        headers={"Retry-After": "30"} if status == 503 else None,
    )
