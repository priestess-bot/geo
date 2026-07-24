"""Internal API composition for the PostgreSQL Model Gateway runtime catalog."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol
from uuid import UUID

from geo_core.model_gateway.postgres_runtime_catalog import PostgresRuntimeCatalog
from geo_core.model_gateway.runtime_catalog import ApprovedRuntimeOptions


class ModelGatewayRuntimeApi(Protocol):
    persistence: str

    def list_options(self, *, project_id: UUID) -> ApprovedRuntimeOptions: ...


class DurableModelGatewayRuntimeApi:
    persistence = "durable"

    def __init__(self, catalog: PostgresRuntimeCatalog) -> None:
        self._catalog = catalog

    def list_options(self, *, project_id: UUID) -> ApprovedRuntimeOptions:
        return self._catalog.list_approved_runtime_options(project_id=project_id)


def build_model_gateway_runtime_api() -> ModelGatewayRuntimeApi | None:
    database_url = _secret("GEO_DATABASE_URL")
    if not database_url:
        return None
    return DurableModelGatewayRuntimeApi(PostgresRuntimeCatalog(database_url))


def _secret(name: str) -> str:
    direct = os.getenv(name, "").strip()
    file_name = os.getenv(f"{name}_FILE", "").strip()
    if direct and file_name:
        raise ValueError(f"{name} and {name}_FILE cannot both be configured")
    if not file_name:
        return direct
    return Path(file_name).read_text(encoding="utf-8").strip()


__all__ = [
    "DurableModelGatewayRuntimeApi",
    "ModelGatewayRuntimeApi",
    "build_model_gateway_runtime_api",
]
