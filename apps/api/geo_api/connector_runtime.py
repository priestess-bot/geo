"""Connector Admin composition root."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from geo_core.connectors.admin import ConnectorAdminService
from geo_core.connectors.external_data import ExternalDataService


def build_connector_admin_service() -> ConnectorAdminService | None:
    database_url = _secret("GEO_DATABASE_URL")
    if not database_url:
        return None
    return ConnectorAdminService(
        connect=lambda: psycopg.connect(database_url, row_factory=dict_row)
    )


def build_external_data_service() -> ExternalDataService | None:
    database_url = _secret("GEO_DATABASE_URL")
    if not database_url:
        return None
    return ExternalDataService(
        connect=lambda: psycopg.connect(database_url, row_factory=dict_row)
    )


def _secret(name: str) -> str:
    direct = os.getenv(name, "").strip()
    file_name = os.getenv(f"{name}_FILE", "").strip()
    if direct and file_name:
        raise RuntimeError(f"{name} and {name}_FILE cannot both be configured")
    if file_name:
        return Path(file_name).read_text(encoding="utf-8").strip()
    return direct


__all__ = ["build_connector_admin_service", "build_external_data_service"]
