"""Compatibility facade for PostgreSQL-backed Model Gateway persistence."""

from geo_core.model_gateway.postgres_catalog import (
    PostgresModelGatewayPersistence,
    build_model_gateway_persistence,
)
from geo_core.model_gateway.postgres_repository import PsycopgModelCallRepository
from geo_core.model_gateway.postgres_runtime_catalog import PostgresRuntimeCatalog
from geo_core.model_gateway.postgres_uow import (
    PostgresModelCallUnitOfWork,
    PostgresModelCallUnitOfWorkFactory,
)


__all__ = [
    "PostgresModelCallUnitOfWork",
    "PostgresModelCallUnitOfWorkFactory",
    "PostgresModelGatewayPersistence",
    "PostgresRuntimeCatalog",
    "PsycopgModelCallRepository",
    "build_model_gateway_persistence",
]
