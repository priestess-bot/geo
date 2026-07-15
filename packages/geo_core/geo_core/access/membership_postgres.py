"""PostgreSQL repository for governed internal project membership changes."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from geo_core.access.models import (
    AccessPersistenceUnavailable,
    IdentityRecord,
    ManagedMembershipRecord,
    ManagedMembershipRole,
    MembershipCommandRecord,
    MembershipCommandType,
)


def _persistence_error(operation: str, error: psycopg.Error) -> AccessPersistenceUnavailable:
    return AccessPersistenceUnavailable(f"PostgreSQL could not {operation}.")


class PsycopgMembershipRepository:
    """Serialize project changes and preserve exact OIDC identity attributes."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def lock_project(self, *, tenant_id: UUID, project_id: UUID) -> bool:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT 1
                    FROM projects
                    WHERE id = %s AND tenant_id = %s
                    FOR UPDATE
                    """,
                    (project_id, tenant_id),
                )
                return cursor.fetchone() is not None
        except psycopg.Error as error:
            raise _persistence_error("lock the project membership scope", error) from error

    def get_or_create_identity_exact(
        self,
        *,
        issuer: str,
        subject: str,
        email: str,
        display_name: str,
    ) -> tuple[IdentityRecord, bool]:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO identities (id, issuer, subject, email, display_name)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (issuer, subject) DO NOTHING
                    RETURNING id, issuer, subject, email, display_name, status
                    """,
                    (uuid4(), issuer, subject, email, display_name),
                )
                row = cursor.fetchone()
                if row:
                    return _identity(row), True
                cursor.execute(
                    """
                    SELECT id, issuer, subject, email, display_name, status
                    FROM identities
                    WHERE issuer = %s AND subject = %s
                    """,
                    (issuer, subject),
                )
                existing = cursor.fetchone()
        except psycopg.Error as error:
            raise _persistence_error("create an OIDC member identity", error) from error
        if not existing:
            raise RuntimeError("OIDC identity conflict lookup did not return a row.")
        return _identity(existing), False

    def add_exact(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        identity_id: UUID,
        role: ManagedMembershipRole,
    ) -> tuple[ManagedMembershipRecord, bool]:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO project_memberships
                        (tenant_id, project_id, identity_id, role)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (project_id, identity_id) DO NOTHING
                    RETURNING id
                    """,
                    (tenant_id, project_id, identity_id, role),
                )
                inserted = cursor.fetchone()
                membership = self._get_by_identity(
                    cursor, project_id=project_id, identity_id=identity_id
                )
        except psycopg.Error as error:
            raise _persistence_error("add a project member", error) from error
        if membership is None:
            raise RuntimeError("Project membership creation did not return a row.")
        return membership, inserted is not None

    def list_project(
        self, *, project_id: UUID, limit: int, offset: int
    ) -> tuple[ManagedMembershipRecord, ...]:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    _MEMBER_SELECT
                    + """
                    WHERE membership.project_id = %s
                    ORDER BY membership.created_at, membership.id
                    LIMIT %s OFFSET %s
                    """,
                    (project_id, limit, offset),
                )
                rows = cursor.fetchall()
        except psycopg.Error as error:
            raise _persistence_error("list project members", error) from error
        return tuple(_member(row) for row in rows)

    def count_project(self, *, project_id: UUID) -> int:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) AS total FROM project_memberships WHERE project_id = %s",
                    (project_id,),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise _persistence_error("count project members", error) from error
        return int(row["total"]) if row else 0

    def get_for_update(
        self, *, project_id: UUID, membership_id: UUID
    ) -> ManagedMembershipRecord | None:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    _MEMBER_SELECT
                    + """
                    WHERE membership.project_id = %s AND membership.id = %s
                    FOR UPDATE OF membership
                    """,
                    (project_id, membership_id),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise _persistence_error("read a project member", error) from error
        return _member(row) if row else None

    def count_active_role(self, *, project_id: UUID, roles: tuple[str, ...]) -> int:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT count(*) AS total
                    FROM project_memberships
                    WHERE project_id = %s AND status = 'active' AND role = ANY(%s::text[])
                    """,
                    (project_id, list(roles)),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise _persistence_error("count active project managers", error) from error
        return int(row["total"]) if row else 0

    def revoke(self, *, project_id: UUID, membership_id: UUID) -> ManagedMembershipRecord:
        return self._set_membership(
            project_id=project_id,
            membership_id=membership_id,
            assignment="status = 'revoked'",
            parameters=(),
            operation="revoke a project member",
        )

    def change_role(
        self,
        *,
        project_id: UUID,
        membership_id: UUID,
        role: ManagedMembershipRole,
    ) -> ManagedMembershipRecord:
        return self._set_membership(
            project_id=project_id,
            membership_id=membership_id,
            assignment="role = %s",
            parameters=(role,),
            operation="change a project member role",
        )

    def reactivate(
        self, *, project_id: UUID, membership_id: UUID
    ) -> ManagedMembershipRecord:
        return self._set_membership(
            project_id=project_id,
            membership_id=membership_id,
            assignment="status = 'active'",
            parameters=(),
            operation="reactivate a project member",
        )

    def get_command(
        self, *, project_id: UUID, idempotency_key_hash: str
    ) -> MembershipCommandRecord | None:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT command_type, request_hash, result_snapshot
                    FROM membership_commands
                    WHERE project_id = %s AND idempotency_key_hash = %s
                    """,
                    (project_id, idempotency_key_hash),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise _persistence_error("recover a membership command", error) from error
        if not row:
            return None
        return MembershipCommandRecord(
            command_type=cast(MembershipCommandType, str(row["command_type"])),
            request_hash=str(row["request_hash"]),
            membership=_snapshot_member(cast(dict[str, Any], row["result_snapshot"])),
        )

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
    ) -> None:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO membership_commands (
                        tenant_id, project_id, actor_identity_id, command_type,
                        idempotency_key_hash, request_hash, membership_id, result_snapshot
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        tenant_id,
                        project_id,
                        actor_identity_id,
                        command_type,
                        idempotency_key_hash,
                        request_hash,
                        membership.id,
                        Jsonb(_member_snapshot(membership)),
                    ),
                )
        except psycopg.Error as error:
            raise _persistence_error("record a membership command", error) from error

    def _set_membership(
        self,
        *,
        project_id: UUID,
        membership_id: UUID,
        assignment: str,
        parameters: tuple[object, ...],
        operation: str,
    ) -> ManagedMembershipRecord:
        if assignment not in {"status = 'revoked'", "status = 'active'", "role = %s"}:
            raise ValueError("unsupported membership assignment")
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE project_memberships
                    SET {assignment}
                    WHERE project_id = %s AND id = %s
                    """,  # noqa: S608 - assignment is restricted to the allowlist above.
                    (*parameters, project_id, membership_id),
                )
                cursor.execute(
                    _MEMBER_SELECT
                    + " WHERE membership.project_id = %s AND membership.id = %s",
                    (project_id, membership_id),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise _persistence_error(operation, error) from error
        if not row:
            raise RuntimeError("Changed project membership did not return a row.")
        return _member(row)

    @staticmethod
    def _get_by_identity(
        cursor: Any, *, project_id: UUID, identity_id: UUID
    ) -> ManagedMembershipRecord | None:
        cursor.execute(
            _MEMBER_SELECT
            + " WHERE membership.project_id = %s AND membership.identity_id = %s",
            (project_id, identity_id),
        )
        row = cursor.fetchone()
        return _member(row) if row else None


_MEMBER_SELECT = """
SELECT membership.id, membership.tenant_id, membership.project_id,
       membership.identity_id, identity.issuer, identity.subject,
       identity.email, identity.display_name, membership.role,
       membership.status, membership.created_at
FROM project_memberships AS membership
JOIN identities AS identity ON identity.id = membership.identity_id
"""


def _identity(row: dict[str, Any]) -> IdentityRecord:
    return IdentityRecord(
        id=cast(UUID, row["id"]),
        issuer=str(row["issuer"]),
        subject=str(row["subject"]),
        email=str(row["email"]) if row["email"] is not None else None,
        display_name=str(row["display_name"]) if row["display_name"] is not None else None,
        status=str(row["status"]),
    )


def _member(row: dict[str, Any]) -> ManagedMembershipRecord:
    return ManagedMembershipRecord(
        id=cast(UUID, row["id"]),
        tenant_id=cast(UUID, row["tenant_id"]),
        project_id=cast(UUID, row["project_id"]),
        identity_id=cast(UUID, row["identity_id"]),
        issuer=str(row["issuer"]),
        subject=str(row["subject"]),
        email=str(row["email"] or ""),
        display_name=str(row["display_name"] or ""),
        role=cast(ManagedMembershipRole, str(row["role"])),
        status=cast(Literal["active", "revoked"], str(row["status"])),
        created_at=row["created_at"],
    )


def _member_snapshot(member: ManagedMembershipRecord) -> dict[str, object]:
    return {
        "id": str(member.id),
        "tenant_id": str(member.tenant_id),
        "project_id": str(member.project_id),
        "identity_id": str(member.identity_id),
        "issuer": member.issuer,
        "subject": member.subject,
        "email": member.email,
        "display_name": member.display_name,
        "role": member.role,
        "status": member.status,
        "created_at": member.created_at.isoformat(),
    }


def _snapshot_member(snapshot: dict[str, Any]) -> ManagedMembershipRecord:
    return ManagedMembershipRecord(
        id=UUID(str(snapshot["id"])),
        tenant_id=UUID(str(snapshot["tenant_id"])),
        project_id=UUID(str(snapshot["project_id"])),
        identity_id=UUID(str(snapshot["identity_id"])),
        issuer=str(snapshot["issuer"]),
        subject=str(snapshot["subject"]),
        email=str(snapshot["email"]),
        display_name=str(snapshot["display_name"]),
        role=cast(ManagedMembershipRole, str(snapshot["role"])),
        status=cast(Literal["active", "revoked"], str(snapshot["status"])),
        created_at=datetime.fromisoformat(str(snapshot["created_at"])),
    )
