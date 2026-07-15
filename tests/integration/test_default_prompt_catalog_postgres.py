from __future__ import annotations

import os
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
from tests.integration.placement_worker_support import login_url, seed_project


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_default_prompt_catalog_converges_without_overwriting_user_selection() -> None:
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
    application = PlacementApplication(
        placement_uow_factory(lambda: psycopg.connect(app_url))
    )
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
        changed_schema = default_output_schema()
        changed_schema["properties"]["submission_notes"] = {"type": "string"}
        custom = application.publish_skill_version(
            project_id=ids["project"],
            skill_id=owned_skill.id,
            source=owned_definition.source,
            actor_id=ids["owner"],
            output_schema=changed_schema,
            client_variable_names=(),
        )
        assert custom.release_hash != original.release_hash
        application.select_prompt_release(
            project_id=ids["project"],
            task_key="owned_site",
            release_id=custom.id,
            selected_by=ids["owner"],
        )

        after_customization = application.install_default_prompt_catalog(
            project_id=ids["project"], actor_id=ids["owner"]
        )
        owned_binding = next(
            item for item in after_customization if item["task_key"] == "owned_site"
        )
        assert owned_binding["template_release_id"] == custom.id

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
            admin.execute("SET LOCAL session_replication_role = 'replica'")
            admin.execute("DELETE FROM tenants WHERE id = %s", (ids["tenant"],))
            admin.execute("SET LOCAL session_replication_role = 'origin'")
            admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(app_login)))
