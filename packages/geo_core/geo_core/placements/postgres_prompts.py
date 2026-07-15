"""Prompt persistence mixin kept separate from the placement aggregate adapter."""

from __future__ import annotations

import json
from typing import Any, Mapping
from uuid import UUID, uuid4

from geo_core.placements.domain import (
    JobReference,
    PromptBundleView,
    PromptReleaseView,
    PromptSkill,
)
from geo_core.prompts.domain import SkillVersion, TemplateRelease, render_bundle


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
                    skill_version.id, values["project_id"], values["skill_id"],
                    version, values["source"],
                    skill_version.source_hash, values["actor_id"],
                ),
            )
        )
        if record["id"] != skill_version.id:
            raise RuntimeError("stored prompt skill version identity changed")
        return skill_version

    def create_template_release(self, **values: Any) -> PromptReleaseView:
        template: TemplateRelease = values["template"]
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
                   RETURNING id, project_id, skill_version_id, release_number, release_hash""",
                (
                    template.id, values["project_id"], values["skill_version_id"], release_number,
                    "Use only the evidence supplied by the immutable prompt bundle.", template.template,
                    json.dumps({"required": template.required_variables}),
                    json.dumps(values["output_schema"]), "geo-prompt-compiler-v1", template.release_hash,
                ),
            )
        )
        return PromptReleaseView(**record)

    def get_template_release(
        self, *, project_id: UUID, release_id: UUID
    ) -> TemplateRelease | None:
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
            id=row["id"], skill_version_id=row["skill_version_id"],
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
        pack = _one(
            self._db.execute(
                """SELECT pack_hash FROM evidence_pack_attempts
                   WHERE id = %s AND project_id = %s AND status = 'ready'""",
                (values["evidence_pack_attempt_id"], values["project_id"]),
            )
        )
        bundle_id = uuid4()
        bundle = render_bundle(
            bundle_id=bundle_id, project_id=values["project_id"],
            brief_version_id=values["brief_version_id"],
            evidence_pack_id=values["evidence_pack_attempt_id"], template=release,
            variables=dict(values["variables"]), evidence_pack_hash=pack["pack_hash"],
            model_policy_hash=values["model_policy_hash"],
        )
        uri = (
            f"content-prompts/{values['project_id']}/{values['brief_version_id']}/"
            f"{bundle_id}/prompt-bundle-{bundle.bundle_hash}.json"
        )
        snapshot = {
            "variables": dict(values["variables"]), "rendered_prompt": bundle.rendered_prompt,
            "evidence_pack_hash": bundle.evidence_pack_hash,
            "model_policy_hash": bundle.model_policy_hash,
        }
        self._db.execute(
            """INSERT INTO prompt_bundles
                 (id, project_id, brief_version_id, evidence_pack_attempt_id,
                  template_release_id, input_snapshot, storage_uri, bundle_hash)
               VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)""",
            (
                bundle_id, values["project_id"], values["brief_version_id"],
                values["evidence_pack_attempt_id"], values["release_id"],
                json.dumps(snapshot), uri, bundle.bundle_hash,
            ),
        )
        return PromptBundleView(
            bundle_id, values["project_id"], values["brief_version_id"],
            values["evidence_pack_attempt_id"], values["release_id"], bundle.bundle_hash, uri,
        )

    def enqueue_generation(self, **values: Any) -> JobReference:
        job = self._enqueue_job(
            project_id=values["project_id"], kind="placement.generate",
            input_value={"prompt_bundle_id": str(values["prompt_bundle_id"])},
            idempotency_key=values["idempotency_key"],
        )
        self._db.execute(
            """INSERT INTO generation_job_specs
                 (job_id, project_id, prompt_bundle_id, configured_model, model_call_budget)
               VALUES (%s, %s, %s, %s, %s) ON CONFLICT (job_id) DO NOTHING""",
            (
                job.id, values["project_id"], values["prompt_bundle_id"],
                values["configured_model"], values["model_call_budget"],
            ),
        )
        return job
