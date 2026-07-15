"""Provision non-superuser development logins after the Alembic baseline."""

from __future__ import annotations

import os

import psycopg
from psycopg import sql


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


if __name__ == "__main__":
    main()
