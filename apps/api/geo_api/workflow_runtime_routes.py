"""Project-scoped read model for Dify workflow execution."""

from __future__ import annotations

import os
from typing import Annotated, Literal, cast
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Header, Request
import psycopg

from geo_api.foundation_services import AuthenticationInput, FoundationServiceUnavailable
from geo_api.problems import ApiProblem
from geo_api.stable_routes import PROBLEM_RESPONSES
from geo_api.workflow_runtime_api import WorkflowRuntimeApi
from geo_api.workflow_runtime_contracts import (
    WorkflowRuntimeCardResponse,
    WorkflowRuntimePageResponse,
)
from geo_core.workflow_runtime import WorkflowExecutionError


AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]
_READ_ROLES = frozenset({"owner", "admin", "analyst"})


def workflow_runtime_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/dify-workflows",
        tags=["workflow runtimes"],
        responses=PROBLEM_RESPONSES,
    )

    @router.get(
        "",
        response_model=WorkflowRuntimePageResponse,
        operation_id="listWorkflowRuntimes",
    )
    def list_workflow_runtimes(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> WorkflowRuntimePageResponse:
        _require_project(request, authorization, project_id)
        try:
            cards = _api(request).list_cards(project_id=project_id)
        except (WorkflowExecutionError, psycopg.Error) as exc:
            raise ApiProblem(
                status=503,
                title="Service Unavailable",
                detail=str(exc),
                type_uri="urn:geo:problem:workflow-runtime-unavailable",
                headers={"Retry-After": "30"},
            ) from exc
        backend = os.getenv("GEO_WORKFLOW_RUNTIME_BACKEND", "native").strip().lower()
        runtime_backend = cast(
            Literal["native", "dify"], "dify" if backend == "dify" else "native"
        )
        console_origin = os.getenv("GEO_DIFY_CONSOLE_URL", "").strip().rstrip("/")
        items = [
            WorkflowRuntimeCardResponse(
                **card.__dict__,
                console_url=(
                    f"{console_origin}/app/{quote(card.dify_app_id, safe='')}/workflow"
                    if console_origin and card.dify_app_id
                    else None
                ),
            )
            for card in cards
        ]
        return WorkflowRuntimePageResponse(
            runtime_backend=runtime_backend,
            items=items,
            total=len(items),
        )

    return router


def _require_project(
    request: Request,
    authorization: str | None,
    project_id: UUID,
) -> None:
    authentication = AuthenticationInput(
        authorization=authorization,
        customer_session=request.cookies.get(request.app.state.customer_session_cookie_name),
        development_actor_id=request.headers.get("X-GEO-Actor-ID"),
        development_tenant_id=request.headers.get("X-GEO-Tenant-ID"),
    )
    operation = getattr(request.app.state.services, "require_project_role", None)
    if not callable(operation):
        raise FoundationServiceUnavailable("Project authorization is not connected.")
    operation(authentication, project_id=project_id, allowed_roles=_READ_ROLES)


def _api(request: Request) -> WorkflowRuntimeApi:
    value = getattr(request.app.state, "workflow_runtime_api", None)
    if value is None:
        raise FoundationServiceUnavailable("Workflow runtime catalog is unavailable.")
    return cast(WorkflowRuntimeApi, value)


__all__ = ["workflow_runtime_router"]
