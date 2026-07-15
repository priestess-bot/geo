"""Composition root for the Project Catalog application slice."""

from __future__ import annotations

import os
from pathlib import Path

from geo_core.catalog.application import CatalogApplication


def build_catalog_application(
    *, dev_tools_enabled: bool, deployment_environment: str
) -> CatalogApplication | None:
    database_url = _secret("GEO_DATABASE_URL")
    if not database_url:
        return None
    from geo_core.catalog.postgres import PsycopgCatalogUnitOfWorkFactory

    bootstrap_allowed = dev_tools_enabled and deployment_environment != "production"
    return CatalogApplication(
        PsycopgCatalogUnitOfWorkFactory(database_url),
        development_bootstrap_allowed=bootstrap_allowed,
    )


def _secret(name: str) -> str:
    direct = os.getenv(name, "").strip()
    file_name = os.getenv(f"{name}_FILE", "").strip()
    if direct and file_name:
        raise ValueError(f"{name} and {name}_FILE cannot both be configured")
    if file_name:
        return Path(file_name).read_text(encoding="utf-8").strip()
    return direct
