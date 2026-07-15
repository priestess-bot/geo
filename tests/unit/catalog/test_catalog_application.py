from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from uuid import UUID, uuid4

import pytest

from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.catalog.application import CatalogApplication
from geo_core.catalog.domain import (
    CatalogForbidden,
    CatalogRuleViolation,
    EntityType,
    EvidenceDraft,
    EvidenceItem,
    EvidenceItemType,
    EvidenceSnapshot,
    ProductEntity,
    PublicCitation,
    SubjectRole,
    UsageRights,
    Confidentiality,
)


NOW = datetime(2026, 7, 16, tzinfo=UTC)


def principal(role: str = "analyst", *, with_project: bool = True) -> AccessPrincipal:
    tenant_id, identity_id, project_id = uuid4(), uuid4(), uuid4()
    memberships = (
        (MembershipRecord(project_id=project_id, tenant_id=tenant_id, role=role),)
        if with_project
        else ()
    )
    return AccessPrincipal(
        identity_id=identity_id,
        actor_id=f"subject-{identity_id}",
        tenant_id=tenant_id,
        memberships=memberships,
        auth_method="development",
    )


class FakeRepository:
    def __init__(self) -> None:
        self.entities: dict[UUID, ProductEntity] = {}
        self.created_project_principal: AccessPrincipal | None = None
        self.evidence: list[EvidenceItem] = []

    def create_project(self, *, project_id: UUID, principal: AccessPrincipal, name: str):
        from geo_core.catalog.domain import Project

        self.created_project_principal = principal
        return Project(project_id, principal.tenant_id, name, "active", NOW, NOW)

    def get_project(self, **values: object):
        del values
        return None

    def update_project(self, **values: object):
        del values
        return None

    def create_entity(self, **values: object) -> ProductEntity:
        entity = ProductEntity(
            id=uuid4(),
            project_id=values["project_id"],
            entity_type=values["entity_type"],
            canonical_name=str(values["canonical_name"]),
            canonical_url=None,
            attributes={},
            status="active",
            created_at=NOW,
        )
        self.entities[entity.id] = entity
        return entity

    def get_entity(self, *, project_id: UUID, entity_id: UUID):
        entity = self.entities.get(entity_id)
        return entity if entity and entity.project_id == project_id else None

    def create_evidence(self, *, project_id: UUID, draft: EvidenceDraft) -> EvidenceItem:
        item = EvidenceItem(uuid4(), project_id, draft, NOW)
        self.evidence.append(item)
        return item

    def list_entities(self, **values: object):
        del values
        return tuple(self.entities.values())

    def list_market_profiles(self, **values: object):
        del values
        return ()

    def list_evidence(self, **values: object):
        del values
        return tuple(self.evidence)


class FakeUnitOfWork:
    def __init__(self, repository: FakeRepository) -> None:
        self.catalog = repository
        self.committed = False
        self.included: UUID | None = None

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def include_project(self, project_id: UUID) -> None:
        self.included = project_id

    def commit(self) -> None:
        self.committed = True


class FakeFactory:
    def __init__(self) -> None:
        self.repository = FakeRepository()
        self.units: list[FakeUnitOfWork] = []

    def __call__(self, principal: AccessPrincipal | None = None):
        del principal
        unit = FakeUnitOfWork(self.repository)
        self.units.append(unit)
        return unit


def _draft(*, subject_id: UUID, rights: UsageRights = UsageRights.OWNED) -> EvidenceDraft:
    text = "Verified product fact"
    return EvidenceDraft(
        item_type=EvidenceItemType.APPROVED_FACT,
        source_id=uuid4(),
        subject_entity_id=subject_id,
        subject_role=SubjectRole.PRODUCT,
        locator={"json_pointer": "/facts/0"},
        snapshot=EvidenceSnapshot(
            text=text, uri=None, sha256=hashlib.sha256(text.encode()).hexdigest()
        ),
        source_revision_kind="content_hash",
        source_revision_value="revision-one",
        usage_rights=rights,
        confidentiality=Confidentiality.INTERNAL,
        public_citation=PublicCitation(False),
    )


def test_project_creation_requires_tenant_admin_and_adds_new_rls_scope() -> None:
    actor = principal("owner")
    factory = FakeFactory()
    service = CatalogApplication(factory)  # type: ignore[arg-type]

    project = service.create_project(actor, name="First project")

    assert factory.repository.created_project_principal is actor
    assert factory.units[-1].included == project.id
    assert factory.units[-1].committed

    for role in ("viewer", "customer"):
        with pytest.raises(CatalogForbidden):
            service.create_project(principal(role), name="Forbidden project")


def test_analyst_can_create_typed_subject_evidence_but_cannot_admin_project() -> None:
    actor = principal("analyst")
    project_id = actor.project_ids[0]
    factory = FakeFactory()
    service = CatalogApplication(factory)  # type: ignore[arg-type]
    entity = service.create_entity(
        actor,
        project_id=project_id,
        entity_type=EntityType.PRODUCT,
        canonical_name="Product One",
        canonical_url=None,
        attributes={},
    )

    evidence = service.create_evidence(
        actor, project_id=project_id, draft=_draft(subject_id=entity.id)
    )

    assert evidence.eligible_for_generation
    with pytest.raises(CatalogForbidden):
        service.update_project(
            actor, project_id=project_id, name="Forbidden", status=None
        )


@pytest.mark.parametrize("role", ["viewer", "customer"])
def test_reader_roles_cannot_write_catalog_resources(role: str) -> None:
    actor = principal(role)
    service = CatalogApplication(FakeFactory())  # type: ignore[arg-type]

    with pytest.raises(CatalogForbidden):
        service.create_entity(
            actor,
            project_id=actor.project_ids[0],
            entity_type=EntityType.BRAND,
            canonical_name="Forbidden brand",
            canonical_url=None,
            attributes={},
        )


def test_unknown_rights_are_stored_but_fail_closed_for_generation_and_publication() -> None:
    actor = principal("owner")
    project_id = actor.project_ids[0]
    factory = FakeFactory()
    service = CatalogApplication(factory)  # type: ignore[arg-type]
    entity = service.create_entity(
        actor,
        project_id=project_id,
        entity_type=EntityType.PRODUCT,
        canonical_name="Product One",
        canonical_url=None,
        attributes={},
    )

    evidence = service.create_evidence(
        actor,
        project_id=project_id,
        draft=_draft(subject_id=entity.id, rights=UsageRights.UNKNOWN),
    )

    assert not evidence.eligible_for_generation
    assert not evidence.eligible_for_publication


def test_evidence_hash_minio_and_public_disclosure_rules_are_fail_closed() -> None:
    with pytest.raises(CatalogRuleViolation, match="hash does not match"):
        EvidenceSnapshot(text="content", uri=None, sha256="0" * 64)
    with pytest.raises(CatalogRuleViolation, match="s3://"):
        EvidenceSnapshot(text=None, uri="https://bucket/object", sha256="0" * 64)
    with pytest.raises(CatalogRuleViolation, match="eligible rights"):
        EvidenceDraft(
            item_type=EvidenceItemType.CITATION,
            source_id=uuid4(),
            subject_entity_id=None,
            subject_role=SubjectRole.NEUTRAL,
            locator={},
            snapshot=EvidenceSnapshot(
                text=None, uri="s3://geo-evidence/path/item.txt", sha256="0" * 64
            ),
            source_revision_kind="content_hash",
            source_revision_value="one",
            usage_rights=UsageRights.RESTRICTED,
            confidentiality=Confidentiality.PUBLIC,
            public_citation=PublicCitation(
                True, "https://source.example", "Source", "Source"
            ),
        )
