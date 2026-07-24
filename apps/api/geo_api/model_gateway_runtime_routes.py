"""Manager-only, project-scoped Model Gateway runtime option routes."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Header, Request

from geo_api.foundation_services import AuthenticationInput, FoundationServiceUnavailable
from geo_api.model_gateway_runtime_api import ModelGatewayRuntimeApi
from geo_api.model_gateway_runtime_contracts import (
    ApprovedRuntimeOptionResponse,
    ApprovedRuntimeOptionsResponse,
)
from geo_api.problems import ApiProblem
from geo_api.stable_routes import PROBLEM_RESPONSES
from geo_core.model_gateway.contracts import ModelRouteError
from geo_core.model_gateway.ports import ModelCallPersistenceError


AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]
_ADMIN_READ_ROLES = frozenset({"owner", "admin", "analyst"})


def model_gateway_runtime_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/model-gateway",
        tags=["model gateway"],
        responses=PROBLEM_RESPONSES,
    )

    @router.get(
        "/options",
        response_model=ApprovedRuntimeOptionsResponse,
        operation_id="listApprovedModelGatewayRuntimeOptions",
    )
    def list_runtime_options(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> ApprovedRuntimeOptionsResponse:
        _require_manager(request, authorization, project_id)
        try:
            page = _api(request).list_options(project_id=project_id)
        except (ModelCallPersistenceError, ModelRouteError) as error:
            raise ApiProblem(
                status=503,
                title="Service Unavailable",
                detail="Approved Model Gateway runtime options are unavailable.",
                type_uri="urn:geo:problem:model-gateway-runtime-unavailable",
                headers={"Retry-After": "30"},
            ) from error
        return ApprovedRuntimeOptionsResponse(
            current_manifest_id=page.current_manifest_id,
            items=[
                ApprovedRuntimeOptionResponse(
                    selection_id=item.selection_id,
                    manifest_id=item.manifest_id,
                    provider=item.provider,
                    adapter_release_id=item.adapter_release_id,
                    model_release_id=item.model_release_id,
                    configured_model=item.configured_model,
                    capture_method=item.capture_method.value,
                    allowed_purposes=list(item.allowed_purposes),
                    allowed_search_modes=list(item.allowed_search_modes),
                )
                for item in page.items
            ],
        )

    return router


def _require_manager(
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
    operation(
        authentication,
        project_id=project_id,
        allowed_roles=_ADMIN_READ_ROLES,
    )


def _api(request: Request) -> ModelGatewayRuntimeApi:
    application = getattr(request.app.state, "model_gateway_runtime_api", None)
    if application is None:
        raise FoundationServiceUnavailable(
            "Model Gateway runtime catalog persistence is unavailable."
        )
    return cast(ModelGatewayRuntimeApi, application)


__all__ = ["model_gateway_runtime_router"]
