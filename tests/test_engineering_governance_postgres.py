from __future__ import annotations

import hashlib
import hmac
import json
import os
from uuid import uuid4

import psycopg
import pytest

from geo_core.engineering.postgres import PostgresEngineeringUnitOfWork
from geo_core.engineering.service import EngineeringService


DATABASE_URL = os.getenv("GEO_TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="GEO_TEST_DATABASE_URL is required for PostgreSQL integration"
)


def test_signed_delivery_persists_inbox_job_spec_and_outbox_atomically() -> None:
    tenant_id, project_id = uuid4(), uuid4()
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute(
            "INSERT INTO tenants (id, name) VALUES (%s, 'Engineering integration')",
            (tenant_id,),
        )
        connection.execute(
            "INSERT INTO projects (id, tenant_id, name) VALUES (%s, %s, 'Board')",
            (project_id, tenant_id),
        )

    def unit_of_work() -> PostgresEngineeringUnitOfWork:
        return PostgresEngineeringUnitOfWork(
            lambda: psycopg.connect(DATABASE_URL), project_id=project_id
        )

    with unit_of_work() as uow:
        repository_id = uow.repository.register_repository(
            installation_id=321,
            external_repository_id=654,
            full_name="geo/example",
            web_url="https://github.example/geo/example",
            default_branch="main",
        )
        uow.commit()

    secret = "postgres-integration-secret"
    body = json.dumps({"repository": {"id": 654}, "action": "opened"}).encode()
    signature = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    service = EngineeringService(
        unit_of_work_factory=unit_of_work, github_webhook_secret=secret
    )

    first = service.accept_github_delivery(
        delivery_id="postgres-delivery",
        event_name="issues",
        signature=signature,
        body=body,
    )
    replay = service.accept_github_delivery(
        delivery_id="postgres-delivery",
        event_name="issues",
        signature=signature,
        body=body,
    )

    assert first.duplicate is False
    assert replay.duplicate is True
    assert replay.job_id == first.job_id
    with psycopg.connect(DATABASE_URL) as connection:
        assert connection.execute(
            "SELECT count(*) FROM engineering_webhook_deliveries WHERE project_id = %s",
            (project_id,),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT operation, repository_id FROM engineering_job_specs WHERE job_id = %s",
            (first.job_id,),
        ).fetchone() == ("github_project", repository_id)
        assert connection.execute(
            "SELECT count(*) FROM broker_outbox WHERE job_id = %s", (first.job_id,)
        ).fetchone()[0] == 1
