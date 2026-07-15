from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from geo_core.auth import (
    AUTH_SURFACE_POLICY_VERSION,
    RUNTIME_SESSION_SCOPE_VERSION,
    InvitationRedeemRecoveryStatus,
    InvitationSurface,
    InvitationSurfaceCompatibility,
)


class AuthInvitationPreflightRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invitation_id: UUID
    invite_token: str = Field(min_length=1, max_length=512)
    requested_surface: InvitationSurface


class AuthInvitationPreflightResponse(BaseModel):
    compatibility: InvitationSurfaceCompatibility
    requested_surface: InvitationSurface
    recommended_surface: InvitationSurface | None = None
    invitation_role: str | None = None
    policy_version: Literal["auth_surface_policy_v1"] = AUTH_SURFACE_POLICY_VERSION
    correlation_id: str


class AuthInvitationRedeemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invitation_id: UUID
    invite_token: str = Field(min_length=1, max_length=512)
    requested_surface: InvitationSurface


class RuntimeProjectSessionScope(BaseModel):
    project_id: str
    roles: list[str]
    permissions: list[str]
    portal_capabilities: list[str]
    scope_sources: list[Literal["direct_member", "tenant_role"]]


class RuntimeSessionScopeV2(BaseModel):
    scope_version: Literal["runtime_session_scope_v2"] = RUNTIME_SESSION_SCOPE_VERSION
    authz_policy_version: Literal["auth_surface_policy_v1"] = AUTH_SURFACE_POLICY_VERSION
    actor_id: str
    tenant_id: str
    tenant_roles: list[str]
    project_scopes: list[RuntimeProjectSessionScope]
    project_ids: list[str]


class AuthInvitationRedeemResponse(BaseModel):
    recovery_status: InvitationRedeemRecoveryStatus
    session: RuntimeSessionScopeV2
    correlation_id: str


class AuthMeResponse(BaseModel):
    session: RuntimeSessionScopeV2


class AuthLogoutResponse(BaseModel):
    status: Literal["logged_out"] = "logged_out"


class AuthErrorResponse(BaseModel):
    code: str
    detail: str
    correlation_id: str
    recommended_surface: InvitationSurface | None = None
    invitation_consumed: bool | None = None
