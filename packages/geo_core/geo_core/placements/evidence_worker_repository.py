"""Evidence Pack construction with subject and usage-policy enforcement."""

from __future__ import annotations

from typing import Any, Mapping

from geo_core.jobs.postgres import PostgresDurableJobStore, WorkerLease
from geo_core.placements.domain import canonical_hash


def _dict(cursor: Any) -> dict[str, Any] | None:
    row = cursor.fetchone()
    if row is None:
        return None
    if isinstance(row, Mapping):
        return dict(row)
    return dict(zip((item.name for item in cursor.description), row, strict=True))


def _dicts(cursor: Any) -> list[dict[str, Any]]:
    rows = cursor.fetchall()
    if not rows:
        return []
    if isinstance(rows[0], Mapping):
        return [dict(row) for row in rows]
    names = [item.name for item in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in rows]


_SUBJECT_FILTER = """
    ((e.subject_entity_id IS NULL AND e.subject_role IN ('market', 'neutral'))
      OR (e.subject_entity_id = b.primary_brand_entity_id
          AND e.subject_role IN ('primary_brand', 'product'))
      OR EXISTS (
          SELECT 1 FROM placement_brief_subject_entities s
          WHERE s.brief_version_id = bv.id AND s.project_id = bv.project_id
            AND s.entity_id = e.subject_entity_id
            AND (s.subject_scope = 'allowed'
                 OR (s.subject_scope = 'compared' AND e.subject_role = 'competitor'))
      ))
"""


class EvidenceWorkerRepositoryMixin:
    _store: PostgresDurableJobStore

    def build_evidence_pack(self, lease: WorkerLease) -> str:
        with self._store.fenced_transaction(lease) as connection:
            spec = _dict(
                connection.execute(
                    """SELECT brief_version_id, evidence_pack_attempt_id
                       FROM evidence_pack_job_specs WHERE job_id = %s AND project_id = %s""",
                    (lease.job_id, lease.project_id),
                )
            )
            if spec is None:
                raise RuntimeError("evidence pack job input does not exist")
            attempt = _dict(
                connection.execute(
                    """SELECT status FROM evidence_pack_attempts
                       WHERE id = %s AND project_id = %s FOR UPDATE""",
                    (spec["evidence_pack_attempt_id"], lease.project_id),
                )
            )
            if attempt is None or attempt["status"] != "building":
                raise RuntimeError("evidence pack attempt is not buildable")
            eligible = _dicts(
                connection.execute(
                    f"""SELECT e.id, e.item_type, e.subject_entity_id, e.subject_role,
                              e.snapshot_hash, e.snapshot_text, e.snapshot_uri, e.usage_rights,
                              e.public_disclosure_allowed, e.public_source_url,
                              e.public_source_title, e.citation_label,
                              e.quotation_allowed, e.attribution_required,
                              lineage.pipeline_run_id,
                              lineage.knowledge_source_id,
                              lineage.knowledge_document_id,
                              lineage.knowledge_chunk_id,
                              lineage.knowledge_fact_id,
                              lineage.evidence_title,
                              lineage.promoted_by,
                              lineage.promoted_at,
                              lineage.idempotency_key,
                              lineage.promotion_request_hash,
                              lineage.lineage_contract_version,
                              lineage.source_content_hash,
                              lineage.document_cleaned_text_hash,
                              lineage.chunk_text_hash,
                              lineage.fact_statement_hash,
                              lineage.evidence_snapshot_hash
                       FROM evidence_items e
                       LEFT JOIN knowledge_fact_evidence_lineages lineage
                         ON lineage.evidence_item_id = e.id
                        AND lineage.project_id = e.project_id
                       JOIN placement_brief_versions bv
                         ON bv.id = %s AND bv.project_id = e.project_id
                       JOIN placement_briefs b
                         ON b.id = bv.brief_id AND b.project_id = bv.project_id
                       WHERE e.project_id = %s
                         AND e.usage_rights IN
                           ('owned', 'licensed', 'public_reference', 'authorised_experience')
                         AND e.confidentiality <> 'restricted'
                         AND (e.item_type <> 'approved_fact'
                              OR (e.fact_lineage_status = 'verified'
                                  AND lineage.lineage_contract_version =
                                      'knowledge-fact-evidence-v1'))
                         AND {_SUBJECT_FILTER}
                       ORDER BY e.created_at, e.id""",
                    (spec["brief_version_id"], lease.project_id),
                )
            )
            if not eligible:
                return self._finish_without_evidence(connection, lease, spec)
            for ordinal, item in enumerate(eligible):
                connection.execute(
                    """INSERT INTO evidence_pack_items
                         (pack_attempt_id, project_id, evidence_item_id, ordinal)
                       VALUES (%s, %s, %s, %s)""",
                    (spec["evidence_pack_attempt_id"], lease.project_id, item["id"], ordinal),
                )
            manifest = [
                {key: value for key, value in item.items() if key != "snapshot_text"}
                for item in eligible
            ]
            pack_hash = canonical_hash(manifest)
            connection.execute(
                """UPDATE evidence_pack_attempts SET status = 'ready', pack_hash = %s,
                     completed_at = clock_timestamp() WHERE id = %s AND project_id = %s""",
                (pack_hash, spec["evidence_pack_attempt_id"], lease.project_id),
            )
            connection.execute(
                """UPDATE evidence_pack_attempts SET status = 'superseded',
                     superseded_by_attempt_id = %s, superseded_at = clock_timestamp()
                   WHERE project_id = %s AND brief_version_id = %s
                     AND id <> %s AND status IN ('ready', 'needs_evidence', 'blocked')""",
                (
                    spec["evidence_pack_attempt_id"],
                    lease.project_id,
                    spec["brief_version_id"],
                    spec["evidence_pack_attempt_id"],
                ),
            )
            self._store.complete_in_transaction(
                connection,
                lease,
                result_ref=f"evidence-pack:{spec['evidence_pack_attempt_id']}",
                details={"status": "ready", "pack_hash": pack_hash, "item_count": len(eligible)},
            )
            return "ready"

    def _finish_without_evidence(
        self, connection: Any, lease: WorkerLease, spec: Mapping[str, Any]
    ) -> str:
        restricted = _dict(
            connection.execute(
                f"""SELECT COUNT(*) AS count FROM evidence_items e
                   JOIN placement_brief_versions bv
                     ON bv.id = %s AND bv.project_id = e.project_id
                   JOIN placement_briefs b ON b.id = bv.brief_id AND b.project_id = bv.project_id
                   WHERE e.project_id = %s
                     AND (e.usage_rights = 'restricted' OR e.confidentiality = 'restricted')
                     AND (e.item_type <> 'approved_fact' OR (
                       e.fact_lineage_status = 'verified' AND EXISTS (
                         SELECT 1 FROM knowledge_fact_evidence_lineages lineage
                         WHERE lineage.project_id = e.project_id
                           AND lineage.evidence_item_id = e.id
                           AND lineage.lineage_contract_version =
                               'knowledge-fact-evidence-v1'
                       )
                     ))
                     AND {_SUBJECT_FILTER}""",
                (spec["brief_version_id"], lease.project_id),
            )
        )
        status = "blocked" if restricted and restricted["count"] else "needs_evidence"
        reason = (
            "eligible evidence is restricted by rights or confidentiality"
            if status == "blocked"
            else "no eligible evidence matches the brief subjects"
        )
        connection.execute(
            """UPDATE evidence_pack_attempts SET status = %s, failure_reason = %s,
                 completed_at = clock_timestamp() WHERE id = %s AND project_id = %s""",
            (status, reason, spec["evidence_pack_attempt_id"], lease.project_id),
        )
        self._store.complete_in_transaction(
            connection,
            lease,
            result_ref=f"evidence-pack:{spec['evidence_pack_attempt_id']}",
            details={"status": status, "reason": reason},
        )
        return status
