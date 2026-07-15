"""Persistence ports owned by the access application slice."""

from __future__ import annotations

from datetime import datetime
from types import TracebackType
from typing import Protocol
from uuid import UUID

from geo_core.access.models import (
    AccessPrincipal,
    IdentityRecord,
    InvitationRecord,
    InvitationRedemptionRecord,
    JobRecord,
    ManagedMembershipRecord,
    ManagedMembershipRole,
    MembershipCommandRecord,
    MembershipCommandType,
    MembershipRecord,
    ProjectRecord,
    SessionRecord,
)


class IdentityRepository(Protocol):
    def find_external(self, *, issuer: str, subject: str) -> IdentityRecord | None: ...

    def get(self, *, identity_id: UUID) -> IdentityRecord | None: ...

    def get_or_create_customer(self, *, email: str) -> IdentityRecord: ...


class SessionRepository(Protocol):
    def find_active(self, *, token_hash: str) -> SessionRecord | None: ...

    def revoke(self, *, session_id: UUID) -> None: ...

    def create(
        self,
        *,
        session_id: UUID,
        identity_id: UUID,
        tenant_id: UUID,
        token_hash: str,
        csrf_token_hash: str,
        expires_at: datetime,
    ) -> SessionRecord: ...


class ProjectRepository(Protocol):
    def upsert_membership(
        self,
        *,
        identity_id: UUID,
        tenant_id: UUID,
        project_id: UUID,
        role: str,
    ) -> None: ...

    def list_memberships(
        self, *, identity_id: UUID, tenant_id: UUID
    ) -> tuple[MembershipRecord, ...]: ...

    def list_authorized(
        self, *, identity_id: UUID, tenant_id: UUID, limit: int, offset: int
    ) -> tuple[ProjectRecord, ...]: ...

    def count_authorized(self, *, identity_id: UUID, tenant_id: UUID) -> int: ...


class JobRepository(Protocol):
    def list_authorized(
        self, *, project_ids: tuple[UUID, ...], limit: int, offset: int
    ) -> tuple[JobRecord, ...]: ...

    def count_authorized(self, *, project_ids: tuple[UUID, ...]) -> int: ...

    def get_authorized(
        self, *, job_id: UUID, project_ids: tuple[UUID, ...]
    ) -> JobRecord | None: ...


class InvitationRepository(Protocol):
    def create_or_get(self, invitation: InvitationRecord) -> tuple[InvitationRecord, bool]: ...

    def list_project(
        self, *, project_id: UUID, limit: int, offset: int
    ) -> tuple[InvitationRecord, ...]: ...

    def count_project(self, *, project_id: UUID) -> int: ...

    def get_for_update(
        self, *, invitation_id: UUID, token_hash: str
    ) -> InvitationRecord | None: ...

    def get_redemption(
        self, *, invitation_id: UUID, idempotency_key_hash: str
    ) -> InvitationRedemptionRecord | None: ...

    def add_redemption(self, redemption: InvitationRedemptionRecord) -> None: ...

    def redeem(self, *, invitation_id: UUID, identity_id: UUID) -> None: ...

    def revoke(self, *, invitation_id: UUID, project_id: UUID, actor_id: UUID) -> bool: ...

    def expire(self, *, invitation_id: UUID) -> None: ...


class AccessAuditRepository(Protocol):
    def add(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_identity_id: UUID | None,
        event_type: str,
        subject_type: str,
        subject_id: UUID,
        metadata: dict[str, object] | None = None,
    ) -> None: ...


class MembershipRepository(Protocol):
    def lock_project(self, *, tenant_id: UUID, project_id: UUID) -> bool: ...

    def get_or_create_identity_exact(
        self,
        *,
        issuer: str,
        subject: str,
        email: str,
        display_name: str,
    ) -> tuple[IdentityRecord, bool]: ...

    def add_exact(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        identity_id: UUID,
        role: ManagedMembershipRole,
    ) -> tuple[ManagedMembershipRecord, bool]: ...

    def list_project(
        self, *, project_id: UUID, limit: int, offset: int
    ) -> tuple[ManagedMembershipRecord, ...]: ...

    def count_project(self, *, project_id: UUID) -> int: ...

    def get_for_update(
        self, *, project_id: UUID, membership_id: UUID
    ) -> ManagedMembershipRecord | None: ...

    def count_active_role(self, *, project_id: UUID, roles: tuple[str, ...]) -> int: ...

    def revoke(self, *, project_id: UUID, membership_id: UUID) -> ManagedMembershipRecord: ...

    def change_role(
        self,
        *,
        project_id: UUID,
        membership_id: UUID,
        role: ManagedMembershipRole,
    ) -> ManagedMembershipRecord: ...

    def reactivate(
        self, *, project_id: UUID, membership_id: UUID
    ) -> ManagedMembershipRecord: ...

    def get_command(
        self, *, project_id: UUID, idempotency_key_hash: str
    ) -> MembershipCommandRecord | None: ...

    def add_command(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_identity_id: UUID,
        command_type: MembershipCommandType,
        idempotency_key_hash: str,
        request_hash: str,
        membership: ManagedMembershipRecord,
    ) -> None: ...


class AccessUnitOfWork(Protocol):
    identities: IdentityRepository
    sessions: SessionRepository
    projects: ProjectRepository
    jobs: JobRepository
    invitations: InvitationRepository
    audit: AccessAuditRepository
    members: MembershipRepository

    def __enter__(self) -> "AccessUnitOfWork": ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

    def set_principal(self, principal: AccessPrincipal | None) -> None: ...

    def set_identity_scope(self, *, identity_id: UUID, tenant_id: UUID) -> None: ...

    def set_invitation_scope(self, *, token_hash: str) -> None: ...

    def set_project_scope(self, *, tenant_id: UUID, project_ids: tuple[UUID, ...]) -> None: ...


class AccessUnitOfWorkFactory(Protocol):
    def __call__(self) -> AccessUnitOfWork: ...
