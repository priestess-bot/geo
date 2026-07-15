"""Provision non-superuser development logins after the Alembic baseline."""

from __future__ import annotations

import os
from uuid import UUID

import psycopg
from psycopg import sql


DEV_TENANT_ID = UUID("10000000-0000-4000-8000-000000000001")
DEV_PROJECT_ID = UUID("20000000-0000-4000-8000-000000000002")
DEV_IDENTITY_ID = UUID("30000000-0000-4000-8000-000000000003")


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def provision_login(
    cursor: psycopg.Cursor[tuple[object, ...]], *, login: str, password: str, group: str
) -> None:
    cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (login,))
    if cursor.fetchone() is None:
        cursor.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOBYPASSRLS PASSWORD {}"
            ).format(sql.Identifier(login), sql.Literal(password))
        )
    else:
        cursor.execute(
            sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                sql.Identifier(login), sql.Literal(password)
            )
        )
    cursor.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(group), sql.Identifier(login)))


def provision_workspace(cursor: psycopg.Cursor[tuple[object, ...]]) -> None:
    """Create the deterministic local Owner used by the Admin development BFF."""
    cursor.execute(
        """INSERT INTO tenants (id, name) VALUES (%s, 'GEO Development Tenant')
           ON CONFLICT (id) DO NOTHING""",
        (DEV_TENANT_ID,),
    )
    cursor.execute(
        """INSERT INTO identities (id, issuer, subject, email, display_name)
           VALUES (%s, 'https://development.geo.local', 'development-owner',
                   'owner@development.geo.local', 'Development Owner')
           ON CONFLICT (id) DO NOTHING""",
        (DEV_IDENTITY_ID,),
    )
    cursor.execute(
        """INSERT INTO projects (id, tenant_id, name)
           VALUES (%s, %s, 'GEO Development Project')
           ON CONFLICT (id) DO NOTHING""",
        (DEV_PROJECT_ID, DEV_TENANT_ID),
    )
    cursor.execute(
        """INSERT INTO project_memberships
             (tenant_id, project_id, identity_id, role, status)
           VALUES (%s, %s, %s, 'owner', 'active')
           ON CONFLICT (project_id, identity_id) DO NOTHING""",
        (DEV_TENANT_ID, DEV_PROJECT_ID, DEV_IDENTITY_ID),
    )
    actual = cursor.execute(
        """SELECT t.name, p.tenant_id, p.name, i.issuer, m.role, m.status
           FROM tenants t JOIN projects p ON p.tenant_id = t.id
           JOIN project_memberships m ON m.project_id = p.id AND m.tenant_id = p.tenant_id
           JOIN identities i ON i.id = m.identity_id
           WHERE t.id = %s AND p.id = %s AND i.id = %s""",
        (DEV_TENANT_ID, DEV_PROJECT_ID, DEV_IDENTITY_ID),
    ).fetchone()
    expected = (
        "GEO Development Tenant",
        DEV_TENANT_ID,
        "GEO Development Project",
        "https://development.geo.local",
        "owner",
        "active",
    )
    if actual != expected:
        raise RuntimeError("development workspace conflicts with deterministic bootstrap IDs")


def main() -> None:
    database_url = required("GEO_DATABASE_URL")
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            provision_login(
                cursor,
                login="geo_app_dev",
                password=required("GEO_DEV_APP_PASSWORD"),
                group="geo_app",
            )
            provision_login(
                cursor,
                login="geo_worker_dev",
                password=required("GEO_DEV_WORKER_PASSWORD"),
                group="geo_worker",
            )
            if os.getenv("GEO_DEV_BOOTSTRAP_ENABLED", "0").strip() == "1":
                provision_workspace(cursor)


if __name__ == "__main__":
    main()
