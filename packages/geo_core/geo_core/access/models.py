"""Framework-independent access domain values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


class AccessError(RuntimeError):
    """Base class for errors safe to map at the transport boundary."""


class AuthenticationRequired(AccessError):
    """Raised when credentials are missing, invalid, expired, or revoked."""


class AccessForbidden(AccessError):
    """Raised when a known identity has no active access to the requested tenant."""


class AccessPersistenceUnavailable(AccessError):
    """Raised when PostgreSQL cannot complete an access operation."""


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
