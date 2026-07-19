"""Fenced worker persistence for non-publishable prompt simulations."""

from __future__ import annotations

import json
from typing import Any, Literal, Mapping
from uuid import NAMESPACE_URL, uuid5

from geo_core.jobs.postgres import WorkerLease
from geo_core.model_gateway import ModelGatewayResult
from geo_core.placements.domain import PlacementRuleViolation, canonical_hash
from geo_core.placements.execution_eligibility import (
    approved_fact_evidence_is_current,
    question_candidate_sources_are_current,
)
from geo_core.placements.ports import GeneratedPlacement
from geo_core.placements.simulation import PromptSimulationAuthenticityMode
from geo_core.placements.worker_models import PromptSimulationClaim


def _one(cursor: Any) -> dict[str, Any] | None:
    row = cursor.fetchone()
    if row is None:
        return None
    if isinstance(row, Mapping):
        return dict(row)
    return dict(zip((item.name for item in cursor.description), row, strict=True))


def _many(cursor: Any) -> list[dict[str, Any]]:
    rows = cursor.fetchall()
    if not rows:
        return []
    if isinstance(rows[0], Mapping):
        return [dict(row) for row in rows]
    names = [item.name for item in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in rows]


class PromptSimulationWorkerRepositoryMixin:
    _store: Any

    def load_prompt_simulation(self, lease: WorkerLease) -> PromptSimulationClaim:
        connection = self._store.open_project(lease.project_id)
        try:
            record = _one(
                connection.execute(
                    """SELECT spec.simulation_id, spec.campaign_id, spec.opportunity_id,
                              simulation.destination_id, simulation.binding_id,
                              simulation.binding_version,
                              simulation.binding_contract_version, spec.configured_model,
                              spec.model_call_budget, simulation.input_hash,
                              simulation.input_snapshot, release.output_schema
                              , simulation.simulation_purpose,
                              simulation.question_candidate_id
                       FROM prompt_simulation_job_specs spec
                       JOIN prompt_simulations simulation
                        ON simulation.id = spec.simulation_id
                        AND simulation.project_id = spec.project_id
                        AND simulation.campaign_id IS NOT DISTINCT FROM spec.campaign_id
                        AND simulation.opportunity_id IS NOT DISTINCT FROM spec.opportunity_id
                       JOIN generation_template_releases release
                         ON release.id = simulation.template_release_id
                        AND release.project_id = simulation.project_id
                       WHERE spec.job_id = %s AND spec.project_id = %s""",
                    (lease.job_id, lease.project_id),
                )
            )
            if record is None:
                raise RuntimeError("prompt simulation job input does not exist")
            if connection.execute(
                """SELECT 1 FROM prompt_simulation_results
                   WHERE simulation_id = %s AND project_id = %s""",
                (record["simulation_id"], lease.project_id),
            ).fetchone():
                raise RuntimeError("prompt simulation already has an immutable result")
            evidence = _many(
                connection.execute(
                    """SELECT relation.evidence_item_id,
                              item.public_disclosure_allowed, item.public_source_url
                       FROM prompt_simulation_evidence relation
                       JOIN evidence_items item
                         ON item.id = relation.evidence_item_id
                        AND item.project_id = relation.project_id
                       WHERE relation.simulation_id = %s AND relation.project_id = %s
                       ORDER BY relation.ordinal""",
                    (record["simulation_id"], lease.project_id),
                )
            )
            evidence_ids = tuple(item["evidence_item_id"] for item in evidence)
            if not approved_fact_evidence_is_current(
                connection,
                project_id=lease.project_id,
                evidence_ids=evidence_ids,
            ):
                raise PlacementRuleViolation(
                    "prompt simulation Evidence includes a retired approved Fact source"
                )
            if (
                record["simulation_purpose"] != "content_preview"
                or record["question_candidate_id"] is not None
            ) and (
                record["question_candidate_id"] is None
                or not question_candidate_sources_are_current(
                    connection,
                    project_id=lease.project_id,
                    candidate_id=record["question_candidate_id"],
                )
            ):
                raise PlacementRuleViolation(
                    "prompt simulation question sources are no longer current"
                )
            snapshot = record["input_snapshot"]
            raw_contract_version = str(record["binding_contract_version"])
            lineage = (
                record["campaign_id"],
                record["opportunity_id"],
                record["binding_id"],
                record["binding_version"],
            )
            contract_version: Literal["legacy-v1", "opportunity-binding-v2"]
            if raw_contract_version == "legacy-v1":
                contract_version = "legacy-v1"
                if any(value is not None for value in lineage):
                    raise PlacementRuleViolation(
                        "legacy prompt simulation has unexpected Campaign lineage"
                    )
                expected_input_schema = "geo-prompt-simulation-input-v2"
            elif raw_contract_version == "opportunity-binding-v2":
                contract_version = "opportunity-binding-v2"
                if any(value is None for value in lineage):
                    raise PlacementRuleViolation(
                        "current prompt simulation is missing exact Campaign lineage"
                    )
                expected_input_schema = "geo-prompt-simulation-input-v3"
            else:
                raise PlacementRuleViolation("prompt simulation binding contract is unsupported")
            if snapshot.get("schema") != expected_input_schema:
                raise PlacementRuleViolation(
                    "prompt simulation frozen input contract does not match its lineage"
                )
            if canonical_hash(snapshot) != record["input_hash"]:
                raise PlacementRuleViolation("prompt simulation frozen input hash is invalid")
            connection.commit()
            return PromptSimulationClaim(
                simulation_id=record["simulation_id"],
                project_id=lease.project_id,
                input_hash=record["input_hash"],
                input_snapshot=snapshot,
                authenticity_mode=PromptSimulationAuthenticityMode(
                    str(snapshot.get("authenticity_mode", "brand_authored"))
                ),
                system_prompt=str(snapshot["system_prompt"]),
                rendered_prompt=str(snapshot["rendered_prompt"]),
                configured_model=record["configured_model"],
                model_call_budget=record["model_call_budget"],
                evidence_item_ids=evidence_ids,
                public_citation_item_ids=tuple(
                    item["evidence_item_id"]
                    for item in evidence
                    if item["public_disclosure_allowed"] and item["public_source_url"]
                ),
                output_schema=record["output_schema"],
                binding_contract_version=contract_version,
                campaign_id=record["campaign_id"],
                opportunity_id=record["opportunity_id"],
                destination_id=record["destination_id"],
                simulation_purpose=str(record["simulation_purpose"]),
                question_binding=(
                    dict(snapshot["question_binding"])
                    if isinstance(snapshot.get("question_binding"), Mapping)
                    else None
                ),
                question_candidate_id=record["question_candidate_id"],
            )
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def finalize_prompt_simulation(
        self,
        lease: WorkerLease,
        claim: PromptSimulationClaim,
        placement: GeneratedPlacement,
        result: ModelGatewayResult,
    ) -> Mapping[str, object]:
        output = {
            "content_json": dict(placement.content_json),
            "rendered_text": placement.rendered_text,
            "claims": [
                {
                    "text": generated.text,
                    "kind": generated.kind,
                    "support_status": generated.support_status,
                    "evidence_item_ids": [
                        str(evidence_id) for evidence_id in generated.evidence_item_ids
                    ],
                }
                for generated in placement.claims
            ],
            "internal_evidence_refs": [
                str(evidence_id) for evidence_id in placement.internal_evidence_refs
            ],
            "public_citation_refs": [
                str(evidence_id) for evidence_id in placement.public_citation_refs
            ],
        }
        output_hash = canonical_hash(output)
        is_legacy = claim.binding_contract_version == "legacy-v1"
        if is_legacy:
            if claim.campaign_id is not None or claim.opportunity_id is not None:
                raise PlacementRuleViolation(
                    "legacy prompt simulation cannot acquire Campaign lineage"
                )
        elif claim.campaign_id is None or claim.opportunity_id is None:
            raise PlacementRuleViolation(
                "current prompt simulation requires exact Campaign lineage"
            )
        manifest: dict[str, object] = {
            "schema": (
                "geo-prompt-simulation-result-v2"
                if is_legacy
                else "geo-prompt-simulation-result-v3"
            ),
            "simulation_id": str(claim.simulation_id),
            "project_id": str(lease.project_id),
            "test_only": True,
            "publication_eligible": False,
            "authenticity_mode": claim.authenticity_mode.value,
            "input_hash": claim.input_hash,
            "output_hash": output_hash,
            "model_call": {
                "gateway_call_log_id": str(result.call_log_id),
                "provider_request_id": result.provider_request_id,
                "configured_model": result.configured_model,
                "provider_reported_model": result.provider_reported_model,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "cost_usd": str(result.cost_usd) if result.cost_usd is not None else None,
                "finish_reason": result.finish_reason,
                "response_hash": result.response_hash,
            },
            "output": output,
        }
        if not is_legacy:
            manifest["campaign_id"] = str(claim.campaign_id)
            manifest["opportunity_id"] = str(claim.opportunity_id)
        if claim.question_binding is not None:
            manifest["question_binding"] = dict(claim.question_binding)
        manifest_hash = canonical_hash(manifest)
        storage_key = (
            f"content-simulations/{lease.project_id}/{claim.simulation_id}/"
            f"simulation-{manifest_hash}.json"
        )
        artifact_job_id = uuid5(
            NAMESPACE_URL,
            f"geo-artifact:prompt-simulation:{lease.project_id}:{claim.simulation_id}",
        )
        artifact_input = {
            "resource_kind": "prompt_simulation",
            "resource_id": str(claim.simulation_id),
            "manifest_hash": manifest_hash,
        }
        artifact_idempotency = f"artifact:prompt-simulation:{claim.simulation_id}"
        artifact_campaign_id = None if is_legacy else claim.campaign_id
        artifact_opportunity_id = None if is_legacy else claim.opportunity_id
        artifact_destination_id = None if is_legacy else claim.destination_id
        lineage_contract_version = "legacy-v1" if is_legacy else "opportunity-binding-v2"
        broker_payload = {
            "job_id": str(artifact_job_id),
            "project_id": str(lease.project_id),
        }
        if artifact_campaign_id is not None:
            broker_payload["campaign_id"] = str(artifact_campaign_id)
        with self._store.fenced_transaction(lease) as connection:
            if not approved_fact_evidence_is_current(
                connection,
                project_id=lease.project_id,
                evidence_ids=claim.evidence_item_ids,
            ):
                raise PlacementRuleViolation(
                    "prompt simulation Evidence became stale before result finalization"
                )
            if (
                claim.simulation_purpose != "content_preview"
                or claim.question_candidate_id is not None
            ) and (
                claim.question_candidate_id is None
                or not question_candidate_sources_are_current(
                    connection,
                    project_id=lease.project_id,
                    candidate_id=claim.question_candidate_id,
                )
            ):
                raise PlacementRuleViolation(
                    "prompt simulation question sources became stale before finalization"
                )
            connection.execute(
                """INSERT INTO prompt_simulation_results
                     (simulation_id, project_id, campaign_id, opportunity_id,
                      generated_by_job_id, artifact_manifest, output_hash, manifest_hash,
                      model_response_hash, storage_key, lineage_contract_version)
                   VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s,
                           %s)""",
                (
                    claim.simulation_id,
                    lease.project_id,
                    claim.campaign_id,
                    claim.opportunity_id,
                    lease.job_id,
                    json.dumps(manifest, ensure_ascii=False),
                    output_hash,
                    manifest_hash,
                    result.response_hash,
                    storage_key,
                    lineage_contract_version,
                ),
            )
            connection.execute(
                """INSERT INTO durable_jobs
                     (id, project_id, campaign_id, kind, input_hash, idempotency_key,
                      parent_job_id)
                   VALUES (%s, %s, %s, 'artifact.finalize', %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (
                    artifact_job_id,
                    lease.project_id,
                    artifact_campaign_id,
                    canonical_hash(artifact_input),
                    artifact_idempotency,
                    lease.job_id,
                ),
            )
            connection.execute(
                """INSERT INTO broker_outbox
                     (project_id, job_id, topic, payload, idempotency_key)
                   VALUES (%s, %s, 'artifact.finalize', %s::jsonb, %s)
                   ON CONFLICT (project_id, idempotency_key) DO NOTHING""",
                (
                    lease.project_id,
                    artifact_job_id,
                    json.dumps(broker_payload),
                    f"wake:artifact.finalize:{artifact_idempotency}",
                ),
            )
            connection.execute(
                """INSERT INTO artifact_finalize_outbox
                     (project_id, campaign_id, opportunity_id, destination_id, job_id,
                      resource_kind, resource_id, pending_uri, storage_key, content_hash)
                   VALUES (%s, %s, %s, %s, %s, 'prompt_simulation', %s, %s, %s, %s)""",
                (
                    lease.project_id,
                    artifact_campaign_id,
                    artifact_opportunity_id,
                    artifact_destination_id,
                    artifact_job_id,
                    claim.simulation_id,
                    (
                        "postgres://prompt_simulation_results/"
                        f"{claim.simulation_id}/artifact_manifest"
                    ),
                    storage_key,
                    manifest_hash,
                ),
            )
            details = {
                "simulation_id": str(claim.simulation_id),
                "input_hash": claim.input_hash,
                "output_hash": output_hash,
                "manifest_hash": manifest_hash,
                "response_hash": result.response_hash,
                "artifact_job_id": str(artifact_job_id),
                "test_only": True,
                "publication_eligible": False,
                "authenticity_mode": claim.authenticity_mode.value,
            }
            self._store.complete_in_transaction(
                connection,
                lease,
                result_ref=f"prompt-simulation:{claim.simulation_id}",
                details=details,
            )
        return details
