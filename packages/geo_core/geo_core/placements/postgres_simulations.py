"""PostgreSQL persistence for isolated prompt simulations."""

from __future__ import annotations

import json
from typing import Any, Mapping
from uuid import NAMESPACE_URL, UUID, uuid5

from geo_core.placements.domain import (
    JobReference,
    PlacementRuleViolation,
    canonical_hash,
)
from geo_core.placements.simulation import PromptSimulation
from geo_core.prompts.domain import TemplateRelease, render_template


def _one(cursor: Any) -> dict[str, Any] | None:
    record = cursor.fetchone()
    if record is None:
        return None
    if isinstance(record, Mapping):
        return dict(record)
    return dict(zip((item.name for item in cursor.description), record, strict=True))


def _many(cursor: Any) -> list[dict[str, Any]]:
    records = cursor.fetchall()
    if not records:
        return []
    if isinstance(records[0], Mapping):
        return [dict(record) for record in records]
    names = [item.name for item in cursor.description]
    return [dict(zip(names, record, strict=True)) for record in records]


class PostgresPromptSimulationMixin:
    _db: Any

    def _enqueue_job(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        kind: str,
        input_value: Mapping[str, object],
        idempotency_key: str,
    ) -> JobReference:
        raise NotImplementedError

    def create_prompt_simulation(self, **values: Any) -> tuple[PromptSimulation, JobReference]:
        destination = self._destination_snapshot(
            project_id=values["project_id"], destination_id=values["destination_id"]
        )
        release = self._release_snapshot(
            project_id=values["project_id"],
            campaign_id=values["campaign_id"],
            opportunity_id=values["opportunity_id"],
            destination_id=values["destination_id"],
            binding_id=values["prompt_release_binding_id"],
            confirmed_release_hash=values["confirmed_release_hash"],
        )
        subjects = self._subject_snapshots(
            project_id=values["project_id"],
            brand_id=values["primary_brand_entity_id"],
            product_id=values["product_entity_id"],
        )
        evidence = self._evidence_snapshots(
            project_id=values["project_id"],
            evidence_ids=values["evidence_item_ids"],
            subject_ids={values["primary_brand_entity_id"], values["product_entity_id"]},
        )
        question_binding = self._question_binding(values)
        client_variables = dict(values["variables"])
        allowed = set(release["variable_schema"].get("client_allowed", ()))
        if not set(client_variables).issubset(allowed):
            raise PlacementRuleViolation(
                "prompt simulation contains non-allowlisted client variables"
            )
        required = set(release["variable_schema"].get("required", ()))
        if not allowed.intersection(required).issubset(client_variables):
            raise PlacementRuleViolation("prompt simulation is missing required client variables")
        brief_snapshot = {
            "goals": dict(values["goals"]),
            "constraints": dict(values["constraints"]),
            "primary_brand": subjects["brand"],
            "product": subjects["product"],
        }
        if question_binding is not None:
            brief_snapshot["geo_test_question"] = question_binding
        policy_snapshot = {
            **destination,
            "technical_preview_only": True,
            "publication_eligible": False,
        }
        authoritative_variables = {
            "brief": json.dumps(
                brief_snapshot, ensure_ascii=False, sort_keys=True, default=str
            ),
            "evidence": json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str),
            "destination_policy": json.dumps(
                policy_snapshot, ensure_ascii=False, sort_keys=True, default=str
            ),
        }
        template = TemplateRelease(
            id=release["id"],
            skill_version_id=release["skill_version_id"],
            template=release["user_template"],
            required_variables=tuple(release["variable_schema"].get("required", ())),
            release_hash=release["release_hash"],
        )
        rendered_prompt = render_template(
            template=template,
            variables={**client_variables, **authoritative_variables},
        )
        simulation_id = uuid5(
            NAMESPACE_URL,
            f"geo-prompt-simulation:{values['project_id']}:{values['idempotency_key']}",
        )
        snapshot = {
            "schema": "geo-prompt-simulation-input-v3",
            "simulation_id": str(simulation_id),
            "project_id": str(values["project_id"]),
            "campaign_id": str(values["campaign_id"]),
            "opportunity_id": str(values["opportunity_id"]),
            "test_only": True,
            "publication_eligible": False,
            "authenticity_mode": values["authenticity_mode"],
            "template_release": {
                "id": str(release["id"]),
                "binding_id": str(release["binding_id"]),
                "binding_version": release["binding_version"],
                "skill_version_id": str(release["skill_version_id"]),
                "release_number": release["release_number"],
                "release_hash": release["release_hash"],
                "compiler_version": release["compiler_version"],
            },
            "destination": policy_snapshot,
            "brief": brief_snapshot,
            "evidence_items": evidence,
            "client_variables": client_variables,
            "system_prompt": release["system_template"],
            "rendered_prompt": rendered_prompt,
            "model_policy_hash": values["model_policy_hash"],
            "configured_model": values["configured_model"],
            "model_call_budget": values["model_call_budget"],
        }
        if question_binding is not None:
            snapshot["question_binding"] = question_binding
        input_hash = canonical_hash(snapshot)
        self._db.execute(
            """INSERT INTO prompt_simulations
                 (id, project_id, campaign_id, opportunity_id, destination_id,
                  destination_policy_version_id, binding_id, binding_version,
                  template_release_id, template_skill_version_id,
                  template_release_number, template_release_hash,
                  primary_brand_entity_id, product_entity_id, requested_by,
                  input_snapshot, input_hash, binding_contract_version,
                  simulation_purpose, question_set_id, question_set_hash,
                  question_set_item_id, question_candidate_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s::jsonb, %s, 'opportunity-binding-v2',
                       %s, %s, %s, %s, %s)
               ON CONFLICT (id) DO NOTHING""",
            (
                simulation_id,
                values["project_id"],
                values["campaign_id"],
                values["opportunity_id"],
                values["destination_id"],
                destination["policy_version_id"],
                release["binding_id"],
                release["binding_version"],
                release["id"],
                release["skill_version_id"],
                release["release_number"],
                release["release_hash"],
                values["primary_brand_entity_id"],
                values["product_entity_id"],
                values["requested_by"],
                json.dumps(snapshot, ensure_ascii=False, default=str),
                input_hash,
                values.get("simulation_purpose", "content_preview"),
                values.get("question_set_id"),
                values.get("confirmed_question_set_hash"),
                values.get("question_set_item_id"),
                question_binding["candidate_id"] if question_binding is not None else None,
            ),
        )
        for ordinal, item in enumerate(evidence):
            self._db.execute(
                """INSERT INTO prompt_simulation_evidence
                     (simulation_id, project_id, evidence_item_id, ordinal)
                   VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                (simulation_id, values["project_id"], item["id"], ordinal),
            )
        job = self._enqueue_job(
            project_id=values["project_id"],
            campaign_id=values["campaign_id"],
            kind="prompt_simulation.generate",
            input_value={
                "simulation_id": str(simulation_id),
                "input_hash": input_hash,
                "configured_model": values["configured_model"],
                "model_call_budget": values["model_call_budget"],
            },
            idempotency_key=values["idempotency_key"],
        )
        self._db.execute(
            """INSERT INTO prompt_simulation_job_specs
                 (job_id, project_id, campaign_id, opportunity_id, simulation_id,
                  configured_model, model_call_budget, requested_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (job_id) DO NOTHING""",
            (
                job.id,
                values["project_id"],
                values["campaign_id"],
                values["opportunity_id"],
                simulation_id,
                values["configured_model"],
                values["model_call_budget"],
                values["requested_by"],
            ),
        )
        simulation = self.get_prompt_simulation(
            project_id=values["project_id"], simulation_id=simulation_id
        )
        if simulation is None:
            raise RuntimeError("prompt simulation disappeared during creation")
        if simulation.input_hash != input_hash:
            raise PlacementRuleViolation(
                "idempotency key was already used with different simulation input"
            )
        return simulation, job

    def list_prompt_simulations(
        self, *, project_id: UUID, campaign_id: UUID
    ) -> tuple[PromptSimulation, ...]:
        return tuple(
            self._simulation(record, include_payload=False)
            for record in _many(
                self._db.execute(
                    self._select(False)
                    + " ORDER BY simulation.created_at DESC, simulation.id DESC",
                    (project_id, campaign_id),
                )
            )
        )

    def get_prompt_simulation(
        self, *, project_id: UUID, simulation_id: UUID
    ) -> PromptSimulation | None:
        record = _one(
            self._db.execute(
                self._select(True) + " AND simulation.id = %s",
                (project_id, None, simulation_id),
            )
        )
        return self._simulation(record, include_payload=True) if record else None

    @staticmethod
    def _select(include_payload: bool) -> str:
        payload = (
            ", simulation.input_snapshot, result.artifact_manifest"
            if include_payload
            else ""
        )
        return f"""SELECT simulation.id, simulation.project_id, simulation.campaign_id,
                          simulation.opportunity_id, simulation.destination_id,
                          simulation.destination_policy_version_id,
                          simulation.template_release_id,
                          simulation.binding_id AS prompt_release_binding_id,
                          simulation.binding_version AS prompt_release_binding_version,
                          simulation.template_skill_version_id AS skill_version_id,
                          simulation.template_release_number AS release_version,
                          simulation.template_release_hash AS release_hash,
                          simulation.primary_brand_entity_id, simulation.product_entity_id,
                          simulation.simulation_purpose, simulation.question_set_id,
                          simulation.question_set_hash, simulation.question_set_item_id,
                          simulation.question_candidate_id,
                          COALESCE(
                            simulation.input_snapshot ->> 'authenticity_mode',
                            'brand_authored'
                          ) AS authenticity_mode,
                          simulation.requested_by, simulation.input_hash,
                          simulation.test_only, simulation.publication_eligible,
                          simulation.created_at, latest.job_id AS generation_job_id,
                          latest.status AS generation_status, latest.configured_model,
                          latest.model_call_budget,
                          COALESCE(artifact.status, 'not_created') AS artifact_status,
                          artifact.final_uri AS artifact_uri, result.storage_key,
                          result.output_hash, result.manifest_hash,
                          result.model_response_hash{payload}
                   FROM prompt_simulations simulation
                   JOIN LATERAL (
                     SELECT spec.job_id, job.status, spec.configured_model,
                            spec.model_call_budget
                     FROM prompt_simulation_job_specs spec
                     JOIN durable_jobs job
                       ON job.id = spec.job_id AND job.project_id = spec.project_id
                     WHERE spec.simulation_id = simulation.id
                       AND spec.project_id = simulation.project_id
                     ORDER BY job.created_at DESC, job.id DESC LIMIT 1
                   ) latest ON true
                   LEFT JOIN prompt_simulation_results result
                     ON result.simulation_id = simulation.id
                    AND result.project_id = simulation.project_id
                   LEFT JOIN artifact_finalize_outbox artifact
                     ON artifact.resource_kind = 'prompt_simulation'
                    AND artifact.resource_id = simulation.id
                    AND artifact.project_id = simulation.project_id
                   WHERE simulation.project_id = %s
                     AND simulation.campaign_id =
                         COALESCE(%s::uuid, simulation.campaign_id)"""

    @staticmethod
    def _simulation(record: Mapping[str, Any], *, include_payload: bool) -> PromptSimulation:
        values = dict(record)
        if not include_payload:
            values["input_snapshot"] = None
            values["artifact_manifest"] = None
        return PromptSimulation(**values)

    def _question_binding(self, values: Mapping[str, Any]) -> dict[str, object] | None:
        purpose = str(values.get("simulation_purpose", "content_preview"))
        if purpose == "content_preview":
            return None
        record = _one(
            self._db.execute(
                """SELECT question_set.id AS question_set_id,
                          question_set.content_hash AS question_set_hash,
                          item.id AS item_id, item.question_candidate_id AS candidate_id,
                          item.query_text_snapshot AS question_text,
                          item.dimension_key,
                          COALESCE((
                            SELECT array_agg(source.fact_candidate_id ORDER BY source.fact_candidate_id)
                            FROM knowledge_question_candidate_fact_sources source
                            WHERE source.candidate_id = item.question_candidate_id
                          ), ARRAY[]::uuid[]) AS source_fact_ids,
                          COALESCE((
                            SELECT array_agg(source.graph_entity_id ORDER BY source.graph_entity_id)
                            FROM knowledge_question_candidate_entity_sources source
                            WHERE source.candidate_id = item.question_candidate_id
                          ), ARRAY[]::uuid[]) AS source_entity_ids
                   FROM knowledge_question_sets question_set
                   JOIN knowledge_question_set_items item
                     ON item.question_set_id = question_set.id
                    AND item.project_id = question_set.project_id
                    AND item.campaign_id = question_set.campaign_id
                   JOIN knowledge_question_candidates candidate
                     ON candidate.id = item.question_candidate_id
                    AND candidate.project_id = item.project_id
                    AND candidate.campaign_id = item.campaign_id
                   WHERE question_set.id = %s AND question_set.project_id = %s
                     AND question_set.campaign_id = %s
                     AND question_set.content_hash = %s
                     AND question_set.status = 'frozen' AND item.id = %s
                     AND candidate.workflow_status = 'approved'
                     AND geo_question_candidate_sources_current(candidate.id)
                   FOR SHARE OF question_set, candidate""",
                (
                    values.get("question_set_id"),
                    values["project_id"],
                    values["campaign_id"],
                    values.get("confirmed_question_set_hash"),
                    values.get("question_set_item_id"),
                ),
            )
        )
        if record is None:
            raise PlacementRuleViolation(
                "GEO simulation requires an approved current item from the frozen QuestionSet"
            )
        return {
            "question_set_id": str(record["question_set_id"]),
            "question_set_hash": str(record["question_set_hash"]),
            "item_id": str(record["item_id"]),
            "candidate_id": str(record["candidate_id"]),
            "question_text": str(record["question_text"]),
            "dimension_key": str(record["dimension_key"]),
            "source_fact_ids": [str(value) for value in record["source_fact_ids"]],
            "source_entity_ids": [str(value) for value in record["source_entity_ids"]],
        }

    def _destination_snapshot(self, *, project_id: UUID, destination_id: UUID) -> dict[str, Any]:
        record = _one(
            self._db.execute(
                """SELECT destination.id, destination.publication_channel,
                          destination.destination_key, destination.operation_mode,
                          destination.destination_account_id, destination.canonical_url,
                          destination.allowed_hosts, destination.policy_status,
                          policy.id AS policy_version_id,
                          policy.version_number AS policy_version_number,
                          policy.status AS policy_version_status, policy.rules,
                          policy.identity_requirements, policy.disclosure_requirements
                   FROM publication_destinations destination
                   LEFT JOIN LATERAL (
                     SELECT value.id, value.version_number, value.status, value.rules,
                            value.identity_requirements, value.disclosure_requirements
                     FROM destination_policy_versions value
                     WHERE value.destination_id = destination.id
                       AND value.project_id = destination.project_id
                     ORDER BY value.version_number DESC LIMIT 1
                   ) policy ON true
                   WHERE destination.project_id = %s AND destination.id = %s""",
                (project_id, destination_id),
            )
        )
        if record is None:
            raise PlacementRuleViolation("prompt simulation destination does not exist")
        return record

    def _release_snapshot(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        opportunity_id: UUID,
        destination_id: UUID,
        binding_id: UUID,
        confirmed_release_hash: str,
    ) -> dict[str, Any]:
        record = _one(
            self._db.execute(
                """SELECT release.id, release.skill_version_id, release.release_number,
                          release.release_hash, binding.id AS binding_id,
                          binding.binding_version,
                          release.compiler_version, release.system_template,
                          release.user_template, release.variable_schema,
                          release.output_schema
                   FROM current_opportunity_prompt_release_bindings binding
                   JOIN generation_template_releases release
                     ON release.id = binding.template_release_id
                    AND release.project_id = binding.project_id
                   JOIN current_generation_template_release_states state
                     ON state.template_release_id = release.id
                    AND state.project_id = release.project_id
                   WHERE binding.id = %s AND binding.project_id = %s
                     AND binding.campaign_id = %s AND binding.opportunity_id = %s
                     AND binding.destination_id = %s AND binding.binding_state = 'bound'
                     AND binding.release_hash = %s AND state.status = 'approved'
                   FOR UPDATE OF release""",
                (
                    binding_id,
                    project_id,
                    campaign_id,
                    opportunity_id,
                    destination_id,
                    confirmed_release_hash,
                ),
            )
        )
        if record is None:
            raise PlacementRuleViolation(
                "prompt simulation binding is stale, unbound, or not approved"
            )
        return record

    def _subject_snapshots(
        self, *, project_id: UUID, brand_id: UUID, product_id: UUID
    ) -> dict[str, dict[str, Any]]:
        records = _many(
            self._db.execute(
                """SELECT id, entity_type, canonical_name, canonical_url, attributes
                   FROM product_entities WHERE project_id = %s AND id = ANY(%s)
                     AND status = 'active'""",
                (project_id, [brand_id, product_id]),
            )
        )
        by_id = {record["id"]: record for record in records}
        if by_id.get(brand_id, {}).get("entity_type") != "brand":
            raise PlacementRuleViolation("primary brand must reference an active brand entity")
        if by_id.get(product_id, {}).get("entity_type") != "product":
            raise PlacementRuleViolation("product must reference an active product entity")
        return {"brand": by_id[brand_id], "product": by_id[product_id]}

    def _evidence_snapshots(
        self,
        *,
        project_id: UUID,
        evidence_ids: tuple[UUID, ...],
        subject_ids: set[UUID],
    ) -> list[dict[str, Any]]:
        records = _many(
            self._db.execute(
                """SELECT id, item_type, subject_entity_id, subject_role,
                          snapshot_text, snapshot_uri, snapshot_hash, usage_rights,
                          confidentiality, public_disclosure_allowed, public_source_url,
                          public_source_title, citation_label, quotation_allowed,
                          attribution_required
                   FROM evidence_items WHERE project_id = %s AND id = ANY(%s)
                     AND usage_rights IN
                       ('owned', 'licensed', 'public_reference', 'authorised_experience')
                     AND confidentiality <> 'restricted'""",
                (project_id, list(evidence_ids)),
            )
        )
        by_id = {record["id"]: record for record in records}
        if set(by_id) != set(evidence_ids):
            raise PlacementRuleViolation(
                "prompt simulation evidence is missing or not eligible for generation"
            )
        ordered = [by_id[evidence_id] for evidence_id in evidence_ids]
        invalid_subject = next(
            (
                item
                for item in ordered
                if item["subject_role"] not in {"market", "neutral"}
                and item["subject_entity_id"] not in subject_ids
            ),
            None,
        )
        if invalid_subject is not None:
            raise PlacementRuleViolation(
                "prompt simulation evidence belongs to an unapproved subject"
            )
        return ordered
