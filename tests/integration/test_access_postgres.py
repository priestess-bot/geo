from __future__ import annotations

from hashlib import sha256
import os
from uuid import uuid4

import psycopg
import pytest

from geo_core.access.postgres import PsycopgAccessUnitOfWorkFactory
from geo_core.access.service import AccessApplicationService


APP_URL = os.getenv("GEO_ACCESS_TEST_DATABASE_URL", "").strip()
ADMIN_URL = os.getenv("GEO_ACCESS_TEST_ADMIN_DATABASE_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not APP_URL or not ADMIN_URL,
        reason="GEO_ACCESS_TEST_DATABASE_URL and GEO_ACCESS_TEST_ADMIN_DATABASE_URL are required",
    ),
]


def test_session_projects_jobs_and_uow_rollback_obey_rls() -> None:
    tenant_id = uuid4()
    identity_id = uuid4()
    session_id = uuid4()
    member_projects = (uuid4(), uuid4())
    foreign_project = uuid4()
    raw_token = f"customer-session-{uuid4()}"
    marker = uuid4().hex[:8]
    with psycopg.connect(ADMIN_URL) as admin:
        with admin.cursor() as cursor:
            cursor.execute(
                "INSERT INTO tenants (id, name) VALUES (%s, %s)",
                (tenant_id, f"Access tenant {marker}"),
            )
            cursor.execute(
                """
                INSERT INTO identities (id, issuer, subject, email)
                VALUES (%s, 'https://issuer.example', %s, %s)
                """,
                (identity_id, f"subject-{marker}", f"{marker}@example.com"),
            )
            for index, project_id in enumerate((*member_projects, foreign_project)):
                cursor.execute(
                    "INSERT INTO projects (id, tenant_id, name) VALUES (%s, %s, %s)",
                    (project_id, tenant_id, f"Project {index} {marker}"),
                )
                cursor.execute(
                    """
                    INSERT INTO market_profiles
                        (project_id, market_code, locale, timezone)
                    VALUES (%s, %s, 'en-AU', 'Australia/Sydney')
                    """,
                    (project_id, "AU" if index < 2 else "NZ"),
                )
                cursor.execute(
                    """
                    INSERT INTO durable_jobs
                        (project_id, kind, input_hash, idempotency_key)
                    VALUES (%s, 'collection', %s, %s)
                    """,
                    (project_id, "0" * 64, f"job-{index}-{marker}"),
                )
            for index, project_id in enumerate(member_projects):
                cursor.execute(
                    """
                    INSERT INTO project_memberships
                        (tenant_id, project_id, identity_id, role)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (tenant_id, project_id, identity_id, "customer" if index == 0 else "viewer"),
                )
            cursor.execute(
                """
                INSERT INTO customer_sessions
                    (id, identity_id, tenant_id, token_hash, expires_at)
                VALUES (%s, %s, %s, %s, clock_timestamp() + interval '1 hour')
                """,
                (session_id, identity_id, tenant_id, sha256(raw_token.encode()).hexdigest()),
            )

    factory = PsycopgAccessUnitOfWorkFactory(APP_URL)
    service = AccessApplicationService(factory)
    try:
        principal = service.authenticate_customer_session(raw_token=raw_token)
        projects = service.list_projects(principal, limit=50, offset=0)
        jobs = service.list_jobs(principal, limit=50, offset=0)

        assert set(principal.project_ids) == set(member_projects)
        assert {project.id for project in projects.items} == set(member_projects)
        assert projects.total == 2
        assert jobs.total == 2

        with pytest.raises(RuntimeError, match="force rollback"):
            with factory() as unit_of_work:
                unit_of_work.set_principal(principal)
                unit_of_work.sessions.revoke(session_id=session_id)
                raise RuntimeError("force rollback")

        with psycopg.connect(ADMIN_URL) as admin, admin.cursor() as cursor:
            cursor.execute("SELECT status FROM customer_sessions WHERE id = %s", (session_id,))
            assert cursor.fetchone()[0] == "active"

        service.logout(principal)
        with psycopg.connect(ADMIN_URL) as admin, admin.cursor() as cursor:
            cursor.execute("SELECT status FROM customer_sessions WHERE id = %s", (session_id,))
            assert cursor.fetchone()[0] == "revoked"
    finally:
        with psycopg.connect(ADMIN_URL) as admin, admin.cursor() as cursor:
            cursor.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))
            cursor.execute("DELETE FROM identities WHERE id = %s", (identity_id,))
