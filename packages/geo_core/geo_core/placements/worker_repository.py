"""Domain persistence used only by the new durable placement handlers."""

from __future__ import annotations

import json
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid4, uuid5

from geo_core.jobs.postgres import PostgresDurableJobStore, WorkerLease
from geo_core.model_gateway import ModelGatewayResult
from geo_core.placements.evidence_worker_repository import EvidenceWorkerRepositoryMixin
from geo_core.placements.domain import PackageVersion, WorkflowStatus, canonical_hash
from geo_core.placements.ports import GeneratedPlacement, GenerationClaim, ModelCallClaim
from geo_core.placements.publication_worker_support import (
    advance_generated_opportunity,
    open_measurement_window,
)
from geo_core.placements.publication_verification_worker import (
    begin_publication_verification,
    persist_completed_verification,
    persist_verification_error,
)
from geo_core.placements.simulation_worker_repository import (
    PromptSimulationWorkerRepositoryMixin,
)
from geo_core.placements.worker_models import ModelCallReservation, VerificationSnapshot
from geo_core.placements.url_verification_contracts import (
    UrlVerificationResult,
    VerificationError,
)


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


class PlacementWorkerRepository(
    EvidenceWorkerRepositoryMixin, PromptSimulationWorkerRepositoryMixin
):
    def __init__(self, store: PostgresDurableJobStore) -> None:
        self._store = store

    def load_generation(self, lease: WorkerLease) -> GenerationClaim:
        connection = self._store.open_project(lease.project_id)
        try:
            row = _dict(
                connection.execute(
                    """SELECT s.prompt_bundle_id, s.configured_model, s.model_call_budget,
                              s.campaign_id, s.opportunity_id, pb.destination_id,
                              pb.bundle_hash, pb.input_snapshot, pb.evidence_pack_attempt_id,
                              r.output_schema
                       FROM generation_job_specs s
                       JOIN prompt_bundles pb
                         ON pb.id = s.prompt_bundle_id AND pb.project_id = s.project_id
                       JOIN generation_template_releases r
                         ON r.id = pb.template_release_id AND r.project_id = pb.project_id
                       WHERE s.job_id = %s AND s.project_id = %s
                         AND s.campaign_id = pb.campaign_id
                         AND s.opportunity_id = pb.opportunity_id""",
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
                system_prompt=snapshot["system_prompt"],
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
                campaign_id=row["campaign_id"],
                opportunity_id=row["opportunity_id"],
                destination_id=row["destination_id"],
            )
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def reserve_model_call(
        self,
        lease: WorkerLease,
        claim: ModelCallClaim,
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
                    claim.prompt_input_hash,
                    provider,
                    claim.configured_model,
                ),
            )
            return ModelCallReservation(call_number, request_hash, provider)

    def record_model_call_success(
        self,
        lease: WorkerLease,
        claim: ModelCallClaim,
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
                    claim.prompt_input_hash,
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
        claim: ModelCallClaim,
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
                    claim.prompt_input_hash,
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
                    """SELECT campaign_id, opportunity_id, destination_id
                       FROM prompt_bundles
                       WHERE project_id = %s AND id = %s""",
                    (lease.project_id, claim.prompt_bundle_id),
                )
            )
            if opportunity is None:
                raise RuntimeError("generation opportunity no longer exists")
            connection.execute(
                """INSERT INTO placement_packages
                     (id, project_id, campaign_id, opportunity_id, destination_id)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (opportunity_id) DO NOTHING""",
                (
                    claim.package_id,
                    lease.project_id,
                    opportunity["campaign_id"],
                    opportunity["opportunity_id"],
                    opportunity["destination_id"],
                ),
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
                     (id, project_id, campaign_id, opportunity_id, destination_id,
                      package_id, prompt_bundle_id, version_number, base_version_id,
                      workflow_status, content_json, rendered_text, content_hash,
                      generated_by_job_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'generated',
                           %s::jsonb, %s, %s, %s)""",
                (
                    version_id,
                    lease.project_id,
                    opportunity["campaign_id"],
                    opportunity["opportunity_id"],
                    opportunity["destination_id"],
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
            advance_generated_opportunity(connection, lease.project_id, claim.package_id)
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
            campaign_id=opportunity["campaign_id"],
            opportunity_id=opportunity["opportunity_id"],
            destination_id=opportunity["destination_id"],
        )

    def begin_verification(self, lease: WorkerLease) -> VerificationSnapshot:
        return begin_publication_verification(self._store, lease)

    def persist_completed_verification(
        self,
        lease: WorkerLease,
        snapshot: VerificationSnapshot,
        *,
        result: UrlVerificationResult,
    ) -> bool:
        return persist_completed_verification(self._store, lease, snapshot, result)

    def persist_verification_error(
        self,
        lease: WorkerLease,
        snapshot: VerificationSnapshot,
        *,
        error: VerificationError,
    ) -> str:
        return persist_verification_error(self._store, lease, snapshot, error)

    def open_measurement_window(self, lease: WorkerLease) -> Mapping[str, object]:
        return open_measurement_window(self._store, lease)
