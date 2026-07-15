"""Application service for internal OIDC project membership governance."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
import json
from urllib.parse import urlsplit
from uuid import UUID

from geo_core.access.models import (
    AccessForbidden,
    AccessPrincipal,
    ChangedMembership,
    CreatedMembership,
    IdempotencyConflict,
    ManagedMembershipRecord,
    ManagedMembershipRole,
    MembershipConflict,
    MembershipCommandType,
    MembershipNotFound,
    MembershipSafetyViolation,
    Page,
    RevokedMembership,
)
from geo_core.access.ports import AccessUnitOfWork, AccessUnitOfWorkFactory


_MANAGER_ROLES = frozenset({"owner", "admin"})


class AccessMembershipService:
    """Manage OIDC members without silently mutating identities or roles."""

    def __init__(self, unit_of_work_factory: AccessUnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def list_members(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        limit: int,
        offset: int,
    ) -> Page:
        _manager_role(principal, project_id)
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.set_principal(principal)
            items = unit_of_work.members.list_project(
                project_id=project_id, limit=limit, offset=offset
            )
            total = unit_of_work.members.count_project(project_id=project_id)
        return Page(items=items, total=total, limit=limit, offset=offset)

    def add_member(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        issuer: str,
        subject: str,
        email: str,
        display_name: str,
        role: ManagedMembershipRole,
        idempotency_key: str,
    ) -> CreatedMembership:
        actor_role = _manager_role(principal, project_id)
        _require_role_authority(actor_role, target_role=role)
        normalized_issuer = _issuer(issuer)
        normalized_subject = _required_text(subject, field="subject", maximum=512)
        normalized_email = _email(email)
        normalized_name = _required_text(display_name, field="display_name", maximum=200)
        key_hash = _digest(idempotency_key)
        request_hash = _request_hash(
            command="add",
            project_id=str(project_id),
            issuer=normalized_issuer,
            subject=normalized_subject,
            email=normalized_email,
            display_name=normalized_name,
            role=role,
        )
        with self._locked(principal, project_id) as unit_of_work:
            replay = _recover(unit_of_work, project_id, key_hash, "add", request_hash)
            if replay:
                return CreatedMembership(membership=replay, replayed=True)
            identity, identity_created = unit_of_work.members.get_or_create_identity_exact(
                issuer=normalized_issuer,
                subject=normalized_subject,
                email=normalized_email,
                display_name=normalized_name,
            )
            if not identity_created and (
                identity.status != "active"
                or identity.email != normalized_email
                or identity.display_name != normalized_name
            ):
                raise MembershipConflict(
                    "The OIDC identity already exists with different managed attributes."
                )
            membership, membership_created = unit_of_work.members.add_exact(
                tenant_id=principal.tenant_id,
                project_id=project_id,
                identity_id=identity.id,
                role=role,
            )
            if not membership_created and (
                membership.status != "active" or membership.role != role
            ):
                raise MembershipConflict(
                    "Use the explicit role-change or reactivate command for this membership."
                )
            if membership_created:
                _audit(unit_of_work, principal, membership, "member.added")
            _record(
                unit_of_work, principal, membership, "add", key_hash, request_hash
            )
        return CreatedMembership(membership=membership, replayed=not membership_created)

    def revoke_member(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        membership_id: UUID,
        idempotency_key: str,
    ) -> RevokedMembership:
        actor_role = _manager_role(principal, project_id)
        key_hash = _digest(idempotency_key)
        request_hash = _request_hash(
            command="revoke", project_id=str(project_id), membership_id=str(membership_id)
        )
        with self._locked(principal, project_id) as unit_of_work:
            replay = _recover(unit_of_work, project_id, key_hash, "revoke", request_hash)
            if replay:
                return RevokedMembership(membership=replay, replayed=True)
            membership = _member(unit_of_work, project_id, membership_id)
            _require_role_authority(actor_role, target_role=membership.role)
            if membership.status == "revoked":
                _record(
                    unit_of_work, principal, membership, "revoke", key_hash, request_hash
                )
                return RevokedMembership(membership=membership, replayed=True)
            _protect_manager_removal(unit_of_work, principal, membership, new_role=None)
            revoked = unit_of_work.members.revoke(
                project_id=project_id, membership_id=membership_id
            )
            _audit(unit_of_work, principal, revoked, "member.revoked")
            _record(unit_of_work, principal, revoked, "revoke", key_hash, request_hash)
        return RevokedMembership(membership=revoked, replayed=False)

    def change_role(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        membership_id: UUID,
        role: ManagedMembershipRole,
        idempotency_key: str,
    ) -> ChangedMembership:
        actor_role = _manager_role(principal, project_id)
        key_hash = _digest(idempotency_key)
        request_hash = _request_hash(
            command="change_role",
            project_id=str(project_id),
            membership_id=str(membership_id),
            role=role,
        )
        with self._locked(principal, project_id) as unit_of_work:
            replay = _recover(unit_of_work, project_id, key_hash, "change_role", request_hash)
            if replay:
                return ChangedMembership(membership=replay, replayed=True)
            membership = _member(unit_of_work, project_id, membership_id)
            _require_role_authority(
                actor_role, target_role=membership.role, assigned_role=role
            )
            if membership.status != "active":
                raise MembershipConflict("A revoked membership must be reactivated first.")
            if membership.role == role:
                _record(
                    unit_of_work,
                    principal,
                    membership,
                    "change_role",
                    key_hash,
                    request_hash,
                )
                return ChangedMembership(membership=membership, replayed=True)
            _protect_manager_removal(unit_of_work, principal, membership, new_role=role)
            changed = unit_of_work.members.change_role(
                project_id=project_id, membership_id=membership_id, role=role
            )
            _audit(
                unit_of_work,
                principal,
                changed,
                "member.role_changed",
                metadata={"previous_role": membership.role},
            )
            _record(
                unit_of_work, principal, changed, "change_role", key_hash, request_hash
            )
        return ChangedMembership(membership=changed, replayed=False)

    def reactivate_member(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        membership_id: UUID,
        idempotency_key: str,
    ) -> ChangedMembership:
        actor_role = _manager_role(principal, project_id)
        key_hash = _digest(idempotency_key)
        request_hash = _request_hash(
            command="reactivate",
            project_id=str(project_id),
            membership_id=str(membership_id),
        )
        with self._locked(principal, project_id) as unit_of_work:
            replay = _recover(unit_of_work, project_id, key_hash, "reactivate", request_hash)
            if replay:
                return ChangedMembership(membership=replay, replayed=True)
            membership = _member(unit_of_work, project_id, membership_id)
            _require_role_authority(actor_role, target_role=membership.role)
            if membership.status == "active":
                _record(
                    unit_of_work,
                    principal,
                    membership,
                    "reactivate",
                    key_hash,
                    request_hash,
                )
                return ChangedMembership(membership=membership, replayed=True)
            reactivated = unit_of_work.members.reactivate(
                project_id=project_id, membership_id=membership_id
            )
            _audit(unit_of_work, principal, reactivated, "member.reactivated")
            _record(
                unit_of_work, principal, reactivated, "reactivate", key_hash, request_hash
            )
        return ChangedMembership(membership=reactivated, replayed=False)

    @contextmanager
    def _locked(
        self, principal: AccessPrincipal, project_id: UUID
    ) -> Iterator[AccessUnitOfWork]:
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.set_principal(principal)
            if not unit_of_work.members.lock_project(
                tenant_id=principal.tenant_id, project_id=project_id
            ):
                raise MembershipNotFound("The project does not exist.")
            yield unit_of_work


def _manager_role(principal: AccessPrincipal, project_id: UUID) -> str:
    membership = next(
        (item for item in principal.memberships if item.project_id == project_id), None
    )
    if membership is None or membership.role not in _MANAGER_ROLES:
        raise AccessForbidden("An active project owner or admin role is required.")
    return membership.role


def _require_role_authority(
    actor_role: str,
    *,
    target_role: ManagedMembershipRole,
    assigned_role: ManagedMembershipRole | None = None,
) -> None:
    if actor_role != "owner" and (
        target_role == "owner" or assigned_role == "owner"
    ):
        raise AccessForbidden("Only a project owner can manage an owner role.")


def _member(
    unit_of_work: AccessUnitOfWork, project_id: UUID, membership_id: UUID
) -> ManagedMembershipRecord:
    membership = unit_of_work.members.get_for_update(
        project_id=project_id, membership_id=membership_id
    )
    if membership is None:
        raise MembershipNotFound("The project membership does not exist.")
    return membership


def _protect_manager_removal(
    unit_of_work: AccessUnitOfWork,
    principal: AccessPrincipal,
    membership: ManagedMembershipRecord,
    *,
    new_role: ManagedMembershipRole | None,
) -> None:
    removes_owner = membership.role == "owner" and new_role != "owner"
    if removes_owner and unit_of_work.members.count_active_role(
        project_id=membership.project_id, roles=("owner",)
    ) <= 1:
        raise MembershipSafetyViolation("The last active project owner cannot be removed.")
    removes_manager = membership.role in _MANAGER_ROLES and new_role not in _MANAGER_ROLES
    if (
        membership.identity_id == principal.identity_id
        and removes_manager
        and unit_of_work.members.count_active_role(
            project_id=membership.project_id, roles=("owner", "admin")
        )
        <= 1
    ):
        raise MembershipSafetyViolation(
            "A project manager cannot remove their own last management role."
        )


def _recover(
    unit_of_work: AccessUnitOfWork,
    project_id: UUID,
    key_hash: str,
    command_type: MembershipCommandType,
    request_hash: str,
) -> ManagedMembershipRecord | None:
    command = unit_of_work.members.get_command(
        project_id=project_id, idempotency_key_hash=key_hash
    )
    if command is None:
        return None
    if command.command_type != command_type or command.request_hash != request_hash:
        raise IdempotencyConflict("The idempotency key was used for another member command.")
    return command.membership


def _record(
    unit_of_work: AccessUnitOfWork,
    principal: AccessPrincipal,
    membership: ManagedMembershipRecord,
    command_type: MembershipCommandType,
    key_hash: str,
    request_hash: str,
) -> None:
    unit_of_work.members.add_command(
        tenant_id=principal.tenant_id,
        project_id=membership.project_id,
        actor_identity_id=principal.identity_id,
        command_type=command_type,
        idempotency_key_hash=key_hash,
        request_hash=request_hash,
        membership=membership,
    )


def _audit(
    unit_of_work: AccessUnitOfWork,
    principal: AccessPrincipal,
    membership: ManagedMembershipRecord,
    event_type: str,
    *,
    metadata: dict[str, object] | None = None,
) -> None:
    unit_of_work.audit.add(
        tenant_id=principal.tenant_id,
        project_id=membership.project_id,
        actor_identity_id=principal.identity_id,
        event_type=event_type,
        subject_type="membership",
        subject_id=membership.id,
        metadata={
            "identity_id": str(membership.identity_id),
            "role": membership.role,
            **(metadata or {}),
        },
    )


def _issuer(value: str) -> str:
    issuer = _required_text(value, field="issuer", maximum=2048)
    parsed = urlsplit(issuer)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("issuer must be an HTTPS URL without userinfo, query, or fragment")
    return issuer


def _email(value: str) -> str:
    email = _required_text(value, field="email", maximum=320).lower()
    local, separator, domain = email.partition("@")
    if not separator or not local or "." not in domain or domain.startswith("."):
        raise ValueError("email must be a normalized email address")
    return email


def _required_text(value: str, *, field: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or not normalized.isprintable():
        raise ValueError(f"{field} is invalid")
    return normalized


def _digest(value: str) -> str:
    normalized = value.strip()
    if len(normalized) < 16 or len(normalized) > 512:
        raise ValueError("idempotency key must contain between 16 and 512 characters")
    return sha256(normalized.encode("utf-8")).hexdigest()


def _request_hash(**values: object) -> str:
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()
