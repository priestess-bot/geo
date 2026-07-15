from __future__ import annotations

from datetime import UTC, datetime
from types import TracebackType
from uuid import UUID, uuid4

import pytest

from geo_core.access.models import (
    AccessForbidden,
    AccessPrincipal,
    AuthenticationRequired,
    IdentityRecord,
    JobRecord,
    MembershipRecord,
    ProjectRecord,
    SessionRecord,
)
from geo_core.access.service import AccessApplicationService


class FakeIdentityRepository:
    def __init__(self, identity: IdentityRecord) -> None:
        self.identity = identity

    def find_external(self, *, issuer: str, subject: str) -> IdentityRecord | None:
        if (issuer, subject) == (self.identity.issuer, self.identity.subject):
            return self.identity
        return None

    def get(self, *, identity_id: UUID) -> IdentityRecord | None:
        return self.identity if identity_id == self.identity.id else None


class FakeSessionRepository:
    def __init__(self, session: SessionRecord, token_hash: str) -> None:
        self.session = session
        self.token_hash = token_hash
        self.revoked: list[UUID] = []

    def find_active(self, *, token_hash: str) -> SessionRecord | None:
        return self.session if token_hash == self.token_hash else None

    def revoke(self, *, session_id: UUID) -> None:
        self.revoked.append(session_id)


class FakeProjectRepository:
    def __init__(
        self,
        memberships: tuple[MembershipRecord, ...],
        projects: tuple[ProjectRecord, ...],
    ) -> None:
        self.memberships = memberships
        self.projects = projects

    def list_memberships(
        self, *, identity_id: UUID, tenant_id: UUID
    ) -> tuple[MembershipRecord, ...]:
        del identity_id
        return tuple(item for item in self.memberships if item.tenant_id == tenant_id)

    def list_authorized(
        self, *, identity_id: UUID, tenant_id: UUID, limit: int, offset: int
    ) -> tuple[ProjectRecord, ...]:
        del identity_id, tenant_id
        return self.projects[offset : offset + limit]

    def count_authorized(self, *, identity_id: UUID, tenant_id: UUID) -> int:
        del identity_id, tenant_id
        return len(self.projects)


class FakeJobRepository:
    def __init__(self, jobs: tuple[JobRecord, ...]) -> None:
        self.jobs = jobs

    def list_authorized(
        self, *, project_ids: tuple[UUID, ...], limit: int, offset: int
    ) -> tuple[JobRecord, ...]:
        del project_ids
        return self.jobs[offset : offset + limit]

    def count_authorized(self, *, project_ids: tuple[UUID, ...]) -> int:
        del project_ids
        return len(self.jobs)

    def get_authorized(
        self, *, job_id: UUID, project_ids: tuple[UUID, ...]
    ) -> JobRecord | None:
        del project_ids
        return next((job for job in self.jobs if job.id == job_id), None)


class FakeUnitOfWork:
    def __init__(
        self,
        *,
        identities: FakeIdentityRepository,
        sessions: FakeSessionRepository,
        projects: FakeProjectRepository,
        jobs: FakeJobRepository,
    ) -> None:
        self.identities = identities
        self.sessions = sessions
        self.projects = projects
        self.jobs = jobs
        self.contexts: list[AccessPrincipal | None] = []
        self.identity_scopes: list[tuple[UUID, UUID]] = []
        self.committed = False
        self.rolled_back = False

    def __enter__(self) -> "FakeUnitOfWork":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exc, traceback
        self.committed = exc_type is None
        self.rolled_back = exc_type is not None
        return False

    def set_principal(self, principal: AccessPrincipal | None) -> None:
        self.contexts.append(principal)

    def set_identity_scope(self, *, identity_id: UUID, tenant_id: UUID) -> None:
        self.identity_scopes.append((identity_id, tenant_id))


def _fixture() -> tuple[AccessApplicationService, FakeUnitOfWork, str]:
    identity_id = uuid4()
    tenant_id = uuid4()
    project_ids = (uuid4(), uuid4())
    identity = IdentityRecord(
        id=identity_id,
        issuer="https://issuer.example",
        subject="customer-42",
        email="customer@example.com",
        display_name="Customer",
        status="active",
    )
    raw_token = "opaque-session-token"
    from hashlib import sha256

    session = SessionRecord(id=uuid4(), identity_id=identity_id, tenant_id=tenant_id)
    memberships = (
        MembershipRecord(project_id=project_ids[0], tenant_id=tenant_id, role="customer"),
        MembershipRecord(project_id=project_ids[1], tenant_id=tenant_id, role="viewer"),
    )
    projects = tuple(
        ProjectRecord(
            id=project_id,
            name=f"Project {index}",
            status="active",
            role=memberships[index].role,
            market_code="AU",
        )
        for index, project_id in enumerate(project_ids)
    )
    now = datetime.now(UTC)
    jobs = (
        JobRecord(
            id=uuid4(),
            kind="collection",
            status="queued",
            created_at=now,
            updated_at=now,
            result_ref=None,
            error_code=None,
        ),
    )
    unit_of_work = FakeUnitOfWork(
        identities=FakeIdentityRepository(identity),
        sessions=FakeSessionRepository(session, sha256(raw_token.encode()).hexdigest()),
        projects=FakeProjectRepository(memberships, projects),
        jobs=FakeJobRepository(jobs),
    )
    return AccessApplicationService(lambda: unit_of_work), unit_of_work, raw_token


def test_customer_session_preserves_every_active_project_membership() -> None:
    service, unit_of_work, raw_token = _fixture()

    principal = service.authenticate_customer_session(raw_token=raw_token)

    assert len(principal.project_ids) == 2
    assert principal.roles == ("customer", "viewer")
    assert principal.session_id == unit_of_work.sessions.session.id
    assert unit_of_work.identity_scopes == [(principal.identity_id, principal.tenant_id)]
    assert unit_of_work.contexts[-1] == principal
    assert unit_of_work.committed


def test_invalid_customer_session_fails_and_rolls_back() -> None:
    service, unit_of_work, _ = _fixture()

    with pytest.raises(AuthenticationRequired):
        service.authenticate_customer_session(raw_token="wrong")

    assert unit_of_work.rolled_back


def test_identity_without_membership_is_forbidden() -> None:
    service, unit_of_work, _ = _fixture()
    unit_of_work.projects.memberships = ()

    with pytest.raises(AccessForbidden):
        service.authenticate_development(
            identity_id=unit_of_work.identities.identity.id,
            tenant_id=unit_of_work.sessions.session.tenant_id,
        )


def test_list_operations_reapply_full_principal_scope() -> None:
    service, unit_of_work, raw_token = _fixture()
    principal = service.authenticate_customer_session(raw_token=raw_token)

    project_page = service.list_projects(principal, limit=1, offset=1)
    job_page = service.list_jobs(principal, limit=50, offset=0)

    assert project_page.total == 2
    assert len(project_page.items) == 1
    assert job_page.total == 1
    assert unit_of_work.contexts[-1] == principal


def test_logout_revokes_only_the_authenticated_session() -> None:
    service, unit_of_work, raw_token = _fixture()
    principal = service.authenticate_customer_session(raw_token=raw_token)

    service.logout(principal)

    assert unit_of_work.sessions.revoked == [unit_of_work.sessions.session.id]
