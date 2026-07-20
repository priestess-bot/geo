"""Prompt persistence mixin kept separate from the placement aggregate adapter."""

from __future__ import annotations

import json
import hashlib
from typing import Any, Mapping
from uuid import UUID, uuid4

from geo_core.placements.domain import (
    JobReference,
    PlacementRuleViolation,
    PromptReleaseView,
    PromptSkill,
    canonical_hash,
)
from geo_core.placements.default_prompts import DefaultPromptDefinition
from geo_core.prompts.domain import (
    SkillVersion,
    TemplateRelease,
    compile_template,
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
        campaign_id: UUID,
        kind: str,
        input_value: Mapping[str, object],
        idempotency_key: str,
    ) -> JobReference:
        raise NotImplementedError

    def get_prompt_release_view(
        self, *, project_id: UUID, release_id: UUID
    ) -> PromptReleaseView | None:
        raise NotImplementedError

    def transition_prompt_release_state(self, **values: Any) -> PromptReleaseView:
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
        self._db.execute(
            """INSERT INTO generation_template_release_states
                 (project_id, template_release_id, skill_version_id, release_number,
                  release_hash, state_version, status, changed_by, change_reason)
               VALUES (%s, %s, %s, %s, %s, 1, 'draft', %s,
                       'Prompt Release created as draft')""",
            (
                values["project_id"],
                record["id"],
                record["skill_version_id"],
                record["release_number"],
                record["release_hash"],
                values["actor_id"],
            ),
        )
        view = self.get_prompt_release_view(
            project_id=values["project_id"], release_id=record["id"]
        )
        if view is None:
            raise RuntimeError("created Prompt Release could not be projected")
        return view

    def install_default_prompt_catalog(
        self,
        *,
        project_id: UUID,
        definitions: tuple[DefaultPromptDefinition, ...],
        output_schema: Mapping[str, object],
        actor_id: UUID,
    ) -> tuple[Mapping[str, object], ...]:
        _one(self._db.execute("SELECT id FROM projects WHERE id = %s FOR UPDATE", (project_id,)))
        bindings: list[Mapping[str, object]] = []
        for definition in definitions:
            current = _many(
                self._db.execute(
                    """SELECT binding.project_id, binding.task_key,
                              binding.template_release_id, binding.selected_by,
                              binding.selected_at, state.status AS release_status
                       FROM content_task_prompt_releases AS binding
                       LEFT JOIN current_generation_template_release_states AS state
                         ON state.template_release_id = binding.template_release_id
                        AND state.project_id = binding.project_id
                       WHERE binding.project_id = %s AND binding.task_key = %s""",
                    (project_id, definition.task_key),
                )
            )
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
                else self.create_prompt_skill(project_id=project_id, skill_key=definition.skill_key)
            )
            source_hash = hashlib.sha256(definition.source.encode("utf-8")).hexdigest()
            releases = _many(
                self._db.execute(
                    """SELECT r.id FROM generation_template_releases r
                       JOIN prompt_skill_versions v
                         ON v.id = r.skill_version_id AND v.project_id = r.project_id
                       JOIN current_generation_template_release_states state
                         ON state.template_release_id = r.id
                        AND state.project_id = r.project_id
                       WHERE r.project_id = %s AND v.skill_id = %s
                         AND v.source_hash = %s AND r.output_schema = %s::jsonb
                         AND r.system_template = %s AND r.user_template = %s
                         AND state.status IN ('draft', 'approved')
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
                    actor_id=actor_id,
                ).id
            release_view = self.get_prompt_release_view(
                project_id=project_id, release_id=release_id
            )
            if release_view is None:
                raise RuntimeError("default Prompt Release disappeared")
            if release_view.status.value == "draft":
                self.transition_prompt_release_state(
                    project_id=project_id,
                    release_id=release_id,
                    expected_state_version=release_view.state_version,
                    target_status="approved",
                    reason="Default Prompt catalog installation",
                    actor_id=actor_id,
                    idempotency_key=f"default-release-approve:{release_id}",
                )
            if current and current[0]["release_status"] == "approved":
                bindings.append(
                    {
                        key: current[0][key]
                        for key in (
                            "project_id",
                            "task_key",
                            "template_release_id",
                            "selected_by",
                            "selected_at",
                        )
                    }
                )
            else:
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
                """SELECT r.id
                   FROM generation_template_releases r JOIN prompt_skill_versions v
                     ON v.id = r.skill_version_id AND v.project_id = r.project_id
                   WHERE r.project_id = %s AND v.skill_id = %s ORDER BY r.release_number""",
                (project_id, skill_id),
            )
        )
        releases: list[PromptReleaseView] = []
        for row in rows:
            release = self.get_prompt_release_view(project_id=project_id, release_id=row["id"])
            if release is None:
                raise RuntimeError("Prompt Release list contains an unprojectable row")
            releases.append(release)
        return tuple(releases)

    def select_prompt_release(
        self,
        *,
        project_id: UUID,
        task_key: str,
        release_id: UUID,
        selected_by: UUID,
    ) -> Mapping[str, object]:
        release = self.get_prompt_release_view(project_id=project_id, release_id=release_id)
        if release is None or release.status.value != "approved":
            raise PlacementRuleViolation("only an approved Prompt Release can be selected")
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
