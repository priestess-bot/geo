from __future__ import annotations

import hashlib
import os
from uuid import uuid4

import psycopg
import pytest

from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.catalog.application import CatalogApplication
from geo_core.catalog.domain import (
    CatalogNotFound,
    Confidentiality,
    EntityType,
    EvidenceDraft,
    EvidenceItemType,
    EvidenceSnapshot,
    PublicCitation,
    SubjectRole,
    UsageRights,
)
from geo_core.catalog.postgres import PsycopgCatalogUnitOfWorkFactory


APP_URL = os.getenv("GEO_ACCESS_TEST_DATABASE_URL", "").strip()
ADMIN_URL = os.getenv("GEO_ACCESS_TEST_ADMIN_DATABASE_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not APP_URL or not ADMIN_URL,
        reason="GEO_ACCESS_TEST_DATABASE_URL and GEO_ACCESS_TEST_ADMIN_DATABASE_URL are required",
    ),
]


def test_catalog_project_evidence_rls_cross_project_and_rollback() -> None:
    tenant_id, identity_id = uuid4(), uuid4()
    seed_project_id, foreign_project_id = uuid4(), uuid4()
    marker = uuid4().hex[:10]
    with psycopg.connect(ADMIN_URL) as admin, admin.cursor() as cursor:
        cursor.execute(
            "INSERT INTO tenants (id, name) VALUES (%s, %s)",
            (tenant_id, f"Catalog tenant {marker}"),
        )
        cursor.execute(
            """
            INSERT INTO identities (id, issuer, subject)
            VALUES (%s, 'geo-test', %s)
            """,
            (identity_id, f"catalog-{marker}"),
        )
        for project_id, name in (
            (seed_project_id, "Seed project"),
            (foreign_project_id, "Foreign project"),
        ):
            cursor.execute(
                "INSERT INTO projects (id, tenant_id, name) VALUES (%s, %s, %s)",
                (project_id, tenant_id, f"{name} {marker}"),
            )
        cursor.execute(
            """
            INSERT INTO project_memberships (tenant_id, project_id, identity_id, role)
            VALUES (%s, %s, %s, 'owner')
            """,
            (tenant_id, seed_project_id, identity_id),
        )

    principal = AccessPrincipal(
        identity_id=identity_id,
        actor_id=f"catalog-{marker}",
        tenant_id=tenant_id,
        memberships=(MembershipRecord(seed_project_id, tenant_id, "owner"),),
        auth_method="development",
    )
    factory = PsycopgCatalogUnitOfWorkFactory(APP_URL)
    service = CatalogApplication(factory)
    try:
        created_project = service.create_project(principal, name=f"Created {marker}")
        with psycopg.connect(ADMIN_URL) as admin, admin.cursor() as cursor:
            cursor.execute(
                """
                SELECT role FROM project_memberships
                WHERE project_id = %s AND identity_id = %s
                """,
                (created_project.id, identity_id),
            )
            assert cursor.fetchone()[0] == "owner"

        expanded = AccessPrincipal(
            identity_id=identity_id,
            actor_id=principal.actor_id,
            tenant_id=tenant_id,
            memberships=principal.memberships
            + (MembershipRecord(created_project.id, tenant_id, "owner"),),
            auth_method="development",
        )
        entity = service.create_entity(
            expanded,
            project_id=created_project.id,
            entity_type=EntityType.PRODUCT,
            canonical_name=f"Product {marker}",
            canonical_url="https://product.example/item",
            attributes={"model": "one"},
        )
        text = "A governed product statement"
        evidence = service.create_evidence(
            expanded,
            project_id=created_project.id,
            draft=EvidenceDraft(
                item_type=EvidenceItemType.APPROVED_FACT,
                source_id=uuid4(),
                subject_entity_id=entity.id,
                subject_role=SubjectRole.PRODUCT,
                locator={"page": 3},
                snapshot=EvidenceSnapshot(
                    text=text,
                    uri=None,
                    sha256=hashlib.sha256(text.encode()).hexdigest(),
                ),
                source_revision_kind="content_hash",
                source_revision_value=marker,
                usage_rights=UsageRights.UNKNOWN,
                confidentiality=Confidentiality.INTERNAL,
                public_citation=PublicCitation(False),
            ),
        )
        assert not evidence.eligible_for_generation

        with pytest.raises(CatalogNotFound):
            service.get_project(expanded, project_id=foreign_project_id)
        with factory(expanded) as unit_of_work:
            assert unit_of_work.catalog.get_project(
                project_id=foreign_project_id, tenant_id=tenant_id
            ) is None

        rollback_name = f"Rollback {marker}"
        with pytest.raises(RuntimeError, match="force rollback"):
            with factory(expanded) as unit_of_work:
                unit_of_work.catalog.create_entity(
                    project_id=created_project.id,
                    entity_type=EntityType.BRAND,
                    canonical_name=rollback_name,
                    canonical_url=None,
                    attributes={},
                )
                raise RuntimeError("force rollback")
        with psycopg.connect(ADMIN_URL) as admin, admin.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM product_entities WHERE canonical_name = %s",
                (rollback_name,),
            )
            assert cursor.fetchone()[0] == 0
    finally:
        _cleanup(tenant_id=tenant_id, identity_id=identity_id)


def test_empty_database_development_bootstrap_is_atomic_and_creates_owner() -> None:
    marker = uuid4().hex[:10]
    service = CatalogApplication(
        PsycopgCatalogUnitOfWorkFactory(APP_URL), development_bootstrap_allowed=True
    )

    result = service.bootstrap_development(
        tenant_name=f"Bootstrap {marker}",
        identity_subject=f"developer-{marker}",
        identity_email=f"{marker}@example.com",
        project_name=f"First project {marker}",
    )
    try:
        with psycopg.connect(ADMIN_URL) as admin, admin.cursor() as cursor:
            cursor.execute(
                """
                SELECT role FROM project_memberships
                WHERE project_id = %s AND identity_id = %s AND tenant_id = %s
                """,
                (result.project.id, result.identity_id, result.tenant_id),
            )
            assert cursor.fetchone()[0] == "owner"
    finally:
        _cleanup(tenant_id=result.tenant_id, identity_id=result.identity_id)


def _cleanup(*, tenant_id: object, identity_id: object) -> None:
    with psycopg.connect(ADMIN_URL) as admin, admin.cursor() as cursor:
        # Evidence is immutable to application roles. Test cleanup uses an isolated
        # admin session to remove only this test's evidence before tenant cascade.
        cursor.execute("SET LOCAL session_replication_role = 'replica'")
        cursor.execute(
            """
            DELETE FROM evidence_items
            WHERE project_id IN (SELECT id FROM projects WHERE tenant_id = %s)
            """,
            (tenant_id,),
        )
        cursor.execute("SET LOCAL session_replication_role = 'origin'")
        cursor.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))
        cursor.execute("DELETE FROM identities WHERE id = %s", (identity_id,))
