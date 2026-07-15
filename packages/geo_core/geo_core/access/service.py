"""Use cases for authentication, project discovery, and job inspection."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import base64
from hashlib import sha256
import hmac
import json
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from geo_core.access.models import (
    AccessForbidden,
    AccessConfigurationUnavailable,
    AccessPrincipal,
    AuthenticationRequired,
    ExternalIdentity,
    CreatedInvitation,
    CsrfRejected,
    IdempotencyConflict,
    InvitationConsumed,
    InvitationInvalid,
    InvitationPreflight,
    InvitationRecord,
    InvitationRedemptionRecord,
    InvitationRole,
    InvitationSurface,
    InvitationSurfaceMismatch,
    JobRecord,
    Page,
    ProjectRecord,
    RedeemedSession,
)
from geo_core.access.ports import AccessUnitOfWork, AccessUnitOfWorkFactory


class AccessApplicationService:
    """Coordinate short transactions without depending on HTTP or worker code."""

    def __init__(
        self,
        unit_of_work_factory: AccessUnitOfWorkFactory,
        *,
        token_secret: str | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._token_secret = (token_secret or "").encode("utf-8")

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

    def authenticate_development(self, *, identity_id: UUID, tenant_id: UUID) -> AccessPrincipal:
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

    def list_projects(self, principal: AccessPrincipal, *, limit: int, offset: int) -> Page:
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

    def logout_customer_session(self, *, raw_token: str, csrf_token: str) -> None:
        token_hash = sha256(raw_token.strip().encode("utf-8")).hexdigest()
        csrf_hash = sha256(csrf_token.strip().encode("utf-8")).hexdigest()
        problem: CsrfRejected | None = None
        with self._unit_of_work_factory() as unit_of_work:
            session = unit_of_work.sessions.find_active(token_hash=token_hash)
            if session is None:
                raise AuthenticationRequired("The customer session is invalid or expired.")
            unit_of_work.set_identity_scope(
                identity_id=session.identity_id, tenant_id=session.tenant_id
            )
            memberships = unit_of_work.projects.list_memberships(
                identity_id=session.identity_id, tenant_id=session.tenant_id
            )
            if not memberships:
                raise AccessForbidden("The customer session has no active projects.")
            principal = AccessPrincipal(
                identity_id=session.identity_id,
                actor_id=str(session.identity_id),
                tenant_id=session.tenant_id,
                memberships=memberships,
                auth_method="session",
                session_id=session.id,
            )
            unit_of_work.set_principal(principal)
            if not session.csrf_token_hash or not hmac.compare_digest(
                session.csrf_token_hash, csrf_hash
            ):
                unit_of_work.audit.add(
                    tenant_id=principal.tenant_id,
                    project_id=principal.project_ids[0],
                    actor_identity_id=principal.identity_id,
                    event_type="session.csrf_rejected",
                    subject_type="session",
                    subject_id=session.id,
                )
                problem = CsrfRejected("The CSRF token is invalid.")
            else:
                unit_of_work.sessions.revoke(session_id=session.id)
                unit_of_work.audit.add(
                    tenant_id=principal.tenant_id,
                    project_id=principal.project_ids[0],
                    actor_identity_id=principal.identity_id,
                    event_type="session.revoked",
                    subject_type="session",
                    subject_id=session.id,
                )
        if problem:
            raise problem

    def require_project_role(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        allowed_roles: frozenset[str],
    ) -> str:
        membership = next(
            (item for item in principal.memberships if item.project_id == project_id), None
        )
        if membership is None or membership.role not in allowed_roles:
            raise AccessForbidden("The identity does not have the required project role.")
        return membership.role

    def create_invitation(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        email: str,
        role: InvitationRole,
        target_surface: Literal["customer"],
        expires_in_hours: int,
        idempotency_key: str,
    ) -> CreatedInvitation:
        self.require_project_role(
            principal, project_id=project_id, allowed_roles=frozenset({"owner", "admin"})
        )
        self._require_secret()
        normalized_email = email.strip().lower()
        key_hash = _digest(idempotency_key)
        request_hash = _request_hash(
            project_id=str(project_id),
            email=normalized_email,
            role=role,
            target_surface=target_surface,
            expires_in_hours=expires_in_hours,
        )
        invitation_id = uuid4()
        token = self._derive_token("invitation", invitation_id, key_hash)
        now = datetime.now(UTC)
        candidate = InvitationRecord(
            id=invitation_id,
            tenant_id=principal.tenant_id,
            project_id=project_id,
            email=normalized_email,
            role=role,
            target_surface=target_surface,
            token_hash=_digest(token),
            token_hint=token[-8:],
            status="pending",
            expires_at=now + timedelta(hours=expires_in_hours),
            created_by=principal.identity_id,
            created_at=now,
            idempotency_key_hash=key_hash,
            request_hash=request_hash,
        )
        with self._scoped(principal) as unit_of_work:
            invitation, created = unit_of_work.invitations.create_or_get(candidate)
            if invitation.request_hash != request_hash:
                raise IdempotencyConflict("The idempotency key was used for another request.")
            if created:
                unit_of_work.audit.add(
                    tenant_id=invitation.tenant_id,
                    project_id=invitation.project_id,
                    actor_identity_id=principal.identity_id,
                    event_type="invitation.created",
                    subject_type="invitation",
                    subject_id=invitation.id,
                    metadata={"role": role, "target_surface": target_surface},
                )
        token = self._derive_token("invitation", invitation.id, invitation.idempotency_key_hash)
        return CreatedInvitation(invitation=invitation, invite_token=token, replayed=not created)

    def list_invitations(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        limit: int,
        offset: int,
    ) -> Page:
        self.require_project_role(
            principal, project_id=project_id, allowed_roles=frozenset({"owner", "admin"})
        )
        with self._scoped(principal) as unit_of_work:
            items = unit_of_work.invitations.list_project(
                project_id=project_id, limit=limit, offset=offset
            )
            total = unit_of_work.invitations.count_project(project_id=project_id)
        return Page(items=items, total=total, limit=limit, offset=offset)

    def revoke_invitation(
        self, principal: AccessPrincipal, *, project_id: UUID, invitation_id: UUID
    ) -> None:
        self.require_project_role(
            principal, project_id=project_id, allowed_roles=frozenset({"owner", "admin"})
        )
        with self._scoped(principal) as unit_of_work:
            if not unit_of_work.invitations.revoke(
                invitation_id=invitation_id,
                project_id=project_id,
                actor_id=principal.identity_id,
            ):
                raise InvitationInvalid("The invitation is not pending or does not exist.")
            unit_of_work.audit.add(
                tenant_id=principal.tenant_id,
                project_id=project_id,
                actor_identity_id=principal.identity_id,
                event_type="invitation.revoked",
                subject_type="invitation",
                subject_id=invitation_id,
            )

    def preflight_invitation(
        self,
        *,
        invitation_id: UUID,
        invite_token: str,
        requested_surface: InvitationSurface,
    ) -> InvitationPreflight:
        token_hash = _digest(invite_token)
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.set_invitation_scope(token_hash=token_hash)
            invitation = unit_of_work.invitations.get_for_update(
                invitation_id=invitation_id, token_hash=token_hash
            )
            if invitation is None or invitation.status != "pending":
                return InvitationPreflight("invalid", requested_surface, None, None)
            unit_of_work.set_project_scope(
                tenant_id=invitation.tenant_id, project_ids=(invitation.project_id,)
            )
            if invitation.expires_at <= datetime.now(UTC):
                unit_of_work.invitations.expire(invitation_id=invitation.id)
                unit_of_work.audit.add(
                    tenant_id=invitation.tenant_id,
                    project_id=invitation.project_id,
                    actor_identity_id=None,
                    event_type="invitation.expired",
                    subject_type="invitation",
                    subject_id=invitation.id,
                )
                return InvitationPreflight("invalid", requested_surface, None, None)
            if requested_surface != invitation.target_surface:
                unit_of_work.audit.add(
                    tenant_id=invitation.tenant_id,
                    project_id=invitation.project_id,
                    actor_identity_id=None,
                    event_type="invitation.preflight_failed",
                    subject_type="invitation",
                    subject_id=invitation.id,
                    metadata={"reason": "surface_mismatch"},
                )
                return InvitationPreflight(
                    "surface_mismatch", requested_surface, "customer", invitation.role
                )
            return InvitationPreflight("compatible", requested_surface, "customer", invitation.role)

    def redeem_invitation(
        self,
        *,
        invitation_id: UUID,
        invite_token: str,
        requested_surface: InvitationSurface,
        idempotency_key: str,
    ) -> RedeemedSession:
        self._require_secret()
        token_hash = _digest(invite_token)
        key_hash = _digest(idempotency_key)
        request_hash = _request_hash(
            invitation_id=str(invitation_id), requested_surface=requested_surface
        )
        problem: Exception | None = None
        redeemed: RedeemedSession | None = None
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.set_invitation_scope(token_hash=token_hash)
            invitation = unit_of_work.invitations.get_for_update(
                invitation_id=invitation_id, token_hash=token_hash
            )
            if invitation is None:
                problem = InvitationInvalid("The invitation is invalid.")
            else:
                unit_of_work.set_project_scope(
                    tenant_id=invitation.tenant_id, project_ids=(invitation.project_id,)
                )
                if requested_surface != invitation.target_surface:
                    unit_of_work.audit.add(
                        tenant_id=invitation.tenant_id,
                        project_id=invitation.project_id,
                        actor_identity_id=None,
                        event_type="invitation.preflight_failed",
                        subject_type="invitation",
                        subject_id=invitation.id,
                        metadata={"reason": "surface_mismatch_on_redeem"},
                    )
                    problem = InvitationSurfaceMismatch(
                        "This invitation belongs to the Customer portal."
                    )
                elif invitation.role not in {"analyst", "viewer", "customer"}:
                    problem = InvitationInvalid("The invitation role is not allowed.")
                else:
                    existing = unit_of_work.invitations.get_redemption(
                        invitation_id=invitation.id, idempotency_key_hash=key_hash
                    )
                    if existing and existing.request_hash != request_hash:
                        problem = IdempotencyConflict(
                            "The idempotency key was used for another request."
                        )
                    elif existing:
                        redeemed = self._replayed_session(unit_of_work, invitation, existing)
                    elif invitation.expires_at <= datetime.now(UTC):
                        unit_of_work.invitations.expire(invitation_id=invitation.id)
                        unit_of_work.audit.add(
                            tenant_id=invitation.tenant_id,
                            project_id=invitation.project_id,
                            actor_identity_id=None,
                            event_type="invitation.expired",
                            subject_type="invitation",
                            subject_id=invitation.id,
                        )
                        problem = InvitationInvalid("The invitation has expired.")
                    elif invitation.status != "pending":
                        problem = InvitationConsumed("The invitation was already consumed.")
                    else:
                        redeemed = self._redeem_new(
                            unit_of_work, invitation, key_hash, request_hash
                        )
        if problem:
            raise problem
        if redeemed is None:
            raise RuntimeError("Invitation redemption did not produce a session.")
        return redeemed

    def _redeem_new(
        self,
        unit_of_work: AccessUnitOfWork,
        invitation: InvitationRecord,
        key_hash: str,
        request_hash: str,
    ) -> RedeemedSession:
        identity = unit_of_work.identities.get_or_create_customer(email=invitation.email)
        if identity.status != "active":
            raise InvitationInvalid("The invited identity is disabled.")
        unit_of_work.set_identity_scope(identity_id=identity.id, tenant_id=invitation.tenant_id)
        unit_of_work.projects.upsert_membership(
            identity_id=identity.id,
            tenant_id=invitation.tenant_id,
            project_id=invitation.project_id,
            role=invitation.role,
        )
        principal = self._principal(
            unit_of_work,
            identity_id=identity.id,
            actor_id=identity.subject,
            tenant_id=invitation.tenant_id,
            auth_method="session",
            session_id=_session_id(invitation.id, key_hash),
        )
        session_token = self._derive_token("session", invitation.id, key_hash)
        csrf_token = self._derive_token("csrf", invitation.id, key_hash)
        expires_at = datetime.now(UTC) + timedelta(days=7)
        session = unit_of_work.sessions.create(
            session_id=principal.session_id or _session_id(invitation.id, key_hash),
            identity_id=identity.id,
            tenant_id=invitation.tenant_id,
            token_hash=_digest(session_token),
            csrf_token_hash=_digest(csrf_token),
            expires_at=expires_at,
        )
        unit_of_work.invitations.add_redemption(
            InvitationRedemptionRecord(
                invitation_id=invitation.id,
                project_id=invitation.project_id,
                idempotency_key_hash=key_hash,
                request_hash=request_hash,
                identity_id=identity.id,
                session_id=session.id,
            )
        )
        unit_of_work.invitations.redeem(invitation_id=invitation.id, identity_id=identity.id)
        for event_type, subject_type, subject_id in (
            ("invitation.redeemed", "invitation", invitation.id),
            ("session.created", "session", session.id),
        ):
            unit_of_work.audit.add(
                tenant_id=invitation.tenant_id,
                project_id=invitation.project_id,
                actor_identity_id=identity.id,
                event_type=event_type,
                subject_type=subject_type,
                subject_id=subject_id,
            )
        return RedeemedSession(principal, session_token, csrf_token, expires_at, False)

    def _replayed_session(
        self,
        unit_of_work: AccessUnitOfWork,
        invitation: InvitationRecord,
        redemption: InvitationRedemptionRecord,
    ) -> RedeemedSession:
        session_token = self._derive_token(
            "session", invitation.id, redemption.idempotency_key_hash
        )
        csrf_token = self._derive_token("csrf", invitation.id, redemption.idempotency_key_hash)
        session = unit_of_work.sessions.find_active(token_hash=_digest(session_token))
        if session is None or session.expires_at is None:
            raise InvitationConsumed("The redeemed session is no longer active.")
        identity = unit_of_work.identities.get(identity_id=redemption.identity_id)
        if identity is None or identity.status != "active":
            raise InvitationConsumed("The redeemed identity is no longer active.")
        principal = self._principal(
            unit_of_work,
            identity_id=identity.id,
            actor_id=identity.subject,
            tenant_id=invitation.tenant_id,
            auth_method="session",
            session_id=session.id,
        )
        return RedeemedSession(principal, session_token, csrf_token, session.expires_at, True)

    def _require_secret(self) -> None:
        if len(self._token_secret) < 32:
            raise AccessConfigurationUnavailable(
                "GEO_AUTH_TOKEN_SECRET must contain at least 32 characters."
            )

    def _derive_token(self, purpose: str, subject_id: UUID, key_hash: str) -> str:
        digest = hmac.new(
            self._token_secret,
            f"geo:{purpose}:{subject_id}:{key_hash}".encode("utf-8"),
            sha256,
        ).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

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


def _digest(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("A non-empty token or idempotency key is required.")
    return sha256(normalized.encode("utf-8")).hexdigest()


def _request_hash(**values: object) -> str:
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def _session_id(invitation_id: UUID, key_hash: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"geo:customer-session:{invitation_id}:{key_hash}")
