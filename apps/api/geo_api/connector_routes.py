"""Internal Admin routes for Connector Core."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Request, status

from geo_api.catalog_routes import _principal
from geo_api.connector_contracts import (
    CancelConnectorSyncRequest,
    ConnectorConnectionResponse,
    ConnectorConnectionTestResponse,
    ConnectorDefinitionResponse,
    ConnectorInventoryResponse,
    ConnectorScopeResponse,
    ConnectorSyncAccepted,
    ConnectorSyncControlResponse,
    CreateConnectorConnectionRequest,
    CreateConnectorScopeRequest,
    InstallConnectorDefinitionRequest,
    RotateConnectorSecretRequest,
    SetConnectorConnectionStatusRequest,
    StartConnectorSyncRequest,
    TestConnectorConnectionRequest,
)
from geo_api.foundation_services import FoundationServiceUnavailable
from geo_api.problems import ApiProblem
from geo_api.stable_routes import PROBLEM_RESPONSES
from geo_core.access.models import AccessPrincipal
from geo_core.connectors.admin import ConnectorAdminError, ConnectorAdminService


AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]
IdempotencyHeader = Annotated[str, Header(alias="Idempotency-Key")]


def connector_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/connectors",
        tags=["connectors"],
        responses=PROBLEM_RESPONSES,
    )

    @router.get("", response_model=ConnectorInventoryResponse, operation_id="getConnectorInventory")
    def inventory(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> ConnectorInventoryResponse:
        _require_admin(_principal(request, authorization), project_id)
        return ConnectorInventoryResponse.model_validate(
            _call(lambda: _service(request).inventory(project_id=project_id))
        )

    @router.post(
        "/definitions",
        response_model=ConnectorDefinitionResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="installConnectorDefinition",
    )
    def install_definition(
        project_id: UUID,
        payload: InstallConnectorDefinitionRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> ConnectorDefinitionResponse:
        principal = _require_admin(_principal(request, authorization), project_id)
        return ConnectorDefinitionResponse.model_validate(
            _call(
                lambda: _service(request).install_definition(
                    project_id=project_id,
                    actor_id=principal.identity_id,
                    kind=payload.kind,
                )
            )
        )

    @router.post(
        "/definitions/{definition_id}/approve",
        response_model=ConnectorDefinitionResponse,
        operation_id="approveConnectorDefinition",
    )
    def approve_definition(
        project_id: UUID,
        definition_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> ConnectorDefinitionResponse:
        principal = _require_admin(_principal(request, authorization), project_id)
        return ConnectorDefinitionResponse.model_validate(
            _call(
                lambda: _service(request).approve_definition(
                    project_id=project_id,
                    definition_id=definition_id,
                    reviewer_id=principal.identity_id,
                )
            )
        )

    @router.post(
        "/connections",
        response_model=ConnectorConnectionResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createConnectorConnection",
    )
    def create_connection(
        project_id: UUID,
        payload: CreateConnectorConnectionRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> ConnectorConnectionResponse:
        principal = _require_admin(_principal(request, authorization), project_id)
        return ConnectorConnectionResponse.model_validate(
            _call(
                lambda: _service(request).create_connection(
                    project_id=project_id,
                    actor_id=principal.identity_id,
                    **payload.model_dump(),
                )
            )
        )

    @router.post(
        "/connections/{connection_id}/status",
        response_model=ConnectorConnectionResponse,
        operation_id="setConnectorConnectionStatus",
    )
    def set_connection_status(
        project_id: UUID,
        connection_id: UUID,
        payload: SetConnectorConnectionStatusRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> ConnectorConnectionResponse:
        _require_admin(_principal(request, authorization), project_id)
        return ConnectorConnectionResponse.model_validate(
            _call(
                lambda: _service(request).set_connection_status(
                    project_id=project_id,
                    connection_id=connection_id,
                    **payload.model_dump(),
                )
            )
        )

    @router.post(
        "/connections/{connection_id}/rotate-secret",
        response_model=ConnectorConnectionResponse,
        operation_id="rotateConnectorConnectionSecret",
    )
    def rotate_connection_secret(
        project_id: UUID,
        connection_id: UUID,
        payload: RotateConnectorSecretRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> ConnectorConnectionResponse:
        _require_admin(_principal(request, authorization), project_id)
        return ConnectorConnectionResponse.model_validate(
            _call(
                lambda: _service(request).rotate_connection_secret(
                    project_id=project_id,
                    connection_id=connection_id,
                    **payload.model_dump(),
                )
            )
        )

    @router.post(
        "/connections/{connection_id}/tests",
        response_model=ConnectorConnectionTestResponse,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="testConnectorConnection",
    )
    def test_connection(
        project_id: UUID,
        connection_id: UUID,
        payload: TestConnectorConnectionRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> ConnectorConnectionTestResponse:
        principal = _require_admin(_principal(request, authorization), project_id)
        return ConnectorConnectionTestResponse.model_validate(
            _call(
                lambda: _service(request).test_connection(
                    project_id=project_id,
                    actor_id=principal.identity_id,
                    connection_id=connection_id,
                    expected_version=payload.expected_version,
                    idempotency_key=idempotency_key,
                )
            )
        )

    @router.post(
        "/scopes",
        response_model=ConnectorScopeResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createConnectorScope",
    )
    def create_scope(
        project_id: UUID,
        payload: CreateConnectorScopeRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> ConnectorScopeResponse:
        principal = _require_admin(_principal(request, authorization), project_id)
        return ConnectorScopeResponse.model_validate(
            _call(
                lambda: _service(request).create_scope(
                    project_id=project_id,
                    actor_id=principal.identity_id,
                    **payload.model_dump(),
                )
            )
        )

    @router.post(
        "/scopes/{scope_id}/syncs",
        response_model=ConnectorSyncAccepted,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="startConnectorSync",
    )
    def start_sync(
        project_id: UUID,
        scope_id: UUID,
        payload: StartConnectorSyncRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> ConnectorSyncAccepted:
        principal = _require_admin(_principal(request, authorization), project_id)
        return ConnectorSyncAccepted.model_validate(
            _call(
                lambda: _service(request).start_sync(
                    project_id=project_id,
                    actor_id=principal.identity_id,
                    scope_id=scope_id,
                    **payload.model_dump(),
                )
            )
        )

    @router.post(
        "/syncs/{run_id}/cancel",
        response_model=ConnectorSyncControlResponse,
        operation_id="cancelConnectorSync",
    )
    def cancel_sync(
        project_id: UUID,
        run_id: UUID,
        payload: CancelConnectorSyncRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> ConnectorSyncControlResponse:
        _require_admin(_principal(request, authorization), project_id)
        return ConnectorSyncControlResponse.model_validate(
            _call(
                lambda: _service(request).cancel_sync(
                    project_id=project_id,
                    run_id=run_id,
                    **payload.model_dump(),
                )
            )
        )

    return router


def _require_admin(principal: AccessPrincipal, project_id: UUID) -> AccessPrincipal:
    role = next(
        (
            membership.role
            for membership in principal.memberships
            if membership.project_id == project_id
        ),
        None,
    )
    if role not in {"owner", "admin"}:
        raise ApiProblem(
            status=403,
            title="Forbidden",
            detail="Connector administration requires project owner or admin access.",
            type_uri="urn:geo:problem:connector-forbidden",
        )
    return principal


def _service(request: Request) -> ConnectorAdminService:
    service = getattr(request.app.state, "connector_admin_service", None)
    if not isinstance(service, ConnectorAdminService):
        raise FoundationServiceUnavailable("Connector Core persistence is unavailable.")
    return service


def _call(operation):
    try:
        return operation()
    except ConnectorAdminError as error:
        raise ApiProblem(
            status=409,
            title="Connector State Conflict",
            detail=str(error),
            type_uri="urn:geo:problem:connector-conflict",
        ) from error


__all__ = ["connector_router"]
