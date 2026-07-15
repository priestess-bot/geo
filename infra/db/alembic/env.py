from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from alembic.script import ScriptDirectory
from sqlalchemy import engine_from_config, pool

from infra.db.alembic.checksums import (
    ensure_ledger,
    synchronize_ledger,
    verify_applied,
)


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

def database_url_from_environment() -> str:
    direct = [
        value.strip()
        for name in ("GEO_DATABASE_URL", "DATABASE_URL")
        if (value := os.getenv(name, "")).strip()
    ]
    files = [
        value.strip()
        for name in ("GEO_DATABASE_URL_FILE", "DATABASE_URL_FILE")
        if (value := os.getenv(name, "")).strip()
    ]
    if len(direct) + len(files) > 1:
        raise RuntimeError("configure exactly one database URL or database URL file")
    if direct:
        return sqlalchemy_psycopg_url(direct[0])
    if files:
        try:
            value = Path(files[0]).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError("unable to read database URL file") from exc
        if not value:
            raise RuntimeError("database URL file is empty")
        return sqlalchemy_psycopg_url(value)
    return ""


def sqlalchemy_psycopg_url(value: str) -> str:
    if value.startswith("postgresql://"):
        return "postgresql+psycopg://" + value.removeprefix("postgresql://")
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value.removeprefix("postgres://")
    return value


explicit_database_url = config.attributes.get("geo_database_url_override")
database_url = (
    sqlalchemy_psycopg_url(explicit_database_url)
    if isinstance(explicit_database_url, str) and explicit_database_url.strip()
    else database_url_from_environment()
)
if database_url:
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

target_metadata = None


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            script = ScriptDirectory.from_config(config)
            sql_directory = Path(script.dir) / "sql"
            ensure_ledger(connection)
            if connection.exec_driver_sql(
                "SELECT count(*) FROM alembic_sql_checksum_ledger"
            ).scalar_one():
                verify_applied(
                    connection, script=script, sql_directory=sql_directory
                )
            context.run_migrations()
            synchronize_ledger(
                connection, script=script, sql_directory=sql_directory
            )


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
