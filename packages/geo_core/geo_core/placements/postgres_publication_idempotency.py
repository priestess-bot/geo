"""Idempotent replay lookups for publication request and submission writes."""

from __future__ import annotations

from typing import Any, Mapping
from uuid import UUID

from geo_core.placements.domain import PlacementConflict


def find_submission_replay(
    db: Any,
    *,
    project_id: UUID,
    idempotency_key: str,
    payload_hash: str,
) -> dict[str, Any] | None:
    existing = _optional_row(
        db.execute(
            """SELECT id, project_id, campaign_id, opportunity_id, destination_id,
                      publication_request_id, status, submitted_url,
                      provider_submission_id, verification_result,
                      url_backfilled_by, url_backfilled_at, idempotency_key,
                      submitted_by, payload_hash
               FROM publication_submissions
               WHERE project_id = %s AND idempotency_key = %s""",
            (project_id, idempotency_key),
        )
    )
    if existing is None:
        return None
    if existing.pop("payload_hash") != payload_hash:
        raise PlacementConflict(
            "submission idempotency key was already used with a different payload"
        )
    return existing


def find_publication_request_replay(db: Any, values: Mapping[str, Any]) -> dict[str, Any] | None:
    existing = _optional_row(
        db.execute(
            """SELECT request.id, request.project_id, request.campaign_id,
                      request.opportunity_id, request.package_version_id,
                      request.destination_id, request.publication_attempt,
                      request.idempotency_key, request.restricted_policy_acknowledged,
                      request.policy_basis, request.status, destination.publication_channel,
                      destination.destination_key
               FROM publication_requests request
               JOIN publication_destinations destination
                 ON destination.id = request.destination_id
                AND destination.project_id = request.project_id
               WHERE request.project_id = %s AND request.idempotency_key = %s""",
            (values["project_id"], values["idempotency_key"]),
        )
    )
    if existing is None:
        return None
    if (
        existing["package_version_id"] != values["version_id"]
        or existing["destination_id"] != values["destination_id"]
        or existing["publication_attempt"] != values["publication_attempt"]
    ):
        raise PlacementConflict("publication idempotency key was already used with different input")
    return existing


def _optional_row(cursor: Any) -> dict[str, Any] | None:
    row = cursor.fetchone()
    if row is None:
        return None
    if isinstance(row, Mapping):
        return dict(row)
    return dict(zip((item.name for item in cursor.description), row, strict=True))
