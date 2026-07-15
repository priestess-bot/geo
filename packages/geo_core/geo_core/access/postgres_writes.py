"""psycopg write repositories for invitations, memberships, and access audit."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from geo_core.access.models import InvitationRecord, InvitationRedemptionRecord


def _persistence_error(operation: str, error: psycopg.Error) -> RuntimeError:
    from geo_core.access.models import AccessPersistenceUnavailable

    return AccessPersistenceUnavailable(f"PostgreSQL could not {operation}.")


class PsycopgInvitationRepository:
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def create_or_get(self, invitation: InvitationRecord) -> tuple[InvitationRecord, bool]:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO project_invitations (
                        id, tenant_id, project_id, email, role, target_surface,
                        token_hash, token_hint, expires_at, created_by,
                        idempotency_key_hash, request_hash
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (project_id, idempotency_key_hash) DO NOTHING
                    RETURNING *
                    """,
                    (
                        invitation.id,
                        invitation.tenant_id,
                        invitation.project_id,
                        invitation.email,
                        invitation.role,
                        invitation.target_surface,
                        invitation.token_hash,
                        invitation.token_hint,
                        invitation.expires_at,
                        invitation.created_by,
                        invitation.idempotency_key_hash,
                        invitation.request_hash,
                    ),
                )
                row = cursor.fetchone()
                if row:
                    return _invitation(row), True
                cursor.execute(
                    """
                    SELECT * FROM project_invitations
                    WHERE project_id = %s AND idempotency_key_hash = %s
                    """,
                    (invitation.project_id, invitation.idempotency_key_hash),
                )
                existing = cursor.fetchone()
        except psycopg.Error as error:
            raise _persistence_error("create an invitation", error) from error
        if not existing:
            raise RuntimeError("Invitation idempotency lookup did not return a row.")
        return _invitation(existing), False

    def list_project(
        self, *, project_id: UUID, limit: int, offset: int
    ) -> tuple[InvitationRecord, ...]:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT *, CASE
                        WHEN status = 'pending' AND expires_at <= clock_timestamp()
                        THEN 'expired' ELSE status END AS effective_status
                    FROM project_invitations
                    WHERE project_id = %s
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s OFFSET %s
                    """,
                    (project_id, limit, offset),
                )
                rows = cursor.fetchall()
        except psycopg.Error as error:
            raise _persistence_error("list invitations", error) from error
        return tuple(_invitation(row, status_key="effective_status") for row in rows)

    def count_project(self, *, project_id: UUID) -> int:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) AS total FROM project_invitations WHERE project_id = %s",
                    (project_id,),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise _persistence_error("count invitations", error) from error
        return int(row["total"]) if row else 0

    def get_for_update(self, *, invitation_id: UUID, token_hash: str) -> InvitationRecord | None:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT * FROM project_invitations
                    WHERE id = %s AND token_hash = %s
                    FOR UPDATE
                    """,
                    (invitation_id, token_hash),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise _persistence_error("lock an invitation", error) from error
        return _invitation(row) if row else None

    def get_redemption(
        self, *, invitation_id: UUID, idempotency_key_hash: str
    ) -> InvitationRedemptionRecord | None:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT invitation_id, project_id, idempotency_key_hash,
                           request_hash, identity_id, session_id
                    FROM invitation_redemptions
                    WHERE invitation_id = %s AND idempotency_key_hash = %s
                    """,
                    (invitation_id, idempotency_key_hash),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise _persistence_error("read invitation redemption", error) from error
        return _redemption(row) if row else None

    def add_redemption(self, redemption: InvitationRedemptionRecord) -> None:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO invitation_redemptions (
                        invitation_id, project_id, idempotency_key_hash,
                        request_hash, identity_id, session_id
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        redemption.invitation_id,
                        redemption.project_id,
                        redemption.idempotency_key_hash,
                        redemption.request_hash,
                        redemption.identity_id,
                        redemption.session_id,
                    ),
                )
        except psycopg.Error as error:
            raise _persistence_error("record invitation redemption", error) from error

    def redeem(self, *, invitation_id: UUID, identity_id: UUID) -> None:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE project_invitations
                    SET status = 'redeemed', redeemed_by = %s,
                        redeemed_at = clock_timestamp()
                    WHERE id = %s AND status = 'pending'
                    """,
                    (identity_id, invitation_id),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("Invitation state changed during redemption.")
        except psycopg.Error as error:
            raise _persistence_error("consume an invitation", error) from error

    def revoke(self, *, invitation_id: UUID, project_id: UUID, actor_id: UUID) -> bool:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE project_invitations
                    SET status = 'revoked', revoked_by = %s,
                        revoked_at = clock_timestamp()
                    WHERE id = %s AND project_id = %s AND status = 'pending'
                      AND expires_at > clock_timestamp()
                    """,
                    (actor_id, invitation_id, project_id),
                )
                return cursor.rowcount == 1
        except psycopg.Error as error:
            raise _persistence_error("revoke an invitation", error) from error

    def expire(self, *, invitation_id: UUID) -> None:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE project_invitations SET status = 'expired'
                    WHERE id = %s AND status = 'pending'
                    """,
                    (invitation_id,),
                )
        except psycopg.Error as error:
            raise _persistence_error("expire an invitation", error) from error


class PsycopgAccessAuditRepository:
    def __init__(self, connection: Any) -> None:
        self._connection = connection

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
    ) -> None:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO access_audit_events (
                        tenant_id, project_id, actor_identity_id, event_type,
                        subject_type, subject_id, metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        tenant_id,
                        project_id,
                        actor_identity_id,
                        event_type,
                        subject_type,
                        subject_id,
                        Jsonb(metadata or {}),
                    ),
                )
        except psycopg.Error as error:
            raise _persistence_error("append an access audit event", error) from error


def _invitation(row: dict[str, Any], *, status_key: str = "status") -> InvitationRecord:
    return InvitationRecord(
        id=cast(UUID, row["id"]),
        tenant_id=cast(UUID, row["tenant_id"]),
        project_id=cast(UUID, row["project_id"]),
        email=str(row["email"]),
        role=cast(Any, row["role"]),
        target_surface="customer",
        token_hash=str(row["token_hash"]),
        token_hint=str(row["token_hint"]),
        status=str(row[status_key]),
        expires_at=row["expires_at"],
        created_by=cast(UUID, row["created_by"]),
        created_at=row["created_at"],
        idempotency_key_hash=str(row["idempotency_key_hash"]),
        request_hash=str(row["request_hash"]),
    )


def _redemption(row: dict[str, Any]) -> InvitationRedemptionRecord:
    return InvitationRedemptionRecord(
        invitation_id=cast(UUID, row["invitation_id"]),
        project_id=cast(UUID, row["project_id"]),
        idempotency_key_hash=str(row["idempotency_key_hash"]),
        request_hash=str(row["request_hash"]),
        identity_id=cast(UUID, row["identity_id"]),
        session_id=cast(UUID, row["session_id"]),
    )
