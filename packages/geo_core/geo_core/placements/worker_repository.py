"""Domain persistence used only by the new durable placement handlers."""

from __future__ import annotations

import json
from typing import Any, Mapping
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from geo_core.jobs.postgres import PostgresDurableJobStore, WorkerLease
from geo_core.model_gateway import ModelGatewayResult
from geo_core.placements.domain import PackageVersion, WorkflowStatus, canonical_hash
from geo_core.placements.ports import GeneratedPlacement, GenerationClaim
from geo_core.placements.publication_worker_support import (
    content_fragments,
    open_measurement_window,
    schedule_measurements,
    string_values,
)
from geo_core.placements.worker_models import ModelCallReservation, VerificationSnapshot


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


class PlacementWorkerRepository:
    def __init__(self, store: PostgresDurableJobStore) -> None:
        self._store = store

    def load_generation(self, lease: WorkerLease) -> GenerationClaim:
        connection = self._store.open_project(lease.project_id)
        try:
            row = _dict(
                connection.execute(
                    """SELECT s.prompt_bundle_id, s.configured_model, s.model_call_budget,
                              pb.bundle_hash, pb.input_snapshot, pb.evidence_pack_attempt_id,
                              b.opportunity_id, r.output_schema
                       FROM generation_job_specs s
                       JOIN prompt_bundles pb
                         ON pb.id = s.prompt_bundle_id AND pb.project_id = s.project_id
                       JOIN generation_template_releases r
                         ON r.id = pb.template_release_id AND r.project_id = pb.project_id
                       JOIN placement_brief_versions bv
                         ON bv.id = pb.brief_version_id AND bv.project_id = pb.project_id
                       JOIN placement_briefs b
                         ON b.id = bv.brief_id AND b.project_id = bv.project_id
                       WHERE s.job_id = %s AND s.project_id = %s""",
                    (lease.job_id, lease.project_id),
                )
            )
            if row is None:
                raise RuntimeError("generation job input does not exist")
            evidence = _dicts(
                connection.execute(
                    """SELECT pi.evidence_item_id, e.public_disclosure_allowed,
                              e.public_source_url
                       FROM evidence_pack_items pi JOIN evidence_items e
                         ON e.id = pi.evidence_item_id AND e.project_id = pi.project_id
                       WHERE pi.project_id = %s AND pi.pack_attempt_id = %s
                       ORDER BY pi.ordinal""",
                    (lease.project_id, row["evidence_pack_attempt_id"]),
                )
            )
            package_id = uuid5(NAMESPACE_URL, f"geo-placement-package:{row['opportunity_id']}")
            latest = _dict(
                connection.execute(
                    """SELECT id, version_number FROM placement_package_versions
                       WHERE project_id = %s AND package_id = %s
                       ORDER BY version_number DESC LIMIT 1""",
                    (lease.project_id, package_id),
                )
            )
            connection.commit()
            snapshot = row["input_snapshot"]
            return GenerationClaim(
                job_id=lease.job_id,
                project_id=lease.project_id,
                lease_token=lease.lease_token,
                fencing_generation=lease.fencing_generation,
                prompt_bundle_id=row["prompt_bundle_id"],
                prompt_bundle_hash=row["bundle_hash"],
                rendered_prompt=snapshot["rendered_prompt"],
                configured_model=row["configured_model"],
                model_call_budget=row["model_call_budget"],
                package_id=package_id,
                next_version_number=(latest["version_number"] + 1) if latest else 1,
                base_version_id=latest["id"] if latest else None,
                evidence_item_ids=tuple(value["evidence_item_id"] for value in evidence),
                public_citation_item_ids=tuple(
                    value["evidence_item_id"]
                    for value in evidence
                    if value["public_disclosure_allowed"] and value["public_source_url"]
                ),
                output_schema=row["output_schema"],
            )
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def reserve_model_call(
        self,
        lease: WorkerLease,
        claim: GenerationClaim,
        *,
        provider: str,
        request_hash: str,
    ) -> ModelCallReservation:
        with self._store.fenced_transaction(lease) as connection:
            consumed = _dict(
                connection.execute(
                    """SELECT count(*) AS count FROM model_call_logs
                       WHERE job_id = %s AND project_id = %s AND status = 'reserved'""",
                    (lease.job_id, lease.project_id),
                )
            )
            call_number = int(consumed["count"] if consumed else 0) + 1
            if call_number > claim.model_call_budget:
                from geo_core.model_gateway.contracts import ModelCallBudgetExceeded

                raise ModelCallBudgetExceeded("model call budget exhausted")
            connection.execute(
                """INSERT INTO model_call_logs
                     (project_id, job_id, call_number, status, request_hash,
                      prompt_bundle_hash, provider, configured_model)
                   VALUES (%s, %s, %s, 'reserved', %s, %s, %s, %s)""",
                (
                    lease.project_id,
                    lease.job_id,
                    call_number,
                    request_hash,
                    claim.prompt_bundle_hash,
                    provider,
                    claim.configured_model,
                ),
            )
            return ModelCallReservation(call_number, request_hash, provider)

    def record_model_call_success(
        self,
        lease: WorkerLease,
        claim: GenerationClaim,
        reservation: ModelCallReservation,
        result: ModelGatewayResult,
    ) -> None:
        with self._store.fenced_transaction(lease) as connection:
            connection.execute(
                """INSERT INTO model_call_logs
                     (project_id, job_id, call_number, status, request_hash,
                      prompt_bundle_hash, provider, configured_model, gateway_call_log_id,
                      provider_request_id, provider_reported_model, prompt_tokens,
                      completion_tokens, cost_usd, finish_reason, response_hash)
                   VALUES (%s, %s, %s, 'succeeded', %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s, %s)""",
                (
                    lease.project_id,
                    lease.job_id,
                    reservation.call_number,
                    reservation.request_hash,
                    claim.prompt_bundle_hash,
                    reservation.provider,
                    claim.configured_model,
                    result.call_log_id,
                    result.provider_request_id,
                    result.provider_reported_model,
                    result.prompt_tokens,
                    result.completion_tokens,
                    result.cost_usd,
                    result.finish_reason,
                    result.response_hash,
                ),
            )

    def record_model_call_failure(
        self,
        lease: WorkerLease,
        claim: GenerationClaim,
        reservation: ModelCallReservation,
        *,
        classification: str,
        error_code: str,
    ) -> None:
        with self._store.fenced_transaction(lease) as connection:
            connection.execute(
                """INSERT INTO model_call_logs
                     (project_id, job_id, call_number, status, request_hash,
                      prompt_bundle_hash, provider, configured_model,
                      error_classification, error_code)
                   VALUES (%s, %s, %s, 'failed', %s, %s, %s, %s, %s, %s)""",
                (
                    lease.project_id,
                    lease.job_id,
                    reservation.call_number,
                    reservation.request_hash,
                    claim.prompt_bundle_hash,
                    reservation.provider,
                    claim.configured_model,
                    classification,
                    error_code,
                ),
            )

    def finalize_generation(
        self,
        lease: WorkerLease,
        claim: GenerationClaim,
        placement: GeneratedPlacement,
        result: ModelGatewayResult,
    ) -> PackageVersion:
        version_id = uuid4()
        payload = {
            "content_json": dict(placement.content_json),
            "rendered_text": placement.rendered_text,
        }
        content_hash = canonical_hash(payload)
        with self._store.fenced_transaction(lease) as connection:
            opportunity = _dict(
                connection.execute(
                    """SELECT b.opportunity_id FROM prompt_bundles pb
                       JOIN placement_brief_versions bv
                         ON bv.id = pb.brief_version_id AND bv.project_id = pb.project_id
                       JOIN placement_briefs b
                         ON b.id = bv.brief_id AND b.project_id = bv.project_id
                       WHERE pb.project_id = %s AND pb.id = %s""",
                    (lease.project_id, claim.prompt_bundle_id),
                )
            )
            if opportunity is None:
                raise RuntimeError("generation opportunity no longer exists")
            connection.execute(
                """INSERT INTO placement_packages (id, project_id, opportunity_id)
                   VALUES (%s, %s, %s) ON CONFLICT (opportunity_id) DO NOTHING""",
                (claim.package_id, lease.project_id, opportunity["opportunity_id"]),
            )
            if claim.base_version_id is not None:
                changed = connection.execute(
                    """UPDATE placement_package_versions SET workflow_status = 'superseded'
                       WHERE id = %s AND project_id = %s AND package_id = %s
                         AND version_number = %s AND workflow_status <> 'superseded'""",
                    (
                        claim.base_version_id,
                        lease.project_id,
                        claim.package_id,
                        claim.next_version_number - 1,
                    ),
                ).rowcount
                if changed != 1:
                    raise RuntimeError("generation package lineage changed concurrently")
            connection.execute(
                """INSERT INTO placement_package_versions
                     (id, project_id, package_id, prompt_bundle_id, version_number,
                      base_version_id, workflow_status, content_json, rendered_text,
                      content_hash, generated_by_job_id)
                   VALUES (%s, %s, %s, %s, %s, %s, 'generated', %s::jsonb, %s, %s, %s)""",
                (
                    version_id,
                    lease.project_id,
                    claim.package_id,
                    claim.prompt_bundle_id,
                    claim.next_version_number,
                    claim.base_version_id,
                    json.dumps(dict(placement.content_json)),
                    placement.rendered_text,
                    content_hash,
                    lease.job_id,
                ),
            )
            for generated in placement.claims:
                claim_id = uuid4()
                connection.execute(
                    """INSERT INTO placement_claims
                         (id, project_id, package_version_id, claim_text, claim_kind, support_status)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (
                        claim_id,
                        lease.project_id,
                        version_id,
                        generated.text,
                        generated.kind,
                        generated.support_status,
                    ),
                )
                for evidence_id in generated.evidence_item_ids:
                    classification = (
                        "conflicts" if generated.support_status == "conflict" else "supports"
                    )
                    connection.execute(
                        """INSERT INTO placement_claim_evidence
                             (claim_id, project_id, evidence_item_id, support_classification)
                           VALUES (%s, %s, %s, %s)""",
                        (claim_id, lease.project_id, evidence_id, classification),
                    )
            details = {
                "model_call_log_id": str(result.call_log_id),
                "configured_model": result.configured_model,
                "provider_reported_model": result.provider_reported_model,
                "response_hash": result.response_hash,
                "prompt_bundle_hash": claim.prompt_bundle_hash,
                "claim_count": len(placement.claims),
            }
            self._store.complete_in_transaction(
                connection,
                lease,
                result_ref=f"placement-package-version:{version_id}",
                details=details,
            )
        return PackageVersion(
            id=version_id,
            project_id=lease.project_id,
            package_id=claim.package_id,
            prompt_bundle_id=claim.prompt_bundle_id,
            version_number=claim.next_version_number,
            base_version_id=claim.base_version_id,
            content_json=placement.content_json,
            rendered_text=placement.rendered_text,
            content_hash=content_hash,
            workflow_status=WorkflowStatus.GENERATED,
            generated_by_job_id=lease.job_id,
        )

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
                    """SELECT e.id, e.item_type, e.subject_entity_id, e.subject_role,
                              e.snapshot_hash, e.snapshot_text, e.snapshot_uri, e.usage_rights,
                              e.public_disclosure_allowed, e.public_source_url,
                              e.public_source_title, e.citation_label,
                              e.quotation_allowed, e.attribution_required
                       FROM evidence_items e
                       JOIN placement_brief_versions bv
                         ON bv.id = %s AND bv.project_id = e.project_id
                       JOIN placement_briefs b
                         ON b.id = bv.brief_id AND b.project_id = bv.project_id
                       WHERE e.project_id = %s
                         AND e.usage_rights IN
                           ('owned', 'licensed', 'public_reference', 'authorised_experience')
                         AND e.confidentiality <> 'restricted'
                         AND (e.subject_entity_id IS NULL
                           OR e.subject_entity_id = b.primary_brand_entity_id
                           OR EXISTS (
                               SELECT 1 FROM placement_brief_subject_entities s
                               WHERE s.brief_version_id = bv.id AND s.project_id = bv.project_id
                                 AND s.entity_id = e.subject_entity_id
                           ))
                       ORDER BY e.created_at, e.id""",
                    (spec["brief_version_id"], lease.project_id),
                )
            )
            if not eligible:
                restricted = _dict(
                    connection.execute(
                        """SELECT COUNT(*) AS count FROM evidence_items
                           WHERE project_id = %s
                             AND (usage_rights = 'restricted' OR confidentiality = 'restricted')""",
                        (lease.project_id,),
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
            for ordinal, item in enumerate(eligible):
                connection.execute(
                    """INSERT INTO evidence_pack_items
                         (pack_attempt_id, project_id, evidence_item_id, ordinal)
                       VALUES (%s, %s, %s, %s)""",
                    (spec["evidence_pack_attempt_id"], lease.project_id, item["id"], ordinal),
                )
            manifest = [
                {key: value for key, value in item.items() if key not in {"snapshot_text"}}
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

    def begin_verification(self, lease: WorkerLease) -> VerificationSnapshot:
        with self._store.fenced_transaction(lease) as connection:
            row = _dict(
                connection.execute(
                    """SELECT s.id AS submission_id, s.submitted_url,
                              s.publication_request_id, v.rendered_text, v.content_json,
                              r.policy_basis, d.allowed_hosts
                       FROM verification_job_specs spec
                       JOIN publication_submissions s
                         ON s.id = spec.submission_id AND s.project_id = spec.project_id
                       JOIN publication_requests r
                         ON r.id = s.publication_request_id AND r.project_id = s.project_id
                       JOIN publication_destinations d
                         ON d.id = r.destination_id AND d.project_id = r.project_id
                       JOIN placement_package_versions v
                         ON v.id = r.package_version_id AND v.project_id = r.project_id
                       WHERE spec.job_id = %s AND spec.project_id = %s""",
                    (lease.job_id, lease.project_id),
                )
            )
            if row is None or not row["submitted_url"]:
                raise RuntimeError("verification requires a submitted URL")
            connection.execute(
                """UPDATE publication_submissions SET status = 'verifying'
                   WHERE id = %s AND project_id = %s""",
                (row["submission_id"], lease.project_id),
            )
            connection.execute(
                """UPDATE publication_requests SET status = 'publishing'
                   WHERE id = %s AND project_id = %s""",
                (row["publication_request_id"], lease.project_id),
            )
            fragments = content_fragments(row["rendered_text"])
            disclosures = string_values(row["content_json"], key_hint="disclosure")
            links = string_values(row["content_json"], key_hint="url")
            return VerificationSnapshot(
                row["submission_id"],
                row["publication_request_id"],
                row["submitted_url"],
                fragments,
                disclosures,
                links,
                tuple(row["allowed_hosts"]),
            )

    def finalize_verification(
        self,
        lease: WorkerLease,
        snapshot: VerificationSnapshot,
        *,
        success: bool,
        result: Mapping[str, object],
    ) -> None:
        with self._store.fenced_transaction(lease) as connection:
            submission_status = "verified" if success else "failed"
            publication_status = "published" if success else "failed"
            connection.execute(
                """UPDATE publication_submissions SET status = %s,
                     verified_at = CASE WHEN %s THEN clock_timestamp() ELSE NULL END,
                     verification_result = %s::jsonb
                   WHERE id = %s AND project_id = %s""",
                (
                    submission_status,
                    success,
                    json.dumps(dict(result)),
                    snapshot.submission_id,
                    lease.project_id,
                ),
            )
            connection.execute(
                """UPDATE publication_requests SET status = %s
                   WHERE id = %s AND project_id = %s""",
                (publication_status, snapshot.publication_request_id, lease.project_id),
            )
            scheduled = (
                self._schedule_measurements(connection, lease, snapshot.submission_id)
                if success
                else 0
            )
            details = {**dict(result), "verified": success, "measurement_jobs": scheduled}
            self._store.complete_in_transaction(
                connection,
                lease,
                result_ref=f"publication-verification:{snapshot.submission_id}",
                details=details,
            )

    def fail_verification_permanently(
        self,
        lease: WorkerLease,
        snapshot: VerificationSnapshot,
        *,
        error_code: str,
        result: Mapping[str, object],
    ) -> None:
        with self._store.fenced_transaction(lease) as connection:
            connection.execute(
                """UPDATE publication_submissions SET status = 'failed',
                     verification_result = %s::jsonb
                   WHERE id = %s AND project_id = %s""",
                (json.dumps(dict(result)), snapshot.submission_id, lease.project_id),
            )
            connection.execute(
                """UPDATE publication_requests SET status = 'failed'
                   WHERE id = %s AND project_id = %s""",
                (snapshot.publication_request_id, lease.project_id),
            )
            self._store.fail_in_transaction(
                connection,
                lease,
                error_code=error_code,
                details=result,
            )

    def mark_verification_retry(
        self, lease: WorkerLease, snapshot: VerificationSnapshot, *, terminal: bool
    ) -> None:
        connection = self._store.open_project(lease.project_id)
        try:
            connection.execute(
                """UPDATE publication_submissions SET status = %s
                   WHERE id = %s AND project_id = %s""",
                ("failed" if terminal else "verifying", snapshot.submission_id, lease.project_id),
            )
            connection.execute(
                """UPDATE publication_requests SET status = %s
                   WHERE id = %s AND project_id = %s""",
                (
                    "failed" if terminal else "retrying",
                    snapshot.publication_request_id,
                    lease.project_id,
                ),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def open_measurement_window(self, lease: WorkerLease) -> Mapping[str, object]:
        return open_measurement_window(self._store, lease)

    def _schedule_measurements(
        self, connection: Any, lease: WorkerLease, submission_id: UUID
    ) -> int:
        return schedule_measurements(connection, lease, submission_id)
