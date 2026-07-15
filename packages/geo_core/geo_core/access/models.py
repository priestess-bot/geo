"""Framework-independent access domain values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID


class AccessError(RuntimeError):
    """Base class for errors safe to map at the transport boundary."""


class AuthenticationRequired(AccessError):
    """Raised when credentials are missing, invalid, expired, or revoked."""


class AccessForbidden(AccessError):
    """Raised when a known identity has no active access to the requested tenant."""


class AccessPersistenceUnavailable(AccessError):
    """Raised when PostgreSQL cannot complete an access operation."""


class AccessConfigurationUnavailable(AccessError):
    """Raised when a write-only signing secret is not configured."""


class InvitationInvalid(AccessError):
    """Raised when invitation credentials are invalid, expired, or revoked."""


class InvitationSurfaceMismatch(AccessError):
    """Raised before token consumption when a Customer invite reaches Admin."""


class InvitationConsumed(AccessError):
    """Raised when another redemption already consumed the invitation."""


class IdempotencyConflict(AccessError):
    """Raised when an idempotency key is reused with a different request."""


class CsrfRejected(AccessError):
    """Raised when an unsafe Session operation lacks the bound CSRF token."""


class MembershipConflict(AccessError):
    """Raised when a managed identity or membership conflicts with stored state."""


class MembershipNotFound(AccessError):
    """Raised when the requested project membership is not visible to the caller."""


class MembershipSafetyViolation(AccessError):
    """Raised when a member change would remove required project governance."""


@dataclass(frozen=True)
class ExternalIdentity:
    issuer: str
    subject: str
    tenant_id: UUID
    email: str | None = None
    display_name: str | None = None


@dataclass(frozen=True)
class IdentityRecord:
    id: UUID
    issuer: str
    subject: str
    email: str | None
    display_name: str | None
    status: str


@dataclass(frozen=True)
class MembershipRecord:
    project_id: UUID
    tenant_id: UUID
    role: str


@dataclass(frozen=True)
class SessionRecord:
    id: UUID
    identity_id: UUID
    tenant_id: UUID
    csrf_token_hash: str | None = None
    expires_at: datetime | None = None
    surface: str = "customer"


@dataclass(frozen=True)
class AccessPrincipal:
    identity_id: UUID
    actor_id: str
    tenant_id: UUID
    memberships: tuple[MembershipRecord, ...]
    auth_method: str
    session_id: UUID | None = None

    @property
    def project_ids(self) -> tuple[UUID, ...]:
        return tuple(membership.project_id for membership in self.memberships)

    @property
    def roles(self) -> tuple[str, ...]:
        return tuple(sorted({membership.role for membership in self.memberships}))


@dataclass(frozen=True)
class ProjectRecord:
    id: UUID
    name: str
    status: str
    role: str
    market_code: str | None


@dataclass(frozen=True)
class JobRecord:
    id: UUID
    kind: str
    status: str
    created_at: datetime
    updated_at: datetime
    result_ref: str | None
    error_code: str | None
    result_details: dict[str, object] | None = None


@dataclass(frozen=True)
class Page:
    items: tuple[object, ...]
    total: int
    limit: int
    offset: int


InvitationRole = Literal["analyst", "viewer", "customer"]
InvitationSurface = Literal["admin", "customer"]
ManagedMembershipRole = Literal["owner", "admin", "analyst"]


@dataclass(frozen=True)
class InvitationRecord:
    id: UUID
    tenant_id: UUID
    project_id: UUID
    email: str
    role: InvitationRole
    target_surface: Literal["customer"]
    token_hash: str
    token_hint: str
    status: str
    expires_at: datetime
    created_by: UUID
    created_at: datetime
    idempotency_key_hash: str
    request_hash: str


@dataclass(frozen=True)
class InvitationRedemptionRecord:
    invitation_id: UUID
    project_id: UUID
    idempotency_key_hash: str
    request_hash: str
    identity_id: UUID
    session_id: UUID


@dataclass(frozen=True)
class CreatedInvitation:
    invitation: InvitationRecord
    invite_token: str
    replayed: bool


@dataclass(frozen=True)
class InvitationPreflight:
    compatibility: Literal["compatible", "surface_mismatch", "invalid"]
    requested_surface: InvitationSurface
    recommended_surface: Literal["customer"] | None
    invitation_role: InvitationRole | None


@dataclass(frozen=True)
class RedeemedSession:
    principal: AccessPrincipal
    session_token: str
    csrf_token: str
    expires_at: datetime
    replayed: bool


@dataclass(frozen=True)
class ManagedMembershipRecord:
    id: UUID
    tenant_id: UUID
    project_id: UUID
    identity_id: UUID
    issuer: str
    subject: str
    email: str
    display_name: str
    role: ManagedMembershipRole
    status: Literal["active", "revoked"]
    created_at: datetime


@dataclass(frozen=True)
class CreatedMembership:
    membership: ManagedMembershipRecord
    replayed: bool


@dataclass(frozen=True)
class RevokedMembership:
    membership: ManagedMembershipRecord
    replayed: bool


MembershipCommandType = Literal["add", "revoke", "change_role", "reactivate"]


@dataclass(frozen=True)
class MembershipCommandRecord:
    command_type: MembershipCommandType
    request_hash: str
    membership: ManagedMembershipRecord


@dataclass(frozen=True)
class ChangedMembership:
    membership: ManagedMembershipRecord
    replayed: bool
