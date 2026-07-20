from __future__ import annotations

import os
from pathlib import Path
import shutil
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from geo_core.placements.application import PlacementApplication
from geo_core.placements.default_prompts import (
    DEFAULT_PROMPT_DEFINITIONS,
    default_output_schema,
)
from geo_core.placements.postgres_uow import placement_uow_factory
from tests.integration.placement_worker_support import cleanup_projects, login_url, seed_project


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_default_prompt_catalog_converges_without_overwriting_user_selection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    suffix = uuid4().hex[:10]
    app_login = f"geo_prompt_it_{suffix}"
    password = uuid4().hex
    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                sql.Identifier(app_login), sql.Literal(password)
            )
        )
        ids = seed_project(admin, suffix=f"prompt-{suffix}")
    app_url = login_url(ADMIN_URL, user=app_login, password=password)
    application = PlacementApplication(placement_uow_factory(lambda: psycopg.connect(app_url)))
    try:
        installed = application.install_default_prompt_catalog(
            project_id=ids["project"], actor_id=ids["owner"]
        )
        replayed = application.install_default_prompt_catalog(
            project_id=ids["project"], actor_id=ids["owner"]
        )

        assert len(installed) == 9
        assert [item["template_release_id"] for item in replayed] == [
            item["template_release_id"] for item in installed
        ]
        assert {item["task_key"] for item in installed} == {
            definition.task_key for definition in DEFAULT_PROMPT_DEFINITIONS
        }

        owned_definition = next(
            item for item in DEFAULT_PROMPT_DEFINITIONS if item.task_key == "owned_site"
        )
        owned_skill = next(
            item
            for item in application.list_prompt_skills(project_id=ids["project"])
            if item.skill_key == owned_definition.skill_key
        )
        original = application.list_prompt_releases(
            project_id=ids["project"], skill_id=owned_skill.id
        )[0]
        assert original.source_text == owned_definition.source
        assert original.system_template == owned_definition.system_template
        assert original.user_template == owned_definition.source
        assert original.variable_schema["server_authoritative"] == [
            "brief",
            "evidence",
            "destination_policy",
        ]
        assert original.output_schema == default_output_schema()
        assert original.compiler_version == "geo-prompt-compiler-v1"
        assert original.status.value == "approved"
        same_content = application.publish_skill_version(
            project_id=ids["project"],
            skill_id=owned_skill.id,
            source=owned_definition.source,
            actor_id=ids["owner"],
            output_schema=default_output_schema(),
            client_variable_names=(),
            system_template=owned_definition.system_template,
            user_template=owned_definition.source,
        )
        assert same_content.release_hash == original.release_hash
        changed_schema = default_output_schema()
        changed_schema["properties"]["submission_notes"] = {"type": "string"}
        custom_system = application.publish_skill_version(
            project_id=ids["project"],
            skill_id=owned_skill.id,
            source=owned_definition.source,
            actor_id=ids["owner"],
            output_schema=default_output_schema(),
            client_variable_names=(),
            system_template="Use a project-specific official voice.",
            user_template=owned_definition.source,
        )
        assert custom_system.release_hash != original.release_hash
        assert custom_system.status.value == "draft"
        custom_schema = application.publish_skill_version(
            project_id=ids["project"],
            skill_id=owned_skill.id,
            source=owned_definition.source,
            actor_id=ids["owner"],
            output_schema=changed_schema,
            client_variable_names=(),
            system_template=owned_definition.system_template,
            user_template=owned_definition.source,
        )
        assert custom_schema.release_hash != original.release_hash
        with psycopg.connect(ADMIN_URL) as admin:
            with pytest.raises(psycopg.Error):
                admin.execute(
                    """UPDATE generation_template_releases SET system_template = 'changed'
                       WHERE id = %s""",
                    (original.id,),
                )
            admin.rollback()
        custom_system = application.transition_prompt_release(
            project_id=ids["project"],
            release_id=custom_system.id,
            command="approve",
            expected_state_version=custom_system.state_version,
            reason="Approve project-specific Prompt Release",
            actor_id=ids["owner"],
            idempotency_key=f"approve-custom-system:{custom_system.id}",
        )
        application.select_prompt_release(
            project_id=ids["project"],
            task_key="owned_site",
            release_id=custom_system.id,
            selected_by=ids["owner"],
        )

        editable_root = tmp_path / "prompt"
        shutil.copytree(Path(__file__).resolve().parents[2] / "prompt", editable_root)
        channel_file = editable_root / "channels" / "owned-site.md"
        channel_file.write_text(
            channel_file.read_text(encoding="utf-8") + "\n\nIntegration prompt catalog revision.",
            encoding="utf-8",
        )
        monkeypatch.setenv("GEO_PROMPT_ROOT", str(editable_root))

        after_customization = application.install_default_prompt_catalog(
            project_id=ids["project"], actor_id=ids["owner"]
        )
        owned_binding = next(
            item for item in after_customization if item["task_key"] == "owned_site"
        )
        assert owned_binding["template_release_id"] == custom_system.id
        refreshed_releases = application.list_prompt_releases(
            project_id=ids["project"], skill_id=owned_skill.id
        )
        assert any(
            "Integration prompt catalog revision." in item.source_text
            for item in refreshed_releases
        )

        reddit_binding = next(
            item for item in after_customization if item["task_key"] == "reddit"
        )
        reddit_skill = next(
            item
            for item in application.list_prompt_skills(project_id=ids["project"])
            if item.skill_key
            == next(
                definition.skill_key
                for definition in DEFAULT_PROMPT_DEFINITIONS
                if definition.task_key == "reddit"
            )
        )
        reddit_release = next(
            item
            for item in application.list_prompt_releases(
                project_id=ids["project"], skill_id=reddit_skill.id
            )
            if item.id == reddit_binding["template_release_id"]
        )
        application.transition_prompt_release(
            project_id=ids["project"],
            release_id=reddit_release.id,
            command="revoke",
            expected_state_version=reddit_release.state_version,
            reason="Exercise revoked default reinstall",
            actor_id=ids["owner"],
            idempotency_key=f"revoke-default:{reddit_release.id}",
        )
        after_revoke = application.install_default_prompt_catalog(
            project_id=ids["project"], actor_id=ids["owner"]
        )
        replacement = next(item for item in after_revoke if item["task_key"] == "reddit")
        assert replacement["template_release_id"] != reddit_release.id
        replacement_view = next(
            item
            for item in application.list_prompt_releases(
                project_id=ids["project"], skill_id=reddit_skill.id
            )
            if item.id == replacement["template_release_id"]
        )
        assert replacement_view.status.value == "approved"

        with psycopg.connect(ADMIN_URL) as admin:
            counts = admin.execute(
                """SELECT
                     (SELECT count(*) FROM prompt_skills WHERE project_id = %s),
                     (SELECT count(*) FROM content_task_prompt_releases WHERE project_id = %s)""",
                (ids["project"], ids["project"]),
            ).fetchone()
        assert counts == (9, 9)
    finally:
        with psycopg.connect(ADMIN_URL) as admin:
            cleanup_projects(
                admin,
                projects=[ids],
                tenant_ids=[ids["tenant"]],
                app_login=app_login,
            )
