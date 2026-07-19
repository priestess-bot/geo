from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Mapping
from uuid import UUID

import psycopg

from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.placements.application import PlacementApplication
from geo_core.placements.domain import JobReference
from geo_core.placements.worker_composition import (
    MeasurementWindowHandler,
    PlacementWorkerDispatcher,
    PublicationVerificationHandler,
)
from geo_core.placements.worker_repository import PlacementWorkerRepository


def new_verification(
    application: PlacementApplication, **values: object
) -> tuple[UUID, JobReference]:
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
    submission = application.create_submission(
        project_id=values["project_id"],
        campaign_id=values["campaign_id"],
        publication_request_id=publication.id,
        submitted_url=f"https://reddit.com/{suffix}",
        provider_submission_id=None,
        idempotency_key=f"submission-{suffix}",
        submitted_by=values["owner_id"],
    )
    return submission.id, application.request_verification(
        project_id=values["project_id"],
        campaign_id=values["campaign_id"],
        submission_id=submission.id,
        idempotency_key=f"verification-{suffix}",
    )


def open_due_measurement(
    admin_url: str,
    *,
    store: PostgresDurableJobStore,
    repository: PlacementWorkerRepository,
    project_id: UUID,
    submission_id: UUID,
    offset: int,
) -> tuple[Mapping[str, object], UUID | None, UUID]:
    with psycopg.connect(admin_url) as admin:
        row = admin.execute(
            """SELECT spec.job_id, query.monitoring_query_id
               FROM measurement_job_specs spec
               JOIN measurement_job_queries query
                 ON query.job_id = spec.job_id AND query.project_id = spec.project_id
               WHERE spec.project_id = %s AND spec.submission_id = %s
                 AND spec.due_offset_days = %s
               ORDER BY query.monitoring_query_id LIMIT 1""",
            (project_id, submission_id, offset),
        ).fetchone()
        assert row is not None
        job_id, monitoring_query_id = row
        admin.execute(
            """UPDATE durable_jobs SET next_run_at = clock_timestamp()
               WHERE id = %s AND project_id = %s""",
            (job_id, project_id),
        )
        admin.commit()
    dispatcher = PlacementWorkerDispatcher(
        store=store,
        handlers={"placement.measure": MeasurementWindowHandler(repository)},
        worker_id=f"integration-measurement-{offset}",
        lease_for=timedelta(seconds=30),
    )
    result = dispatcher.process(job_id=job_id, project_id=project_id)
    with psycopg.connect(admin_url) as admin:
        task = admin.execute(
            """SELECT id FROM measurement_collection_tasks
               WHERE job_id = %s AND project_id = %s""",
            (job_id, project_id),
        ).fetchone()
    return result, task[0] if task is not None else None, monitoring_query_id


def verification_dispatcher(
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


def set_existing_verification_result(
    admin_url: str,
    *,
    project_id: UUID,
    submission_id: UUID,
    value: dict[str, str],
) -> None:
    with psycopg.connect(admin_url) as admin:
        admin.execute(
            """UPDATE publication_submissions SET verification_result = %s
               WHERE id = %s AND project_id = %s""",
            (psycopg.types.json.Jsonb(value), submission_id, project_id),
        )
        admin.commit()


def publication_request_id(
    admin_url: str, *, project_id: UUID, submission_id: UUID
) -> UUID:
    with psycopg.connect(admin_url) as admin:
        row = admin.execute(
            """SELECT publication_request_id FROM publication_submissions
               WHERE id = %s AND project_id = %s""",
            (submission_id, project_id),
        ).fetchone()
    assert row is not None
    return row[0]


def mark_submission_verifying(
    admin_url: str,
    *,
    project_id: UUID,
    submission_id: UUID,
    value: str,
) -> None:
    with psycopg.connect(admin_url) as admin:
        request_id = admin.execute(
            """UPDATE publication_submissions
               SET status = 'verifying', verification_result = %s
               WHERE id = %s AND project_id = %s
               RETURNING publication_request_id""",
            (
                psycopg.types.json.Jsonb({"existing": value}),
                submission_id,
                project_id,
            ),
        ).fetchone()[0]
        admin.execute(
            """UPDATE publication_requests SET status = 'publishing'
               WHERE id = %s AND project_id = %s""",
            (request_id, project_id),
        )
        admin.commit()


def make_job_due(admin_url: str, *, project_id: UUID, job_id: UUID) -> None:
    with psycopg.connect(admin_url) as admin:
        admin.execute(
            """UPDATE durable_jobs SET next_run_at = clock_timestamp()
               WHERE id = %s AND project_id = %s""",
            (job_id, project_id),
        )
        admin.commit()


def durable_job_state(admin_url: str, *, project_id: UUID, job_id: UUID) -> tuple[str, int]:
    with psycopg.connect(admin_url) as admin:
        row = admin.execute(
            """SELECT status, attempt_count FROM durable_jobs
               WHERE id = %s AND project_id = %s""",
            (job_id, project_id),
        ).fetchone()
    assert row is not None
    return row


def set_submission_status(
    admin_url: str, *, project_id: UUID, submission_id: UUID, status: str
) -> None:
    with psycopg.connect(admin_url) as admin:
        admin.execute(
            """UPDATE publication_submissions SET status = %s
               WHERE id = %s AND project_id = %s""",
            (status, submission_id, project_id),
        )
        admin.commit()


def process_with_measurement_job_locked(
    admin_url: str,
    *,
    dispatcher: PlacementWorkerDispatcher,
    project_id: UUID,
    submission_id: UUID,
    verification_job_id: UUID,
    offset: int,
) -> Mapping[str, object]:
    with psycopg.connect(admin_url) as lock_connection:
        measurement_job_id = lock_connection.execute(
            """SELECT job_id FROM measurement_job_specs
               WHERE project_id = %s AND submission_id = %s AND due_offset_days = %s
               FOR UPDATE""",
            (project_id, submission_id, offset),
        ).fetchone()[0]
        lock_connection.execute(
            """SELECT id FROM durable_jobs WHERE id = %s AND project_id = %s
               FOR UPDATE""",
            (measurement_job_id, project_id),
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                dispatcher.process,
                job_id=verification_job_id,
                project_id=project_id,
            )
            try:
                return future.result(timeout=5)
            finally:
                lock_connection.rollback()


def mark_newer_verification_active(
    admin_url: str, *, project_id: UUID, submission_id: UUID
) -> None:
    with psycopg.connect(admin_url) as admin:
        request_id = admin.execute(
            """UPDATE publication_submissions
               SET status = 'verifying',
                   verification_result = '{"existing":"newer-job"}'::jsonb
               WHERE id = %s AND project_id = %s
               RETURNING publication_request_id""",
            (submission_id, project_id),
        ).fetchone()[0]
        admin.execute(
            """UPDATE publication_requests SET status = 'publishing'
               WHERE id = %s AND project_id = %s""",
            (request_id, project_id),
        )
        admin.commit()


def terminalize_job_without_projection(
    admin_url: str, *, project_id: UUID, job_id: UUID
) -> None:
    with psycopg.connect(admin_url) as admin:
        admin.execute(
            """UPDATE durable_jobs
               SET status = 'dead_lettered', error_code = 'fixture_terminal',
                   completed_at = clock_timestamp(), updated_at = clock_timestamp()
               WHERE id = %s AND project_id = %s""",
            (job_id, project_id),
        )
        admin.commit()


def prepare_exhausted_verification_job(
    admin_url: str,
    *,
    project_id: UUID,
    job_id: UUID,
    submission_id: UUID,
) -> None:
    with psycopg.connect(admin_url) as admin:
        request_id = admin.execute(
            """UPDATE publication_submissions
               SET status = 'verifying',
                   verification_result = '{"existing":"claim-budget"}'::jsonb
               WHERE id = %s AND project_id = %s
               RETURNING publication_request_id""",
            (submission_id, project_id),
        ).fetchone()[0]
        admin.execute(
            """UPDATE publication_requests SET status = 'publishing'
               WHERE id = %s AND project_id = %s""",
            (request_id, project_id),
        )
        admin.execute(
            """UPDATE durable_jobs SET attempt_count = max_attempts,
                   next_run_at = clock_timestamp()
               WHERE id = %s AND project_id = %s""",
            (job_id, project_id),
        )
        admin.commit()


def verification_state(
    admin_url: str, project_id: UUID, job_id: UUID
) -> tuple[object, ...]:
    with psycopg.connect(admin_url) as admin:
        row = admin.execute(
            """SELECT job.status, submission.status, request.status,
                      submission.verification_result,
                      (SELECT count(*) FROM publication_verification_attempts attempt
                       WHERE attempt.project_id = job.project_id
                         AND attempt.job_id = job.id)
               FROM durable_jobs job
               JOIN verification_job_specs spec
                 ON spec.job_id = job.id AND spec.project_id = job.project_id
                AND spec.campaign_id = job.campaign_id
               JOIN publication_submissions submission
                 ON submission.id = spec.submission_id
                AND submission.project_id = spec.project_id
                AND submission.campaign_id = spec.campaign_id
                AND submission.opportunity_id = spec.opportunity_id
               JOIN publication_requests request
                 ON request.id = submission.publication_request_id
                AND request.project_id = submission.project_id
                AND request.campaign_id = submission.campaign_id
                AND request.opportunity_id = submission.opportunity_id
               WHERE job.id = %s AND job.project_id = %s""",
            (job_id, project_id),
        ).fetchone()
    assert row is not None
    return tuple(row)
