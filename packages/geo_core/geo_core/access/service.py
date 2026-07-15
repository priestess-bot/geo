"""Use cases for authentication, project discovery, and job inspection."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from uuid import UUID

from geo_core.access.models import (
    AccessForbidden,
    AccessPrincipal,
    AuthenticationRequired,
    ExternalIdentity,
    JobRecord,
    Page,
    ProjectRecord,
)
from geo_core.access.ports import AccessUnitOfWork, AccessUnitOfWorkFactory


class AccessApplicationService:
    """Coordinate short transactions without depending on HTTP or worker code."""

    def __init__(self, unit_of_work_factory: AccessUnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def authenticate_external(self, external: ExternalIdentity) -> AccessPrincipal:
        with self._unit_of_work_factory() as unit_of_work:
            identity = unit_of_work.identities.find_external(
                issuer=external.issuer, subject=external.subject
            )
            if identity is None or identity.status != "active":
                raise AccessForbidden("The identity is not provisioned for GEO.")
            return self._principal(
                unit_of_work,
                identity_id=identity.id,
                actor_id=identity.subject,
                tenant_id=external.tenant_id,
                auth_method="oidc",
            )

    def authenticate_development(
        self, *, identity_id: UUID, tenant_id: UUID
    ) -> AccessPrincipal:
        with self._unit_of_work_factory() as unit_of_work:
            identity = unit_of_work.identities.get(identity_id=identity_id)
            if identity is None or identity.status != "active":
                raise AuthenticationRequired("Development identity is invalid.")
            return self._principal(
                unit_of_work,
                identity_id=identity.id,
                actor_id=identity.subject,
                tenant_id=tenant_id,
                auth_method="development",
            )

    def authenticate_customer_session(self, *, raw_token: str) -> AccessPrincipal:
        normalized = raw_token.strip()
        if not normalized:
            raise AuthenticationRequired("A customer session is required.")
        token_hash = sha256(normalized.encode("utf-8")).hexdigest()
        with self._unit_of_work_factory() as unit_of_work:
            session = unit_of_work.sessions.find_active(token_hash=token_hash)
            if session is None:
                raise AuthenticationRequired("The customer session is invalid or expired.")
            identity = unit_of_work.identities.get(identity_id=session.identity_id)
            if identity is None or identity.status != "active":
                raise AuthenticationRequired("The customer identity is disabled.")
            return self._principal(
                unit_of_work,
                identity_id=identity.id,
                actor_id=identity.subject,
                tenant_id=session.tenant_id,
                auth_method="session",
                session_id=session.id,
            )

    def list_projects(
        self, principal: AccessPrincipal, *, limit: int, offset: int
    ) -> Page:
        with self._scoped(principal) as unit_of_work:
            items: tuple[ProjectRecord, ...] = unit_of_work.projects.list_authorized(
                identity_id=principal.identity_id,
                tenant_id=principal.tenant_id,
                limit=limit,
                offset=offset,
            )
            total = unit_of_work.projects.count_authorized(
                identity_id=principal.identity_id, tenant_id=principal.tenant_id
            )
        return Page(items=items, total=total, limit=limit, offset=offset)

    def list_jobs(self, principal: AccessPrincipal, *, limit: int, offset: int) -> Page:
        with self._scoped(principal) as unit_of_work:
            items: tuple[JobRecord, ...] = unit_of_work.jobs.list_authorized(
                project_ids=principal.project_ids, limit=limit, offset=offset
            )
            total = unit_of_work.jobs.count_authorized(project_ids=principal.project_ids)
        return Page(items=items, total=total, limit=limit, offset=offset)

    def get_job(self, principal: AccessPrincipal, *, job_id: UUID) -> JobRecord | None:
        with self._scoped(principal) as unit_of_work:
            return unit_of_work.jobs.get_authorized(
                job_id=job_id, project_ids=principal.project_ids
            )

    def logout(self, principal: AccessPrincipal) -> None:
        if principal.session_id is None:
            return
        with self._scoped(principal) as unit_of_work:
            unit_of_work.sessions.revoke(session_id=principal.session_id)

    def _principal(
        self,
        unit_of_work: AccessUnitOfWork,
        *,
        identity_id: UUID,
        actor_id: str,
        tenant_id: UUID,
        auth_method: str,
        session_id: UUID | None = None,
    ) -> AccessPrincipal:
        unit_of_work.set_identity_scope(identity_id=identity_id, tenant_id=tenant_id)
        memberships = unit_of_work.projects.list_memberships(
            identity_id=identity_id, tenant_id=tenant_id
        )
        if not memberships:
            raise AccessForbidden("The identity has no active projects in this tenant.")
        principal = AccessPrincipal(
            identity_id=identity_id,
            actor_id=actor_id,
            tenant_id=tenant_id,
            memberships=memberships,
            auth_method=auth_method,
            session_id=session_id,
        )
        unit_of_work.set_principal(principal)
        return principal

    @contextmanager
    def _scoped(self, principal: AccessPrincipal) -> Iterator[AccessUnitOfWork]:
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.set_principal(principal)
            yield unit_of_work
