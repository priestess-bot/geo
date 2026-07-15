"""Prompt persistence mixin kept separate from the placement aggregate adapter."""

from __future__ import annotations

import json
import hashlib
from typing import Any, Mapping
from uuid import UUID, uuid4

from geo_core.placements.domain import (
    JobReference,
    PlacementRuleViolation,
    PromptBundleView,
    PromptReleaseView,
    PromptSkill,
    canonical_hash,
)
from geo_core.placements.default_prompts import DefaultPromptDefinition
from geo_core.prompts.domain import (
    SkillVersion,
    TemplateRelease,
    compile_template,
    render_bundle,
)


def _one(cursor: Any) -> dict[str, Any]:
    record = cursor.fetchone()
    if record is None:
        raise RuntimeError("expected PostgreSQL row was not returned")
    if isinstance(record, Mapping):
        return dict(record)
    names = [item.name for item in cursor.description]
    return dict(zip(names, record, strict=True))


def _many(cursor: Any) -> list[dict[str, Any]]:
    records = cursor.fetchall()
    if not records:
        return []
    if isinstance(records[0], Mapping):
        return [dict(record) for record in records]
    names = [item.name for item in cursor.description]
    return [dict(zip(names, record, strict=True)) for record in records]


class PostgresPromptRepositoryMixin:
    _db: Any

    def _enqueue_job(
        self,
        *,
        project_id: UUID,
        kind: str,
        input_value: Mapping[str, object],
        idempotency_key: str,
    ) -> JobReference:
        raise NotImplementedError

    def create_prompt_skill(self, *, project_id: UUID, skill_key: str) -> PromptSkill:
        record = _one(
            self._db.execute(
                """INSERT INTO prompt_skills (project_id, skill_key) VALUES (%s, %s)
                   RETURNING id, project_id, skill_key, status""",
                (project_id, skill_key),
            )
        )
        return PromptSkill(**record)

    def create_skill_version(self, **values: Any) -> SkillVersion:
        version = _one(
            self._db.execute(
                """SELECT COALESCE(MAX(version_number), 0) + 1 AS value
                   FROM prompt_skill_versions WHERE skill_id = %s""",
                (values["skill_id"],),
            )
        )["value"]
        skill_version = SkillVersion.create(
            id=uuid4(), skill_id=values["skill_id"], version=version, source=values["source"]
        )
        record = _one(
            self._db.execute(
                """INSERT INTO prompt_skill_versions
                     (id, project_id, skill_id, version_number, source_text, source_hash, created_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (
                    skill_version.id,
                    values["project_id"],
                    values["skill_id"],
                    version,
                    values["source"],
                    skill_version.source_hash,
                    values["actor_id"],
                ),
            )
        )
        if record["id"] != skill_version.id:
            raise RuntimeError("stored prompt skill version identity changed")
        return skill_version

    def create_template_release(self, **values: Any) -> PromptReleaseView:
        template: TemplateRelease = values["template"]
        source_text = str(values["source_text"]).strip()
        system_template = str(values["system_template"]).strip()
        if not source_text or not system_template:
            raise PlacementRuleViolation("prompt source and system template are required")
        variable_schema = {
            "required": template.required_variables,
            "client_allowed": values["client_variable_names"],
            "server_authoritative": ["brief", "evidence", "destination_policy"],
        }
        compiler_version = "geo-prompt-compiler-v1"
        release_hash = canonical_hash(
            {
                "source_text": source_text,
                "system_template": system_template,
                "user_template": template.template,
                "variable_schema": variable_schema,
                "output_schema": values["output_schema"],
                "compiler_version": compiler_version,
            }
        )
        release_number = _one(
            self._db.execute(
                """SELECT COALESCE(MAX(release_number), 0) + 1 AS value
                   FROM generation_template_releases WHERE skill_version_id = %s""",
                (values["skill_version_id"],),
            )
        )["value"]
        record = _one(
            self._db.execute(
                """INSERT INTO generation_template_releases
                     (id, project_id, skill_version_id, release_number, system_template,
                      user_template, variable_schema, output_schema, compiler_version, release_hash)
                   VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
                   RETURNING id, project_id, skill_version_id, release_number, release_hash,
                             system_template, user_template, variable_schema, output_schema,
                             compiler_version""",
                (
                    template.id,
                    values["project_id"],
                    values["skill_version_id"],
                    release_number,
                    system_template,
                    template.template,
                    json.dumps(variable_schema),
                    json.dumps(values["output_schema"]),
                    compiler_version,
                    release_hash,
                ),
            )
        )
        record["source_text"] = source_text
        return PromptReleaseView(**record)

    def install_default_prompt_catalog(
        self,
        *,
        project_id: UUID,
        definitions: tuple[DefaultPromptDefinition, ...],
        output_schema: Mapping[str, object],
        actor_id: UUID,
    ) -> tuple[Mapping[str, object], ...]:
        _one(
            self._db.execute(
                "SELECT id FROM projects WHERE id = %s FOR UPDATE", (project_id,)
            )
        )
        bindings: list[Mapping[str, object]] = []
        for definition in definitions:
            current = _many(
                self._db.execute(
                    """SELECT project_id, task_key, template_release_id,
                              selected_by, selected_at
                       FROM content_task_prompt_releases
                       WHERE project_id = %s AND task_key = %s""",
                    (project_id, definition.task_key),
                )
            )
            if current:
                bindings.append(current[0])
                continue
            skills = _many(
                self._db.execute(
                    """SELECT id, project_id, skill_key, status FROM prompt_skills
                       WHERE project_id = %s AND skill_key = %s""",
                    (project_id, definition.skill_key),
                )
            )
            skill = (
                PromptSkill(**skills[0])
                if skills
                else self.create_prompt_skill(
                    project_id=project_id, skill_key=definition.skill_key
                )
            )
            source_hash = hashlib.sha256(definition.source.encode("utf-8")).hexdigest()
            releases = _many(
                self._db.execute(
                    """SELECT r.id FROM generation_template_releases r
                       JOIN prompt_skill_versions v
                         ON v.id = r.skill_version_id AND v.project_id = r.project_id
                       WHERE r.project_id = %s AND v.skill_id = %s
                         AND v.source_hash = %s AND r.output_schema = %s::jsonb
                         AND r.system_template = %s AND r.user_template = %s
                       ORDER BY r.release_number LIMIT 1""",
                    (
                        project_id,
                        skill.id,
                        source_hash,
                        json.dumps(output_schema),
                        definition.system_template,
                        definition.source,
                    ),
                )
            )
            if releases:
                release_id = releases[0]["id"]
            else:
                version = self.create_skill_version(
                    project_id=project_id,
                    skill_id=skill.id,
                    source=definition.source,
                    actor_id=actor_id,
                )
                template = compile_template(release_id=uuid4(), skill=version)
                release_id = self.create_template_release(
                    project_id=project_id,
                    skill_version_id=version.id,
                    template=template,
                    source_text=version.source,
                    system_template=definition.system_template,
                    output_schema=output_schema,
                    client_variable_names=(),
                ).id
            bindings.append(
                self.select_prompt_release(
                    project_id=project_id,
                    task_key=definition.task_key,
                    release_id=release_id,
                    selected_by=actor_id,
                )
            )
        return tuple(bindings)

    def get_template_release(self, *, project_id: UUID, release_id: UUID) -> TemplateRelease | None:
        records = _many(
            self._db.execute(
                """SELECT id, skill_version_id, user_template, variable_schema, release_hash
                   FROM generation_template_releases WHERE project_id = %s AND id = %s""",
                (project_id, release_id),
            )
        )
        if not records:
            return None
        row = records[0]
        return TemplateRelease(
            id=row["id"],
            skill_version_id=row["skill_version_id"],
            template=row["user_template"],
            required_variables=tuple(row["variable_schema"].get("required", ())),
            release_hash=row["release_hash"],
        )

    def create_prompt_bundle(self, **values: Any) -> PromptBundleView:
        release = self.get_template_release(
            project_id=values["project_id"], release_id=values["release_id"]
        )
        if release is None:
            raise RuntimeError("template release disappeared")
        release_record = _one(
            self._db.execute(
                """SELECT system_template, variable_schema, release_hash, compiler_version
                   FROM generation_template_releases
                   WHERE id = %s AND project_id = %s""",
                (values["release_id"], values["project_id"]),
            )
        )
        client_variables = dict(values["variables"])
        allowed = set(release_record["variable_schema"].get("client_allowed", ()))
        if not set(client_variables).issubset(allowed):
            raise PlacementRuleViolation("prompt bundle contains non-allowlisted client variables")
        required_client = allowed.intersection(release.required_variables)
        if not required_client.issubset(client_variables):
            raise PlacementRuleViolation("prompt bundle is missing required client variables")
        pack = _one(
            self._db.execute(
                """SELECT p.pack_hash, bv.goals, bv.constraints, b.primary_brand_entity_id,
                          o.id AS opportunity_id, d.id AS destination_id,
                          d.publication_channel, d.destination_key, d.operation_mode,
                          d.policy_status, d.canonical_url, pv.id AS policy_version_id,
                          pv.version_number AS policy_version_number, pv.rules AS policy_rules,
                          pv.identity_requirements, pv.disclosure_requirements,
                          pv.allowed_hosts
                   FROM evidence_pack_attempts p
                   JOIN placement_brief_versions bv
                     ON bv.id = p.brief_version_id AND bv.project_id = p.project_id
                   JOIN placement_briefs b
                     ON b.id = bv.brief_id AND b.project_id = bv.project_id
                   JOIN placement_opportunities o
                     ON o.id = b.opportunity_id AND o.project_id = b.project_id
                   JOIN publication_destinations d
                     ON d.id = o.destination_id AND d.project_id = o.project_id
                   JOIN LATERAL (
                     SELECT * FROM destination_policy_versions value
                     WHERE value.destination_id = d.id AND value.project_id = d.project_id
                     ORDER BY value.version_number DESC LIMIT 1
                   ) pv ON true
                   WHERE p.id = %s AND p.project_id = %s AND p.status = 'ready'
                     AND bv.id = %s AND o.status IN ('qualified', 'in_progress')""",
                (
                    values["evidence_pack_attempt_id"],
                    values["project_id"],
                    values["brief_version_id"],
                ),
            )
        )
        evidence = _many(
            self._db.execute(
                """SELECT e.id, e.item_type, e.subject_entity_id, e.subject_role,
                          e.snapshot_text, e.snapshot_uri, e.snapshot_hash, e.usage_rights,
                          e.confidentiality, e.public_disclosure_allowed,
                          e.public_source_url, e.public_source_title, e.citation_label,
                          e.quotation_allowed, e.attribution_required
                   FROM evidence_pack_items pi JOIN evidence_items e
                     ON e.id = pi.evidence_item_id AND e.project_id = pi.project_id
                   WHERE pi.pack_attempt_id = %s AND pi.project_id = %s
                   ORDER BY pi.ordinal""",
                (values["evidence_pack_attempt_id"], values["project_id"]),
            )
        )
        if not evidence:
            raise PlacementRuleViolation("ready evidence pack must contain frozen items")
        selected_release = self._db.execute(
            """SELECT template_release_id FROM content_task_prompt_releases
               WHERE project_id = %s AND task_key = %s""",
            (values["project_id"], pack["publication_channel"]),
        ).fetchone()
        if selected_release is None or selected_release[0] != values["release_id"]:
            raise PlacementRuleViolation(
                "prompt release is not selected for the destination task key"
            )
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
        authoritative_variables = {
            "brief": json.dumps(brief_snapshot, ensure_ascii=False, sort_keys=True),
            "evidence": json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str),
            "destination_policy": json.dumps(policy_snapshot, ensure_ascii=False, sort_keys=True),
        }
        rendered_variables = {**client_variables, **authoritative_variables}
        bundle_id = uuid4()
        bundle = render_bundle(
            bundle_id=bundle_id,
            project_id=values["project_id"],
            brief_version_id=values["brief_version_id"],
            evidence_pack_id=values["evidence_pack_attempt_id"],
            template=release,
            variables=rendered_variables,
            evidence_pack_hash=pack["pack_hash"],
            model_policy_hash=values["model_policy_hash"],
        )
        snapshot = {
            "schema": "geo-prompt-bundle-v2",
            "project_id": str(values["project_id"]),
            "brief_version_id": str(values["brief_version_id"]),
            "evidence_pack_attempt_id": str(values["evidence_pack_attempt_id"]),
            "template_release_id": str(values["release_id"]),
            "template_release_hash": release_record["release_hash"],
            "compiler_version": release_record["compiler_version"],
            "system_prompt": release_record["system_template"],
            "client_variables": client_variables,
            "authoritative": {
                "brief": brief_snapshot,
                "destination_policy": policy_snapshot,
                "evidence_items": evidence,
            },
            "rendered_prompt": bundle.rendered_prompt,
            "evidence_pack_hash": bundle.evidence_pack_hash,
            "model_policy_hash": bundle.model_policy_hash,
        }
        artifact_hash = canonical_hash(snapshot)
        storage_key = (
            f"content-prompts/{values['project_id']}/{values['brief_version_id']}/"
            f"{bundle_id}/prompt-bundle-{artifact_hash}.json"
        )
        self._db.execute(
            """INSERT INTO prompt_bundles
                 (id, project_id, brief_version_id, evidence_pack_attempt_id,
                  template_release_id, input_snapshot, storage_key, bundle_hash)
               VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)""",
            (
                bundle_id,
                values["project_id"],
                values["brief_version_id"],
                values["evidence_pack_attempt_id"],
                values["release_id"],
                json.dumps(snapshot, default=str),
                storage_key,
                artifact_hash,
            ),
        )
        artifact_job = self._enqueue_job(
            project_id=values["project_id"],
            kind="artifact.finalize",
            input_value={"resource_kind": "prompt_bundle", "resource_id": str(bundle_id)},
            idempotency_key=f"artifact:prompt-bundle:{bundle_id}",
        )
        self._db.execute(
            """INSERT INTO artifact_finalize_outbox
                 (project_id, job_id, resource_kind, resource_id, pending_uri,
                  storage_key, content_hash)
               VALUES (%s, %s, 'prompt_bundle', %s, %s, %s, %s)""",
            (
                values["project_id"],
                artifact_job.id,
                bundle_id,
                f"postgres://prompt_bundles/{bundle_id}/input_snapshot",
                storage_key,
                artifact_hash,
            ),
        )
        return PromptBundleView(
            bundle_id,
            values["project_id"],
            values["brief_version_id"],
            values["evidence_pack_attempt_id"],
            values["release_id"],
            artifact_hash,
            storage_key,
            "pending",
            None,
        )

    def list_prompt_skills(self, *, project_id: UUID) -> tuple[PromptSkill, ...]:
        return tuple(
            PromptSkill(**row)
            for row in _many(
                self._db.execute(
                    """SELECT id, project_id, skill_key, status FROM prompt_skills
                       WHERE project_id = %s ORDER BY created_at""",
                    (project_id,),
                )
            )
        )

    def list_prompt_releases(
        self, *, project_id: UUID, skill_id: UUID
    ) -> tuple[PromptReleaseView, ...]:
        rows = _many(
            self._db.execute(
                """SELECT r.id, r.project_id, r.skill_version_id,
                          r.release_number, r.release_hash, v.source_text,
                          r.system_template, r.user_template, r.variable_schema,
                          r.output_schema, r.compiler_version
                   FROM generation_template_releases r JOIN prompt_skill_versions v
                     ON v.id = r.skill_version_id AND v.project_id = r.project_id
                   WHERE r.project_id = %s AND v.skill_id = %s ORDER BY r.release_number""",
                (project_id, skill_id),
            )
        )
        return tuple(PromptReleaseView(**row) for row in rows)

    def list_prompt_bundles(
        self, *, project_id: UUID, brief_version_id: UUID
    ) -> tuple[PromptBundleView, ...]:
        rows = _many(
            self._db.execute(
                """SELECT b.id, b.project_id, b.brief_version_id,
                          b.evidence_pack_attempt_id, b.template_release_id, b.bundle_hash,
                          b.storage_key, a.status AS artifact_status,
                          a.final_uri AS storage_uri
                   FROM prompt_bundles b JOIN artifact_finalize_outbox a
                     ON a.resource_id = b.id AND a.project_id = b.project_id
                    AND a.resource_kind = 'prompt_bundle'
                   WHERE b.project_id = %s AND b.brief_version_id = %s
                   ORDER BY b.created_at""",
                (project_id, brief_version_id),
            )
        )
        return tuple(PromptBundleView(**row) for row in rows)

    def get_prompt_bundle(
        self, *, project_id: UUID, bundle_id: UUID
    ) -> Mapping[str, object] | None:
        records = _many(
            self._db.execute(
                """SELECT b.id, b.project_id, b.brief_version_id,
                          b.evidence_pack_attempt_id, b.template_release_id, b.bundle_hash,
                          b.storage_key, a.status AS artifact_status,
                          a.final_uri AS storage_uri, b.input_snapshot AS manifest
                   FROM prompt_bundles b JOIN artifact_finalize_outbox a
                     ON a.resource_id = b.id AND a.project_id = b.project_id
                    AND a.resource_kind = 'prompt_bundle'
                   WHERE b.project_id = %s AND b.id = %s""",
                (project_id, bundle_id),
            )
        )
        return records[0] if records else None

    def select_prompt_release(
        self,
        *,
        project_id: UUID,
        task_key: str,
        release_id: UUID,
        selected_by: UUID,
    ) -> Mapping[str, object]:
        return _one(
            self._db.execute(
                """INSERT INTO content_task_prompt_releases
                     (project_id, task_key, template_release_id, selected_by)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (project_id, task_key) DO UPDATE
                     SET template_release_id = EXCLUDED.template_release_id,
                         selected_by = EXCLUDED.selected_by,
                         selected_at = clock_timestamp()
                   RETURNING project_id, task_key,
                     template_release_id, selected_by, selected_at""",
                (project_id, task_key, release_id, selected_by),
            )
        )

    def list_prompt_release_selections(
        self, *, project_id: UUID
    ) -> tuple[Mapping[str, object], ...]:
        return tuple(
            _many(
                self._db.execute(
                    """SELECT project_id, task_key, template_release_id,
                              selected_by, selected_at
                       FROM content_task_prompt_releases
                       WHERE project_id = %s ORDER BY task_key""",
                    (project_id,),
                )
            )
        )

    def enqueue_generation(self, **values: Any) -> JobReference:
        finalized = self._db.execute(
            """SELECT 1 FROM artifact_finalize_outbox
               WHERE project_id = %s AND resource_kind = 'prompt_bundle'
                 AND resource_id = %s AND status = 'finalized'""",
            (values["project_id"], values["prompt_bundle_id"]),
        ).fetchone()
        if finalized is None:
            raise PlacementRuleViolation("prompt bundle artifact is not finalized")
        eligible = self._db.execute(
            """SELECT 1 FROM prompt_bundles pb
               JOIN placement_brief_versions bv
                 ON bv.id = pb.brief_version_id AND bv.project_id = pb.project_id
               JOIN placement_briefs b ON b.id = bv.brief_id AND b.project_id = bv.project_id
               JOIN placement_opportunities o
                 ON o.id = b.opportunity_id AND o.project_id = b.project_id
               WHERE pb.id = %s AND pb.project_id = %s
                 AND o.status IN ('qualified', 'in_progress')""",
            (values["prompt_bundle_id"], values["project_id"]),
        ).fetchone()
        if eligible is None:
            raise PlacementRuleViolation("generation requires a qualified opportunity")
        job = self._enqueue_job(
            project_id=values["project_id"],
            kind="placement.generate",
            input_value={"prompt_bundle_id": str(values["prompt_bundle_id"])},
            idempotency_key=values["idempotency_key"],
        )
        self._db.execute(
            """INSERT INTO generation_job_specs
                 (job_id, project_id, prompt_bundle_id, configured_model, model_call_budget,
                  requested_by)
               VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (job_id) DO NOTHING""",
            (
                job.id,
                values["project_id"],
                values["prompt_bundle_id"],
                values["configured_model"],
                values["model_call_budget"],
                values["requested_by"],
            ),
        )
        return job
