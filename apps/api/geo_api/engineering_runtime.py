"""Runtime construction for the engineering governance application service."""

from __future__ import annotations

import os
from pathlib import Path
from collections.abc import Iterator
from typing import Protocol
from uuid import UUID

from geo_core.engineering.postgres import PostgresEngineeringUnitOfWork
from geo_core.engineering.ports import EngineeringEvent, EngineeringUnitOfWork
from geo_core.engineering.service import EngineeringService
from geo_core.engineering.service import WebhookConfigurationError
from geo_api.foundation_services import FoundationServiceUnavailable


class UnavailableEngineeringService:
    """Truthful no-data service used when PostgreSQL is not configured."""

    github_available = False
    persistence_available = False
    runtime_available = False

    def list_work_items(self) -> tuple[object, ...]:
        return ()

    def accept_github_delivery(self, **kwargs: object) -> object:
        del kwargs
        raise WebhookConfigurationError("engineering persistence is not configured")

    def request_reconciliation(self, **kwargs: object) -> object:
        del kwargs
        raise FoundationServiceUnavailable("engineering persistence is not configured")

    def request_health_probe(self, **kwargs: object) -> object:
        del kwargs
        raise FoundationServiceUnavailable("engineering persistence is not configured")

    def events(self, **kwargs: object) -> Iterator[EngineeringEvent]:
        del kwargs
        return iter(())


class EngineeringServices(Protocol):
    github_available: bool


def build_engineering_service() -> EngineeringService | UnavailableEngineeringService:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        return UnavailableEngineeringService()

    import psycopg

    project_value = os.getenv("GEO_ENGINEERING_PROJECT_ID", "").strip()
    project_id = UUID(project_value) if project_value else None
    secret = _secret("GEO_GITHUB_WEBHOOK_SECRET")
    github_source_available = bool(
        secret
        and os.getenv("GEO_GITHUB_APP_ID", "").strip()
        and _secret("GEO_GITHUB_APP_PRIVATE_KEY")
        and project_id
    )
    runtime_source_available = bool(
        project_id and os.getenv("GEO_ENGINEERING_HEALTH_TARGETS", "").strip()
    )

    def unit_of_work() -> EngineeringUnitOfWork:
        return PostgresEngineeringUnitOfWork(
            lambda: psycopg.connect(database_url), project_id=project_id
        )

    service = EngineeringService(
        unit_of_work_factory=unit_of_work,
        github_webhook_secret=secret,
        github_source_available=github_source_available,
        runtime_source_available=runtime_source_available,
    )
    return service


def _secret(name: str) -> str | None:
    direct = os.getenv(name, "").strip()
    file_path = os.getenv(f"{name}_FILE", "").strip()
    if direct and file_path:
        raise RuntimeError(f"configure only one of {name} or {name}_FILE")
    if file_path:
        return Path(file_path).read_text(encoding="utf-8").strip() or None
    return direct or None
