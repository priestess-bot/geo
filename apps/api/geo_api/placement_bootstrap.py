"""Composition root for the PostgreSQL placement application service."""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import psycopg

from geo_core.placements.application import PlacementApplication
from geo_core.placements.postgres_uow import placement_uow_factory
from geo_core.placements.ports import UnitOfWorkFactory
from geo_core.object_store_config import build_object_store


def placement_application_from_environment() -> PlacementApplication | None:
    """Return no adapter when the optional placement database secret is absent."""
    direct = (os.getenv("GEO_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
    secret_path = (
        os.getenv("GEO_DATABASE_URL_FILE") or os.getenv("DATABASE_URL_FILE") or ""
    ).strip()
    if direct and secret_path:
        raise RuntimeError("configure the database URL directly or by file, not both")
    if not direct and not secret_path:
        return None
    database_url = direct
    if secret_path:
        path = Path(secret_path)
        try:
            database_url = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError("database URL secret file cannot be read") from exc
    if not database_url:
        raise RuntimeError("GEO_DATABASE_URL_FILE is empty")
    artifact_reader = build_object_store() if os.getenv("OBJECT_STORE_ENDPOINT") else None
    return PlacementApplication(
        cast(
            UnitOfWorkFactory,
            placement_uow_factory(lambda: psycopg.connect(database_url)),
        ),
        artifact_reader=artifact_reader,
    )
