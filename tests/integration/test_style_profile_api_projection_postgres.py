from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from alembic import command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from geo_core.synthetic_lab.domain import StyleProfileStatus, StyleProfileVersion
from geo_core.synthetic_lab.postgres_api_reads import PostgresSyntheticApiReads
from geo_core.synthetic_lab.postgres_codec import encode_object
from geo_core.synthetic_lab.postgres_api_read_models import StyleProfileAggregateView
from tests.integration.placement_worker_support import seed_project


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_legacy_profile_is_visible_with_rebuild_status_but_not_selectable() -> None:
    database_name = f"geo_style_projection_{uuid4().hex[:10]}"
    target_url = _database_url(ADMIN_URL, database_name)
    created_database = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = target_url
        command.upgrade(migration, "0098_synthetic_dify_lineage")

        with psycopg.connect(target_url) as admin:
            seeded = seed_project(admin, suffix=f"style-projection-{database_name}")
            profile = StyleProfileVersion(
                id=uuid4(),
                project_id=seeded["project"],
                profile_id=uuid4(),
                version_number=1,
                channel="reddit",
                locale="en-AU",
                corpus_hash="a" * 64,
                profile_hash="b" * 64,
                prompt_release_id=uuid4(),
                prompt_release_hash="c" * 64,
                approved_sample_count=200,
                status=StyleProfileStatus.FROZEN,
                reviewed_by=seeded["reviewer"],
                reviewed_at=datetime.now(UTC),
            )
            payload_type, payload, payload_hash = encode_object(profile)
            admin.execute(
                """INSERT INTO synthetic_lab_aggregate_versions(
                       project_id, kind, resource_id, version, submitted_by,
                       payload_type, payload, payload_hash
                   ) VALUES (%s, 'style_profile', %s, 1, %s, %s, %s, %s)""",
                (
                    profile.project_id,
                    profile.id,
                    seeded["owner"],
                    payload_type,
                    Jsonb(payload),
                    payload_hash,
                ),
            )
        command.upgrade(migration, "0099_style_profile_build_binding")

        reads = PostgresSyntheticApiReads(
            lambda: psycopg.connect(target_url, row_factory=dict_row)
        )
        page = reads.profiles(profile.project_id, limit=50, offset=0)
        assert page.total == 1 and len(page.items) == 1
        projected = page.items[0]
        assert isinstance(projected, StyleProfileAggregateView)
        assert projected.payload == profile
        assert projected.build_verification_status == "legacy_unverified"
        assert projected.rebuild_required is True
        assert reads.resource_inventory(profile.project_id)["profiles"] == ()
    finally:
        if created_database:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )


def _database_url(admin_url: str, database_name: str) -> str:
    parsed = urlsplit(admin_url)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database_name}", parsed.query, ""))
