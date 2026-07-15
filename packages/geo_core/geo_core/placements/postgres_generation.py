"""Fenced PostgreSQL adapter for placement generation workers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
import json
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from geo_core.model_gateway import ModelGatewayResult
from geo_core.placements.domain import PackageVersion, WorkflowStatus, canonical_hash
from geo_core.placements.ports import GeneratedPlacement, GenerationClaim


def _one(cursor: Any) -> dict[str, Any] | None:
    record = cursor.fetchone()
    if record is None:
        return None
    if isinstance(record, Mapping):
        return dict(record)
    names = [item.name for item in cursor.description]
    return dict(zip(names, record, strict=True))


class PsycopgGenerationWorkerPort:
    """Uses one project-scoped connection per state transition."""

    def __init__(self, *, connection_factory: Callable[[], Any], project_id: UUID) -> None:
        self._connection_factory = connection_factory
        self._project_id = project_id

    def _open(self) -> Any:
        connection = self._connection_factory()
        connection.execute(
            "SELECT set_config('geo.project_id', %s, true)", (str(self._project_id),)
        )
        return connection

    def claim_next(self, *, worker_id: str, lease_for: timedelta) -> GenerationClaim | None:
        connection = self._open()
        try:
            record = _one(
                connection.execute(
                    """SELECT j.id, j.project_id, j.attempt_count, j.max_attempts,
                              s.prompt_bundle_id, s.configured_model, s.model_call_budget
                       FROM durable_jobs j JOIN generation_job_specs s
                         ON s.job_id = j.id AND s.project_id = j.project_id
                       WHERE j.project_id = %s AND j.kind = 'placement.generate'
                         AND j.cancel_requested_at IS NULL
                         AND ((j.status IN ('queued', 'retry_wait') AND j.next_run_at <= now())
                           OR (j.status IN ('running', 'finalizing')
                               AND j.lease_expires_at <= now()))
                       ORDER BY j.priority DESC, j.next_run_at, j.created_at
                       LIMIT 1 FOR UPDATE OF j SKIP LOCKED""",
                    (self._project_id,),
                )
            )
            if record is None:
                connection.rollback()
                return None
            if record["attempt_count"] >= record["max_attempts"]:
                connection.execute(
                    """UPDATE durable_jobs SET status = 'dead_lettered',
                         error_code = 'attempt_budget_exhausted', updated_at = clock_timestamp(),
                         completed_at = clock_timestamp(), lease_owner = NULL, lease_token = NULL,
                         lease_expires_at = NULL, heartbeat_at = NULL WHERE id = %s""",
                    (record["id"],),
                )
                connection.commit()
                return None
            lease_token = uuid4()
            claimed = _one(
                connection.execute(
                    """UPDATE durable_jobs SET status = 'running', lease_owner = %s,
                         lease_token = %s, lease_expires_at = now() + %s::interval,
                         heartbeat_at = now(), fencing_generation = fencing_generation + 1,
                         attempt_count = attempt_count + 1, updated_at = clock_timestamp()
                       WHERE id = %s
                       RETURNING lease_token, fencing_generation""",
                    (worker_id, lease_token, f"{lease_for.total_seconds()} seconds", record["id"]),
                )
            )
            if claimed is None:
                raise RuntimeError("claimed job was not returned")
            snapshot = _one(
                connection.execute(
                    """SELECT pb.bundle_hash, pb.input_snapshot, pb.evidence_pack_attempt_id,
                              b.opportunity_id
                       FROM prompt_bundles pb JOIN placement_brief_versions bv
                         ON bv.id = pb.brief_version_id AND bv.project_id = pb.project_id
                       JOIN placement_briefs b
                         ON b.id = bv.brief_id AND b.project_id = bv.project_id
                       WHERE pb.project_id = %s AND pb.id = %s""",
                    (self._project_id, record["prompt_bundle_id"]),
                )
            )
            if snapshot is None:
                raise RuntimeError("generation input snapshot does not exist")
            evidence = connection.execute(
                """SELECT evidence_item_id FROM evidence_pack_items
                   WHERE project_id = %s AND pack_attempt_id = %s ORDER BY ordinal""",
                (self._project_id, snapshot["evidence_pack_attempt_id"]),
            ).fetchall()
            package_id = uuid5(NAMESPACE_URL, f"geo-placement-package:{snapshot['opportunity_id']}")
            existing = _one(
                connection.execute(
                    """SELECT COALESCE(MAX(version_number), 0) AS version_number
                       FROM placement_package_versions WHERE project_id = %s AND package_id = %s""",
                    (self._project_id, package_id),
                )
            )
            if existing is None:
                raise RuntimeError("package version counter was not returned")
            connection.commit()
            input_snapshot = snapshot["input_snapshot"]
            return GenerationClaim(
                job_id=record["id"], project_id=self._project_id,
                lease_token=claimed["lease_token"],
                fencing_generation=claimed["fencing_generation"],
                prompt_bundle_id=record["prompt_bundle_id"],
                prompt_bundle_hash=snapshot["bundle_hash"],
                rendered_prompt=input_snapshot["rendered_prompt"],
                configured_model=record["configured_model"],
                model_call_budget=record["model_call_budget"], package_id=package_id,
                next_version_number=existing["version_number"] + 1,
                evidence_item_ids=tuple(
                    row["evidence_item_id"] if isinstance(row, Mapping) else row[0]
                    for row in evidence
                ),
            )
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def finalize(
        self,
        *,
        claim: GenerationClaim,
        placement: GeneratedPlacement,
        model_result: ModelGatewayResult,
        completed_at: datetime,
    ) -> PackageVersion:
        connection = self._open()
        version_id = uuid4()
        payload = {
            "content_json": dict(placement.content_json),
            "rendered_text": placement.rendered_text,
        }
        content_hash = canonical_hash(payload)
        try:
            locked = _one(
                connection.execute(
                    """SELECT id FROM durable_jobs WHERE id = %s AND project_id = %s
                         AND status = 'running' AND lease_token = %s
                         AND fencing_generation = %s AND lease_expires_at > now()
                       FOR UPDATE""",
                    (
                        claim.job_id, claim.project_id, claim.lease_token,
                        claim.fencing_generation,
                    ),
                )
            )
            if locked is None:
                raise RuntimeError("generation lease was lost before finalize")
            opportunity = _one(
                connection.execute(
                    """SELECT b.opportunity_id FROM prompt_bundles pb
                       JOIN placement_brief_versions bv
                         ON bv.id = pb.brief_version_id AND bv.project_id = pb.project_id
                       JOIN placement_briefs b
                         ON b.id = bv.brief_id AND b.project_id = bv.project_id
                       WHERE pb.project_id = %s AND pb.id = %s""",
                    (claim.project_id, claim.prompt_bundle_id),
                )
            )
            if opportunity is None:
                raise RuntimeError("placement opportunity does not exist")
            connection.execute(
                """INSERT INTO placement_packages (id, project_id, opportunity_id)
                   VALUES (%s, %s, %s) ON CONFLICT (opportunity_id) DO NOTHING""",
                (claim.package_id, claim.project_id, opportunity["opportunity_id"]),
            )
            if claim.next_version_number != 1:
                raise RuntimeError("regeneration requires an explicit package lineage contract")
            connection.execute(
                """INSERT INTO placement_package_versions
                     (id, project_id, package_id, prompt_bundle_id, version_number,
                      workflow_status, content_json, rendered_text, content_hash)
                   VALUES (%s, %s, %s, %s, 1, 'pending_human_review',
                           %s::jsonb, %s, %s)""",
                (
                    version_id, claim.project_id, claim.package_id, claim.prompt_bundle_id,
                    json.dumps(dict(placement.content_json)), placement.rendered_text, content_hash,
                ),
            )
            for generated_claim in placement.claims:
                claim_id = uuid4()
                connection.execute(
                    """INSERT INTO placement_claims
                         (id, project_id, package_version_id, claim_text, claim_kind, support_status)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (
                        claim_id, claim.project_id, version_id, generated_claim.text,
                        generated_claim.kind, generated_claim.support_status,
                    ),
                )
                for evidence_id in generated_claim.evidence_item_ids:
                    classification = (
                        "conflicts" if generated_claim.support_status == "conflict" else "supports"
                    )
                    connection.execute(
                        """INSERT INTO placement_claim_evidence
                             (claim_id, project_id, evidence_item_id, support_classification)
                           VALUES (%s, %s, %s, %s)""",
                        (claim_id, claim.project_id, evidence_id, classification),
                    )
            result_ref = f"placement-package-version:{version_id}"
            connection.execute(
                """UPDATE durable_jobs SET status = 'succeeded', result_ref = %s,
                     lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
                     heartbeat_at = NULL, completed_at = %s, updated_at = clock_timestamp(),
                     error_detail = %s::jsonb WHERE id = %s""",
                (
                    result_ref, completed_at,
                    json.dumps({"model_call_log_id": str(model_result.call_log_id),
                                "response_hash": model_result.response_hash}), claim.job_id,
                ),
            )
            connection.commit()
            return PackageVersion(
                id=version_id, project_id=claim.project_id, package_id=claim.package_id,
                prompt_bundle_id=claim.prompt_bundle_id, version_number=1,
                content_json=placement.content_json, rendered_text=placement.rendered_text,
                content_hash=content_hash, workflow_status=WorkflowStatus.PENDING_HUMAN_REVIEW,
            )
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def fail(
        self,
        *,
        claim: GenerationClaim,
        error_code: str,
        retry_at: datetime | None,
    ) -> None:
        connection = self._open()
        try:
            status = "retry_wait" if retry_at is not None else "failed"
            changed = connection.execute(
                """UPDATE durable_jobs SET status = %s, next_run_at = COALESCE(%s, next_run_at),
                     error_code = %s, lease_owner = NULL, lease_token = NULL,
                     lease_expires_at = NULL, heartbeat_at = NULL, updated_at = clock_timestamp(),
                     completed_at = CASE WHEN %s = 'failed' THEN clock_timestamp() ELSE NULL END
                   WHERE id = %s AND project_id = %s AND lease_token = %s
                     AND fencing_generation = %s AND status = 'running'""",
                (
                    status, retry_at, error_code, status, claim.job_id, claim.project_id,
                    claim.lease_token, claim.fencing_generation,
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeError("generation lease was lost before failure transition")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
