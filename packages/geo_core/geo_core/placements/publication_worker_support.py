"""Publication verification projections and measurement-window persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from typing import Any, Mapping
from uuid import NAMESPACE_URL, UUID, uuid5

from geo_core.jobs.postgres import PostgresDurableJobStore, WorkerLease
from geo_core.placements.domain import canonical_hash


def row(cursor: Any) -> dict[str, Any] | None:
    value = cursor.fetchone()
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    return dict(zip((item.name for item in cursor.description), value, strict=True))


def rows(cursor: Any) -> list[dict[str, Any]]:
    values = cursor.fetchall()
    if not values:
        return []
    if isinstance(values[0], Mapping):
        return [dict(value) for value in values]
    names = [item.name for item in cursor.description]
    return [dict(zip(names, value, strict=True)) for value in values]


def content_fragments(rendered_text: str) -> tuple[str, ...]:
    candidates = [part.strip() for part in rendered_text.replace("\n", ". ").split(".")]
    useful = [part[:160] for part in candidates if len(part) >= 16]
    if useful:
        return tuple(useful[:3])
    normalized = rendered_text.strip()
    return (normalized[:160],) if normalized else ()


def open_measurement_window(
    store: PostgresDurableJobStore, lease: WorkerLease
) -> Mapping[str, object]:
    with store.fenced_transaction(lease) as connection:
        spec = row(
            connection.execute(
                """SELECT spec.submission_id, spec.campaign_id, spec.opportunity_id,
                          submission.destination_id, spec.protocol_id, spec.measurement_window,
                          submission.status AS submission_status, submission.verified_at,
                          due_offset_days, scheduled_for, market_profile_id,
                          locale, device, sample_size, expected_sample_count,
                          protocol_snapshot, protocol_hash
                   FROM measurement_job_specs spec
                   JOIN publication_submissions submission
                     ON submission.id = spec.submission_id
                    AND submission.project_id = spec.project_id
                    AND submission.campaign_id = spec.campaign_id
                    AND submission.opportunity_id = spec.opportunity_id
                   WHERE spec.job_id = %s AND spec.project_id = %s
                   FOR UPDATE OF submission""",
                (lease.job_id, lease.project_id),
            )
        )
        if spec is None:
            raise RuntimeError("measurement job specification does not exist")
        if spec["submission_status"] not in {"verified", "blocked", "cancelled"}:
            transient_details: dict[str, object] = {
                "status": "retry_wait",
                "reason": "submission_not_currently_verified",
                "submission_id": str(spec["submission_id"]),
            }
            store.defer_in_transaction(
                connection,
                lease,
                reason_code="submission_not_currently_verified",
                details=transient_details,
                retry_delay=timedelta(hours=6),
            )
            return transient_details
        if spec["submission_status"] != "verified" or spec["verified_at"] is None:
            skipped_details: dict[str, object] = {
                "status": "skipped",
                "reason": "submission_not_verified",
                "submission_id": str(spec["submission_id"]),
            }
            store.complete_in_transaction(
                connection,
                lease,
                result_ref=f"measurement-skipped:{spec['submission_id']}",
                details=skipped_details,
            )
            return skipped_details
        task = row(
            connection.execute(
                """INSERT INTO measurement_collection_tasks
                     (project_id, campaign_id, opportunity_id, destination_id,
                      job_id, submission_id, protocol_id,
                      measurement_window, expected_sample_count, scheduled_for)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (job_id) DO UPDATE SET job_id = EXCLUDED.job_id
                   RETURNING id""",
                (
                    lease.project_id, spec["campaign_id"], spec["opportunity_id"],
                    spec["destination_id"], lease.job_id, spec["submission_id"],
                    spec["protocol_id"], spec["measurement_window"],
                    spec["expected_sample_count"], spec["scheduled_for"],
                ),
            )
        )
        if task is None:
            raise RuntimeError("measurement collection task was not persisted")
        queries = connection.execute(
            """SELECT monitoring_query_id FROM measurement_job_queries
               WHERE job_id = %s AND project_id = %s ORDER BY monitoring_query_id""",
            (lease.job_id, lease.project_id),
        ).fetchall()
        details = {
            "status": "awaiting_manual_samples",
            "measurement_collection_task_id": str(task["id"]),
            "submission_id": str(spec["submission_id"]),
            "due_offset_days": spec["due_offset_days"],
            "scheduled_for": spec["scheduled_for"].isoformat(),
            "market_profile_id": str(spec["market_profile_id"]),
            "locale": spec["locale"],
            "device": spec["device"],
            "sample_size": spec["sample_size"],
            "protocol_snapshot": spec["protocol_snapshot"],
            "protocol_hash": spec["protocol_hash"],
            "monitoring_query_ids": [str(value[0]) for value in queries],
        }
        store.complete_in_transaction(
            connection,
            lease,
            result_ref=f"measurement-window:{lease.job_id}",
            details=details,
        )
        return details


def schedule_measurements(
    connection: Any,
    lease: WorkerLease,
    submission_id: UUID,
) -> int:
    protocols = rows(
        connection.execute(
            """SELECT protocol.id, s.campaign_id, s.opportunity_id, s.destination_id,
                      protocol.market_profile_id, protocol.locale,
                      protocol.device, protocol.sample_size, protocol.protocol_hash
               FROM publication_submissions s
               JOIN publication_requests r
                 ON r.id = s.publication_request_id AND r.project_id = s.project_id
               JOIN placement_package_versions v
                 ON v.id = r.package_version_id AND v.project_id = r.project_id
               JOIN placement_packages package
                 ON package.id = v.package_id AND package.project_id = v.project_id
               JOIN placement_opportunities o
                 ON o.id = package.opportunity_id AND o.project_id = package.project_id
               JOIN monitoring_protocols protocol
                 ON protocol.campaign_id = o.campaign_id
                AND protocol.project_id = o.project_id
               WHERE s.id = %s AND s.project_id = %s AND protocol.status = 'frozen'
               ORDER BY protocol.id""",
            (submission_id, lease.project_id),
        )
    )
    if not protocols:
        return 0
    verified_at = datetime.now(UTC)
    scheduled = 0
    for protocol in protocols:
        queries = rows(
            connection.execute(
                """SELECT monitoring_query_id AS id, query_text_snapshot AS query_text,
                          locale_snapshot AS locale
                   FROM monitoring_protocol_queries
                   WHERE project_id = %s AND protocol_id = %s ORDER BY ordinal""",
                (lease.project_id, protocol["id"]),
            )
        )
        if not queries:
            continue
        snapshot = {
            "version": "geo-measurement-v2", "protocol_id": str(protocol["id"]),
            "device": protocol["device"], "sample_size": protocol["sample_size"],
            "queries": [{"id": str(value["id"]), "text": value["query_text"],
                         "locale": value["locale"]} for value in queries],
        }
        expected = protocol["sample_size"] * len(queries)
        for offset in (28, 56, 84):
            window = f"t{offset}"
            job_id = uuid5(
                NAMESPACE_URL,
                f"geo-measurement:{submission_id}:{protocol['id']}:{window}",
            )
            scheduled_for = verified_at + timedelta(days=offset)
            if row(
                connection.execute(
                    """SELECT job_id FROM measurement_job_specs
                       WHERE project_id = %s AND submission_id = %s
                         AND protocol_id = %s AND measurement_window = %s""",
                    (lease.project_id, submission_id, protocol["id"], window),
                )
            ) is not None:
                continue
            connection.execute(
                """INSERT INTO durable_jobs
                     (id, project_id, campaign_id, kind, input_hash,
                      idempotency_key, next_run_at)
                   VALUES (%s, %s, %s, 'placement.measure', %s, %s, %s)
                   ON CONFLICT (id) DO NOTHING""",
                (job_id, lease.project_id, protocol["campaign_id"],
                 canonical_hash({"submission_id": str(submission_id),
                                 "protocol_id": str(protocol["id"]), "window": window}),
                 f"measurement:{submission_id}:{protocol['id']}:{window}", scheduled_for),
            )
            connection.execute(
                """INSERT INTO measurement_job_specs
                     (job_id, project_id, campaign_id, opportunity_id,
                      submission_id, protocol_id, measurement_window,
                      due_offset_days, scheduled_for, market_profile_id, locale, device,
                      sample_size, expected_sample_count, protocol_snapshot, protocol_hash)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s::jsonb, %s)
                   ON CONFLICT (job_id) DO NOTHING""",
                (job_id, lease.project_id, protocol["campaign_id"],
                 protocol["opportunity_id"], submission_id, protocol["id"], window, offset,
                 scheduled_for, protocol["market_profile_id"], protocol["locale"],
                 protocol["device"], protocol["sample_size"], expected,
                 json.dumps(snapshot), protocol["protocol_hash"]),
            )
            for query in queries:
                connection.execute(
                    """INSERT INTO measurement_job_queries
                         (job_id, project_id, monitoring_query_id)
                       VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
                    (job_id, lease.project_id, query["id"]),
                )
            connection.execute(
                """INSERT INTO broker_outbox
                     (project_id, job_id, topic, payload, idempotency_key, available_at)
                   VALUES (%s, %s, 'placement.measure', %s::jsonb, %s, %s)
                   ON CONFLICT (project_id, idempotency_key) DO NOTHING""",
                (lease.project_id, job_id,
                 json.dumps({"job_id": str(job_id), "project_id": str(lease.project_id),
                             "campaign_id": str(protocol["campaign_id"])}),
                 f"wake:placement.measure:{submission_id}:{protocol['id']}:{window}",
                 scheduled_for),
            )
            scheduled += 1
    return scheduled


def advance_generated_opportunity(connection: Any, project_id: UUID, package_id: UUID) -> None:
    connection.execute(
        """UPDATE placement_opportunities o SET status = 'in_progress',
             blocked_reason = NULL, updated_at = clock_timestamp()
           FROM placement_packages p
           WHERE p.id = %s AND p.project_id = %s
             AND o.id = p.opportunity_id AND o.project_id = p.project_id
             AND o.status = 'briefing'""",
        (package_id, project_id),
    )


def advance_verified_opportunity(
    connection: Any, project_id: UUID, submission_id: UUID
) -> None:
    connection.execute(
        """UPDATE placement_opportunities o SET status = 'completed',
             blocked_reason = NULL, updated_at = clock_timestamp()
           FROM publication_submissions s
           JOIN publication_requests r
             ON r.id = s.publication_request_id AND r.project_id = s.project_id
           JOIN placement_package_versions v
             ON v.id = r.package_version_id AND v.project_id = r.project_id
           JOIN placement_packages p ON p.id = v.package_id AND p.project_id = v.project_id
           WHERE s.id = %s AND s.project_id = %s
             AND o.id = p.opportunity_id AND o.project_id = p.project_id
             AND o.status = 'in_progress'""",
        (submission_id, project_id),
    )
