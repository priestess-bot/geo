from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

import psycopg
import pytest

from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.placements.application import PlacementApplication
from geo_core.placements.domain import (
    JobReference,
    PlacementConflict,
    PlacementNotFound,
    PlacementRuleViolation,
    canonical_hash,
)
from geo_core.placements.worker_composition import (
    PlacementWorkerDispatcher,
    PublicationVerificationHandler,
)
from geo_core.placements.worker_repository import PlacementWorkerRepository
from tests.integration.placement_worker_support import (
    ContentFailureVerifier,
    FakeVerifier,
    PermanentVerifier,
    RetryableVerifier,
)


def assert_legacy_publication_contract_rejected(
    application: PlacementApplication,
    *,
    admin_url: str,
    project_id: UUID,
    campaign_id: UUID,
    version_id: UUID,
    destination_id: UUID,
    owner_id: UUID,
    suffix: str,
) -> None:
    legacy_version_id = uuid4()
    legacy_content = {"body": "legacy"}
    legacy_rendered_text = "Legacy approved content"
    legacy_content_hash = canonical_hash(
        {
            "content_json": legacy_content,
            "rendered_text": legacy_rendered_text,
        }
    )
    with psycopg.connect(admin_url) as admin:
        source = admin.execute(
            """SELECT package_id, prompt_bundle_id, campaign_id,
                      opportunity_id, destination_id
               FROM placement_package_versions
               WHERE id = %s AND project_id = %s""",
            (version_id, project_id),
        ).fetchone()
        next_version = admin.execute(
            """SELECT max(version_number) + 1 FROM placement_package_versions
               WHERE package_id = %s AND project_id = %s""",
            (source[0], project_id),
        ).fetchone()[0]
        admin.execute("SET LOCAL session_replication_role = 'replica'")
        admin.execute(
            """INSERT INTO placement_package_versions
                 (id, project_id, campaign_id, opportunity_id, destination_id,
                  package_id, prompt_bundle_id, version_number, base_version_id,
                  workflow_status, content_json, rendered_text, content_hash,
                  edited_by, edit_reason)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                       'approved', %s::jsonb, %s, %s, %s,
                       'legacy publication contract fixture')""",
            (
                legacy_version_id,
                project_id,
                source[2],
                source[3],
                source[4],
                source[0],
                source[1],
                next_version,
                version_id,
                psycopg.types.json.Jsonb(legacy_content),
                legacy_rendered_text,
                legacy_content_hash,
                owner_id,
            ),
        )
        admin.execute("SET LOCAL session_replication_role = 'origin'")
        before = admin.execute(
            "SELECT count(*) FROM publication_requests WHERE project_id = %s",
            (project_id,),
        ).fetchone()[0]

    with pytest.raises(PlacementRuleViolation, match="required_disclosures"):
        application.request_publication(
            project_id=project_id,
            campaign_id=campaign_id,
            version_id=legacy_version_id,
            destination_id=destination_id,
            requested_by=owner_id,
            publication_attempt=99,
            idempotency_key=f"legacy-publication-{suffix}",
            restricted_policy_acknowledged=False,
            policy_basis=None,
        )

    with psycopg.connect(admin_url) as admin:
        assert admin.execute(
            "SELECT count(*) FROM publication_requests WHERE project_id = %s",
            (project_id,),
        ).fetchone()[0] == before
        admin.execute("SET LOCAL session_replication_role = 'replica'")
        admin.execute(
            "DELETE FROM placement_package_versions WHERE id = %s AND project_id = %s",
            (legacy_version_id, project_id),
        )
        admin.execute("SET LOCAL session_replication_role = 'origin'")


def exercise_invalid_submission_verification(
    application: PlacementApplication,
    store: PostgresDurableJobStore,
    repository: PlacementWorkerRepository,
    *,
    project_id: UUID,
    campaign_id: UUID,
    version_id: UUID,
    destination_id: UUID,
    owner_id: UUID,
    suffix: str,
) -> JobReference:
    connection = store.open_project(project_id)
    try:
        model_calls_before = connection.execute(
            "SELECT count(*) FROM model_call_logs WHERE project_id = %s",
            (project_id,),
        ).fetchone()[0]
        connection.commit()
    finally:
        connection.close()
    publication = application.request_publication(
        project_id=project_id,
        campaign_id=campaign_id,
        version_id=version_id,
        destination_id=destination_id,
        requested_by=owner_id,
        publication_attempt=2,
        idempotency_key=f"publication-{suffix}-0002",
        restricted_policy_acknowledged=False,
        policy_basis=None,
    )
    with pytest.raises(PlacementRuleViolation, match="destination HTTPS host"):
        application.create_submission(
            project_id=project_id,
            campaign_id=campaign_id,
            publication_request_id=publication.id,
            submitted_url="https://attacker.example/post",
            provider_submission_id=None,
            idempotency_key=f"submission-{suffix}-invalid-host",
            submitted_by=owner_id,
        )
    submission = application.create_submission(
        project_id=project_id,
        campaign_id=campaign_id,
        publication_request_id=publication.id,
        submitted_url=None,
        provider_submission_id=None,
        idempotency_key=f"submission-{suffix}-0002",
        submitted_by=owner_id,
    )
    with pytest.raises(PlacementRuleViolation, match="destination HTTPS host"):
        application.backfill_submission_url(
            project_id=project_id,
            campaign_id=campaign_id,
            submission_id=submission.id,
            submitted_url="https://attacker.example/post",
            actor_id=owner_id,
        )
    submission = application.backfill_submission_url(
        project_id=project_id,
        campaign_id=campaign_id,
        submission_id=submission.id,
        submitted_url="https://reddit.com/missing-post",
        actor_id=owner_id,
    )
    assert (
        application.backfill_submission_url(
            project_id=project_id,
            campaign_id=campaign_id,
            submission_id=submission.id,
            submitted_url="https://reddit.com/missing-post",
            actor_id=owner_id,
        ).submitted_url
        == submission.submitted_url
    )
    verification_job = application.request_verification(
        project_id=project_id,
        campaign_id=campaign_id,
        submission_id=submission.id,
        idempotency_key=f"verification-{suffix}-0002",
    )
    assert (
        application.request_verification(
            project_id=project_id,
            campaign_id=campaign_id,
            submission_id=submission.id,
            idempotency_key=f"verification-{suffix}-0002",
        ).id
        == verification_job.id
    )
    with pytest.raises(PlacementConflict, match="already active"):
        application.request_verification(
            project_id=project_id,
            campaign_id=campaign_id,
            submission_id=submission.id,
            idempotency_key=f"verification-{suffix}-0002-duplicate",
        )
    dispatcher = _verification_dispatcher(
        store, repository, PermanentVerifier(), worker_id="integration-invalid-url"
    )
    assert dispatcher.process(job_id=verification_job.id, project_id=project_id)["status"] == "failed"

    failed_submission, failed_job = _new_verification(
        application,
        project_id=project_id,
        campaign_id=campaign_id,
        version_id=version_id,
        destination_id=destination_id,
        owner_id=owner_id,
        suffix=f"{suffix}-content",
        publication_attempt=3,
    )
    failed_dispatcher = _verification_dispatcher(
        store, repository, ContentFailureVerifier(), worker_id="integration-content-failure"
    )
    assert failed_dispatcher.process(job_id=failed_job.id, project_id=project_id)["status"] == (
        "verification_failed"
    )
    retry_job = application.request_verification(
        project_id=project_id,
        campaign_id=campaign_id,
        submission_id=failed_submission,
        idempotency_key=f"verification-{suffix}-explicit-retry",
    )
    passed_dispatcher = _verification_dispatcher(
        store, repository, FakeVerifier(), worker_id="integration-explicit-retry"
    )
    assert passed_dispatcher.process(job_id=retry_job.id, project_id=project_id)["status"] == (
        "verified"
    )
    attempts = application.list_verification_attempts(
        project_id=project_id,
        campaign_id=campaign_id,
        submission_id=failed_submission,
    )
    assert [attempt.outcome for attempt in attempts] == ["passed", "failed"]
    assert attempts[0].verifier_version == "publication-url-verifier-v2"
    assert all(attempt.result_hash for attempt in attempts)

    retryable_submission, retryable_job = _new_verification(
        application,
        project_id=project_id,
        campaign_id=campaign_id,
        version_id=version_id,
        destination_id=destination_id,
        owner_id=owner_id,
        suffix=f"{suffix}-retryable",
        publication_attempt=4,
    )
    retryable_dispatcher = _verification_dispatcher(
        store, repository, RetryableVerifier(), worker_id="integration-retryable"
    )
    assert retryable_dispatcher.process(
        job_id=retryable_job.id, project_id=project_id
    )["status"] == "retry_wait"
    with pytest.raises(PlacementConflict, match="already active"):
        application.request_verification(
            project_id=project_id,
            campaign_id=campaign_id,
            submission_id=retryable_submission,
            idempotency_key=f"verification-{suffix}-retryable-duplicate",
        )

    legacy_submission = _new_submission(
        application,
        project_id=project_id,
        campaign_id=campaign_id,
        version_id=version_id,
        destination_id=destination_id,
        owner_id=owner_id,
        suffix=f"{suffix}-legacy",
        publication_attempt=5,
    )
    connection = store.open_project(project_id)
    try:
        connection.execute(
            """UPDATE publication_submissions
               SET verification_result = '{"legacy": true}'::jsonb
               WHERE id = %s AND project_id = %s""",
            (legacy_submission, project_id),
        )
        model_calls_after = connection.execute(
            "SELECT count(*) FROM model_call_logs WHERE project_id = %s",
            (project_id,),
        ).fetchone()[0]
        connection.commit()
    finally:
        connection.close()
    assert model_calls_after == model_calls_before
    assert application.list_verification_attempts(
        project_id=project_id,
        campaign_id=campaign_id,
        submission_id=legacy_submission,
    ) == ()
    assert application.get_submission(
        project_id=project_id,
        campaign_id=campaign_id,
        submission_id=legacy_submission,
    ).verification_result == {"legacy": True}
    with pytest.raises(PlacementNotFound):
        application.list_verification_attempts(
            project_id=project_id,
            campaign_id=uuid4(),
            submission_id=failed_submission,
        )
    outcomes = application.list_verification_attempts(
        project_id=project_id,
        campaign_id=campaign_id,
        submission_id=submission.id,
    ) + application.list_verification_attempts(
        project_id=project_id,
        campaign_id=campaign_id,
        submission_id=retryable_submission,
    ) + attempts
    assert {attempt.outcome for attempt in outcomes} == {
        "passed", "failed", "retryable_error", "permanent_error"
    }
    return verification_job


def _verification_dispatcher(
    store: PostgresDurableJobStore,
    repository: PlacementWorkerRepository,
    verifier: object,
    *,
    worker_id: str,
) -> PlacementWorkerDispatcher:
    return PlacementWorkerDispatcher(
        store=store,
        handlers={
            "publication.verify": PublicationVerificationHandler(
                store=store,
                repository=repository,
                verifier=verifier,
                lease_for=timedelta(seconds=30),
            )
        },
        worker_id=worker_id,
        lease_for=timedelta(seconds=30),
    )


def _new_verification(
    application: PlacementApplication,
    **values: object,
) -> tuple[UUID, JobReference]:
    submission_id = _new_submission(application, **values)
    suffix = str(values["suffix"])
    return submission_id, application.request_verification(
        project_id=values["project_id"],
        campaign_id=values["campaign_id"],
        submission_id=submission_id,
        idempotency_key=f"verification-{suffix}",
    )


def _new_submission(application: PlacementApplication, **values: object) -> UUID:
    suffix = str(values["suffix"])
    publication = application.request_publication(
        project_id=values["project_id"],
        campaign_id=values["campaign_id"],
        version_id=values["version_id"],
        destination_id=values["destination_id"],
        requested_by=values["owner_id"],
        publication_attempt=values["publication_attempt"],
        idempotency_key=f"publication-{suffix}",
        restricted_policy_acknowledged=False,
        policy_basis=None,
    )
    return application.create_submission(
        project_id=values["project_id"],
        campaign_id=values["campaign_id"],
        publication_request_id=publication.id,
        submitted_url=f"https://reddit.com/{suffix}",
        provider_submission_id=None,
        idempotency_key=f"submission-{suffix}",
        submitted_by=values["owner_id"],
    ).id


def assert_generation_call_log(admin_url: str, project_id: UUID, job_id: UUID) -> None:
    with psycopg.connect(admin_url) as admin:
        statuses = admin.execute(
            """SELECT array_agg(status ORDER BY created_at)
               FROM model_call_logs WHERE project_id = %s AND job_id = %s""",
            (project_id, job_id),
        ).fetchone()[0]
        assert statuses == ["reserved", "succeeded"]


def exercise_artifact_replay_context(
    application: PlacementApplication,
    *,
    admin_url: str,
    project_id: UUID,
    campaign_id: UUID,
    owner_id: UUID,
    artifact_job_id: UUID,
    suffix: str,
) -> None:
    with psycopg.connect(admin_url) as admin:
        admin.execute(
            """UPDATE artifact_finalize_outbox
               SET status = 'failed', final_uri = NULL, finalized_at = NULL,
                   last_error = 'resolver replay test'
               WHERE job_id = %s AND project_id = %s""",
            (artifact_job_id, project_id),
        )
        admin.commit()
    replay = application.replay_job(
        project_id=project_id,
        campaign_id=campaign_id,
        source_job_id=artifact_job_id,
        actor_id=owner_id,
        idempotency_key=f"artifact-replay-{suffix}",
    )
    assert application.list_job_events(
        project_id=project_id,
        campaign_id=campaign_id,
        job_id=artifact_job_id,
    )
    assert application.list_job_events(
        project_id=project_id,
        campaign_id=campaign_id,
        job_id=replay.id,
    )
    with pytest.raises(PlacementNotFound):
        application.list_job_events(
            project_id=project_id,
            campaign_id=uuid4(),
            job_id=artifact_job_id,
        )


def assert_worker_persistence(
    *,
    admin_url: str,
    project_id: UUID,
    evidence_job_id: UUID,
    submission_id: UUID,
    budget_job_id: UUID,
    replay_job_id: UUID,
    bundle_id: UUID,
    invalid_job_id: UUID,
) -> None:
    with psycopg.connect(admin_url) as admin:
        lease_reclaims = admin.execute(
            """SELECT count(*) FROM durable_job_events
               WHERE project_id = %s AND job_id = %s
                 AND event_type = 'lease_reclaimed'""",
            (project_id, evidence_job_id),
        ).fetchone()[0]
        assert lease_reclaims >= 1
        measurement_jobs = admin.execute(
            """SELECT count(*) FROM measurement_job_specs
               WHERE project_id = %s AND submission_id = %s""",
            (project_id, submission_id),
        ).fetchone()[0]
        assert measurement_jobs == 3
        measurements = admin.execute(
            """SELECT count(*) FROM placement_measurements
               WHERE project_id = %s AND submission_id = %s""",
            (project_id, submission_id),
        ).fetchone()[0]
        assert measurements == 0
        reserved_calls = admin.execute(
            """SELECT count(*) FROM model_call_logs
               WHERE project_id = %s AND job_id = %s AND status = 'reserved'""",
            (project_id, budget_job_id),
        ).fetchone()[0]
        assert reserved_calls == 2
        retryable_calls = admin.execute(
            """SELECT count(*) FROM model_call_logs
               WHERE project_id = %s AND job_id = %s AND status = 'failed'
                 AND error_classification = 'retryable'""",
            (project_id, budget_job_id),
        ).fetchone()[0]
        assert retryable_calls == 2
        replay_lineage = admin.execute(
            """SELECT j.parent_job_id, s.prompt_bundle_id,
                      EXISTS (SELECT 1 FROM broker_outbox o
                              WHERE o.project_id = j.project_id AND o.job_id = j.id)
               FROM durable_jobs j JOIN generation_job_specs s
                 ON s.job_id = j.id AND s.project_id = j.project_id
               WHERE j.id = %s AND j.project_id = %s""",
            (replay_job_id, project_id),
        ).fetchone()
        assert replay_lineage == (budget_job_id, bundle_id, True)
        invalid_state = admin.execute(
            """SELECT j.status, s.status, r.status, s.verification_result
               FROM durable_jobs j
               JOIN verification_job_specs spec ON spec.job_id = j.id
               JOIN publication_submissions s ON s.id = spec.submission_id
               JOIN publication_requests r ON r.id = s.publication_request_id
               WHERE j.id = %s AND j.project_id = %s""",
            (invalid_job_id, project_id),
        ).fetchone()
        assert invalid_state[:3] == ("failed", "failed", "failed")
        assert invalid_state[3]["accessibility"] is False
