"""Provision the first production tenant owner without exposing an HTTP bootstrap path."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


MAX_DATABASE_URL_BYTES = 4096
MAX_NAME_LENGTH = 200
MAX_IDENTITY_FIELD_LENGTH = 320
LOCK_NAMESPACE = "geo:initial-owner:tenant"
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class InitialOwnerProvisionError(RuntimeError):
    """Stable fail-closed error that never contains configuration or database values."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class InitialOwnerConfig:
    tenant_id: UUID
    tenant_name: str
    oidc_issuer: str
    oidc_subject: str
    email: str
    display_name: str
    project_id: UUID
    project_name: str


@dataclass(frozen=True)
class InitialOwnerResult:
    tenant_id: UUID
    identity_id: UUID
    project_id: UUID
    replayed: bool

    def public_dict(self) -> dict[str, str | bool]:
        return {
            "tenant_id": str(self.tenant_id),
            "identity_id": str(self.identity_id),
            "project_id": str(self.project_id),
            "replayed": self.replayed,
        }


def configuration_from_environment(
    env: Mapping[str, str] | None = None,
) -> tuple[str, InitialOwnerConfig]:
    values = env if env is not None else os.environ
    database_url = _database_url(values)
    issuer = _issuer(_required(values, "GEO_BOOTSTRAP_OIDC_ISSUER"))
    jwt_issuer = _issuer(_required(values, "GEO_JWT_ISSUER"))
    if issuer != jwt_issuer:
        raise InitialOwnerProvisionError("bootstrap_oidc_issuer_mismatch")
    email = _required(values, "GEO_BOOTSTRAP_EMAIL")
    if (
        email != email.lower()
        or len(email) > MAX_IDENTITY_FIELD_LENGTH
        or not EMAIL_PATTERN.fullmatch(email)
    ):
        raise InitialOwnerProvisionError("bootstrap_email_invalid")
    return database_url, InitialOwnerConfig(
        tenant_id=_uuid(values, "GEO_BOOTSTRAP_TENANT_ID"),
        tenant_name=_name(values, "GEO_BOOTSTRAP_TENANT_NAME"),
        oidc_issuer=issuer,
        oidc_subject=_identity_field(values, "GEO_BOOTSTRAP_OIDC_SUBJECT"),
        email=email,
        display_name=_identity_field(values, "GEO_BOOTSTRAP_DISPLAY_NAME"),
        project_id=_uuid(values, "GEO_BOOTSTRAP_PROJECT_ID"),
        project_name=_name(values, "GEO_BOOTSTRAP_PROJECT_NAME"),
    )


def provision_from_url(database_url: str, config: InitialOwnerConfig) -> InitialOwnerResult:
    try:
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            return provision_connection(connection, config)
    except InitialOwnerProvisionError:
        raise
    except psycopg.Error as error:
        raise InitialOwnerProvisionError("bootstrap_database_operation_failed") from error


def provision_connection(
    connection: psycopg.Connection[dict[str, Any]], config: InitialOwnerConfig
) -> InitialOwnerResult:
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        cursor.execute("SET LOCAL statement_timeout = '10s'")
        cursor.execute("SET LOCAL lock_timeout = '5s'")
        _require_installer(cursor)
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"{LOCK_NAMESPACE}:{config.tenant_id}",),
        )
        tenant = _one(
            cursor,
            "SELECT id, name, status FROM tenants WHERE id = %s",
            (config.tenant_id,),
        )
        identity = _one(
            cursor,
            """
            SELECT id, issuer, subject, email, display_name, status
            FROM identities WHERE issuer = %s AND subject = %s
            """,
            (config.oidc_issuer, config.oidc_subject),
        )
        project = _one(
            cursor,
            "SELECT id, tenant_id, name, status FROM projects WHERE id = %s",
            (config.project_id,),
        )
        membership = None
        if identity is not None:
            membership = _one(
                cursor,
                """
                SELECT tenant_id, project_id, identity_id, role, status
                FROM project_memberships WHERE project_id = %s AND identity_id = %s
                """,
                (config.project_id, identity["id"]),
            )

        present = (
            tenant is not None,
            identity is not None,
            project is not None,
            membership is not None,
        )
        if any(present):
            if not all(present):
                raise InitialOwnerProvisionError("bootstrap_partial_state_conflict")
            assert tenant is not None
            assert identity is not None
            assert project is not None
            assert membership is not None
            identity_id = _validate_exact_replay(
                config=config,
                tenant=tenant,
                identity=identity,
                project=project,
                membership=membership,
            )
            replayed = True
        else:
            _reject_tenant_name_collision(cursor, config)
            identity_id = uuid4()
            cursor.execute(
                "INSERT INTO tenants (id, name) VALUES (%s, %s)",
                (config.tenant_id, config.tenant_name),
            )
            cursor.execute(
                """
                INSERT INTO identities (id, issuer, subject, email, display_name)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    identity_id,
                    config.oidc_issuer,
                    config.oidc_subject,
                    config.email,
                    config.display_name,
                ),
            )
            cursor.execute(
                "INSERT INTO projects (id, tenant_id, name) VALUES (%s, %s, %s)",
                (config.project_id, config.tenant_id, config.project_name),
            )
            cursor.execute(
                """
                INSERT INTO project_memberships
                    (tenant_id, project_id, identity_id, role)
                VALUES (%s, %s, %s, 'owner')
                """,
                (config.tenant_id, config.project_id, identity_id),
            )
            replayed = False

        cursor.execute(
            """
            INSERT INTO access_audit_events
                (tenant_id, project_id, actor_identity_id, event_type,
                 subject_type, subject_id, metadata)
            VALUES (%s, %s, %s, 'tenant.bootstrap', 'project', %s, %s)
            """,
            (
                config.tenant_id,
                config.project_id,
                identity_id,
                config.project_id,
                Jsonb(
                    {
                        "issuer": config.oidc_issuer,
                        "provisioner": "initial_owner_v1",
                        "replayed": replayed,
                    }
                ),
            ),
        )
    return InitialOwnerResult(config.tenant_id, identity_id, config.project_id, replayed)


def _require_installer(cursor: psycopg.Cursor[dict[str, Any]]) -> None:
    cursor.execute(
        """
        SELECT current_user AS current_role, session_user AS session_role,
               pg_get_userbyid(database_owner.datdba) AS database_owner,
               role.rolsuper, role.rolbypassrls,
               current_user = 'geo_app' OR EXISTS (
                   SELECT 1 FROM pg_auth_members AS membership
                   JOIN pg_roles AS granted ON granted.oid = membership.roleid
                   JOIN pg_roles AS member ON member.oid = membership.member
                   WHERE member.rolname = current_user AND granted.rolname = 'geo_app'
               ) AS is_app,
               current_user = 'geo_worker' OR EXISTS (
                   SELECT 1 FROM pg_auth_members AS membership
                   JOIN pg_roles AS granted ON granted.oid = membership.roleid
                   JOIN pg_roles AS member ON member.oid = membership.member
                   WHERE member.rolname = current_user AND granted.rolname = 'geo_worker'
               ) AS is_worker,
               has_table_privilege(current_user, 'public.tenants', 'SELECT,INSERT')
                   AS can_write_tenants,
               has_table_privilege(current_user, 'public.identities', 'SELECT,INSERT')
                   AS can_write_identities
        FROM pg_database AS database_owner
        JOIN pg_roles AS role ON role.rolname = current_user
        WHERE database_owner.datname = current_database()
        """
    )
    row = cursor.fetchone()
    allowed = bool(
        row
        and row["current_role"] == row["session_role"] == row["database_owner"]
        and (row["rolsuper"] or row["rolbypassrls"])
        and not row["is_app"]
        and not row["is_worker"]
        and row["can_write_tenants"]
        and row["can_write_identities"]
    )
    if not allowed:
        raise InitialOwnerProvisionError("bootstrap_installer_role_required")


def _validate_exact_replay(
    *,
    config: InitialOwnerConfig,
    tenant: dict[str, Any],
    identity: dict[str, Any],
    project: dict[str, Any],
    membership: dict[str, Any],
) -> UUID:
    identity_id = UUID(str(identity["id"]))
    exact = (
        tenant["name"] == config.tenant_name
        and tenant["status"] == "active"
        and identity["issuer"] == config.oidc_issuer
        and identity["subject"] == config.oidc_subject
        and identity["email"] == config.email
        and identity["display_name"] == config.display_name
        and identity["status"] == "active"
        and project["tenant_id"] == config.tenant_id
        and project["name"] == config.project_name
        and project["status"] == "active"
        and membership["tenant_id"] == config.tenant_id
        and membership["project_id"] == config.project_id
        and membership["identity_id"] == identity_id
        and membership["role"] == "owner"
        and membership["status"] == "active"
    )
    if not exact:
        raise InitialOwnerProvisionError("bootstrap_existing_state_conflict")
    return identity_id


def _reject_tenant_name_collision(
    cursor: psycopg.Cursor[dict[str, Any]], config: InitialOwnerConfig
) -> None:
    cursor.execute(
        "SELECT id FROM tenants WHERE lower(name) = lower(%s) AND id <> %s LIMIT 1",
        (config.tenant_name, config.tenant_id),
    )
    if cursor.fetchone() is not None:
        raise InitialOwnerProvisionError("bootstrap_tenant_name_conflict")


def _one(
    cursor: psycopg.Cursor[dict[str, Any]], query: str, parameters: tuple[object, ...]
) -> dict[str, Any] | None:
    cursor.execute(query, parameters)
    return cursor.fetchone()


def _database_url(env: Mapping[str, str]) -> str:
    direct = env.get("GEO_INSTALLER_DATABASE_URL", "").strip()
    file_name = env.get("GEO_INSTALLER_DATABASE_URL_FILE", "").strip()
    if bool(direct) == bool(file_name):
        raise InitialOwnerProvisionError("bootstrap_database_configuration_invalid")
    if file_name:
        try:
            path = Path(file_name)
            if not path.is_file() or path.stat().st_size > MAX_DATABASE_URL_BYTES:
                raise OSError
            direct = path.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise InitialOwnerProvisionError("bootstrap_database_file_unreadable") from error
    if not direct or not direct.startswith(("postgresql://", "postgres://")):
        raise InitialOwnerProvisionError("bootstrap_database_configuration_invalid")
    return direct


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "")
    if not value or value != value.strip() or any(ord(char) < 32 for char in value):
        raise InitialOwnerProvisionError("bootstrap_environment_invalid")
    return value


def _uuid(env: Mapping[str, str], name: str) -> UUID:
    try:
        return UUID(_required(env, name))
    except ValueError as error:
        raise InitialOwnerProvisionError("bootstrap_uuid_invalid") from error


def _name(env: Mapping[str, str], name: str) -> str:
    value = _required(env, name)
    if len(value) > MAX_NAME_LENGTH:
        raise InitialOwnerProvisionError("bootstrap_name_invalid")
    return value


def _identity_field(env: Mapping[str, str], name: str) -> str:
    value = _required(env, name)
    if len(value) > MAX_IDENTITY_FIELD_LENGTH:
        raise InitialOwnerProvisionError("bootstrap_identity_field_invalid")
    return value


def _issuer(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise InitialOwnerProvisionError("bootstrap_oidc_issuer_invalid")
    return value


def main() -> int:
    if len(sys.argv) != 1:
        error = InitialOwnerProvisionError("bootstrap_cli_arguments_forbidden")
    else:
        try:
            database_url, config = configuration_from_environment()
            result = provision_from_url(database_url, config)
            sys.stdout.write(json.dumps(result.public_dict(), sort_keys=True) + "\n")
            return 0
        except InitialOwnerProvisionError as caught:
            error = caught
    sys.stderr.write(json.dumps({"code": error.code}) + "\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
