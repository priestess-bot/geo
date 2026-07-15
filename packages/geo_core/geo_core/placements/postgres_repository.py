"""PostgreSQL adapter for placement application commands and queries."""

from __future__ import annotations

import json
from typing import Any, Mapping
from uuid import NAMESPACE_URL, UUID, uuid5

from geo_core.placements.domain import (
    BriefVersion,
    Campaign,
    Claim,
    Destination,
    EvidencePackAttempt,
    JobReference,
    MonitoringQuery,
    Opportunity,
    PackageVersion,
    PlacementConflict,
    WorkflowStatus,
    canonical_hash,
)
from geo_core.placements.postgres_prompts import PostgresPromptRepositoryMixin
from geo_core.placements.postgres_policy import PostgresDestinationPolicyMixin
from geo_core.placements.postgres_job_control import PostgresJobControlMixin
from geo_core.placements.postgres_package_versions import PostgresPackageVersionMixin
from geo_core.placements.postgres_measurement_tasks import PostgresMeasurementTaskMixin
from geo_core.placements.postgres_review_publication import PostgresReviewPublicationMixin


def _row(cursor: Any) -> dict[str, Any]:
    record = cursor.fetchone()
    if record is None:
        raise RuntimeError("expected PostgreSQL row was not returned")
    if isinstance(record, Mapping):
        return dict(record)
    names = [item.name for item in cursor.description]
    return dict(zip(names, record, strict=True))


def _rows(cursor: Any) -> list[dict[str, Any]]:
    records = cursor.fetchall()
    if not records:
        return []
    if isinstance(records[0], Mapping):
        return [dict(record) for record in records]
    names = [item.name for item in cursor.description]
    return [dict(zip(names, record, strict=True)) for record in records]


def _campaign(value: Mapping[str, Any]) -> Campaign:
    return Campaign(**{key: value[key] for key in Campaign.__dataclass_fields__})


def _destination(value: Mapping[str, Any]) -> Destination:
    return Destination(
        id=value["id"],
        project_id=value["project_id"],
        publication_channel=value["publication_channel"],
        destination_key=value["destination_key"],
        operation_mode=value["operation_mode"],
        destination_account_id=value.get("destination_account_id"),
        canonical_url=value.get("canonical_url"),
        canonical_host=value["canonical_host"],
        allowed_hosts=tuple(value["allowed_hosts"]),
        policy_status=value["policy_status"],
    )


def _opportunity(value: Mapping[str, Any]) -> Opportunity:
    return Opportunity(**{key: value[key] for key in Opportunity.__dataclass_fields__})


def _brief(value: Mapping[str, Any]) -> BriefVersion:
    return BriefVersion(
        id=value["id"],
        project_id=value["project_id"],
        brief_id=value["brief_id"],
        version_number=value["version_number"],
        base_version_id=value.get("base_version_id"),
        goals=value["goals"],
        constraints=value["constraints"],
        content_hash=value["content_hash"],
    )


def _package(value: Mapping[str, Any]) -> PackageVersion:
    return PackageVersion(
        id=value["id"],
        project_id=value["project_id"],
        package_id=value["package_id"],
        prompt_bundle_id=value["prompt_bundle_id"],
        version_number=value["version_number"],
        base_version_id=value.get("base_version_id"),
        workflow_status=WorkflowStatus(value["workflow_status"]),
        content_json=value["content_json"],
        rendered_text=value["rendered_text"],
        content_hash=value["content_hash"],
        edited_by=value.get("edited_by"),
        edit_reason=value.get("edit_reason"),
        generated_by_job_id=value.get("generated_by_job_id"),
    )


class PsycopgPlacementRepository(
    PostgresMeasurementTaskMixin,
    PostgresPromptRepositoryMixin,
    PostgresPackageVersionMixin,
    PostgresReviewPublicationMixin,
    PostgresJobControlMixin,
    PostgresDestinationPolicyMixin,
):
    def __init__(self, connection: Any) -> None:
        self._db = connection

    def create_campaign(self, **values: Any) -> Campaign:
        result = _row(
            self._db.execute(
                """
                INSERT INTO geo_campaigns
                  (project_id, market_profile_id, primary_product_entity_id,
                   name, objective, created_by)
                VALUES (%(project_id)s, %(market_profile_id)s, %(primary_product_entity_id)s,
                        %(name)s, %(objective)s, %(actor_id)s)
                RETURNING id, project_id, market_profile_id, primary_product_entity_id,
                          name, objective, status
                """,
                values,
            )
        )
        return _campaign(result)

    def list_campaigns(self, *, project_id: UUID) -> tuple[Campaign, ...]:
        records = _rows(
            self._db.execute(
                """SELECT id, project_id, market_profile_id, primary_product_entity_id,
                          name, objective, status FROM geo_campaigns
                   WHERE project_id = %s ORDER BY created_at DESC""",
                (project_id,),
            )
        )
        return tuple(_campaign(item) for item in records)

    def get_campaign(self, *, project_id: UUID, campaign_id: UUID) -> Campaign | None:
        cursor = self._db.execute(
            """SELECT id, project_id, market_profile_id, primary_product_entity_id,
                      name, objective, status FROM geo_campaigns
               WHERE project_id = %s AND id = %s""",
            (project_id, campaign_id),
        )
        records = _rows(cursor)
        return _campaign(records[0]) if records else None

    def create_monitoring_query(self, **values: Any) -> MonitoringQuery:
        record = _row(
            self._db.execute(
                """INSERT INTO monitoring_queries
                     (project_id, market_profile_id, query_text, query_kind, locale)
                   VALUES (%(project_id)s, %(market_profile_id)s, %(query_text)s,
                           %(query_kind)s, %(locale)s)
                   RETURNING id, project_id, market_profile_id, query_text,
                             query_kind, locale, status""",
                values,
            )
        )
        self._db.execute(
            """INSERT INTO campaign_monitoring_queries
                 (campaign_id, project_id, monitoring_query_id)
               VALUES (%s, %s, %s)""",
            (values["campaign_id"], values["project_id"], record["id"]),
        )
        return MonitoringQuery(**record)

    def list_monitoring_queries(
        self, *, project_id: UUID, campaign_id: UUID
    ) -> tuple[MonitoringQuery, ...]:
        records = _rows(
            self._db.execute(
                """SELECT q.id, q.project_id, q.market_profile_id, q.query_text,
                          q.query_kind, q.locale, q.status
                   FROM monitoring_queries q JOIN campaign_monitoring_queries cq
                     ON cq.monitoring_query_id = q.id AND cq.project_id = q.project_id
                   WHERE q.project_id = %s AND cq.campaign_id = %s
                   ORDER BY q.created_at""",
                (project_id, campaign_id),
            )
        )
        return tuple(MonitoringQuery(**record) for record in records)

    def create_destination(self, **values: Any) -> Destination:
        values = {**values, "allowed_hosts": list(values["allowed_hosts"])}
        record = _row(
            self._db.execute(
                """INSERT INTO publication_destinations
                 (project_id, publication_channel, destination_key, operation_mode,
                      destination_account_id, canonical_url, canonical_host, allowed_hosts,
                      policy_status)
                   VALUES (%(project_id)s, %(publication_channel)s, %(destination_key)s,
                           %(operation_mode)s, %(destination_account_id)s, %(canonical_url)s,
                           %(canonical_host)s, %(allowed_hosts)s, 'unreviewed')
                   RETURNING id, project_id, publication_channel, destination_key,
                     operation_mode, destination_account_id, canonical_url, canonical_host,
                     allowed_hosts, policy_status""",
                values,
            )
        )
        return _destination(record)

    def list_destinations(self, *, project_id: UUID) -> tuple[Destination, ...]:
        records = _rows(
            self._db.execute(
                """SELECT id, project_id, publication_channel, destination_key,
                          operation_mode, destination_account_id, canonical_url, canonical_host,
                          allowed_hosts, policy_status
                   FROM publication_destinations WHERE project_id = %s ORDER BY created_at""",
                (project_id,),
            )
        )
        return tuple(_destination(item) for item in records)

    def create_opportunities(self, **values: Any) -> tuple[Opportunity, ...]:
        result: list[Opportunity] = []
        for destination_id in values["destination_ids"]:
            reference = f"destination:{destination_id}"
            destination = _row(
                self._db.execute(
                    """SELECT policy_status FROM publication_destinations
                       WHERE project_id = %s AND id = %s""",
                    (values["project_id"], destination_id),
                )
            )
            eligible = destination["policy_status"] == "approved"
            status = "identified" if eligible else "blocked"
            blocked_reason = None if eligible else "destination_policy_not_eligible"
            record = _row(
                self._db.execute(
                    """INSERT INTO placement_opportunities
                         (project_id, campaign_id, destination_id, opportunity_ref, rationale,
                          status, blocked_reason)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)
                       RETURNING id, project_id, campaign_id, destination_id,
                                 opportunity_ref, rationale, status""",
                    (
                        values["project_id"],
                        values["campaign_id"],
                        destination_id,
                        reference,
                        values["rationale"],
                        status,
                        blocked_reason,
                    ),
                )
            )
            result.append(_opportunity(record))
        return tuple(result)

    def list_opportunities(self, *, project_id: UUID, campaign_id: UUID) -> tuple[Opportunity, ...]:
        records = _rows(
            self._db.execute(
                """SELECT id, project_id, campaign_id, destination_id, opportunity_ref,
                          rationale, status FROM placement_opportunities
                   WHERE project_id = %s AND campaign_id = %s ORDER BY created_at""",
                (project_id, campaign_id),
            )
        )
        return tuple(_opportunity(item) for item in records)

    def create_brief_version(self, **values: Any) -> BriefVersion:
        project_id, opportunity_id = values["project_id"], values["opportunity_id"]
        opportunity = _row(
            self._db.execute(
                """SELECT status FROM placement_opportunities
                   WHERE id = %s AND project_id = %s FOR UPDATE""",
                (opportunity_id, project_id),
            )
        )
        existing = _rows(
            self._db.execute(
                """SELECT id FROM placement_briefs
                   WHERE project_id = %s AND opportunity_id = %s FOR UPDATE""",
                (project_id, opportunity_id),
            )
        )
        if existing:
            if opportunity["status"] not in {"briefing", "in_progress"}:
                raise PlacementConflict(
                    "another brief version is not allowed from the current opportunity state"
                )
            brief_id = existing[0]["id"]
        else:
            if opportunity["status"] != "qualified":
                raise PlacementConflict(
                    "the first brief requires a qualified opportunity"
                )
            brief_id = _row(
                self._db.execute(
                    """INSERT INTO placement_briefs
                         (project_id, opportunity_id, primary_brand_entity_id)
                       VALUES (%s, %s, %s) RETURNING id""",
                    (project_id, opportunity_id, values["primary_brand_entity_id"]),
                )
            )["id"]
            self._db.execute(
                """UPDATE placement_opportunities SET status = 'briefing',
                     blocked_reason = NULL, updated_at = clock_timestamp()
                   WHERE id = %s AND project_id = %s AND status = 'qualified'""",
                (opportunity_id, project_id),
            )
        version_number = _row(
            self._db.execute(
                """SELECT COALESCE(MAX(version_number), 0) + 1 AS value
                   FROM placement_brief_versions WHERE brief_id = %s""",
                (brief_id,),
            )
        )["value"]
        record = _row(
            self._db.execute(
                """INSERT INTO placement_brief_versions
                     (project_id, brief_id, version_number, base_version_id, goals,
                      constraints, content_hash, created_by)
                   VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
                   RETURNING id, project_id, brief_id, version_number, base_version_id,
                             goals, constraints, content_hash""",
                (
                    project_id,
                    brief_id,
                    version_number,
                    values["base_version_id"],
                    json.dumps(values["goals"]),
                    json.dumps(values["constraints"]),
                    values["content_hash"],
                    values["actor_id"],
                ),
            )
        )
        for scope, ids in (
            ("compared", values["compared_entity_ids"]),
            ("allowed", values["allowed_subject_entity_ids"]),
        ):
            for entity_id in ids:
                self._db.execute(
                    """INSERT INTO placement_brief_subject_entities
                         (brief_version_id, project_id, entity_id, subject_scope)
                       VALUES (%s, %s, %s, %s)""",
                    (record["id"], project_id, entity_id, scope),
                )
        return _brief(record)

    def list_brief_versions(
        self, *, project_id: UUID, opportunity_id: UUID
    ) -> tuple[BriefVersion, ...]:
        records = _rows(
            self._db.execute(
                """SELECT v.id, v.project_id, v.brief_id, v.version_number,
                          v.base_version_id, v.goals, v.constraints, v.content_hash
                   FROM placement_brief_versions v JOIN placement_briefs b
                     ON b.id = v.brief_id AND b.project_id = v.project_id
                   WHERE v.project_id = %s AND b.opportunity_id = %s
                   ORDER BY v.version_number""",
                (project_id, opportunity_id),
            )
        )
        return tuple(_brief(item) for item in records)

    def create_evidence_attempt(
        self, *, project_id: UUID, brief_version_id: UUID, idempotency_key: str
    ) -> tuple[EvidencePackAttempt, JobReference]:
        eligible = self._db.execute(
            """SELECT bv.id FROM placement_brief_versions bv
               JOIN placement_briefs b ON b.id = bv.brief_id AND b.project_id = bv.project_id
               JOIN placement_opportunities o
                 ON o.id = b.opportunity_id AND o.project_id = b.project_id
               WHERE bv.project_id = %s AND bv.id = %s
                 AND o.status IN ('briefing', 'in_progress') FOR UPDATE OF bv""",
            (project_id, brief_version_id),
        ).fetchone()
        if eligible is None:
            raise PlacementConflict(
                "evidence build requires a briefing or in-progress opportunity"
            )
        attempt_number = _row(
            self._db.execute(
                """SELECT COALESCE(MAX(attempt_number), 0) + 1 AS value
                   FROM evidence_pack_attempts WHERE brief_version_id = %s""",
                (brief_version_id,),
            )
        )["value"]
        attempt_id = uuid5(
            NAMESPACE_URL,
            f"geo-evidence-pack-attempt:{project_id}:{brief_version_id}:{idempotency_key}",
        )
        inserted = _rows(
            self._db.execute(
                """INSERT INTO evidence_pack_attempts
                     (id, project_id, brief_version_id, attempt_number)
                   VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING
                   RETURNING id, project_id, brief_version_id, attempt_number,
                             status, pack_hash, failure_reason""",
                (attempt_id, project_id, brief_version_id, attempt_number),
            )
        )
        attempt = (
            inserted[0]
            if inserted
            else _row(
                self._db.execute(
                    """SELECT id, project_id, brief_version_id, attempt_number,
                          status, pack_hash, failure_reason
                   FROM evidence_pack_attempts WHERE project_id = %s AND id = %s""",
                    (project_id, attempt_id),
                )
            )
        )
        job = self._enqueue_job(
            project_id=project_id,
            kind="evidence_pack.build",
            input_value={
                "brief_version_id": str(brief_version_id),
                "attempt_id": str(attempt["id"]),
            },
            idempotency_key=idempotency_key,
        )
        self._db.execute(
            """INSERT INTO evidence_pack_job_specs
                 (job_id, project_id, brief_version_id, evidence_pack_attempt_id)
               VALUES (%s, %s, %s, %s) ON CONFLICT (job_id) DO NOTHING""",
            (job.id, project_id, brief_version_id, attempt["id"]),
        )
        return EvidencePackAttempt(**attempt), job

    def list_evidence_attempts(
        self, *, project_id: UUID, brief_version_id: UUID
    ) -> tuple[EvidencePackAttempt, ...]:
        records = _rows(
            self._db.execute(
                """SELECT id, project_id, brief_version_id, attempt_number,
                          status, pack_hash, failure_reason
                   FROM evidence_pack_attempts WHERE project_id = %s AND brief_version_id = %s
                   ORDER BY attempt_number""",
                (project_id, brief_version_id),
            )
        )
        return tuple(EvidencePackAttempt(**record) for record in records)

    def get_evidence_attempt(
        self, *, project_id: UUID, attempt_id: UUID
    ) -> EvidencePackAttempt | None:
        records = _rows(
            self._db.execute(
                """SELECT id, project_id, brief_version_id, attempt_number,
                          status, pack_hash, failure_reason
                   FROM evidence_pack_attempts WHERE project_id = %s AND id = %s""",
                (project_id, attempt_id),
            )
        )
        return EvidencePackAttempt(**records[0]) if records else None

    def list_evidence_attempt_items(
        self, *, project_id: UUID, attempt_id: UUID
    ) -> tuple[Mapping[str, object], ...]:
        return tuple(
            _rows(
                self._db.execute(
                    """SELECT e.id, e.item_type, e.subject_entity_id, e.subject_role,
                              e.snapshot_hash, e.usage_rights, e.confidentiality,
                              e.public_disclosure_allowed, e.public_source_url,
                              e.public_source_title, e.citation_label,
                              e.quotation_allowed, e.attribution_required
                       FROM evidence_pack_items pi JOIN evidence_items e
                         ON e.id = pi.evidence_item_id AND e.project_id = pi.project_id
                       WHERE pi.project_id = %s AND pi.pack_attempt_id = %s
                       ORDER BY pi.ordinal""",
                    (project_id, attempt_id),
                )
            )
        )

    def list_package_versions(
        self, *, project_id: UUID, opportunity_id: UUID
    ) -> tuple[PackageVersion, ...]:
        records = _rows(
            self._db.execute(
                """SELECT v.id, v.project_id, v.package_id, v.prompt_bundle_id,
                          v.version_number, v.base_version_id, v.workflow_status,
                          v.content_json, v.rendered_text, v.content_hash, v.edited_by, v.edit_reason,
                          v.generated_by_job_id
                   FROM placement_package_versions v JOIN placement_packages p
                     ON p.id = v.package_id AND p.project_id = v.project_id
                   WHERE v.project_id = %s AND p.opportunity_id = %s ORDER BY v.version_number""",
                (project_id, opportunity_id),
            )
        )
        return tuple(_package(item) for item in records)

    def get_package_version(self, *, project_id: UUID, version_id: UUID) -> PackageVersion | None:
        records = _rows(
            self._db.execute(
                """SELECT id, project_id, package_id, prompt_bundle_id, version_number,
                          base_version_id, workflow_status, content_json, rendered_text,
                          content_hash, edited_by, edit_reason, generated_by_job_id
                   FROM placement_package_versions WHERE project_id = %s AND id = %s""",
                (project_id, version_id),
            )
        )
        return _package(records[0]) if records else None

    def list_claims(self, *, project_id: UUID, version_id: UUID) -> tuple[Claim, ...]:
        records = _rows(
            self._db.execute(
                """SELECT c.id, c.project_id, c.package_version_id, c.claim_text,
                          c.claim_kind, c.support_status,
                          COALESCE(array_agg(ce.evidence_item_id)
                            FILTER (WHERE ce.evidence_item_id IS NOT NULL), '{}') AS evidence_item_ids
                   FROM placement_claims c LEFT JOIN placement_claim_evidence ce
                     ON ce.claim_id = c.id AND ce.project_id = c.project_id
                   WHERE c.project_id = %s AND c.package_version_id = %s
                   GROUP BY c.id ORDER BY c.created_at""",
                (project_id, version_id),
            )
        )
        return tuple(
            Claim(**{**item, "evidence_item_ids": tuple(item["evidence_item_ids"])})
            for item in records
        )

    def _enqueue_job(
        self,
        *,
        project_id: UUID,
        kind: str,
        input_value: Mapping[str, object],
        idempotency_key: str,
    ) -> JobReference:
        input_hash = canonical_hash(input_value)
        inserted = _rows(
            self._db.execute(
                """INSERT INTO durable_jobs
                     (project_id, kind, input_hash, idempotency_key)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (project_id, kind, idempotency_key, replay_nonce)
                   DO NOTHING
                   RETURNING id, project_id, kind, status""",
                (project_id, kind, input_hash, idempotency_key),
            )
        )
        if inserted:
            record = inserted[0]
        else:
            record = _row(
                self._db.execute(
                    """SELECT id, project_id, kind, status, input_hash
                       FROM durable_jobs WHERE project_id = %s AND kind = %s
                         AND idempotency_key = %s AND replay_nonce = 0""",
                    (project_id, kind, idempotency_key),
                )
            )
            if record["input_hash"] != input_hash:
                raise PlacementConflict("idempotency key was already used with different input")
        job = JobReference(
            id=record["id"],
            project_id=record["project_id"],
            kind=record["kind"],
            status=record["status"],
        )
        self._db.execute(
            """INSERT INTO broker_outbox
                 (project_id, job_id, topic, payload, idempotency_key)
               VALUES (%s, %s, %s, %s::jsonb, %s)
               ON CONFLICT (project_id, idempotency_key) DO NOTHING""",
            (
                project_id,
                job.id,
                kind,
                json.dumps({"job_id": str(job.id)}),
                f"wake:{kind}:{idempotency_key}",
            ),
        )
        return job
