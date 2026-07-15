"""Destination policy versions and opportunity qualification persistence."""

from __future__ import annotations

import json
from typing import Any, Mapping
from uuid import UUID

from geo_core.placements.domain import (
    DestinationPolicyVersion,
    Opportunity,
    PlacementConflict,
    PlacementRuleViolation,
    transition_opportunity_status,
)


def _row(cursor: Any) -> dict[str, Any]:
    value = cursor.fetchone()
    if value is None:
        raise RuntimeError("expected PostgreSQL row was not returned")
    if isinstance(value, Mapping):
        return dict(value)
    return dict(zip((item.name for item in cursor.description), value, strict=True))


def _rows(cursor: Any) -> list[dict[str, Any]]:
    values = cursor.fetchall()
    if not values:
        return []
    if isinstance(values[0], Mapping):
        return [dict(value) for value in values]
    names = [item.name for item in cursor.description]
    return [dict(zip(names, value, strict=True)) for value in values]


class PostgresDestinationPolicyMixin:
    _db: Any

    def review_destination_policy(self, **values: Any) -> DestinationPolicyVersion:
        destination = _row(
            self._db.execute(
                """SELECT canonical_host FROM publication_destinations
                   WHERE id = %s AND project_id = %s FOR UPDATE""",
                (values["destination_id"], values["project_id"]),
            )
        )
        allowed_hosts = tuple(dict.fromkeys(value.casefold() for value in values["allowed_hosts"]))
        if destination["canonical_host"] not in allowed_hosts:
            raise PlacementRuleViolation(
                "policy allowed hosts must include the canonical destination host"
            )
        version_number = _row(
            self._db.execute(
                """SELECT COALESCE(MAX(version_number), 0) + 1 AS value
                   FROM destination_policy_versions WHERE destination_id = %s""",
                (values["destination_id"],),
            )
        )["value"]
        record = _row(
            self._db.execute(
                """INSERT INTO destination_policy_versions
                     (project_id, destination_id, version_number, status, rules,
                      identity_requirements, disclosure_requirements, allowed_hosts, reviewed_by)
                   VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s)
                   RETURNING id, project_id, destination_id, version_number, status, rules,
                     identity_requirements, disclosure_requirements, allowed_hosts,
                     reviewed_by, reviewed_at""",
                (
                    values["project_id"],
                    values["destination_id"],
                    version_number,
                    values["status"],
                    json.dumps(values["rules"]),
                    json.dumps(values["identity_requirements"]),
                    json.dumps(values["disclosure_requirements"]),
                    list(allowed_hosts),
                    values["reviewed_by"],
                ),
            )
        )
        self._db.execute(
            """UPDATE publication_destinations SET policy_status = %s, allowed_hosts = %s
               WHERE id = %s AND project_id = %s""",
            (
                values["status"],
                list(allowed_hosts),
                values["destination_id"],
                values["project_id"],
            ),
        )
        if values["status"] != "approved":
            self._db.execute(
                """UPDATE placement_opportunities
                   SET status = 'blocked', blocked_reason = 'destination_policy_not_eligible',
                       updated_at = clock_timestamp()
                   WHERE destination_id = %s AND project_id = %s
                     AND status NOT IN ('completed', 'cancelled')""",
                (values["destination_id"], values["project_id"]),
            )
        record["allowed_hosts"] = tuple(record["allowed_hosts"])
        return DestinationPolicyVersion(**record)

    def list_destination_policies(
        self, *, project_id: UUID, destination_id: UUID
    ) -> tuple[DestinationPolicyVersion, ...]:
        records = _rows(
            self._db.execute(
                """SELECT id, project_id, destination_id, version_number, status, rules,
                          identity_requirements, disclosure_requirements, allowed_hosts,
                          reviewed_by, reviewed_at
                   FROM destination_policy_versions
                   WHERE project_id = %s AND destination_id = %s ORDER BY version_number""",
                (project_id, destination_id),
            )
        )
        return tuple(
            DestinationPolicyVersion(**{**record, "allowed_hosts": tuple(record["allowed_hosts"])})
            for record in records
        )

    def transition_opportunity(
        self, *, project_id: UUID, opportunity_id: UUID, command: str, reason: str | None
    ) -> Opportunity:
        current = _row(
            self._db.execute(
                """SELECT o.id, o.project_id, o.campaign_id, o.destination_id,
                          o.opportunity_ref, o.rationale, o.status, d.policy_status
                   FROM placement_opportunities o JOIN publication_destinations d
                     ON d.id = o.destination_id AND d.project_id = o.project_id
                   WHERE o.id = %s AND o.project_id = %s FOR UPDATE OF o""",
                (opportunity_id, project_id),
            )
        )
        target = transition_opportunity_status(
            status=current["status"], command=command
        ).value
        if command == "qualify" and current["policy_status"] != "approved":
            raise PlacementConflict(
                "opportunity qualification requires approved destination policy"
            )
        blocked_reason = (reason or "manually_blocked") if target == "blocked" else None
        self._db.execute(
            """UPDATE placement_opportunities SET status = %s, blocked_reason = %s,
                 updated_at = clock_timestamp() WHERE id = %s AND project_id = %s""",
            (target, blocked_reason, opportunity_id, project_id),
        )
        current["status"] = target
        current.pop("policy_status")
        return Opportunity(**current)
