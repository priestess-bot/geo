"""Invitation write routes isolated from stable read-only routers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response, status

from geo_api.access_contracts import (
    CreateInvitationRequest,
    CreatedInvitationResponse,
    InvitationCredentialRequest,
    InvitationListResponse,
    InvitationPreflightResponse,
    InvitationRedeemResponse,
    RevokeInvitationResponse,
)
from geo_api.stable_routes import (
    PROBLEM_RESPONSES,
    authentication_input,
    services_for_request,
)


IdempotencyHeader = Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=512)]


def invitation_auth_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/auth/invitations",
        tags=["authentication"],
        responses=PROBLEM_RESPONSES,
    )

    @router.post(
        "/preflight",
        response_model=InvitationPreflightResponse,
        operation_id="preflightInvitation",
    )
    def preflight(payload: InvitationCredentialRequest, request: Request) -> object:
        return services_for_request(request).preflight_invitation(payload)

    @router.post(
        "/redeem",
        response_model=InvitationRedeemResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="redeemInvitation",
    )
    def redeem(
        payload: InvitationCredentialRequest,
        request: Request,
        response: Response,
        idempotency_key: IdempotencyHeader,
    ) -> object:
        result = services_for_request(request).redeem_invitation(
            payload, idempotency_key=idempotency_key
        )
        expires_at = result.expires_at.astimezone(UTC)
        max_age = max(0, int((expires_at - datetime.now(UTC)).total_seconds()))
        response.set_cookie(
            request.app.state.customer_session_cookie_name,
            result.session_token,
            max_age=max_age,
            expires=expires_at,
            path="/",
            secure=request.app.state.cookie_secure,
            httponly=True,
            samesite="lax",
        )
        response.set_cookie(
            request.app.state.csrf_cookie_name,
            result.csrf_token,
            max_age=max_age,
            expires=expires_at,
            path="/",
            secure=request.app.state.cookie_secure,
            httponly=False,
            samesite="lax",
        )
        response.headers["Cache-Control"] = "no-store"
        return InvitationRedeemResponse(
            recovery_status="replayed" if result.replayed else "created",
            session=services_for_request(request).identity_contract(result.principal),
            expires_at=result.expires_at,
        )

    return router


def invitation_management_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/invitations",
        tags=["project invitations"],
        responses=PROBLEM_RESPONSES,
    )

    @router.post(
        "",
        response_model=CreatedInvitationResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createProjectInvitation",
    )
    def create(
        project_id: UUID,
        payload: CreateInvitationRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    ) -> object:
        return services_for_request(request).create_invitation(
            authentication_input(request, authorization),
            project_id=project_id,
            payload=payload,
            idempotency_key=idempotency_key,
        )

    @router.get(
        "",
        response_model=InvitationListResponse,
        operation_id="listProjectInvitations",
    )
    def list_invitations(
        project_id: UUID,
        request: Request,
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> object:
        return services_for_request(request).list_invitations(
            authentication_input(request, authorization),
            project_id=project_id,
            limit=limit,
            offset=offset,
        )

    @router.post(
        "/{invitation_id}/revoke",
        response_model=RevokeInvitationResponse,
        operation_id="revokeProjectInvitation",
    )
    def revoke(
        project_id: UUID,
        invitation_id: UUID,
        request: Request,
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    ) -> RevokeInvitationResponse:
        services_for_request(request).revoke_invitation(
            authentication_input(request, authorization),
            project_id=project_id,
            invitation_id=invitation_id,
        )
        return RevokeInvitationResponse()

    return router
