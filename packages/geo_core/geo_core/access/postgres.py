"""psycopg adapters and transaction boundary for the access slice."""

from __future__ import annotations

from collections.abc import Callable
import json
from types import TracebackType
from typing import Any, Literal, TypeAlias, cast
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from geo_core.access.models import (
    AccessPersistenceUnavailable,
    AccessPrincipal,
    IdentityRecord,
    JobRecord,
    MembershipRecord,
    ProjectRecord,
    SessionRecord,
)
from geo_core.access.ports import (
    AccessUnitOfWork,
    IdentityRepository,
    JobRepository,
    ProjectRepository,
    SessionRepository,
)


Connection: TypeAlias = psycopg.Connection[dict[str, Any]]
ConnectionFactory = Callable[[], Connection]


def _database_error(operation: str, error: psycopg.Error) -> AccessPersistenceUnavailable:
    return AccessPersistenceUnavailable(f"PostgreSQL could not {operation}.")


class PsycopgIdentityRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def find_external(self, *, issuer: str, subject: str) -> IdentityRecord | None:
        row = self._one(
            """
            SELECT id, issuer, subject, email, display_name, status
            FROM identities
            WHERE issuer = %s AND subject = %s
            """,
            (issuer, subject),
        )
        return _identity(row) if row else None

    def get(self, *, identity_id: UUID) -> IdentityRecord | None:
        row = self._one(
            """
            SELECT id, issuer, subject, email, display_name, status
            FROM identities
            WHERE id = %s
            """,
            (identity_id,),
        )
        return _identity(row) if row else None

    def _one(self, query: str, parameters: tuple[object, ...]) -> dict[str, Any] | None:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(query, parameters)
                return cursor.fetchone()
        except psycopg.Error as error:
            raise _database_error("read an identity", error) from error


class PsycopgSessionRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def find_active(self, *, token_hash: str) -> SessionRecord | None:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, identity_id, tenant_id
                    FROM customer_sessions
                    WHERE token_hash = %s
                      AND status = 'active'
                      AND expires_at > clock_timestamp()
                    """,
                    (token_hash,),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise _database_error("read a customer session", error) from error
        return (
            SessionRecord(
                id=cast(UUID, row["id"]),
                identity_id=cast(UUID, row["identity_id"]),
                tenant_id=cast(UUID, row["tenant_id"]),
            )
            if row
            else None
        )

    def revoke(self, *, session_id: UUID) -> None:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE customer_sessions
                    SET status = 'revoked', revoked_at = clock_timestamp()
                    WHERE id = %s AND status = 'active'
                    """,
                    (session_id,),
                )
        except psycopg.Error as error:
            raise _database_error("revoke a customer session", error) from error


class PsycopgProjectRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def list_memberships(
        self, *, identity_id: UUID, tenant_id: UUID
    ) -> tuple[MembershipRecord, ...]:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT project_id, tenant_id, role
                    FROM project_memberships
                    WHERE identity_id = %s AND tenant_id = %s AND status = 'active'
                    ORDER BY project_id
                    """,
                    (identity_id, tenant_id),
                )
                rows = cursor.fetchall()
        except psycopg.Error as error:
            raise _database_error("read project memberships", error) from error
        return tuple(
            MembershipRecord(
                project_id=cast(UUID, row["project_id"]),
                tenant_id=cast(UUID, row["tenant_id"]),
                role=str(row["role"]),
            )
            for row in rows
        )

    def list_authorized(
        self, *, identity_id: UUID, tenant_id: UUID, limit: int, offset: int
    ) -> tuple[ProjectRecord, ...]:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT p.id, p.name, p.status, membership.role,
                           market.market_code
                    FROM projects AS p
                    JOIN project_memberships AS membership
                      ON membership.project_id = p.id
                     AND membership.tenant_id = p.tenant_id
                    LEFT JOIN LATERAL (
                        SELECT profile.market_code
                        FROM market_profiles AS profile
                        WHERE profile.project_id = p.id AND profile.status = 'active'
                        ORDER BY profile.created_at, profile.id
                        LIMIT 1
                    ) AS market ON true
                    WHERE membership.identity_id = %s
                      AND membership.tenant_id = %s
                      AND membership.status = 'active'
                    ORDER BY p.name, p.id
                    LIMIT %s OFFSET %s
                    """,
                    (identity_id, tenant_id, limit, offset),
                )
                rows = cursor.fetchall()
        except psycopg.Error as error:
            raise _database_error("list projects", error) from error
        return tuple(
            ProjectRecord(
                id=cast(UUID, row["id"]),
                name=str(row["name"]),
                status=str(row["status"]),
                role=str(row["role"]),
                market_code=str(row["market_code"]) if row["market_code"] else None,
            )
            for row in rows
        )

    def count_authorized(self, *, identity_id: UUID, tenant_id: UUID) -> int:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT count(*) AS total
                    FROM project_memberships
                    WHERE identity_id = %s AND tenant_id = %s AND status = 'active'
                    """,
                    (identity_id, tenant_id),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise _database_error("count projects", error) from error
        return int(row["total"]) if row else 0


class PsycopgJobRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def list_authorized(
        self, *, project_ids: tuple[UUID, ...], limit: int, offset: int
    ) -> tuple[JobRecord, ...]:
        if not project_ids:
            return ()
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, kind, status, created_at, updated_at, result_ref, error_code,
                           error_detail
                    FROM durable_jobs
                    WHERE project_id = ANY(%s::uuid[])
                    ORDER BY updated_at DESC, id DESC
                    LIMIT %s OFFSET %s
                    """,
                    (list(project_ids), limit, offset),
                )
                rows = cursor.fetchall()
        except psycopg.Error as error:
            raise _database_error("list durable jobs", error) from error
        return tuple(_job(row) for row in rows)

    def count_authorized(self, *, project_ids: tuple[UUID, ...]) -> int:
        if not project_ids:
            return 0
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) AS total FROM durable_jobs WHERE project_id = ANY(%s::uuid[])",
                    (list(project_ids),),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise _database_error("count durable jobs", error) from error
        return int(row["total"]) if row else 0

    def get_authorized(self, *, job_id: UUID, project_ids: tuple[UUID, ...]) -> JobRecord | None:
        if not project_ids:
            return None
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, kind, status, created_at, updated_at, result_ref, error_code,
                           error_detail
                    FROM durable_jobs
                    WHERE id = %s AND project_id = ANY(%s::uuid[])
                    """,
                    (job_id, list(project_ids)),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise _database_error("read a durable job", error) from error
        return _job(row) if row else None


class PsycopgAccessUnitOfWork:
    """Own one short transaction and its transaction-local RLS variables."""

    identities: IdentityRepository
    sessions: SessionRepository
    projects: ProjectRepository
    jobs: JobRepository

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory
        self._connection: Connection | None = None

    def __enter__(self) -> "PsycopgAccessUnitOfWork":
        try:
            self._connection = self._connection_factory()
            self._connection.execute("SET LOCAL statement_timeout = '10s'")
            self.identities = PsycopgIdentityRepository(self.connection)
            self.sessions = PsycopgSessionRepository(self.connection)
            self.projects = PsycopgProjectRepository(self.connection)
            self.jobs = PsycopgJobRepository(self.connection)
            self.set_principal(None)
        except psycopg.Error as error:
            self._close()
            raise _database_error("open an access transaction", error) from error
        except AccessPersistenceUnavailable:
            self._close()
            raise
        return self

    @property
    def connection(self) -> Connection:
        if self._connection is None:
            raise RuntimeError("The access unit of work has not been entered.")
        return self._connection

    def set_identity_scope(self, *, identity_id: UUID, tenant_id: UUID) -> None:
        self._set_context(
            actor_id=str(identity_id),
            identity_id=str(identity_id),
            tenant_id=str(tenant_id),
            project_ids=(),
        )

    def set_principal(self, principal: AccessPrincipal | None) -> None:
        self._set_context(
            actor_id=principal.actor_id if principal else "",
            identity_id=str(principal.identity_id) if principal else "",
            tenant_id=str(principal.tenant_id) if principal else "",
            project_ids=principal.project_ids if principal else (),
        )

    def _set_context(
        self,
        *,
        actor_id: str,
        identity_id: str,
        tenant_id: str,
        project_ids: tuple[UUID, ...],
    ) -> None:
        values = {
            "geo.actor_id": actor_id,
            "geo.identity_id": identity_id,
            "geo.tenant_id": tenant_id,
            "geo.project_id": str(project_ids[0]) if project_ids else "",
            "geo.project_ids": json.dumps([str(project_id) for project_id in project_ids]),
        }
        try:
            with self.connection.cursor() as cursor:
                for name, value in values.items():
                    cursor.execute(
                        sql.SQL("SELECT set_config({}, %s, true)").format(sql.Literal(name)),
                        (value,),
                    )
        except psycopg.Error as error:
            raise _database_error("set the RLS context", error) from error

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        del exc, traceback
        try:
            if self._connection is not None:
                if exc_type is None:
                    self._connection.commit()
                else:
                    self._connection.rollback()
        except psycopg.Error as error:
            raise _database_error("finish an access transaction", error) from error
        finally:
            self._close()
        return False

    def _close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


class PsycopgAccessUnitOfWorkFactory:
    def __init__(self, database_url: str, *, connect_timeout: int = 5) -> None:
        normalized = database_url.strip()
        if not normalized:
            raise ValueError("database_url is required")
        self._database_url = normalized
        self._connect_timeout = connect_timeout

    def __call__(self) -> AccessUnitOfWork:
        return PsycopgAccessUnitOfWork(self._connect)

    def _connect(self) -> Connection:
        return psycopg.connect(
            self._database_url,
            connect_timeout=self._connect_timeout,
            row_factory=dict_row,
        )


def _identity(row: dict[str, Any]) -> IdentityRecord:
    return IdentityRecord(
        id=cast(UUID, row["id"]),
        issuer=str(row["issuer"]),
        subject=str(row["subject"]),
        email=str(row["email"]) if row["email"] else None,
        display_name=str(row["display_name"]) if row["display_name"] else None,
        status=str(row["status"]),
    )


def _job(row: dict[str, Any]) -> JobRecord:
    return JobRecord(
        id=cast(UUID, row["id"]),
        kind=str(row["kind"]),
        status=str(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        result_ref=str(row["result_ref"]) if row["result_ref"] else None,
        error_code=str(row["error_code"]) if row["error_code"] else None,
        result_details=dict(row["error_detail"]) if row.get("error_detail") else None,
    )
