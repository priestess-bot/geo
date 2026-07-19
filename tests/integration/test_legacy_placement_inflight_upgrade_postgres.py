from __future__ import annotations

from datetime import timedelta
import os
from typing import Any, Mapping
from uuid import UUID, uuid4

from alembic import command
import psycopg
import pytest

from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.placements.application import PlacementApplication
from geo_core.placements.domain import (
    PlacementConflict,
    PlacementRuleViolation,
    canonical_hash,
)
from geo_core.placements.errors import PlacementContractMigrationRequired
from geo_core.placements.postgres_uow import placement_uow_factory
from geo_core.placements.worker_composition import (
    GenerationHandler,
    PlacementWorkerDispatcher,
    PublicationVerificationHandler,
)
from geo_core.placements.worker_repository import PlacementWorkerRepository
from tests.integration.legacy_placement_inflight_support import (
    CountingVerifier,
    UnexpectedGateway,
    bundle_snapshot,
    insert_approved_legacy_version,
    insert_legacy_job,
    package_snapshot,
    seed_existing_replay_result,
    seed_legacy_generation_jobs,
    set_publication_request_status,
)
from tests.integration.test_batch2_migrations_postgres import (
    _seed_legacy_fixture,
    _temporary_database,
)
from tests.integration.test_legacy_prompt_bundle_upgrade_postgres import (
    _seed_legacy_prompt_bundle,
)


ADMIN_URL = os.getenv("GEO_ACCESS_TEST_ADMIN_DATABASE_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not ADMIN_URL,
        reason="GEO_ACCESS_TEST_ADMIN_DATABASE_URL is required",
    ),
]


def test_legacy_generation_jobs_terminalize_with_rebuild_action_after_upgrade() -> None:
    with _temporary_database() as (database_url, configuration):
        command.upgrade(configuration, "0010_campaign_destinations")
        with psycopg.connect(database_url) as connection:
            fixture = _seed_legacy_fixture(connection)
            bundle = _seed_legacy_prompt_bundle(connection, fixture)
            jobs = seed_legacy_generation_jobs(connection, fixture, bundle)
            frozen_bundle = bundle_snapshot(connection, bundle["bundle_id"])

        command.upgrade(configuration, "head")
        application = PlacementApplication(
            placement_uow_factory(lambda: psycopg.connect(database_url))
        )
        assert (
            application.request_generation(
                project_id=fixture["project"],
                campaign_id=fixture["campaign"],
                prompt_bundle_id=bundle["bundle_id"],
                configured_model="deepseek-v4-flash",
                model_call_budget=1,
                idempotency_key="legacy-generation-queued",
                requested_by=fixture["owner"],
            ).id
            == jobs["queued"]
        )
        with psycopg.connect(database_url) as connection:
            generation_count_before_enqueue = connection.execute(
                """SELECT count(*) FROM durable_jobs
                   WHERE project_id = %s AND kind = 'placement.generate'""",
                (fixture["project"],),
            ).fetchone()[0]
        with pytest.raises(PlacementContractMigrationRequired) as raised_enqueue:
            application.request_generation(
                project_id=fixture["project"],
                campaign_id=fixture["campaign"],
                prompt_bundle_id=bundle["bundle_id"],
                configured_model="deepseek-v4-flash",
                model_call_budget=1,
                idempotency_key="must-not-enqueue-new-legacy-generation",
                requested_by=fixture["owner"],
            )
        assert raised_enqueue.value.error_code == "legacy_generation_enqueue_rebuild_required"
        with psycopg.connect(database_url) as connection:
            assert connection.execute(
                """SELECT count(*) FROM durable_jobs
                   WHERE project_id = %s AND kind = 'placement.generate'""",
                (fixture["project"],),
            ).fetchone() == (generation_count_before_enqueue,)
        store = PostgresDurableJobStore(lambda: psycopg.connect(database_url))
        repository = PlacementWorkerRepository(store)
        dispatcher = PlacementWorkerDispatcher(
            store=store,
            handlers={
                "placement.generate": GenerationHandler(
                    store=store,
                    repository=repository,
                    gateway=UnexpectedGateway(),
                    lease_for=timedelta(seconds=30),
                )
            },
            worker_id="legacy-generation-reconciler",
            lease_for=timedelta(seconds=30),
        )

        for job_id in jobs.values():
            assert (
                dispatcher.process(job_id=job_id, project_id=fixture["project"])["status"]
                == "failed"
            )
            assert (
                dispatcher.process(job_id=job_id, project_id=fixture["project"])["status"]
                == "terminal"
            )
        generation_replay_key = "existing-legacy-generation-replay"
        existing_generation_replay = seed_existing_replay_result(
            database_url,
            project_id=fixture["project"],
            source_job_id=jobs["queued"],
            actor_id=fixture["owner"],
            idempotency_key=generation_replay_key,
        )
        assert (
            application.replay_job(
                project_id=fixture["project"],
                campaign_id=fixture["campaign"],
                source_job_id=jobs["queued"],
                actor_id=fixture["owner"],
                idempotency_key=generation_replay_key,
            ).id
            == existing_generation_replay
        )
        with psycopg.connect(database_url) as connection:
            generation_job_count = connection.execute(
                "SELECT count(*) FROM durable_jobs WHERE project_id = %s",
                (fixture["project"],),
            ).fetchone()[0]
        with pytest.raises(PlacementContractMigrationRequired) as raised_generation:
            application.replay_job(
                project_id=fixture["project"],
                campaign_id=fixture["campaign"],
                source_job_id=jobs["queued"],
                actor_id=fixture["owner"],
                idempotency_key="must-not-clone-legacy-generation",
            )
        assert raised_generation.value.error_code == ("legacy_generation_replay_rebuild_required")
        assert "Opportunity-bound Prompt Bundle" in raised_generation.value.operator_action
        with psycopg.connect(database_url) as connection:
            assert connection.execute(
                "SELECT count(*) FROM durable_jobs WHERE project_id = %s",
                (fixture["project"],),
            ).fetchone() == (generation_job_count,)

        with psycopg.connect(database_url) as connection:
            rows = connection.execute(
                """SELECT id, status, attempt_count, error_code, error_detail
                   FROM durable_jobs WHERE id = ANY(%s) ORDER BY id""",
                (list(jobs.values()),),
            ).fetchall()
            assert len(rows) == 2
            expected_attempts = {
                jobs["queued"]: 1,
                jobs["expired_running"]: 2,
            }
            for job_id, status, attempt_count, error_code, detail in rows:
                assert status == "failed"
                assert attempt_count == expected_attempts[job_id]
                assert error_code == "legacy_prompt_bundle_rebuild_required"
                assert detail["classification"] == "migration_contract"
                assert "Opportunity-bound Prompt Bundle" in detail["operator_action"]
                assert "migration history" in detail["operator_action"]
            assert connection.execute(
                """SELECT job_id, call_number, status, request_hash
                   FROM model_call_logs WHERE job_id = ANY(%s)""",
                (list(jobs.values()),),
            ).fetchall() == [(jobs["expired_running"], 1, "reserved", "9" * 64)]
            assert connection.execute(
                """SELECT event_type FROM durable_job_events WHERE job_id = %s
                   ORDER BY created_at""",
                (jobs["expired_running"],),
            ).fetchall() == [("lease_reclaimed",), ("job_failed",)]
            assert bundle_snapshot(connection, bundle["bundle_id"]) == frozen_bundle


def test_legacy_verification_continues_only_with_explicit_frozen_contract() -> None:
    with _temporary_database() as (database_url, configuration):
        command.upgrade(configuration, "0010_campaign_destinations")
        with psycopg.connect(database_url) as connection:
            fixture = _seed_legacy_fixture(connection)
            bundle = _seed_legacy_prompt_bundle(connection, fixture)
            publications = _seed_legacy_publication_jobs(connection, fixture, bundle)
            frozen_versions = {
                name: package_snapshot(connection, version_id)
                for name, version_id in publications["versions"].items()
            }

        command.upgrade(configuration, "head")
        application = PlacementApplication(
            placement_uow_factory(lambda: psycopg.connect(database_url))
        )
        compatible_request_id = publications["requests"]["compatible"]["queued"]
        compatible_request_key = f"legacy-publication-compatible-queued-{compatible_request_id}"
        compatible_attempt = publications["request_attempts"]["compatible"]["queued"]
        assert (
            application.request_publication(
                project_id=fixture["project"],
                campaign_id=fixture["campaign"],
                version_id=publications["versions"]["compatible"],
                destination_id=fixture["destination"],
                requested_by=fixture["owner"],
                publication_attempt=compatible_attempt,
                idempotency_key=compatible_request_key,
                restricted_policy_acknowledged=False,
                policy_basis=None,
            ).id
            == compatible_request_id
        )
        with psycopg.connect(database_url) as connection:
            request_count = connection.execute(
                "SELECT count(*) FROM publication_requests WHERE project_id = %s",
                (fixture["project"],),
            ).fetchone()[0]
        with pytest.raises(PlacementRuleViolation, match="Opportunity-bound Prompt Bundle"):
            application.request_publication(
                project_id=fixture["project"],
                campaign_id=fixture["campaign"],
                version_id=publications["versions"]["compatible"],
                destination_id=fixture["destination"],
                requested_by=fixture["owner"],
                publication_attempt=99,
                idempotency_key="must-not-create-new-legacy-publication-request",
                restricted_policy_acknowledged=False,
                policy_basis=None,
            )
        with psycopg.connect(database_url) as connection:
            assert connection.execute(
                "SELECT count(*) FROM publication_requests WHERE project_id = %s",
                (fixture["project"],),
            ).fetchone() == (request_count,)
        replay_submission_id = publications["incompatible_submissions"][0]
        replay_request_id = publications["requests"]["incompatible"]["queued"]
        replay_values = {
            "project_id": fixture["project"],
            "campaign_id": fixture["campaign"],
            "publication_request_id": replay_request_id,
            "submitted_url": "https://example.test/incompatible/queued",
            "provider_submission_id": f"provider-{replay_submission_id}",
            "idempotency_key": f"legacy-submission-{replay_submission_id}",
            "submitted_by": fixture["owner"],
        }
        assert application.create_submission(**replay_values).id == replay_submission_id
        with pytest.raises(PlacementConflict, match="different payload"):
            application.create_submission(
                **{
                    **replay_values,
                    "submitted_url": "https://example.test/incompatible/changed",
                }
            )
        for request_status in ("blocked", "cancelled"):
            set_publication_request_status(database_url, replay_request_id, request_status)
            assert application.create_submission(**replay_values).id == replay_submission_id
            assert (
                application.backfill_submission_url(
                    project_id=fixture["project"],
                    campaign_id=fixture["campaign"],
                    submission_id=replay_submission_id,
                    submitted_url=replay_values["submitted_url"],
                    actor_id=fixture["owner"],
                ).id
                == replay_submission_id
            )
        set_publication_request_status(database_url, replay_request_id, "publishing")
        with psycopg.connect(database_url) as connection:
            submission_count = connection.execute(
                "SELECT count(*) FROM publication_submissions WHERE project_id = %s",
                (fixture["project"],),
            ).fetchone()[0]
        with pytest.raises(PlacementRuleViolation, match="Opportunity-bound Prompt Bundle"):
            application.create_submission(
                project_id=fixture["project"],
                campaign_id=fixture["campaign"],
                publication_request_id=publications["requests"]["compatible"]["queued"],
                submitted_url="https://example.test/compatible/new-after-upgrade",
                provider_submission_id="must-not-be-created",
                idempotency_key=f"blocked-legacy-submission-{uuid4()}",
                submitted_by=fixture["owner"],
            )
        with psycopg.connect(database_url) as connection:
            assert connection.execute(
                "SELECT count(*) FROM publication_submissions WHERE project_id = %s",
                (fixture["project"],),
            ).fetchone() == (submission_count,)

        first_post_upgrade_request = publications["requests"]["compatible"]["first_post_upgrade"]
        for request_status in ("blocked", "cancelled"):
            with psycopg.connect(database_url) as connection:
                connection.execute(
                    "UPDATE publication_requests SET status = %s WHERE id = %s",
                    (request_status, first_post_upgrade_request),
                )
                connection.commit()
            with pytest.raises(
                PlacementRuleViolation, match="blocked or cancelled publication requests"
            ):
                application.create_submission(
                    project_id=fixture["project"],
                    campaign_id=fixture["campaign"],
                    publication_request_id=first_post_upgrade_request,
                    submitted_url=f"https://example.test/{request_status}/new",
                    provider_submission_id=f"blocked-{request_status}",
                    idempotency_key=f"blocked-request-{request_status}-{uuid4()}",
                    submitted_by=fixture["owner"],
                )
        awaiting_submission = publications["compatible_submissions"][3]
        awaiting_request = publications["requests"]["compatible"]["awaiting_backfill"]
        for request_status in ("blocked", "cancelled"):
            with psycopg.connect(database_url) as connection:
                connection.execute(
                    "UPDATE publication_requests SET status = %s WHERE id = %s",
                    (request_status, awaiting_request),
                )
                connection.commit()
            with pytest.raises(
                PlacementRuleViolation, match="blocked or cancelled publication requests"
            ):
                application.backfill_submission_url(
                    project_id=fixture["project"],
                    campaign_id=fixture["campaign"],
                    submission_id=awaiting_submission,
                    submitted_url="https://example.test/compatible/backfill",
                    actor_id=fixture["owner"],
                )
        with psycopg.connect(database_url) as connection:
            connection.execute(
                """UPDATE publication_requests SET status = 'publishing'
                   WHERE id IN (%s, %s)""",
                (first_post_upgrade_request, awaiting_request),
            )
            connection.commit()

        compatible_queued_submission = publications["compatible_submissions"][0]
        compatible_queued_job = publications["compatible_jobs"]["queued"]
        for submission_status in ("blocked", "cancelled"):
            with psycopg.connect(database_url) as connection:
                connection.execute(
                    "UPDATE publication_submissions SET status = %s WHERE id = %s",
                    (submission_status, compatible_queued_submission),
                )
                connection.commit()
            assert (
                application.request_verification(
                    project_id=fixture["project"],
                    campaign_id=fixture["campaign"],
                    submission_id=compatible_queued_submission,
                    idempotency_key="legacy-verification-compatible-queued",
                ).id
                == compatible_queued_job
            )
            with pytest.raises(PlacementRuleViolation, match="blocked or cancelled submissions"):
                application.request_verification(
                    project_id=fixture["project"],
                    campaign_id=fixture["campaign"],
                    submission_id=compatible_queued_submission,
                    idempotency_key=f"new-key-while-{submission_status}",
                )
        with psycopg.connect(database_url) as connection:
            connection.execute(
                "UPDATE publication_submissions SET status = 'submitted' WHERE id = %s",
                (compatible_queued_submission,),
            )
            connection.commit()
        with pytest.raises(PlacementContractMigrationRequired) as raised_active:
            application.request_verification(
                project_id=fixture["project"],
                campaign_id=fixture["campaign"],
                submission_id=compatible_queued_submission,
                idempotency_key="different-active-verification-key",
            )
        assert raised_active.value.error_code == ("legacy_verification_enqueue_rebuild_required")
        first_post_upgrade_submission = publications["compatible_submissions"][2]
        first_post_upgrade_key = "legacy-verification-compatible-first-post-upgrade"
        with psycopg.connect(database_url) as connection:
            verification_job_count = connection.execute(
                """SELECT count(*) FROM durable_jobs
                   WHERE project_id = %s AND kind = 'publication.verify'""",
                (fixture["project"],),
            ).fetchone()[0]
        with pytest.raises(PlacementContractMigrationRequired) as raised_enqueue:
            application.request_verification(
                project_id=fixture["project"],
                campaign_id=fixture["campaign"],
                submission_id=first_post_upgrade_submission,
                idempotency_key=first_post_upgrade_key,
            )
        assert raised_enqueue.value.error_code == ("legacy_verification_enqueue_rebuild_required")
        with psycopg.connect(database_url) as connection:
            assert connection.execute(
                """SELECT count(*) FROM durable_jobs
                   WHERE project_id = %s AND kind = 'publication.verify'""",
                (fixture["project"],),
            ).fetchone() == (verification_job_count,)

        store = PostgresDurableJobStore(lambda: psycopg.connect(database_url))
        repository = PlacementWorkerRepository(store)
        verifier = CountingVerifier()
        dispatcher = PlacementWorkerDispatcher(
            store=store,
            handlers={
                "publication.verify": PublicationVerificationHandler(
                    store=store,
                    repository=repository,
                    verifier=verifier,
                    lease_for=timedelta(seconds=30),
                )
            },
            worker_id="legacy-publication-reconciler",
            lease_for=timedelta(seconds=30),
        )

        incompatible_jobs = publications["incompatible_jobs"]
        compatible_jobs = publications["compatible_jobs"]
        for job_id in incompatible_jobs.values():
            result = dispatcher.process(job_id=job_id, project_id=fixture["project"])
            assert result == {
                "status": "failed",
                "job_id": str(job_id),
                "error_code": "legacy_publication_contract_rebuild_required",
            }
        for job_id in compatible_jobs.values():
            assert (
                dispatcher.process(job_id=job_id, project_id=fixture["project"])["status"]
                == "verified"
            )

        assert verifier.calls == 2
        publication_replay_key = "existing-legacy-publication-replay"
        existing_publication_replay = seed_existing_replay_result(
            database_url,
            project_id=fixture["project"],
            source_job_id=compatible_queued_job,
            actor_id=fixture["owner"],
            idempotency_key=publication_replay_key,
        )
        assert (
            application.request_verification(
                project_id=fixture["project"],
                campaign_id=fixture["campaign"],
                submission_id=compatible_queued_submission,
                idempotency_key="legacy-verification-compatible-queued",
            ).id
            == compatible_queued_job
        )
        assert (
            application.replay_job(
                project_id=fixture["project"],
                campaign_id=fixture["campaign"],
                source_job_id=compatible_queued_job,
                actor_id=fixture["owner"],
                idempotency_key=publication_replay_key,
            ).id
            == existing_publication_replay
        )
        with psycopg.connect(database_url) as connection:
            publication_job_count = connection.execute(
                "SELECT count(*) FROM durable_jobs WHERE project_id = %s",
                (fixture["project"],),
            ).fetchone()[0]
        with pytest.raises(PlacementContractMigrationRequired) as raised_publication:
            application.replay_job(
                project_id=fixture["project"],
                campaign_id=fixture["campaign"],
                source_job_id=compatible_queued_job,
                actor_id=fixture["owner"],
                idempotency_key="must-not-clone-legacy-publication-verification",
            )
        assert raised_publication.value.error_code == ("legacy_publication_replay_rebuild_required")
        assert "reapprove" in raised_publication.value.operator_action
        with psycopg.connect(database_url) as connection:
            assert connection.execute(
                "SELECT count(*) FROM durable_jobs WHERE project_id = %s",
                (fixture["project"],),
            ).fetchone() == (publication_job_count,)
        all_job_ids = (*incompatible_jobs.values(), *compatible_jobs.values())
        for job_id in all_job_ids:
            assert (
                dispatcher.process(job_id=job_id, project_id=fixture["project"])["status"]
                == "terminal"
            )

        with psycopg.connect(database_url) as connection:
            states = {
                row[0]: row[1:]
                for row in connection.execute(
                    """SELECT id, status, attempt_count, error_code
                       FROM durable_jobs WHERE id = ANY(%s)""",
                    (list(all_job_ids),),
                ).fetchall()
            }
            for label, job_id in incompatible_jobs.items():
                assert states[job_id] == (
                    "failed",
                    2 if label == "expired_running" else 1,
                    "legacy_publication_contract_rebuild_required",
                )
            for label, job_id in compatible_jobs.items():
                assert states[job_id] == (
                    "succeeded",
                    2 if label == "expired_running" else 1,
                    None,
                )

            invalid_attempts = connection.execute(
                """SELECT job_id, outcome, error_code, failure_disposition
                   FROM publication_verification_attempts
                   WHERE job_id = ANY(%s) ORDER BY job_id""",
                (list(incompatible_jobs.values()),),
            ).fetchall()
            assert invalid_attempts == [
                (
                    job_id,
                    "permanent_error",
                    "legacy_publication_contract_rebuild_required",
                    "permanent",
                )
                for job_id in sorted(incompatible_jobs.values())
            ]
            for submission_id in publications["incompatible_submissions"]:
                projection_row = connection.execute(
                    """SELECT status, verification_result
                       FROM publication_submissions WHERE id = %s""",
                    (submission_id,),
                ).fetchone()
                assert projection_row is not None
                status, projection = projection_row
                assert status == "failed"
                assert projection == {"legacy_projection": True}
            for job_id in incompatible_jobs.values():
                detail = connection.execute(
                    "SELECT error_detail FROM durable_jobs WHERE id = %s", (job_id,)
                ).fetchone()[0]
                assert detail["error_code"] == ("legacy_publication_contract_rebuild_required")
                assert "required_disclosures" in detail["operator_action"]
                assert "migration history" in detail["operator_action"]
                assert "legacy_projection" not in str(detail)
            for submission_id in publications["compatible_submissions"][:2]:
                assert connection.execute(
                    """SELECT status, verification_result ->> 'outcome'
                       FROM publication_submissions WHERE id = %s""",
                    (submission_id,),
                ).fetchone() == ("verified", "passed")
            assert connection.execute(
                """SELECT status, verification_result
                   FROM publication_submissions WHERE id = %s""",
                (first_post_upgrade_submission,),
            ).fetchone() == ("submitted", {"legacy_projection": True})
            assert connection.execute(
                """SELECT status, submitted_url, verification_result
                   FROM publication_submissions WHERE id = %s""",
                (awaiting_submission,),
            ).fetchone() == ("awaiting_url", None, {"legacy_projection": True})
            for name, version_id in publications["versions"].items():
                assert package_snapshot(connection, version_id) == frozen_versions[name]
            assert connection.execute(
                """SELECT count(*) FROM durable_jobs WHERE id = ANY(%s)
                   AND status IN ('queued', 'running', 'finalizing', 'retry_wait')""",
                (list(all_job_ids),),
            ).fetchone() == (0,)


def _seed_legacy_publication_jobs(
    connection: psycopg.Connection[Any],
    fixture: Mapping[str, Any],
    bundle: Mapping[str, UUID],
) -> dict[str, Any]:
    reviewer_id = uuid4()
    package_id = uuid4()
    invalid_version_id = uuid4()
    compatible_version_id = uuid4()
    connection.execute(
        """INSERT INTO identities(id, issuer, subject, email)
           VALUES (%s, 'legacy-upgrade-test', %s, 'reviewer@example.invalid')""",
        (reviewer_id, str(reviewer_id)),
    )
    connection.execute(
        """UPDATE publication_destinations SET policy_status = 'approved'
           WHERE id = %s AND project_id = %s""",
        (fixture["destination"], fixture["project"]),
    )
    connection.execute(
        """INSERT INTO placement_packages(id, project_id, opportunity_id)
           VALUES (%s, %s, %s)""",
        (package_id, fixture["project"], fixture["opportunity"]),
    )
    invalid_content = {
        "disclosure": "Posted on behalf of the brand.",
        "cta_url": "https://brand.example/product",
    }
    compatible_content = {
        **invalid_content,
        "required_disclosures": ["Posted on behalf of the brand."],
        "expected_links": ["https://brand.example/product"],
    }
    insert_approved_legacy_version(
        connection,
        fixture=fixture,
        reviewer_id=reviewer_id,
        package_id=package_id,
        bundle_id=bundle["bundle_id"],
        version_id=invalid_version_id,
        version_number=1,
        base_version_id=None,
        content=invalid_content,
    )
    insert_approved_legacy_version(
        connection,
        fixture=fixture,
        reviewer_id=reviewer_id,
        package_id=package_id,
        bundle_id=bundle["bundle_id"],
        version_id=compatible_version_id,
        version_number=2,
        base_version_id=invalid_version_id,
        content=compatible_content,
    )

    incompatible_jobs: dict[str, UUID] = {}
    compatible_jobs: dict[str, UUID] = {}
    incompatible_submissions: list[UUID] = []
    compatible_submissions: list[UUID] = []
    requests: dict[str, dict[str, UUID]] = {
        "incompatible": {},
        "compatible": {},
    }
    request_attempts: dict[str, dict[str, int]] = {
        "incompatible": {},
        "compatible": {},
    }
    attempt = 0
    for contract, version_id, jobs, submissions in (
        ("incompatible", invalid_version_id, incompatible_jobs, incompatible_submissions),
        ("compatible", compatible_version_id, compatible_jobs, compatible_submissions),
    ):
        labels = (
            (
                "queued",
                "expired_running",
                "first_post_upgrade",
                "awaiting_backfill",
            )
            if contract == "compatible"
            else ("queued", "expired_running")
        )
        for label in labels:
            attempt += 1
            job_id = uuid4()
            request_id = uuid4()
            submission_id = uuid4()
            requests[contract][label] = request_id
            request_attempts[contract][label] = attempt
            submissions.append(submission_id)
            submitted_url = f"https://example.test/{contract}/{label}"
            if label == "awaiting_backfill":
                submitted_url = None
            provider_submission_id = f"provider-{submission_id}"
            submission_status = (
                "verifying"
                if label == "expired_running"
                else "awaiting_url"
                if label == "awaiting_backfill"
                else "submitted"
            )
            connection.execute(
                """INSERT INTO publication_requests
                     (id, project_id, package_version_id, destination_id,
                      publication_attempt, idempotency_key, status, requested_by)
                   VALUES (%s, %s, %s, %s, %s, %s, 'publishing', %s)""",
                (
                    request_id,
                    fixture["project"],
                    version_id,
                    fixture["destination"],
                    attempt,
                    f"legacy-publication-{contract}-{label}-{request_id}",
                    fixture["owner"],
                ),
            )
            connection.execute(
                """INSERT INTO publication_submissions
                     (id, project_id, publication_request_id, submitted_url,
                      provider_submission_id, status, submitted_at, idempotency_key,
                      payload_hash, submitted_by, verification_result)
                   VALUES (%s, %s, %s, %s, %s, %s, clock_timestamp(), %s, %s,
                           %s, '{"legacy_projection":true}'::jsonb)""",
                (
                    submission_id,
                    fixture["project"],
                    request_id,
                    submitted_url,
                    provider_submission_id,
                    submission_status,
                    f"legacy-submission-{submission_id}",
                    canonical_hash(
                        {
                            "campaign_id": str(fixture["campaign"]),
                            "publication_request_id": str(request_id),
                            "provider_submission_id": provider_submission_id,
                            "submitted_url": submitted_url,
                        }
                    ),
                    fixture["owner"],
                ),
            )
            if label not in {"first_post_upgrade", "awaiting_backfill"}:
                jobs[label] = job_id
                insert_legacy_job(
                    connection,
                    job_id=job_id,
                    project_id=fixture["project"],
                    kind="publication.verify",
                    label=f"legacy-verification-{contract}-{label}",
                    running=label == "expired_running",
                )
                connection.execute(
                    """INSERT INTO verification_job_specs(job_id, project_id, submission_id)
                       VALUES (%s, %s, %s)""",
                    (job_id, fixture["project"], submission_id),
                )
    connection.commit()
    return {
        "versions": {
            "incompatible": invalid_version_id,
            "compatible": compatible_version_id,
        },
        "incompatible_jobs": incompatible_jobs,
        "compatible_jobs": compatible_jobs,
        "incompatible_submissions": tuple(incompatible_submissions),
        "compatible_submissions": tuple(compatible_submissions),
        "requests": requests,
        "request_attempts": request_attempts,
    }
