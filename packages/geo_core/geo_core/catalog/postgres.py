"""psycopg repository and Unit of Work for Catalog and Evidence."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from types import TracebackType
from typing import Any, Literal, TypeAlias, cast
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from geo_core.access.models import AccessPrincipal
from geo_core.catalog.domain import (
    BootstrapResult,
    CatalogConflict,
    CatalogPersistenceUnavailable,
    Confidentiality,
    EntityType,
    EvidenceDraft,
    EvidenceItem,
    EvidenceItemType,
    EvidenceSnapshot,
    MarketProfile,
    ProductEntity,
    Project,
    PublicCitation,
    SubjectRole,
    UsageRights,
)
from geo_core.catalog.ports import CatalogRepository, CatalogUnitOfWork


Connection: TypeAlias = psycopg.Connection[dict[str, Any]]
ConnectionFactory = Callable[[], Connection]


def _persistence_error(operation: str, error: psycopg.Error) -> RuntimeError:
    if isinstance(error, UniqueViolation):
        return CatalogConflict(f"The {operation} conflicts with an existing catalog record.")
    return CatalogPersistenceUnavailable(f"PostgreSQL could not {operation}.")


class PsycopgCatalogRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def create_project(
        self, *, project_id: UUID, principal: AccessPrincipal, name: str
    ) -> Project:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO projects (id, tenant_id, name)
                    VALUES (%s, %s, %s)
                    RETURNING id, tenant_id, name, status, created_at, updated_at
                    """,
                    (project_id, principal.tenant_id, name),
                )
                project = _project(_required(cursor.fetchone()))
                cursor.execute(
                    """
                    INSERT INTO project_memberships
                      (tenant_id, project_id, identity_id, role)
                    VALUES (%s, %s, %s, 'owner')
                    """,
                    (principal.tenant_id, project_id, principal.identity_id),
                )
                return project
        except psycopg.Error as error:
            raise _persistence_error("create the project", error) from error

    def get_project(self, *, project_id: UUID, tenant_id: UUID) -> Project | None:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, tenant_id, name, status, created_at, updated_at
                    FROM projects WHERE id = %s AND tenant_id = %s
                    """,
                    (project_id, tenant_id),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise _persistence_error("read the project", error) from error
        return _project(row) if row else None

    def update_project(
        self,
        *,
        project_id: UUID,
        tenant_id: UUID,
        name: str | None,
        status: str | None,
    ) -> Project | None:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE projects
                    SET name = COALESCE(%s, name),
                        status = COALESCE(%s, status),
                        updated_at = clock_timestamp()
                    WHERE id = %s AND tenant_id = %s
                    RETURNING id, tenant_id, name, status, created_at, updated_at
                    """,
                    (name, status, project_id, tenant_id),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise _persistence_error("update the project", error) from error
        return _project(row) if row else None

    def create_entity(
        self,
        *,
        project_id: UUID,
        entity_type: EntityType,
        canonical_name: str,
        canonical_url: str | None,
        attributes: Mapping[str, object],
    ) -> ProductEntity:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO product_entities
                      (project_id, entity_type, canonical_name, canonical_url, attributes)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id, project_id, entity_type, canonical_name, canonical_url,
                              attributes, status, created_at
                    """,
                    (project_id, entity_type.value, canonical_name, canonical_url, Jsonb(attributes)),
                )
                return _entity(_required(cursor.fetchone()))
        except psycopg.Error as error:
            raise _persistence_error("create the product entity", error) from error

    def list_entities(
        self, *, project_id: UUID, limit: int, offset: int
    ) -> tuple[ProductEntity, ...]:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, project_id, entity_type, canonical_name, canonical_url,
                           attributes, status, created_at
                    FROM product_entities WHERE project_id = %s
                    ORDER BY created_at, id LIMIT %s OFFSET %s
                    """,
                    (project_id, limit, offset),
                )
                rows = cursor.fetchall()
        except psycopg.Error as error:
            raise _persistence_error("list product entities", error) from error
        return tuple(_entity(row) for row in rows)

    def get_entity(self, *, project_id: UUID, entity_id: UUID) -> ProductEntity | None:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, project_id, entity_type, canonical_name, canonical_url,
                           attributes, status, created_at
                    FROM product_entities WHERE id = %s AND project_id = %s
                    """,
                    (entity_id, project_id),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise _persistence_error("read the evidence subject", error) from error
        return _entity(row) if row else None

    def create_market_profile(
        self,
        *,
        project_id: UUID,
        market_code: str,
        locale: str,
        timezone: str,
        rules: Mapping[str, object],
    ) -> MarketProfile:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO market_profiles
                      (project_id, market_code, locale, timezone, rules)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id, project_id, market_code, locale, timezone,
                              rules, status, created_at
                    """,
                    (project_id, market_code, locale, timezone, Jsonb(rules)),
                )
                return _market(_required(cursor.fetchone()))
        except psycopg.Error as error:
            raise _persistence_error("create the market profile", error) from error

    def list_market_profiles(
        self, *, project_id: UUID, limit: int, offset: int
    ) -> tuple[MarketProfile, ...]:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, project_id, market_code, locale, timezone,
                           rules, status, created_at
                    FROM market_profiles WHERE project_id = %s
                    ORDER BY created_at, id LIMIT %s OFFSET %s
                    """,
                    (project_id, limit, offset),
                )
                rows = cursor.fetchall()
        except psycopg.Error as error:
            raise _persistence_error("list market profiles", error) from error
        return tuple(_market(row) for row in rows)

    def create_evidence(
        self, *, project_id: UUID, draft: EvidenceDraft
    ) -> EvidenceItem:
        citation = draft.public_citation
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO evidence_items (
                      project_id, item_type, source_id, subject_entity_id, subject_role,
                      locator, snapshot_text, snapshot_uri, snapshot_hash,
                      source_revision_kind, source_revision_value, usage_rights,
                      confidentiality, public_disclosure_allowed, public_source_url,
                      public_source_title, citation_label, quotation_allowed,
                      attribution_required
                    ) VALUES (
                      %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    RETURNING *
                    """,
                    (
                        project_id,
                        draft.item_type.value,
                        draft.source_id,
                        draft.subject_entity_id,
                        draft.subject_role.value,
                        Jsonb(dict(draft.locator)),
                        draft.snapshot.text,
                        draft.snapshot.uri,
                        draft.snapshot.sha256,
                        draft.source_revision_kind,
                        draft.source_revision_value,
                        draft.usage_rights.value,
                        draft.confidentiality.value,
                        citation.disclosure_allowed,
                        citation.source_url,
                        citation.source_title,
                        citation.label,
                        citation.quotation_allowed,
                        citation.attribution_required,
                    ),
                )
                return _evidence(_required(cursor.fetchone()))
        except psycopg.Error as error:
            raise _persistence_error("create the evidence item", error) from error

    def list_evidence(
        self, *, project_id: UUID, limit: int, offset: int
    ) -> tuple[EvidenceItem, ...]:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT * FROM evidence_items WHERE project_id = %s
                    ORDER BY created_at, id LIMIT %s OFFSET %s
                    """,
                    (project_id, limit, offset),
                )
                rows = cursor.fetchall()
        except psycopg.Error as error:
            raise _persistence_error("list evidence items", error) from error
        return tuple(_evidence(row) for row in rows)

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
    ) -> BootstrapResult:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO tenants (id, name) VALUES (%s, %s)",
                    (tenant_id, tenant_name),
                )
                cursor.execute(
                    """
                    INSERT INTO identities (id, issuer, subject, email, display_name)
                    VALUES (%s, 'geo-development', %s, %s, %s)
                    """,
                    (identity_id, identity_subject, identity_email, identity_subject),
                )
                cursor.execute(
                    """
                    INSERT INTO projects (id, tenant_id, name)
                    VALUES (%s, %s, %s)
                    RETURNING id, tenant_id, name, status, created_at, updated_at
                    """,
                    (project_id, tenant_id, project_name),
                )
                project = _project(_required(cursor.fetchone()))
                cursor.execute(
                    """
                    INSERT INTO project_memberships
                      (tenant_id, project_id, identity_id, role)
                    VALUES (%s, %s, %s, 'owner')
                    """,
                    (tenant_id, project_id, identity_id),
                )
                return BootstrapResult(tenant_id, identity_id, project)
        except psycopg.Error as error:
            raise _persistence_error("bootstrap the development catalog", error) from error


class PsycopgCatalogUnitOfWork:
    """One transaction with tenant, identity and project RLS context."""

    catalog: CatalogRepository

    def __init__(
        self, connection_factory: ConnectionFactory, principal: AccessPrincipal | None
    ) -> None:
        self._connection_factory = connection_factory
        self._principal = principal
        self._connection: Connection | None = None
        self._project_ids = list(principal.project_ids if principal else ())
        self._committed = False

    def __enter__(self) -> "PsycopgCatalogUnitOfWork":
        try:
            self._connection = self._connection_factory()
            self.connection.execute("SET LOCAL statement_timeout = '10s'")
            self.catalog = PsycopgCatalogRepository(self.connection)
            self._set_context(
                identity_id=self._principal.identity_id if self._principal else None,
                tenant_id=self._principal.tenant_id if self._principal else None,
            )
        except psycopg.Error as error:
            self._close()
            raise _persistence_error("open a catalog transaction", error) from error
        return self

    @property
    def connection(self) -> Connection:
        if self._connection is None:
            raise RuntimeError("The Catalog Unit of Work has not been entered.")
        return self._connection

    def include_project(self, project_id: UUID) -> None:
        if self._principal is None:
            raise RuntimeError("an authenticated principal is required")
        if project_id not in self._project_ids:
            self._project_ids.append(project_id)
        self._set_context(
            identity_id=self._principal.identity_id, tenant_id=self._principal.tenant_id
        )

    def set_bootstrap_scope(
        self, *, identity_id: UUID, tenant_id: UUID, project_id: UUID
    ) -> None:
        if self._principal is not None:
            raise RuntimeError("bootstrap scope cannot replace an authenticated principal")
        self._project_ids = [project_id]
        self._set_context(identity_id=identity_id, tenant_id=tenant_id)

    def _set_context(self, *, identity_id: UUID | None, tenant_id: UUID | None) -> None:
        values = {
            "geo.actor_id": str(identity_id or ""),
            "geo.identity_id": str(identity_id or ""),
            "geo.tenant_id": str(tenant_id or ""),
            "geo.project_id": str(self._project_ids[0]) if self._project_ids else "",
            "geo.project_ids": json.dumps([str(value) for value in self._project_ids]),
        }
        with self.connection.cursor() as cursor:
            for name, value in values.items():
                cursor.execute(
                    sql.SQL("SELECT set_config({}, %s, true)").format(sql.Literal(name)),
                    (value,),
                )

    def commit(self) -> None:
        self.connection.commit()
        self._committed = True

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        del exc, traceback
        try:
            if self._connection is not None and not self._committed:
                self._connection.rollback()
        finally:
            self._close()
        return False

    def _close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


class PsycopgCatalogUnitOfWorkFactory:
    def __init__(self, database_url: str, *, connect_timeout: int = 5) -> None:
        if not database_url.strip():
            raise ValueError("database_url is required")
        self._database_url = database_url.strip()
        self._connect_timeout = connect_timeout

    def __call__(self, principal: AccessPrincipal | None = None) -> CatalogUnitOfWork:
        return PsycopgCatalogUnitOfWork(self._connect, principal)

    def _connect(self) -> Connection:
        return psycopg.connect(
            self._database_url,
            connect_timeout=self._connect_timeout,
            row_factory=dict_row,
        )


def _required(row: dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        raise CatalogPersistenceUnavailable("PostgreSQL did not return the created record.")
    return row


def _project(row: Mapping[str, Any]) -> Project:
    return Project(
        id=cast(UUID, row["id"]),
        tenant_id=cast(UUID, row["tenant_id"]),
        name=str(row["name"]),
        status=str(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _entity(row: Mapping[str, Any]) -> ProductEntity:
    return ProductEntity(
        id=cast(UUID, row["id"]),
        project_id=cast(UUID, row["project_id"]),
        entity_type=EntityType(str(row["entity_type"])),
        canonical_name=str(row["canonical_name"]),
        canonical_url=str(row["canonical_url"]) if row["canonical_url"] else None,
        attributes=cast(Mapping[str, object], row["attributes"]),
        status=str(row["status"]),
        created_at=row["created_at"],
    )


def _market(row: Mapping[str, Any]) -> MarketProfile:
    return MarketProfile(
        id=cast(UUID, row["id"]),
        project_id=cast(UUID, row["project_id"]),
        market_code=str(row["market_code"]),
        locale=str(row["locale"]),
        timezone=str(row["timezone"]),
        rules=cast(Mapping[str, object], row["rules"]),
        status=str(row["status"]),
        created_at=row["created_at"],
    )


def _evidence(row: Mapping[str, Any]) -> EvidenceItem:
    draft = EvidenceDraft(
        item_type=EvidenceItemType(str(row["item_type"])),
        source_id=cast(UUID, row["source_id"]),
        subject_entity_id=cast(UUID | None, row["subject_entity_id"]),
        subject_role=SubjectRole(str(row["subject_role"])),
        locator=cast(Mapping[str, object], row["locator"]),
        snapshot=EvidenceSnapshot(
            text=cast(str | None, row["snapshot_text"]),
            uri=cast(str | None, row["snapshot_uri"]),
            sha256=str(row["snapshot_hash"]),
        ),
        source_revision_kind=str(row["source_revision_kind"]),
        source_revision_value=str(row["source_revision_value"]),
        usage_rights=UsageRights(str(row["usage_rights"])),
        confidentiality=Confidentiality(str(row["confidentiality"])),
        public_citation=PublicCitation(
            disclosure_allowed=bool(row["public_disclosure_allowed"]),
            source_url=str(row["public_source_url"]) if row["public_source_url"] else None,
            source_title=str(row["public_source_title"])
            if row["public_source_title"]
            else None,
            label=str(row["citation_label"]) if row["citation_label"] else None,
            quotation_allowed=bool(row["quotation_allowed"]),
            attribution_required=bool(row["attribution_required"]),
        ),
    )
    return EvidenceItem(
        id=cast(UUID, row["id"]),
        project_id=cast(UUID, row["project_id"]),
        draft=draft,
        created_at=row["created_at"],
    )
