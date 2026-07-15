"""Persistence ports owned by the access application slice."""

from __future__ import annotations

from types import TracebackType
from typing import Protocol
from uuid import UUID

from geo_core.access.models import (
    AccessPrincipal,
    IdentityRecord,
    JobRecord,
    MembershipRecord,
    ProjectRecord,
    SessionRecord,
)


class IdentityRepository(Protocol):
    def find_external(self, *, issuer: str, subject: str) -> IdentityRecord | None: ...

    def get(self, *, identity_id: UUID) -> IdentityRecord | None: ...


class SessionRepository(Protocol):
    def find_active(self, *, token_hash: str) -> SessionRecord | None: ...

    def revoke(self, *, session_id: UUID) -> None: ...


class ProjectRepository(Protocol):
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

    def get_authorized(self, *, job_id: UUID, project_ids: tuple[UUID, ...]) -> JobRecord | None: ...


class AccessUnitOfWork(Protocol):
    identities: IdentityRepository
    sessions: SessionRepository
    projects: ProjectRepository
    jobs: JobRepository

    def __enter__(self) -> "AccessUnitOfWork": ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

    def set_principal(self, principal: AccessPrincipal | None) -> None: ...

    def set_identity_scope(self, *, identity_id: UUID, tenant_id: UUID) -> None: ...


class AccessUnitOfWorkFactory(Protocol):
    def __call__(self) -> AccessUnitOfWork: ...
