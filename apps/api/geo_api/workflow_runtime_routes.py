"""Project-scoped read model for Dify workflow execution."""

from __future__ import annotations

import os
from typing import Annotated, Literal, cast
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Header, Request, Response, status
import psycopg

from geo_core.access.models import AccessPrincipal
from geo_api.foundation_services import AuthenticationInput, FoundationServiceUnavailable
from geo_api.problems import ApiProblem
from geo_api.stable_routes import PROBLEM_RESPONSES
from geo_api.workflow_runtime_api import WorkflowRuntimeApi
from geo_api.workflow_runtime_contracts import (
    DifyResubmissionTokenResponse,
    DifyUnresolvedAttemptPageResponse,
    DifyUnresolvedAttemptResponse,
    IssueDifyResubmissionTokenRequest,
    WorkflowRuntimeCardResponse,
    WorkflowRuntimePageResponse,
)
from geo_core.workflow_runtime import WorkflowExecutionError


AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]
_READ_ROLES = frozenset({"owner", "admin", "analyst"})
_RECONCILE_ROLES = frozenset({"owner", "admin"})


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
        _require_project(request, authorization, project_id, allowed_roles=_READ_ROLES)
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

    @router.get(
        "/unresolved-attempts",
        response_model=DifyUnresolvedAttemptPageResponse,
        operation_id="listUnresolvedDifyWorkflowAttempts",
    )
    def list_unresolved_attempts(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> DifyUnresolvedAttemptPageResponse:
        _require_project(request, authorization, project_id, allowed_roles=_READ_ROLES)
        try:
            attempts = _api(request).list_unresolved_attempts(project_id=project_id)
        except (WorkflowExecutionError, psycopg.Error) as exc:
            raise _runtime_problem(exc) from exc
        items = [DifyUnresolvedAttemptResponse(**item.__dict__) for item in attempts]
        return DifyUnresolvedAttemptPageResponse(items=items, total=len(items))

    @router.post(
        "/unresolved-attempts/{attempt_id}/resubmission-token",
        response_model=DifyResubmissionTokenResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="issueDifyWorkflowResubmissionToken",
    )
    def issue_resubmission_token(
        project_id: UUID,
        attempt_id: UUID,
        payload: IssueDifyResubmissionTokenRequest,
        request: Request,
        response: Response,
        authorization: AuthorizationHeader = None,
    ) -> DifyResubmissionTokenResponse:
        principal = _require_project(
            request,
            authorization,
            project_id,
            allowed_roles=_RECONCILE_ROLES,
        )
        try:
            token = _api(request).authorize_new_parent_after_unknown_outcome(
                project_id=project_id,
                attempt_id=attempt_id,
                authorized_by=principal.identity_id,
                provider_outcome=payload.provider_outcome,
                provider_run_id=payload.provider_run_id,
                evidence_reference=payload.evidence_reference,
                reason=payload.reason,
            )
        except (WorkflowExecutionError, psycopg.Error) as exc:
            raise ApiProblem(
                status=409,
                title="Dify reconciliation rejected",
                detail=str(exc),
                type_uri="urn:geo:problem:dify-reconciliation-conflict",
            ) from exc
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        return DifyResubmissionTokenResponse(
            attempt_id=attempt_id,
            recovery_of_attempt_id=attempt_id,
            dify_reconciliation_token=token,
        )

    return router


def _require_project(
    request: Request,
    authorization: str | None,
    project_id: UUID,
    *,
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
        operation(
            authentication,
            project_id=project_id,
            allowed_roles=allowed_roles,
        ),
    )


def _runtime_problem(error: Exception) -> ApiProblem:
    return ApiProblem(
        status=503,
        title="Service Unavailable",
        detail=str(error),
        type_uri="urn:geo:problem:workflow-runtime-unavailable",
        headers={"Retry-After": "30"},
    )


def _api(request: Request) -> WorkflowRuntimeApi:
    value = getattr(request.app.state, "workflow_runtime_api", None)
    if value is None:
        raise FoundationServiceUnavailable("Workflow runtime catalog is unavailable.")
    return cast(WorkflowRuntimeApi, value)


__all__ = ["workflow_runtime_router"]
