"""Terminal publication-verification status reconciliation."""

from __future__ import annotations

from typing import Any, Mapping
from uuid import UUID

from geo_core.jobs.postgres import PostgresDurableJobStore


_REQUEST_PROJECTION_STATUSES = {
    "publishing",
    "retrying",
    "published",
    "failed",
    "cancelled",
}


def publication_verification_job_owns_projection(
    connection: Any,
    *,
    job_id: UUID,
    project_id: UUID,
    campaign_id: UUID,
    opportunity_id: UUID,
    submission_id: UUID,
) -> bool:
    record = _row(
        connection.execute(
            """SELECT NOT EXISTS (
                     SELECT 1
                     FROM verification_job_specs newer_spec
                     JOIN durable_jobs newer
                       ON newer.id = newer_spec.job_id
                      AND newer.project_id = newer_spec.project_id
                      AND newer.campaign_id = newer_spec.campaign_id
                     WHERE newer_spec.project_id = current.project_id
                       AND newer_spec.campaign_id = current.campaign_id
                       AND newer_spec.opportunity_id = current_spec.opportunity_id
                       AND newer_spec.submission_id = current_spec.submission_id
                       AND (newer.created_at, newer.id) >
                           (current.created_at, current.id)
                   ) AS owns_projection
               FROM durable_jobs current
               JOIN verification_job_specs current_spec
                 ON current_spec.job_id = current.id
                AND current_spec.project_id = current.project_id
                AND current_spec.campaign_id = current.campaign_id
               WHERE current.id = %s AND current.project_id = %s
                 AND current.campaign_id = %s
                 AND current_spec.opportunity_id = %s
                 AND current_spec.submission_id = %s""",
            (job_id, project_id, campaign_id, opportunity_id, submission_id),
        )
    )
    if record is None:
        raise RuntimeError("publication verification job context disappeared")
    return bool(record["owns_projection"])


def update_publication_request_projection(
    connection: Any,
    *,
    project_id: UUID,
    campaign_id: UUID,
    opportunity_id: UUID,
    publication_request_id: UUID,
    submission_id: UUID,
    target_status: str,
) -> None:
    """Apply a submission result without overriding stronger request ownership."""
    if target_status not in _REQUEST_PROJECTION_STATUSES:
        raise ValueError("unsupported publication request projection status")
    request = _row(
        connection.execute(
            """SELECT status FROM publication_requests
               WHERE id = %s AND project_id = %s AND campaign_id = %s
                 AND opportunity_id = %s
               FOR UPDATE""",
            (publication_request_id, project_id, campaign_id, opportunity_id),
        )
    )
    if request is None:
        raise RuntimeError("publication verification request context disappeared")
    connection.execute(
        """UPDATE publication_requests request SET status = %s
           WHERE request.id = %s AND request.project_id = %s
             AND request.campaign_id = %s AND request.opportunity_id = %s
             AND request.status NOT IN ('blocked', 'cancelled')
             AND (
               %s = 'published'
               OR (%s = 'publishing' AND NOT EXISTS (
                 SELECT 1 FROM publication_submissions other
                 WHERE other.publication_request_id = request.id
                   AND other.project_id = request.project_id
                   AND other.campaign_id = request.campaign_id
                   AND other.opportunity_id = request.opportunity_id
                   AND other.status = 'verified'
               ))
               OR (%s NOT IN ('publishing', 'published') AND NOT EXISTS (
                 SELECT 1 FROM publication_submissions other
                 WHERE other.publication_request_id = request.id
                   AND other.project_id = request.project_id
                   AND other.campaign_id = request.campaign_id
                   AND other.opportunity_id = request.opportunity_id
                   AND (other.id <> %s OR other.status = 'verified')
                   AND other.status IN
                       ('awaiting_url', 'submitted', 'verifying', 'verified')
               ))
             )""",
        (
            target_status,
            publication_request_id,
            project_id,
            campaign_id,
            opportunity_id,
            target_status,
            target_status,
            target_status,
            submission_id,
        ),
    )


def reconcile_terminal_publication_verification(
    store: PostgresDurableJobStore, *, job_id: UUID, project_id: UUID
) -> None:
    connection = store.open_project(project_id)
    try:
        reconcile_terminal_publication_verification_in_transaction(
            connection, job_id=job_id, project_id=project_id
        )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def reconcile_terminal_publication_verification_in_transaction(
    connection: Any, *, job_id: UUID, project_id: UUID
) -> None:
    """Project a terminal verification job without rewriting attempt evidence."""

    record = _row(
        connection.execute(
            """SELECT job.status AS job_status,
                      job.campaign_id, spec.opportunity_id, spec.submission_id,
                      submission.publication_request_id,
                      submission.status AS submission_status
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
               WHERE job.id = %s AND job.project_id = %s
                 AND job.kind = 'publication.verify'
               FOR UPDATE OF job, submission, request""",
            (job_id, project_id),
        )
    )
    if record is None or record["job_status"] not in {
        "cancelled",
        "dead_lettered",
        "failed",
    }:
        return
    if record["submission_status"] == "verified":
        return
    if not publication_verification_job_owns_projection(
        connection,
        job_id=job_id,
        project_id=project_id,
        campaign_id=record["campaign_id"],
        opportunity_id=record["opportunity_id"],
        submission_id=record["submission_id"],
    ):
        return
    terminal_status = "cancelled" if record["job_status"] == "cancelled" else "failed"
    connection.execute(
        """UPDATE publication_submissions SET status = %s
           WHERE id = %s AND project_id = %s AND campaign_id = %s
             AND opportunity_id = %s
             AND status IN ('awaiting_url', 'submitted', 'verifying')""",
        (
            terminal_status,
            record["submission_id"],
            project_id,
            record["campaign_id"],
            record["opportunity_id"],
        ),
    )
    update_publication_request_projection(
        connection,
        project_id=project_id,
        campaign_id=record["campaign_id"],
        opportunity_id=record["opportunity_id"],
        publication_request_id=record["publication_request_id"],
        submission_id=record["submission_id"],
        target_status=terminal_status,
    )


def _row(cursor: Any) -> dict[str, Any] | None:
    value = cursor.fetchone()
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    return dict(zip((item.name for item in cursor.description), value, strict=True))
