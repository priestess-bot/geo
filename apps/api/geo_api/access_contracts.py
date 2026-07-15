"""Stable transport contracts for Customer invitation lifecycle."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from geo_api.contracts import AuthIdentity, StrictContract


InvitationRole = Literal["analyst", "viewer", "customer"]
InvitationSurface = Literal["admin", "customer"]
InvitationStatus = Literal["pending", "redeemed", "revoked", "expired"]


class CreateInvitationRequest(StrictContract):
    email: str = Field(min_length=3, max_length=320)
    role: InvitationRole
    target_surface: Literal["customer"] = "customer"
    expires_in_hours: int = Field(default=72, ge=1, le=168)


class InvitationSummary(StrictContract):
    id: UUID
    project_id: UUID
    email: str
    role: InvitationRole
    target_surface: Literal["customer"]
    token_hint: str
    status: InvitationStatus
    expires_at: datetime
    created_at: datetime


class CreatedInvitationResponse(StrictContract):
    invitation: InvitationSummary
    invite_token: str
    replayed: bool


class InvitationListResponse(StrictContract):
    items: list[InvitationSummary]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class RevokeInvitationResponse(StrictContract):
    status: Literal["revoked"] = "revoked"


class InvitationCredentialRequest(StrictContract):
    invitation_id: UUID
    invite_token: str = Field(min_length=32, max_length=512)
    requested_surface: InvitationSurface


class InvitationPreflightResponse(StrictContract):
    compatibility: Literal["compatible", "surface_mismatch", "invalid"]
    requested_surface: InvitationSurface
    recommended_surface: Literal["customer"] | None
    invitation_role: InvitationRole | None


class InvitationRedeemResponse(StrictContract):
    recovery_status: Literal["created", "replayed"]
    session: AuthIdentity
    expires_at: datetime
