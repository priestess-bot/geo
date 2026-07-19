"""Composition root for project export jobs and artifact downloads."""

from __future__ import annotations

import os

import psycopg
from psycopg.rows import dict_row

from geo_api.monitoring_runtime import _secret
from geo_core.object_store_config import build_object_store
from geo_core.project_exports.application import ProjectExportApplication
from geo_core.project_exports.postgres_source import PostgresProjectExportSource
from geo_core.project_exports.repository import PostgresProjectExportRepository


def build_project_export_application() -> ProjectExportApplication | None:
    database_url = _secret("GEO_DATABASE_URL")
    if not database_url or not os.getenv("OBJECT_STORE_ENDPOINT", "").strip():
        return None

    def connection_factory():
        return psycopg.connect(database_url, row_factory=dict_row)

    store = build_object_store()
    return ProjectExportApplication(
        PostgresProjectExportRepository(connection_factory),
        store,
        source=PostgresProjectExportSource(connection_factory),
    )
