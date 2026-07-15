"""Persistence ports for Project Catalog and governed Evidence."""

from __future__ import annotations

from collections.abc import Mapping
from types import TracebackType
from typing import Protocol
from uuid import UUID

from geo_core.access.models import AccessPrincipal
from geo_core.catalog.domain import (
    BootstrapResult,
    EntityType,
    EvidenceDraft,
    EvidenceItem,
    MarketProfile,
    ProductEntity,
    Project,
)


class CatalogRepository(Protocol):
    def create_project(
        self, *, project_id: UUID, principal: AccessPrincipal, name: str
    ) -> Project: ...

    def get_project(self, *, project_id: UUID, tenant_id: UUID) -> Project | None: ...

    def update_project(
        self,
        *,
        project_id: UUID,
        tenant_id: UUID,
        name: str | None,
        status: str | None,
    ) -> Project | None: ...

    def create_entity(
        self,
        *,
        project_id: UUID,
        entity_type: EntityType,
        canonical_name: str,
        canonical_url: str | None,
        attributes: Mapping[str, object],
    ) -> ProductEntity: ...

    def list_entities(
        self, *, project_id: UUID, limit: int, offset: int
    ) -> tuple[ProductEntity, ...]: ...

    def create_market_profile(
        self,
        *,
        project_id: UUID,
        market_code: str,
        locale: str,
        timezone: str,
        rules: Mapping[str, object],
    ) -> MarketProfile: ...

    def list_market_profiles(
        self, *, project_id: UUID, limit: int, offset: int
    ) -> tuple[MarketProfile, ...]: ...

    def get_entity(self, *, project_id: UUID, entity_id: UUID) -> ProductEntity | None: ...

    def create_evidence(
        self, *, project_id: UUID, draft: EvidenceDraft
    ) -> EvidenceItem: ...

    def list_evidence(
        self, *, project_id: UUID, limit: int, offset: int
    ) -> tuple[EvidenceItem, ...]: ...

    def bootstrap_development(
        self,
        *,
        tenant_id: UUID,
        identity_id: UUID,
        project_id: UUID,
        tenant_name: str,
        identity_subject: str,
        identity_email: str | None,
        project_name: str,
    ) -> BootstrapResult: ...


class CatalogUnitOfWork(Protocol):
    catalog: CatalogRepository

    def __enter__(self) -> "CatalogUnitOfWork": ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

    def include_project(self, project_id: UUID) -> None: ...

    def set_bootstrap_scope(
        self, *, identity_id: UUID, tenant_id: UUID, project_id: UUID
    ) -> None: ...

    def commit(self) -> None: ...


class CatalogUnitOfWorkFactory(Protocol):
    def __call__(self, principal: AccessPrincipal | None = None) -> CatalogUnitOfWork: ...
