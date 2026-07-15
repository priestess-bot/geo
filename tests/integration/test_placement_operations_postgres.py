from __future__ import annotations

from datetime import UTC, datetime
import os
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
import pytest

from geo_core.placements.application import PlacementApplication
from geo_core.placements.domain import PlacementConflict
from geo_core.placements.postgres_uow import placement_uow_factory
from tests.integration.placement_worker_support import (
    cleanup_projects,
    login_url,
    seed_frozen_protocol,
    seed_project,
)


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()


@pytest.mark.integration
@pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required")
def test_submission_idempotency_and_measurement_task_completion() -> None:
    suffix = uuid4().hex[:10]
    app_login, app_password = f"geo_app_ops_{suffix}", uuid4().hex
    worker_login = f"geo_worker_ops_{suffix}"
    seeded: dict[str, UUID]
    ids = {name: uuid4() for name in (
        "destination", "campaign", "opportunity", "package", "version",
        "publication", "query", "job", "task",
    )}
    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
            sql.Identifier(app_login), sql.Literal(app_password)
        ))
        admin.execute(sql.SQL("CREATE ROLE {} IN ROLE geo_worker").format(
            sql.Identifier(worker_login)
        ))
        seeded = seed_project(admin, suffix=f"ops-{suffix}")
        _seed_publication_lineage(admin, seeded, ids)
        protocol_id = seed_frozen_protocol(
            admin, project_id=seeded["project"], campaign_id=ids["campaign"],
            market_profile_id=seeded["market"], monitoring_query_id=ids["query"],
            actor_id=seeded["owner"],
        )
        admin.commit()
    app = PlacementApplication(placement_uow_factory(lambda: psycopg.connect(
        login_url(ADMIN_URL, user=app_login, password=app_password)
    )))
    try:
        values = dict(
            project_id=seeded["project"], publication_request_id=ids["publication"],
            submitted_url="https://reddit.com/ops-test", provider_submission_id=None,
            idempotency_key=f"submission-ops-{suffix}", submitted_by=seeded["owner"],
        )
        first = app.create_submission(**values)
        replay = app.create_submission(**values)
        assert replay.id == first.id
        assert replay.submitted_by == seeded["owner"]
        with pytest.raises(PlacementConflict, match="different payload"):
            app.create_submission(**{**values, "submitted_url": "https://reddit.com/changed"})
        with psycopg.connect(ADMIN_URL) as admin:
            _seed_measurement_task(admin, seeded, ids, protocol_id, first.id)
            admin.commit()

        tasks = app.list_measurement_collection_tasks(project_id=seeded["project"])
        assert len(tasks) == 1 and tasks[0].status == "open"
        with pytest.raises(PlacementConflict, match="samples are incomplete"):
            app.complete_measurement_collection_task(
                project_id=seeded["project"], task_id=ids["task"],
                actor_id=seeded["owner"],
            )
        with psycopg.connect(ADMIN_URL) as admin:
            _insert_observation(admin, seeded, ids, protocol_id)
            with pytest.raises(psycopg.errors.CheckViolation):
                admin.execute(
                    "UPDATE placement_opportunities SET status = 'qualified' WHERE id = %s",
                    (ids["opportunity"],),
                )
            admin.rollback()
            _insert_observation(admin, seeded, ids, protocol_id)
            admin.commit()
        completed = app.complete_measurement_collection_task(
            project_id=seeded["project"], task_id=ids["task"], actor_id=seeded["owner"]
        )
        assert completed.status == "completed" and completed.actual_sample_count == 1
    finally:
        with psycopg.connect(ADMIN_URL) as admin:
            cleanup_projects(
                admin, projects=[seeded], tenant_ids=[seeded["tenant"]],
                app_login=app_login, worker_login=worker_login,
            )
            admin.commit()


def _seed_publication_lineage(connection, seeded: dict[str, UUID], ids: dict[str, UUID]) -> None:
    project, owner = seeded["project"], seeded["owner"]
    connection.execute(
        """INSERT INTO publication_destinations
             (id, project_id, publication_channel, destination_key, canonical_url,
              canonical_host, allowed_hosts, policy_status)
           VALUES (%s, %s, 'reddit', 'r/ops', 'https://reddit.com',
                   'reddit.com', ARRAY['reddit.com'], 'approved')""",
        (ids["destination"], project),
    )
    connection.execute(
        """INSERT INTO geo_campaigns
             (id, project_id, market_profile_id, primary_product_entity_id, name, created_by)
           VALUES (%s, %s, %s, %s, 'Operations integration', %s)""",
        (ids["campaign"], project, seeded["market"], seeded["entity"], owner),
    )
    connection.execute(
        """INSERT INTO monitoring_queries
             (id, project_id, market_profile_id, query_text, query_kind, locale)
           VALUES (%s, %s, %s, 'best robot vacuum', 'recommendation', 'en-AU')""",
        (ids["query"], project, seeded["market"]),
    )
    connection.execute(
        """INSERT INTO placement_opportunities
             (id, project_id, campaign_id, destination_id, opportunity_ref, rationale, status)
           VALUES (%s, %s, %s, %s, 'destination:ops', 'integration', 'in_progress')""",
        (ids["opportunity"], project, ids["campaign"], ids["destination"]),
    )
    connection.execute(
        "INSERT INTO placement_packages(id, project_id, opportunity_id) VALUES (%s, %s, %s)",
        (ids["package"], project, ids["opportunity"]),
    )
    connection.execute("SET LOCAL session_replication_role = replica")
    connection.execute(
        """INSERT INTO placement_package_versions
             (id, project_id, package_id, prompt_bundle_id, version_number,
              workflow_status, content_json, rendered_text, content_hash, edited_by, edit_reason)
           VALUES (%s, %s, %s, %s, 1, 'approved', '{}'::jsonb, 'approved copy',
                   %s, %s, 'integration seed')""",
        (ids["version"], project, ids["package"], uuid4(), "a" * 64, owner),
    )
    connection.execute(
        """INSERT INTO publication_requests
             (id, project_id, package_version_id, destination_id, requested_by,
              idempotency_key)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (ids["publication"], project, ids["version"], ids["destination"], owner,
         f"publication-ops-{ids['publication']}"),
    )
    connection.execute("SET LOCAL session_replication_role = origin")


def _seed_measurement_task(
    connection,
    seeded: dict[str, UUID],
    ids: dict[str, UUID],
    protocol_id: UUID,
    submission_id: UUID,
) -> None:
    project = seeded["project"]
    connection.execute(
        """INSERT INTO durable_jobs(id, project_id, kind, input_hash, idempotency_key)
           VALUES (%s, %s, 'placement.measure', %s, %s)""",
        (ids["job"], project, "b" * 64, f"measurement-ops-{ids['job']}"),
    )
    connection.execute(
        """INSERT INTO measurement_collection_tasks
             (id, project_id, job_id, submission_id, protocol_id,
              measurement_window, expected_sample_count, scheduled_for)
           VALUES (%s, %s, %s, %s, %s, 't28', 1, clock_timestamp())""",
        (ids["task"], project, ids["job"], submission_id, protocol_id),
    )


def _insert_observation(
    connection, seeded: dict[str, UUID], ids: dict[str, UUID], protocol_id: UUID
) -> None:
    connection.execute(
        """INSERT INTO monitoring_observations
             (project_id, protocol_id, campaign_id, monitoring_query_id,
              measurement_window, sample_index, result_status, eligible,
              url_verification_status, configured_model, ui_surface, observed_at,
              imported_by, idempotency_key, payload_hash)
           VALUES (%s, %s, %s, %s, 't28', 1, 'succeeded', true, 'unknown',
                   'integration', 'api', %s, %s, %s, %s)
           ON CONFLICT (project_id, idempotency_key) DO NOTHING""",
        (seeded["project"], protocol_id, ids["campaign"], ids["query"],
         datetime.now(UTC), seeded["owner"], f"observation-{ids['task']}", "c" * 64),
    )
