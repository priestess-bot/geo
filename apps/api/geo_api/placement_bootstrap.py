"""Composition root for the PostgreSQL placement application service."""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import psycopg

from geo_core.placements.application import PlacementApplication
from geo_core.placements.postgres_uow import placement_uow_factory
from geo_core.placements.ports import UnitOfWorkFactory


def placement_application_from_environment() -> PlacementApplication | None:
    """Return no adapter when the optional placement database secret is absent."""
    secret_path = os.getenv("GEO_DATABASE_URL_FILE", "").strip()
    if not secret_path:
        return None
    path = Path(secret_path)
    try:
        database_url = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError("GEO_DATABASE_URL_FILE cannot be read") from exc
    if not database_url:
        raise RuntimeError("GEO_DATABASE_URL_FILE is empty")
    return PlacementApplication(
        cast(
            UnitOfWorkFactory,
            placement_uow_factory(lambda: psycopg.connect(database_url)),
        )
    )
