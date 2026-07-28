from __future__ import annotations

import os
from pathlib import Path
from threading import Event, Thread
import time
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4
from datetime import UTC, datetime

from alembic import command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
import pytest

from geo_core.synthetic_lab.execution_contracts import StyleProfileBuildOutput
from geo_core.synthetic_lab.domain import StyleProfileStatus, StyleProfileVersion
from geo_core.synthetic_lab.postgres_codec import encode_object
from tests.integration.placement_worker_support import seed_project


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_0099_roundtrip_restores_0098_and_hashes_python_output_exactly() -> None:
    database_name = f"geo_style_build_binding_{uuid4().hex[:10]}"
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
            seeded = seed_project(admin, suffix=f"style-legacy-{database_name}")
            legacy_profile = StyleProfileVersion(
                id=uuid4(),
                project_id=seeded["project"],
                profile_id=uuid4(),
                version_number=1,
                channel="reddit",
                locale="en-AU",
                corpus_hash="c" * 64,
                profile_hash="d" * 64,
                prompt_release_id=uuid4(),
                prompt_release_hash="e" * 64,
                approved_sample_count=200,
                status=StyleProfileStatus.FROZEN,
                reviewed_by=seeded["reviewer"],
                reviewed_at=datetime.now(UTC),
            )
            _insert_legacy_profile(admin, legacy_profile, seeded["owner"])
        before = _schema_contract(target_url)
        command.upgrade(migration, "0099_style_profile_build_binding")

        output = StyleProfileBuildOutput(
            project_id=uuid4(),
            profile_version_id=uuid4(),
            profile_hash="a" * 64,
            artifact_hash="b" * 64,
            model_call_ids=(),
            workflow_attempt_ids=(uuid4(),),
            profile_summary='{"voice_traits":["Australian English \\u2013 plain"]}',
        )
        _result_type, payload, payload_hash = encode_object(output)
        with psycopg.connect(target_url) as connection:
            assert connection.execute(
                "SELECT geo_synthetic_style_profile_result_hash(%s)",
                (Jsonb(payload),),
            ).fetchone()[0] == output.result_hash
            assert connection.execute(
                """SELECT encode(digest(
                       convert_to(geo_jsonb_canonical_text(%s), 'UTF8'), 'sha256'
                   ), 'hex')""",
                (Jsonb(payload),),
            ).fetchone()[0] == payload_hash
            assert connection.execute(
                "SELECT to_regclass('synthetic_lab_style_profile_build_bindings')"
            ).fetchone()[0] == "synthetic_lab_style_profile_build_bindings"
            assert "submit_profile" in _command_operation_constraint(connection)
            assert connection.execute(
                """SELECT verification_status, binding_source, rebuild_required,
                          execution_job_id, execution_result_id
                   FROM synthetic_lab_style_profile_build_bindings
                   WHERE project_id = %s AND profile_version_id = %s""",
                (legacy_profile.project_id, legacy_profile.id),
            ).fetchone() == (
                "legacy_unverified",
                "migration_legacy",
                True,
                None,
                None,
            )
            lock_definition = connection.execute(
                """SELECT pg_get_functiondef(
                     'geo_lock_style_profile_parent_admission()'::regprocedure
                   )"""
            ).fetchone()[0]
            assert "\\:" not in lock_definition
            assert "chr(58)" in lock_definition

        _assert_exact_style_parent_lock_contends(
            target_url,
            project_id=seeded["project"],
        )

        command.downgrade(migration, "0098_synthetic_dify_lineage")
        assert _schema_contract(target_url) == before
        with psycopg.connect(target_url) as connection:
            assert connection.execute(
                """SELECT payload #>> '{fields,status,value}'
                   FROM synthetic_lab_aggregate_versions
                   WHERE project_id = %s AND kind = 'style_profile'
                     AND resource_id = %s ORDER BY version DESC LIMIT 1""",
                (legacy_profile.project_id, legacy_profile.id),
            ).fetchone() == ("frozen",)
        command.upgrade(migration, "0099_style_profile_build_binding")
        with psycopg.connect(target_url) as connection:
            assert connection.execute(
                """SELECT verification_status, binding_source, rebuild_required
                   FROM synthetic_lab_style_profile_build_bindings
                   WHERE project_id = %s AND profile_version_id = %s""",
                (legacy_profile.project_id, legacy_profile.id),
            ).fetchone() == ("legacy_unverified", "migration_legacy", True)
    finally:
        if created_database:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )


def _schema_contract(database_url: str) -> tuple[object, ...]:
    with psycopg.connect(database_url) as connection:
        view = connection.execute(
            """SELECT pg_get_viewdef(
                 'synthetic_lab_model_call_child_status'::regclass, true
               )"""
        ).fetchone()
        terminal = connection.execute(
            """SELECT pg_get_functiondef(
                 'geo_assert_synthetic_lab_terminal()'::regprocedure
               )"""
        ).fetchone()
        admission_trigger = connection.execute(
            """SELECT pg_get_triggerdef(oid, true)
               FROM pg_trigger
               WHERE tgrelid = 'durable_jobs'::regclass
                 AND tgname = 'style_profile_parent_admission_lock'"""
        ).fetchone()
        command_operation = _command_operation_constraint(connection)
    return view, terminal, admission_trigger, command_operation


def _command_operation_constraint(connection: psycopg.Connection) -> str:
    return connection.execute(
        """SELECT pg_get_constraintdef(oid, true)
           FROM pg_constraint
           WHERE conrelid = 'synthetic_lab_command_receipts'::regclass
             AND conname = 'synthetic_lab_command_receipts_operation_check'"""
    ).fetchone()[0]


def _insert_legacy_profile(
    connection: psycopg.Connection,
    profile: StyleProfileVersion,
    submitted_by,
) -> None:
    payload_type, payload, payload_hash = encode_object(profile)
    connection.execute(
        """INSERT INTO synthetic_lab_aggregate_versions(
               project_id, kind, resource_id, version, submitted_by,
               payload_type, payload, payload_hash
           ) VALUES (%s, 'style_profile', %s, 1, %s, %s, %s, %s)""",
        (
            profile.project_id,
            profile.id,
            submitted_by,
            payload_type,
            Jsonb(payload),
            payload_hash,
        ),
    )


def _assert_exact_style_parent_lock_contends(database_url: str, *, project_id) -> None:
    exact_key = f"dify-binding:{project_id}:synthetic_lab.style_profile"
    started, finished = Event(), Event()
    failures: list[BaseException] = []
    application_name = f"geo-style-lock-{uuid4().hex}"

    def insert_parent() -> None:
        try:
            with psycopg.connect(
                database_url, application_name=application_name
            ) as connection:
                started.set()
                job_id = uuid4()
                connection.execute(
                    """INSERT INTO durable_jobs(
                           id, project_id, kind, status, input_hash,
                           idempotency_key, max_attempts
                       ) VALUES (%s, %s, 'style.profile.build', 'queued', %s, %s, 3)""",
                    (job_id, project_id, "1" * 64, f"style-lock:{job_id}"),
                )
        except BaseException as error:
            failures.append(error)
        finally:
            finished.set()

    with psycopg.connect(database_url) as blocker:
        blocker.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (exact_key,)
        )
        thread = Thread(target=insert_parent, daemon=True)
        thread.start()
        assert started.wait(timeout=2)
        deadline = time.monotonic() + 2
        waiting = False
        while time.monotonic() < deadline:
            waiting = blocker.execute(
                """SELECT EXISTS (
                       SELECT 1 FROM pg_stat_activity
                       WHERE application_name = %s AND wait_event = 'advisory'
                   )""",
                (application_name,),
            ).fetchone()[0]
            if waiting:
                break
            time.sleep(0.02)
        assert waiting and not finished.is_set()
        blocker.commit()
        assert finished.wait(timeout=2)
        thread.join(timeout=2)
    assert not failures


def _database_url(base: str, database_name: str) -> str:
    parsed = urlsplit(base)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database_name}", "", ""))
