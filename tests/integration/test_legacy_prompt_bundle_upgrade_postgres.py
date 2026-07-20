from __future__ import annotations

import hashlib
import os
from typing import Any
from uuid import UUID, uuid4

from alembic import command
from fastapi.testclient import TestClient
import psycopg
import pytest
from psycopg.types.json import Jsonb

from geo_api.app_factory import create_api_app
from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.placements.application import PlacementApplication
from geo_core.placements.errors import PlacementContractMigrationRequired
from geo_core.placements.postgres_uow import placement_uow_factory
from tests.integration.test_batch2_migrations_postgres import (
    _seed_legacy_fixture,
    _temporary_database,
)


ADMIN_URL = os.getenv("GEO_ACCESS_TEST_ADMIN_DATABASE_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not ADMIN_URL,
        reason="GEO_ACCESS_TEST_ADMIN_DATABASE_URL is required",
    ),
]


class _AccessServices:
    def __init__(self, principal: AccessPrincipal) -> None:
        self._principal = principal

    def authenticate(self, authentication: object) -> AccessPrincipal:
        del authentication
        return self._principal


def test_legacy_prompt_bundle_is_readable_but_not_executable_after_upgrade() -> None:
    with _temporary_database() as (database_url, configuration):
        command.upgrade(configuration, "0010_campaign_destinations")
        with psycopg.connect(database_url) as connection:
            fixture = _seed_legacy_fixture(connection)
            bundle = _seed_legacy_prompt_bundle(connection, fixture)

        command.upgrade(configuration, "head")

        application = PlacementApplication(
            placement_uow_factory(lambda: psycopg.connect(database_url))  # type: ignore[arg-type]
        )
        principal = AccessPrincipal(
            identity_id=fixture["owner"],
            actor_id=str(fixture["owner"]),
            tenant_id=fixture["tenant"],
            memberships=(MembershipRecord(fixture["project"], fixture["tenant"], "owner"),),
            auth_method="test",
        )
        app = create_api_app(
            surface="internal",
            services=_AccessServices(principal),  # type: ignore[arg-type]
            placement_services=application,
        )
        list_url = (
            f"/v1/projects/{fixture['project']}/geo/brief-versions/{bundle['brief_version_id']}"
            f"/prompt-bundles?campaign_id={fixture['campaign']}"
        )
        detail_url = (
            f"/v1/projects/{fixture['project']}/geo/prompt-bundles/{bundle['bundle_id']}"
            f"?campaign_id={fixture['campaign']}"
        )

        with TestClient(app) as client:
            listed = client.get(list_url)
            detail = client.get(detail_url)

        assert listed.status_code == 200, listed.text
        assert detail.status_code == 200, detail.text
        assert len(listed.json()) == 1
        for value in (listed.json()[0], detail.json()):
            assert value["id"] == str(bundle["bundle_id"])
            assert value["prompt_release_binding_id"] is None
            assert value["prompt_release_binding_version"] is None
        assert detail.json()["manifest"] == {"legacy": True}

        with pytest.raises(PlacementContractMigrationRequired) as raised:
            application.request_generation(
                project_id=fixture["project"],
                campaign_id=fixture["campaign"],
                prompt_bundle_id=bundle["bundle_id"],
                configured_model="deepseek-v4-flash",
                model_call_budget=1,
                idempotency_key=f"legacy-bundle-generation-{uuid4()}",
                requested_by=fixture["owner"],
            )
        assert raised.value.error_code == "legacy_generation_enqueue_rebuild_required"
        assert "Opportunity-bound Prompt Bundle" in raised.value.operator_action


def _seed_legacy_prompt_bundle(
    connection: psycopg.Connection[Any], fixture: dict[str, Any]
) -> dict[str, UUID]:
    brief_id = uuid4()
    brief_version_id = uuid4()
    evidence_attempt_id = uuid4()
    bundle_id = uuid4()
    artifact_job_id = uuid4()
    digest = hashlib.sha256(b"legacy-prompt-bundle").hexdigest()

    connection.execute(
        "UPDATE placement_opportunities SET status = 'qualified' WHERE id = %s",
        (fixture["opportunity"],),
    )
    connection.execute(
        "UPDATE placement_opportunities SET status = 'briefing' WHERE id = %s",
        (fixture["opportunity"],),
    )
    connection.execute(
        """INSERT INTO placement_briefs
             (id, project_id, opportunity_id, primary_brand_entity_id)
           VALUES (%s, %s, %s, %s)""",
        (brief_id, fixture["project"], fixture["opportunity"], fixture["product"]),
    )
    connection.execute(
        """INSERT INTO placement_brief_versions
             (id, project_id, brief_id, version_number, goals, constraints,
              content_hash, created_by)
           VALUES (%s, %s, %s, 1, '{}'::jsonb, '{}'::jsonb, %s, %s)""",
        (brief_version_id, fixture["project"], brief_id, digest, fixture["owner"]),
    )
    connection.execute(
        """INSERT INTO evidence_pack_attempts
             (id, project_id, brief_version_id, attempt_number, status, pack_hash,
              completed_at)
           VALUES (%s, %s, %s, 1, 'ready', %s, clock_timestamp())""",
        (evidence_attempt_id, fixture["project"], brief_version_id, digest),
    )
    connection.execute(
        """INSERT INTO prompt_bundles
             (id, project_id, brief_version_id, evidence_pack_attempt_id,
              template_release_id, input_snapshot, storage_key, bundle_hash)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            bundle_id,
            fixture["project"],
            brief_version_id,
            evidence_attempt_id,
            fixture["release"],
            Jsonb({"legacy": True}),
            f"content-prompts/{bundle_id}.json",
            digest,
        ),
    )
    connection.execute(
        """INSERT INTO durable_jobs
             (id, project_id, kind, status, input_hash, idempotency_key,
              completed_at)
           VALUES (%s, %s, 'artifact.finalize', 'succeeded', %s, %s,
                   clock_timestamp())""",
        (artifact_job_id, fixture["project"], digest, f"legacy-artifact-{bundle_id}"),
    )
    connection.execute(
        """INSERT INTO artifact_finalize_outbox
             (project_id, job_id, resource_kind, resource_id, pending_uri,
              storage_key, final_uri, content_hash, status, finalized_at)
           VALUES (%s, %s, 'prompt_bundle', %s, %s, %s, %s, %s, 'finalized',
                   clock_timestamp())""",
        (
            fixture["project"],
            artifact_job_id,
            bundle_id,
            f"postgres://prompt_bundles/{bundle_id}/input_snapshot",
            f"content-prompts/{bundle_id}.json",
            f"s3://geo-test/content-prompts/{bundle_id}.json",
            digest,
        ),
    )
    connection.commit()
    return {
        "brief_version_id": brief_version_id,
        "bundle_id": bundle_id,
    }
