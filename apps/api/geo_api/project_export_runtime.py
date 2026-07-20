"""Composition root for project export jobs and artifact downloads."""

from __future__ import annotations

import os
from typing import Literal

import psycopg
from psycopg.rows import dict_row

from geo_api.monitoring_runtime import _secret
from geo_core.object_store_config import build_object_store
from geo_core.project_exports.application import ProjectExportApplication
from geo_core.project_exports.postgres_source import PostgresProjectExportSource
from geo_core.project_exports.repository import PostgresProjectExportRepository


def build_project_export_application(
    *, surface: Literal["internal", "customer"]
) -> ProjectExportApplication | None:
    database_url = _secret("GEO_DATABASE_URL")
    if not database_url:
        return None

    def connection_factory():
        return psycopg.connect(database_url, row_factory=dict_row)

    source = PostgresProjectExportSource(connection_factory)
    if surface == "customer":
        return ProjectExportApplication(source=source)
    if not os.getenv("OBJECT_STORE_ENDPOINT", "").strip():
        return None
    store = build_object_store()
    return ProjectExportApplication(
        PostgresProjectExportRepository(connection_factory),
        store,
        source=source,
    )
