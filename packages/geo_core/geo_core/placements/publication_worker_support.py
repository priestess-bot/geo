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


def string_values(value: object, *, key_hint: str) -> tuple[str, ...]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key_hint in str(key).casefold() and isinstance(child, str) and child.strip():
                found.append(child.strip())
            else:
                found.extend(string_values(child, key_hint=key_hint))
    elif isinstance(value, list):
        for child in value:
            found.extend(string_values(child, key_hint=key_hint))
    return tuple(dict.fromkeys(found))


def open_measurement_window(
    store: PostgresDurableJobStore, lease: WorkerLease
) -> Mapping[str, object]:
    with store.fenced_transaction(lease) as connection:
        spec = row(
            connection.execute(
                """SELECT submission_id, due_offset_days, scheduled_for,
                          market_profile_id, locale, device, sample_size,
                          protocol_snapshot, protocol_hash
                   FROM measurement_job_specs
                   WHERE job_id = %s AND project_id = %s""",
                (lease.job_id, lease.project_id),
            )
        )
        if spec is None:
            raise RuntimeError("measurement job specification does not exist")
        queries = connection.execute(
            """SELECT monitoring_query_id FROM measurement_job_queries
               WHERE job_id = %s AND project_id = %s ORDER BY monitoring_query_id""",
            (lease.job_id, lease.project_id),
        ).fetchall()
        details = {
            "status": "awaiting_manual_samples",
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
    queries = rows(
        connection.execute(
            """SELECT q.id, q.query_text, q.locale, c.market_profile_id
               FROM publication_submissions s
               JOIN publication_requests r
                 ON r.id = s.publication_request_id AND r.project_id = s.project_id
               JOIN placement_package_versions v
                 ON v.id = r.package_version_id AND v.project_id = r.project_id
               JOIN placement_packages p ON p.id = v.package_id AND p.project_id = v.project_id
               JOIN placement_opportunities o
                 ON o.id = p.opportunity_id AND o.project_id = p.project_id
               JOIN geo_campaigns c ON c.id = o.campaign_id AND c.project_id = o.project_id
               JOIN campaign_monitoring_queries cq
                 ON cq.campaign_id = c.id AND cq.project_id = c.project_id
               JOIN monitoring_queries q
                 ON q.id = cq.monitoring_query_id AND q.project_id = cq.project_id
               WHERE s.id = %s AND s.project_id = %s AND q.status = 'active'
               ORDER BY q.id""",
            (submission_id, lease.project_id),
        )
    )
    if not queries:
        return 0
    verified_at = datetime.now(UTC)
    protocol = {
        "version": "geo-measurement-v1",
        "device": "desktop",
        "sample_size": 3,
        "queries": [
            {"id": str(value["id"]), "text": value["query_text"], "locale": value["locale"]}
            for value in queries
        ],
    }
    protocol_hash = canonical_hash(protocol)
    locale = queries[0]["locale"] if len({value["locale"] for value in queries}) == 1 else "mixed"
    for offset in (28, 56, 84):
        job_id = uuid5(NAMESPACE_URL, f"geo-measurement:{submission_id}:{offset}")
        scheduled_for = verified_at + timedelta(days=offset)
        connection.execute(
            """INSERT INTO durable_jobs
                 (id, project_id, kind, input_hash, idempotency_key, next_run_at)
               VALUES (%s, %s, 'placement.measure', %s, %s, %s)
               ON CONFLICT (id) DO NOTHING""",
            (
                job_id,
                lease.project_id,
                canonical_hash({"submission_id": str(submission_id), "offset": offset}),
                f"measurement:{submission_id}:{offset}",
                scheduled_for,
            ),
        )
        connection.execute(
            """INSERT INTO measurement_job_specs
                 (job_id, project_id, submission_id, due_offset_days, scheduled_for,
                  market_profile_id, locale, device, sample_size,
                  protocol_snapshot, protocol_hash)
               VALUES (%s, %s, %s, %s, %s, %s, %s, 'desktop', 3, %s::jsonb, %s)
               ON CONFLICT (job_id) DO NOTHING""",
            (
                job_id,
                lease.project_id,
                submission_id,
                offset,
                scheduled_for,
                queries[0]["market_profile_id"],
                locale,
                json.dumps(protocol),
                protocol_hash,
            ),
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
            (
                lease.project_id,
                job_id,
                json.dumps({"job_id": str(job_id), "project_id": str(lease.project_id)}),
                f"wake:placement.measure:{submission_id}:{offset}",
                scheduled_for,
            ),
        )
    return 3
