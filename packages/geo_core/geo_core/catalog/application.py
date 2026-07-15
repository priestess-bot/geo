"""Transactional Project Catalog and Evidence use cases."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID, uuid4

from geo_core.access.models import AccessPrincipal
from geo_core.catalog.domain import (
    CONTRIBUTOR_ROLES,
    PROJECT_ADMIN_ROLES,
    READER_ROLES,
    BootstrapResult,
    CatalogForbidden,
    CatalogNotFound,
    CatalogRuleViolation,
    EntityType,
    EvidenceDraft,
    EvidenceItem,
    MarketProfile,
    ProductEntity,
    Project,
    SubjectRole,
    require_project_role,
    require_tenant_project_admin,
    validate_subject_type,
)
from geo_core.catalog.ports import CatalogUnitOfWorkFactory


class CatalogApplication:
    """Every command derives tenant, actor and project authority from a principal."""

    def __init__(
        self,
        unit_of_work_factory: CatalogUnitOfWorkFactory,
        *,
        development_bootstrap_allowed: bool = False,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._development_bootstrap_allowed = development_bootstrap_allowed

    def create_project(self, principal: AccessPrincipal, *, name: str) -> Project:
        require_tenant_project_admin(principal)
        if not name.strip():
            raise CatalogRuleViolation("project name is required")
        project_id = uuid4()
        with self._unit_of_work_factory(principal) as unit_of_work:
            unit_of_work.include_project(project_id)
            project = unit_of_work.catalog.create_project(
                project_id=project_id, principal=principal, name=name.strip()
            )
            unit_of_work.commit()
            return project

    def get_project(self, principal: AccessPrincipal, *, project_id: UUID) -> Project:
        require_project_role(principal, project_id, allowed=READER_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            project = unit_of_work.catalog.get_project(
                project_id=project_id, tenant_id=principal.tenant_id
            )
        if project is None:
            raise CatalogNotFound("The requested project does not exist.")
        return project

    def update_project(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        name: str | None,
        status: str | None,
    ) -> Project:
        require_project_role(principal, project_id, allowed=PROJECT_ADMIN_ROLES)
        if name is None and status is None:
            raise CatalogRuleViolation("project update requires name or status")
        if name is not None and not name.strip():
            raise CatalogRuleViolation("project name must not be empty")
        if status is not None and status not in {"active", "paused", "archived"}:
            raise CatalogRuleViolation("project status is unsupported")
        with self._unit_of_work_factory(principal) as unit_of_work:
            project = unit_of_work.catalog.update_project(
                project_id=project_id,
                tenant_id=principal.tenant_id,
                name=name.strip() if name else None,
                status=status,
            )
            if project is None:
                raise CatalogNotFound("The requested project does not exist.")
            unit_of_work.commit()
            return project

    def create_entity(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        entity_type: EntityType,
        canonical_name: str,
        canonical_url: str | None,
        attributes: Mapping[str, object],
    ) -> ProductEntity:
        require_project_role(principal, project_id, allowed=CONTRIBUTOR_ROLES)
        if not canonical_name.strip():
            raise CatalogRuleViolation("entity canonical name is required")
        with self._unit_of_work_factory(principal) as unit_of_work:
            entity = unit_of_work.catalog.create_entity(
                project_id=project_id,
                entity_type=entity_type,
                canonical_name=canonical_name.strip(),
                canonical_url=canonical_url,
                attributes=attributes,
            )
            unit_of_work.commit()
            return entity

    def list_entities(
        self, principal: AccessPrincipal, *, project_id: UUID, limit: int, offset: int
    ) -> tuple[ProductEntity, ...]:
        require_project_role(principal, project_id, allowed=READER_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            return unit_of_work.catalog.list_entities(
                project_id=project_id, limit=limit, offset=offset
            )

    def create_market_profile(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        market_code: str,
        locale: str,
        timezone: str,
        rules: Mapping[str, object],
    ) -> MarketProfile:
        require_project_role(principal, project_id, allowed=CONTRIBUTOR_ROLES)
        normalized_code = market_code.strip().upper()
        if (
            len(normalized_code) != 2
            or not normalized_code.isascii()
            or not normalized_code.isalpha()
        ):
            raise CatalogRuleViolation("market code must contain two ASCII letters")
        if not locale.strip() or not timezone.strip():
            raise CatalogRuleViolation("market locale and timezone are required")
        with self._unit_of_work_factory(principal) as unit_of_work:
            profile = unit_of_work.catalog.create_market_profile(
                project_id=project_id,
                market_code=normalized_code,
                locale=locale.strip(),
                timezone=timezone.strip(),
                rules=rules,
            )
            unit_of_work.commit()
            return profile

    def list_market_profiles(
        self, principal: AccessPrincipal, *, project_id: UUID, limit: int, offset: int
    ) -> tuple[MarketProfile, ...]:
        require_project_role(principal, project_id, allowed=READER_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            return unit_of_work.catalog.list_market_profiles(
                project_id=project_id, limit=limit, offset=offset
            )

    def create_evidence(
        self, principal: AccessPrincipal, *, project_id: UUID, draft: EvidenceDraft
    ) -> EvidenceItem:
        require_project_role(principal, project_id, allowed=CONTRIBUTOR_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            if draft.subject_role != SubjectRole.NEUTRAL:
                subject_id = draft.subject_entity_id
                if subject_id is None:
                    raise CatalogRuleViolation("non-neutral evidence requires a subject entity")
                entity = unit_of_work.catalog.get_entity(
                    project_id=project_id, entity_id=subject_id
                )
                if entity is None:
                    raise CatalogNotFound("The evidence subject does not exist in this project.")
                validate_subject_type(role=draft.subject_role, entity_type=entity.entity_type)
            evidence = unit_of_work.catalog.create_evidence(
                project_id=project_id, draft=draft
            )
            unit_of_work.commit()
            return evidence

    def list_evidence(
        self, principal: AccessPrincipal, *, project_id: UUID, limit: int, offset: int
    ) -> tuple[EvidenceItem, ...]:
        require_project_role(principal, project_id, allowed=READER_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            return unit_of_work.catalog.list_evidence(
                project_id=project_id, limit=limit, offset=offset
            )

    def bootstrap_development(
        self,
        *,
        tenant_name: str,
        identity_subject: str,
        identity_email: str | None,
        project_name: str,
    ) -> BootstrapResult:
        if not self._development_bootstrap_allowed:
            raise CatalogForbidden("development bootstrap is disabled")
        if not all(value.strip() for value in (tenant_name, identity_subject, project_name)):
            raise CatalogRuleViolation("bootstrap tenant, identity and project names are required")
        tenant_id, identity_id, project_id = uuid4(), uuid4(), uuid4()
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.set_bootstrap_scope(
                identity_id=identity_id, tenant_id=tenant_id, project_id=project_id
            )
            result = unit_of_work.catalog.bootstrap_development(
                tenant_id=tenant_id,
                identity_id=identity_id,
                project_id=project_id,
                tenant_name=tenant_name.strip(),
                identity_subject=identity_subject.strip(),
                identity_email=identity_email.strip() if identity_email else None,
                project_name=project_name.strip(),
            )
            unit_of_work.commit()
            return result
