"""Opportunity-bound Prompt Bundle and generation persistence."""

from __future__ import annotations

import json
from typing import Any, Mapping
from uuid import UUID, uuid4

from geo_core.placements.domain import (
    CampaignScope,
    JobReference,
    PlacementConflict,
    PlacementRuleViolation,
    PromptBundleView,
    canonical_hash,
)
from geo_core.prompts.domain import TemplateRelease, render_bundle


_BUNDLE_VIEW_SQL = """
    SELECT bundle.id, bundle.project_id, bundle.brief_version_id,
           bundle.evidence_pack_attempt_id, bundle.template_release_id,
           bundle.bundle_hash, bundle.storage_key,
           artifact.status AS artifact_status, artifact.final_uri AS storage_uri,
           bundle.campaign_id, bundle.opportunity_id, bundle.destination_id,
           bundle.binding_id AS prompt_release_binding_id,
           bundle.binding_version AS prompt_release_binding_version,
           bundle.template_skill_version_id AS skill_version_id,
           bundle.template_release_number AS release_version,
           bundle.template_release_hash AS release_hash
    FROM prompt_bundles AS bundle
    JOIN prompt_skill_versions AS version
      ON version.id = bundle.template_skill_version_id
     AND version.project_id = bundle.project_id
    JOIN artifact_finalize_outbox AS artifact
      ON artifact.resource_id = bundle.id AND artifact.project_id = bundle.project_id
     AND artifact.resource_kind = 'prompt_bundle'
"""


class PostgresPromptBundleMixin:
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

    def create_prompt_bundle(self, **values: Any) -> PromptBundleView:
        scope: CampaignScope = values["scope"]
        command_hash = canonical_hash(
            {
                "campaign_id": str(scope.campaign_id),
                "opportunity_id": str(values["opportunity_id"]),
                "brief_version_id": str(values["brief_version_id"]),
                "evidence_pack_attempt_id": str(values["evidence_pack_attempt_id"]),
                "prompt_release_binding_id": str(values["prompt_release_binding_id"]),
                "confirmed_release_hash": values["confirmed_release_hash"],
                "variables": dict(values["variables"]),
                "model_policy_hash": values["model_policy_hash"],
                "requested_by": str(values["requested_by"]),
            }
        )
        replay = self._bundle_by_idempotency(
            project_id=scope.project_id,
            idempotency_key=values["idempotency_key"],
            command_hash=command_hash,
        )
        if replay is not None:
            return replay
        binding = _optional_row(
            self._db.execute(
                """SELECT binding.*, release.user_template, release.system_template,
                          release.variable_schema, release.compiler_version
                   FROM current_opportunity_prompt_release_bindings AS binding
                   JOIN generation_template_releases AS release
                     ON release.id = binding.template_release_id
                    AND release.project_id = binding.project_id
                   JOIN current_generation_template_release_states AS state
                     ON state.template_release_id = binding.template_release_id
                    AND state.project_id = binding.project_id
                   WHERE binding.id = %s AND binding.project_id = %s
                     AND binding.campaign_id = %s AND binding.opportunity_id = %s
                     AND binding.binding_state = 'bound' AND state.status = 'approved'
                   FOR UPDATE OF release""",
                (
                    values["prompt_release_binding_id"],
                    scope.project_id,
                    scope.campaign_id,
                    values["opportunity_id"],
                ),
            )
        )
        if binding is None:
            raise PlacementConflict("Prompt binding is stale, unbound, or not approved")
        replay = self._bundle_by_idempotency(
            project_id=scope.project_id,
            idempotency_key=values["idempotency_key"],
            command_hash=command_hash,
        )
        if replay is not None:
            return replay
        if binding["release_hash"] != values["confirmed_release_hash"]:
            raise PlacementConflict("confirmed Prompt Release hash is stale")
        template = TemplateRelease(
            id=binding["template_release_id"],
            skill_version_id=binding["skill_version_id"],
            template=binding["user_template"],
            required_variables=tuple(binding["variable_schema"].get("required", ())),
            release_hash=binding["release_hash"],
        )
        client_variables = dict(values["variables"])
        allowed = set(binding["variable_schema"].get("client_allowed", ()))
        if not set(client_variables).issubset(allowed):
            raise PlacementRuleViolation("Prompt Bundle contains non-allowlisted variables")
        if not allowed.intersection(template.required_variables).issubset(client_variables):
            raise PlacementRuleViolation("Prompt Bundle is missing required client variables")
        pack = _load_pack(
            self._db,
            scope=scope,
            opportunity_id=values["opportunity_id"],
            brief_version_id=values["brief_version_id"],
            evidence_pack_attempt_id=values["evidence_pack_attempt_id"],
        )
        evidence = _load_evidence(
            self._db,
            project_id=scope.project_id,
            attempt_id=values["evidence_pack_attempt_id"],
        )
        if not evidence:
            raise PlacementConflict("ready Evidence Pack must contain frozen items")
        brief_snapshot = {
            "goals": pack["goals"],
            "constraints": pack["constraints"],
            "primary_brand_entity_id": str(pack["primary_brand_entity_id"]),
        }
        policy_snapshot = {
            "opportunity_id": str(pack["opportunity_id"]),
            "destination_id": str(pack["destination_id"]),
            "channel": pack["publication_channel"],
            "destination_key": pack["destination_key"],
            "operation_mode": pack["operation_mode"],
            "policy_status": pack["policy_status"],
            "canonical_url": pack["canonical_url"],
            "policy_version_id": str(pack["policy_version_id"]),
            "policy_version_number": pack["policy_version_number"],
            "rules": pack["policy_rules"],
            "identity_requirements": pack["identity_requirements"],
            "disclosure_requirements": pack["disclosure_requirements"],
            "allowed_hosts": pack["allowed_hosts"],
        }
        rendered_variables = {
            **client_variables,
            "brief": _canonical_text(brief_snapshot),
            "evidence": _canonical_text(evidence),
            "destination_policy": _canonical_text(policy_snapshot),
        }
        bundle_id = uuid4()
        rendered = render_bundle(
            bundle_id=bundle_id,
            project_id=scope.project_id,
            brief_version_id=values["brief_version_id"],
            evidence_pack_id=values["evidence_pack_attempt_id"],
            template=template,
            variables=rendered_variables,
            evidence_pack_hash=pack["pack_hash"],
            model_policy_hash=values["model_policy_hash"],
        )
        snapshot = {
            "schema": "geo-prompt-bundle-v3",
            "project_id": str(scope.project_id),
            "campaign_id": str(scope.campaign_id),
            "opportunity_id": str(values["opportunity_id"]),
            "destination_id": str(pack["destination_id"]),
            "brief_version_id": str(values["brief_version_id"]),
            "evidence_pack_attempt_id": str(values["evidence_pack_attempt_id"]),
            "prompt_release_binding_id": str(binding["id"]),
            "prompt_release_binding_version": binding["binding_version"],
            "template_release_id": str(binding["template_release_id"]),
            "template_skill_version_id": str(binding["skill_version_id"]),
            "template_release_version": binding["release_number"],
            "template_release_hash": binding["release_hash"],
            "compiler_version": binding["compiler_version"],
            "system_prompt": binding["system_template"],
            "client_variables": client_variables,
            "authoritative": {
                "brief": brief_snapshot,
                "destination_policy": policy_snapshot,
                "evidence_items": evidence,
            },
            "rendered_prompt": rendered.rendered_prompt,
            "evidence_pack_hash": rendered.evidence_pack_hash,
            "model_policy_hash": rendered.model_policy_hash,
        }
        artifact_hash = canonical_hash(snapshot)
        storage_key = (
            f"content-prompts/{scope.project_id}/{scope.campaign_id}/"
            f"{values['brief_version_id']}/{bundle_id}/prompt-bundle-{artifact_hash}.json"
        )
        inserted = _optional_row(
            self._db.execute(
                """INSERT INTO prompt_bundles
                     (id, project_id, campaign_id, opportunity_id, destination_id,
                      brief_version_id, evidence_pack_attempt_id, template_release_id,
                      binding_id, binding_version, template_skill_version_id,
                      template_release_number, template_release_hash, input_snapshot,
                      storage_key, bundle_hash, idempotency_key, command_hash,
                      binding_contract_version)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s::jsonb, %s, %s, %s, %s, 'opportunity-binding-v2')
                   ON CONFLICT (project_id, idempotency_key)
                     WHERE idempotency_key IS NOT NULL DO NOTHING
                   RETURNING id""",
                (
                    bundle_id,
                    scope.project_id,
                    scope.campaign_id,
                    values["opportunity_id"],
                    pack["destination_id"],
                    values["brief_version_id"],
                    values["evidence_pack_attempt_id"],
                    binding["template_release_id"],
                    binding["id"],
                    binding["binding_version"],
                    binding["skill_version_id"],
                    binding["release_number"],
                    binding["release_hash"],
                    json.dumps(snapshot, default=str),
                    storage_key,
                    artifact_hash,
                    values["idempotency_key"],
                    command_hash,
                ),
            )
        )
        if inserted is None:
            replay = self._bundle_by_idempotency(
                project_id=scope.project_id,
                idempotency_key=values["idempotency_key"],
                command_hash=command_hash,
            )
            if replay is None:
                raise RuntimeError("Prompt Bundle idempotency conflict lost its row")
            return replay
        artifact_job = self._enqueue_job(
            project_id=scope.project_id,
            campaign_id=scope.campaign_id,
            kind="artifact.finalize",
            input_value={"resource_kind": "prompt_bundle", "resource_id": str(bundle_id)},
            idempotency_key=f"artifact:prompt-bundle:{bundle_id}",
        )
        self._db.execute(
            """INSERT INTO artifact_finalize_outbox
                 (project_id, campaign_id, opportunity_id, destination_id, job_id,
                  resource_kind, resource_id, pending_uri, storage_key, content_hash)
               VALUES (%s, %s, %s, %s, %s, 'prompt_bundle', %s, %s, %s, %s)""",
            (
                scope.project_id,
                scope.campaign_id,
                values["opportunity_id"],
                pack["destination_id"],
                artifact_job.id,
                bundle_id,
                f"postgres://prompt_bundles/{bundle_id}/input_snapshot",
                storage_key,
                artifact_hash,
            ),
        )
        view = self._get_bundle_view(project_id=scope.project_id, bundle_id=bundle_id)
        if view is None:
            raise RuntimeError("created Prompt Bundle could not be projected")
        return view

    def list_prompt_bundles(
        self, *, project_id: UUID, brief_version_id: UUID
    ) -> tuple[PromptBundleView, ...]:
        return tuple(
            _bundle_view(row)
            for row in _rows(
                self._db.execute(
                    _BUNDLE_VIEW_SQL
                    + " WHERE bundle.project_id = %s AND bundle.brief_version_id = %s"
                    + " ORDER BY bundle.created_at",
                    (project_id, brief_version_id),
                )
            )
        )

    def get_prompt_bundle(
        self, *, project_id: UUID, bundle_id: UUID
    ) -> Mapping[str, object] | None:
        rows = _rows(
            self._db.execute(
                _BUNDLE_VIEW_SQL.replace(
                    " FROM prompt_bundles AS bundle",
                    ", bundle.input_snapshot AS manifest FROM prompt_bundles AS bundle",
                )
                + " WHERE bundle.project_id = %s AND bundle.id = %s",
                (project_id, bundle_id),
            )
        )
        return rows[0] if rows else None

    def enqueue_generation(self, **values: Any) -> JobReference:
        scope: CampaignScope = values["scope"]
        bundle = _optional_row(
            self._db.execute(
                """SELECT bundle.opportunity_id
                   FROM prompt_bundles AS bundle
                   JOIN artifact_finalize_outbox AS artifact
                     ON artifact.resource_id = bundle.id AND artifact.project_id = bundle.project_id
                    AND artifact.resource_kind = 'prompt_bundle'
                   JOIN placement_opportunities AS opportunity
                     ON opportunity.id = bundle.opportunity_id
                    AND opportunity.project_id = bundle.project_id
                   WHERE bundle.id = %s AND bundle.project_id = %s
                     AND bundle.campaign_id = %s AND artifact.status = 'finalized'
                     AND opportunity.status IN ('briefing', 'in_progress') FOR UPDATE OF opportunity""",
                (values["prompt_bundle_id"], scope.project_id, scope.campaign_id),
            )
        )
        if bundle is None:
            raise PlacementConflict(
                "generation requires a finalized Bundle and generation-ready Opportunity"
            )
        job = self._enqueue_job(
            project_id=scope.project_id,
            campaign_id=scope.campaign_id,
            kind="placement.generate",
            input_value={"prompt_bundle_id": str(values["prompt_bundle_id"])},
            idempotency_key=values["idempotency_key"],
        )
        self._db.execute(
            """INSERT INTO generation_job_specs
                 (job_id, project_id, campaign_id, opportunity_id, prompt_bundle_id,
                  configured_model, model_call_budget, requested_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (job_id) DO NOTHING""",
            (
                job.id,
                scope.project_id,
                scope.campaign_id,
                bundle["opportunity_id"],
                values["prompt_bundle_id"],
                values["configured_model"],
                values["model_call_budget"],
                values["requested_by"],
            ),
        )
        return job

    def _bundle_by_idempotency(
        self, *, project_id: UUID, idempotency_key: str, command_hash: str
    ) -> PromptBundleView | None:
        row = _optional_row(
            self._db.execute(
                """SELECT id, command_hash FROM prompt_bundles
                   WHERE project_id = %s AND idempotency_key = %s""",
                (project_id, idempotency_key),
            )
        )
        if row is None:
            return None
        if row["command_hash"] != command_hash:
            raise PlacementConflict("idempotency key was already used with different input")
        return self._get_bundle_view(project_id=project_id, bundle_id=row["id"])

    def _get_bundle_view(
        self, *, project_id: UUID, bundle_id: UUID
    ) -> PromptBundleView | None:
        rows = _rows(
            self._db.execute(
                _BUNDLE_VIEW_SQL + " WHERE bundle.project_id = %s AND bundle.id = %s",
                (project_id, bundle_id),
            )
        )
        return _bundle_view(rows[0]) if rows else None


def _load_pack(
    db: Any,
    *,
    scope: CampaignScope,
    opportunity_id: UUID,
    brief_version_id: UUID,
    evidence_pack_attempt_id: UUID,
) -> dict[str, Any]:
    row = _optional_row(
        db.execute(
            """SELECT pack.pack_hash, version.goals, version.constraints,
                      brief.primary_brand_entity_id, opportunity.id AS opportunity_id,
                      destination.id AS destination_id, destination.publication_channel,
                      destination.destination_key, destination.operation_mode,
                      destination.policy_status, destination.canonical_url,
                      policy.id AS policy_version_id,
                      policy.version_number AS policy_version_number,
                      policy.rules AS policy_rules, policy.identity_requirements,
                      policy.disclosure_requirements, policy.allowed_hosts
               FROM evidence_pack_attempts AS pack
               JOIN placement_brief_versions AS version
                 ON version.id = pack.brief_version_id AND version.project_id = pack.project_id
               JOIN placement_briefs AS brief
                 ON brief.id = version.brief_id AND brief.project_id = version.project_id
               JOIN placement_opportunities AS opportunity
                 ON opportunity.id = version.opportunity_id
                AND opportunity.project_id = version.project_id
               JOIN publication_destinations AS destination
                 ON destination.id = version.destination_id
                AND destination.project_id = version.project_id
               LEFT JOIN LATERAL (
                 SELECT value.* FROM destination_policy_versions AS value
                 WHERE value.destination_id = destination.id
                   AND value.project_id = destination.project_id
                 ORDER BY value.version_number DESC LIMIT 1
               ) AS policy ON true
               WHERE pack.id = %s AND pack.project_id = %s AND pack.campaign_id = %s
                 AND pack.opportunity_id = %s AND pack.brief_version_id = %s
                 AND pack.status = 'ready'
                 AND opportunity.status IN ('briefing', 'in_progress')
               FOR UPDATE OF opportunity""",
            (
                evidence_pack_attempt_id,
                scope.project_id,
                scope.campaign_id,
                opportunity_id,
                brief_version_id,
            ),
        )
    )
    if row is None:
        raise PlacementConflict(
            "Prompt Bundle requires a ready Evidence Pack in the same Opportunity"
        )
    if row["policy_version_id"] is None or row["policy_status"] != "approved":
        raise PlacementConflict("Prompt Bundle requires an approved Destination policy")
    return row


def _load_evidence(db: Any, *, project_id: UUID, attempt_id: UUID) -> list[dict[str, Any]]:
    return _rows(
        db.execute(
            """SELECT evidence.id, evidence.item_type, evidence.subject_entity_id,
                      evidence.subject_role, evidence.snapshot_text, evidence.snapshot_uri,
                      evidence.snapshot_hash, evidence.usage_rights,
                      evidence.confidentiality, evidence.public_disclosure_allowed,
                      evidence.public_source_url, evidence.public_source_title,
                      evidence.citation_label, evidence.quotation_allowed,
                      evidence.attribution_required
               FROM evidence_pack_items AS item
               JOIN evidence_items AS evidence
                 ON evidence.id = item.evidence_item_id AND evidence.project_id = item.project_id
               WHERE item.pack_attempt_id = %s AND item.project_id = %s
               ORDER BY item.ordinal""",
            (attempt_id, project_id),
        )
    )


def _bundle_view(row: Mapping[str, Any]) -> PromptBundleView:
    return PromptBundleView(**dict(row))


def _canonical_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _optional_row(cursor: Any) -> dict[str, Any] | None:
    row = cursor.fetchone()
    if row is None:
        return None
    if isinstance(row, Mapping):
        return dict(row)
    return dict(zip((item.name for item in cursor.description), row, strict=True))


def _rows(cursor: Any) -> list[dict[str, Any]]:
    rows = cursor.fetchall()
    if not rows:
        return []
    if isinstance(rows[0], Mapping):
        return [dict(row) for row in rows]
    names = [item.name for item in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in rows]
