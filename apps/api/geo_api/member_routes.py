"""Internal-only routes for governed OIDC project membership changes."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, status

from geo_api.foundation_services import FoundationServiceUnavailable
from geo_api.member_contracts import (
    AddProjectMemberRequest,
    AddProjectMemberResponse,
    ChangeProjectMemberResponse,
    ChangeProjectMemberRoleRequest,
    ProjectMemberListResponse,
    ProjectMemberSummary,
    RevokeProjectMemberResponse,
)
from geo_api.stable_routes import (
    PROBLEM_RESPONSES,
    authentication_input,
    services_for_request,
)
from geo_core.access.membership_service import AccessMembershipService
from geo_core.access.models import ManagedMembershipRecord


AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]
IdempotencyHeader = Annotated[
    str, Header(alias="Idempotency-Key", min_length=16, max_length=512)
]


def member_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/members",
        tags=["project members"],
        responses=PROBLEM_RESPONSES,
    )

    @router.get(
        "",
        response_model=ProjectMemberListResponse,
        operation_id="listProjectMembers",
    )
    def list_members(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> ProjectMemberListResponse:
        principal = services_for_request(request).authenticate(
            authentication_input(request, authorization)
        )
        page = _application(request).list_members(
            principal, project_id=project_id, limit=limit, offset=offset
        )
        return ProjectMemberListResponse(
            items=[_member(item) for item in page.items],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    @router.post(
        "",
        response_model=AddProjectMemberResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="addProjectMember",
    )
    def add_member(
        project_id: UUID,
        payload: AddProjectMemberRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> AddProjectMemberResponse:
        principal = services_for_request(request).authenticate(
            authentication_input(request, authorization)
        )
        result = _application(request).add_member(
            principal,
            project_id=project_id,
            issuer=payload.issuer,
            subject=payload.subject,
            email=payload.email,
            display_name=payload.display_name,
            role=payload.role,
            idempotency_key=idempotency_key,
        )
        return AddProjectMemberResponse(
            member=_member(result.membership), replayed=result.replayed
        )

    @router.post(
        "/{membership_id}/revoke",
        response_model=RevokeProjectMemberResponse,
        operation_id="revokeProjectMember",
    )
    def revoke_member(
        project_id: UUID,
        membership_id: UUID,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> RevokeProjectMemberResponse:
        principal = services_for_request(request).authenticate(
            authentication_input(request, authorization)
        )
        result = _application(request).revoke_member(
            principal,
            project_id=project_id,
            membership_id=membership_id,
            idempotency_key=idempotency_key,
        )
        return RevokeProjectMemberResponse(
            member=_member(result.membership), replayed=result.replayed
        )

    @router.post(
        "/{membership_id}/role",
        response_model=ChangeProjectMemberResponse,
        operation_id="changeProjectMemberRole",
    )
    def change_role(
        project_id: UUID,
        membership_id: UUID,
        payload: ChangeProjectMemberRoleRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> ChangeProjectMemberResponse:
        principal = services_for_request(request).authenticate(
            authentication_input(request, authorization)
        )
        result = _application(request).change_role(
            principal,
            project_id=project_id,
            membership_id=membership_id,
            role=payload.role,
            idempotency_key=idempotency_key,
        )
        return ChangeProjectMemberResponse(
            member=_member(result.membership), replayed=result.replayed
        )

    @router.post(
        "/{membership_id}/reactivate",
        response_model=ChangeProjectMemberResponse,
        operation_id="reactivateProjectMember",
    )
    def reactivate(
        project_id: UUID,
        membership_id: UUID,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> ChangeProjectMemberResponse:
        principal = services_for_request(request).authenticate(
            authentication_input(request, authorization)
        )
        result = _application(request).reactivate_member(
            principal,
            project_id=project_id,
            membership_id=membership_id,
            idempotency_key=idempotency_key,
        )
        return ChangeProjectMemberResponse(
            member=_member(result.membership), replayed=result.replayed
        )

    return router


def _application(request: Request) -> AccessMembershipService:
    application = request.app.state.membership_application
    if not isinstance(application, AccessMembershipService):
        raise FoundationServiceUnavailable(
            "The project membership application service is not configured."
        )
    return application


def _member(item: object) -> ProjectMemberSummary:
    member = cast(ManagedMembershipRecord, item)
    if not isinstance(member, ManagedMembershipRecord):
        raise RuntimeError("Membership application returned an invalid record.")
    return ProjectMemberSummary(
        membership_id=member.id,
        project_id=member.project_id,
        identity_id=member.identity_id,
        issuer=member.issuer,
        subject=member.subject,
        email=member.email,
        display_name=member.display_name,
        role=member.role,
        status=member.status,
        created_at=member.created_at,
    )
