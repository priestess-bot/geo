from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
import pytest

from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.execution_contracts import StyleProfileBuildOutput
from geo_core.synthetic_lab.postgres_codec import encode_object
from geo_core.workflow_runtime.contracts import canonical_json_hash
from tests.integration.placement_worker_support import seed_project


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_style_profile_parent_accepts_only_its_exact_pinned_dify_result() -> None:
    database_name = f"geo_style_dify_result_{uuid4().hex[:10]}"
    target_url = _database_url(ADMIN_URL, database_name)
    created_database = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = target_url
        command.upgrade(migration, "0099_style_profile_build_binding")

        fixture = _seed_exact_dify_style_child(target_url)
        exact = _style_output(fixture, fixture["workflow_output"])
        assert _matches_child(target_url, fixture, exact)
        _assert_result_inserted_before_deferred_completion(target_url, fixture, exact)

        source_output = fixture["workflow_output"]
        assert isinstance(source_output, dict)
        changed_output = dict(source_output)
        changed_output["voice_traits"] = ["Australian English - materially changed"]
        changed = _style_output(fixture, changed_output)
        assert not _matches_child(target_url, fixture, changed)
        _assert_result_rejected(target_url, fixture, changed)

        _set_attempt_snapshot(target_url, fixture, uuid4())
        assert not _matches_child(target_url, fixture, exact)
        _assert_result_rejected(target_url, fixture, exact)
    finally:
        if created_database:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )


def _seed_exact_dify_style_child(database_url: str) -> dict[str, object]:
    now = datetime.now(UTC).replace(microsecond=0)
    ids = {
        name: uuid4()
        for name in (
            "parent_job_id",
            "child_job_id",
            "parent_lease_token",
            "fact_snapshot_id",
            "profile_version_id",
            "prompt_program_id",
            "prompt_release_id",
            "workflow_release_id",
            "published_snapshot_id",
            "canary_attempt_id",
            "business_attempt_id",
        )
    }
    hashes = {
        name: _hash(name)
        for name in (
            "parent_input",
            "fact_snapshot",
            "profile",
            "prompt_release",
            "workflow_release",
            "workflow_graph",
            "published_snapshot",
        )
    }
    workflow_output: dict[str, object] = {
        "sample_manifest_hash": _hash("sample-manifest"),
        "voice_traits": ["Australian English - plain-spoken"],
        "lexical_patterns": ["clear local wording"],
        "structure_patterns": ["brief opening, then evidence"],
        "avoid_patterns": ["invented product facts"],
        "review_note": "Evidence is reviewed in Australia \u2013 no copied phrasing.",
        "cadence_score": 4.2,
    }
    response_hash = canonical_json_hash(workflow_output)

    with psycopg.connect(database_url) as connection:
        seeded = seed_project(connection, suffix=f"style-dify-{uuid4().hex[:8]}")
        project_id = seeded["project"]
        owner_id = seeded["owner"]
        connection.execute("SET LOCAL session_replication_role = replica")
        connection.execute(
            """INSERT INTO durable_jobs(
                   id, project_id, kind, status, input_hash, idempotency_key,
                   attempt_count, lease_owner, lease_token, lease_expires_at,
                   fencing_generation, created_at, updated_at
               ) VALUES (
                   %s, %s, 'style.profile.build', 'running', %s, %s,
                   1, 'style-parent-worker', %s, %s, 1, %s, %s
               )""",
            (
                ids["parent_job_id"],
                project_id,
                hashes["parent_input"],
                f"style-parent:{ids['parent_job_id']}",
                ids["parent_lease_token"],
                now + timedelta(minutes=10),
                now,
                now,
            ),
        )
        connection.execute(
            """INSERT INTO synthetic_lab_job_metadata(
                   job_id, project_id, metadata_version, domain_job_kind,
                   payload, payload_hash, fact_snapshot_id, fact_snapshot_hash,
                   profile_version_id, profile_hash, prompt_release_id,
                   prompt_release_hash, facts_current_approved, profile_frozen,
                   prompt_frozen, created_at, updated_at
               ) VALUES (
                   %s, %s, 1, 'style_profile_build', '{}'::jsonb, %s,
                   %s, %s, %s, %s, %s, %s, true, false, true, %s, %s
               )""",
            (
                ids["parent_job_id"],
                project_id,
                _hash("parent-metadata"),
                ids["fact_snapshot_id"],
                hashes["fact_snapshot"],
                ids["profile_version_id"],
                hashes["profile"],
                ids["prompt_release_id"],
                hashes["prompt_release"],
                now,
                now,
            ),
        )
        connection.execute(
            """INSERT INTO synthetic_lab_execution_tasks(
                   project_id, job_id, requested_by, execution_kind,
                   expected_job_input_hash, task_input_hash, task_type,
                   task_payload, task_payload_hash, staged_at
               ) VALUES (
                   %s, %s, %s, 'style.profile.build', %s, %s,
                   'geo_core.synthetic_lab.execution_contracts.StyleProfileBuildTask',
                   '{}'::jsonb, %s, %s
               )""",
            (
                project_id,
                ids["parent_job_id"],
                owner_id,
                hashes["parent_input"],
                hashes["parent_input"],
                _hash("parent-task-payload"),
                now,
            ),
        )
        connection.execute(
            """INSERT INTO durable_jobs(
                   id, project_id, kind, status, input_hash, idempotency_key,
                   result_ref, parent_job_id, created_at, updated_at, completed_at
               ) VALUES (
                   %s, %s, 'synthetic.model.call', 'succeeded', %s, %s,
                   %s, %s, %s, %s, %s
               )""",
            (
                ids["child_job_id"],
                project_id,
                _hash("child-input"),
                f"style-child:{ids['child_job_id']}",
                f"dify-workflow://attempt/{ids['business_attempt_id']}",
                ids["parent_job_id"],
                now,
                now,
                now,
            ),
        )
        connection.execute(
            """INSERT INTO dify_workflow_releases(
                   id, project_id, purpose, version, prompt_program_id,
                   prompt_release_id, prompt_release_hash, dify_app_id,
                   dify_workflow_id, dsl_hash, context_contract_version,
                   input_schema, input_schema_hash, output_schema,
                   output_schema_hash, configured_model, model_provider,
                   api_secret_reference_id, api_secret_purpose,
                   api_secret_version, release_hash, created_by, created_at
               ) VALUES (
                   %s, %s, 'synthetic_lab.style_profile', 1, %s, %s, %s,
                   'style-profile-app', 'style-profile-workflow', %s,
                   'geo-dify-context-v1', '{}'::jsonb, %s, '{}'::jsonb, %s,
                   'deepseek-chat', 'langgenius/deepseek/deepseek', %s,
                   'workflow_runtime.dify', 1, %s, %s, %s
               )""",
            (
                ids["workflow_release_id"],
                project_id,
                ids["prompt_program_id"],
                ids["prompt_release_id"],
                hashes["prompt_release"],
                _hash("style-dsl"),
                _hash("style-input-schema"),
                _hash("style-output-schema"),
                uuid4(),
                hashes["workflow_release"],
                owner_id,
                now,
            ),
        )
        connection.execute(
            """INSERT INTO dify_workflow_published_snapshots(
                   id, project_id, release_id, purpose, dify_app_id,
                   dify_workflow_id, workflow_hash, snapshot_hash,
                   prompt_nodes, input_variables, graph_nodes,
                   published_at, observed_at
               ) VALUES (
                   %s, %s, %s, 'synthetic_lab.style_profile',
                   'style-profile-app', 'style-profile-workflow', %s, %s,
                   '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, %s, %s
               )""",
            (
                ids["published_snapshot_id"],
                project_id,
                ids["workflow_release_id"],
                hashes["workflow_graph"],
                hashes["published_snapshot"],
                now,
                now,
            ),
        )
        connection.execute(
            """INSERT INTO dify_workflow_execution_attempts(
                   id, project_id, release_id, job_id, execution_kind,
                   attempt_number, fencing_generation, status, context_hash,
                   request_hash, dify_run_id, reported_workflow_id, output_hash,
                   retryable, started_at, finished_at, published_snapshot_id
               ) VALUES
                   (%s, %s, %s, NULL, 'canary', 1, NULL, 'succeeded',
                    %s, %s, 'style-canary-run', 'style-profile-workflow', %s,
                    false, %s, %s, %s),
                   (%s, %s, %s, %s, 'business', 1, 1, 'succeeded',
                    %s, %s, 'style-business-run', 'style-profile-workflow', %s,
                    false, %s, %s, %s)
               """,
            (
                ids["canary_attempt_id"],
                project_id,
                ids["workflow_release_id"],
                _hash("canary-context"),
                _hash("canary-request"),
                response_hash,
                now,
                now,
                ids["published_snapshot_id"],
                ids["business_attempt_id"],
                project_id,
                ids["workflow_release_id"],
                ids["child_job_id"],
                _hash("business-context"),
                _hash("business-request"),
                response_hash,
                now,
                now,
                ids["published_snapshot_id"],
            ),
        )
        connection.execute(
            """INSERT INTO dify_workflow_release_snapshot_pins(
                   project_id, release_id, published_snapshot_id,
                   dify_workflow_id, workflow_hash, snapshot_hash,
                   canary_attempt_id, pin_source, pinned_at
               ) VALUES (
                   %s, %s, %s, 'style-profile-workflow', %s, %s, %s,
                   'runtime_canary', %s
               )""",
            (
                project_id,
                ids["workflow_release_id"],
                ids["published_snapshot_id"],
                hashes["workflow_graph"],
                hashes["published_snapshot"],
                ids["canary_attempt_id"],
                now,
            ),
        )
        connection.execute(
            """INSERT INTO dify_workflow_execution_results(
                   attempt_id, project_id, job_id, output, response_hash,
                   configured_model, provider_reported_model, created_at
               ) VALUES (%s, %s, %s, %s, %s, 'deepseek-chat',
                         'deepseek-chat', %s)""",
            (
                ids["business_attempt_id"],
                project_id,
                ids["child_job_id"],
                Jsonb(workflow_output),
                response_hash,
                now,
            ),
        )
        _insert_child(
            connection,
            project_id=project_id,
            owner_id=owner_id,
            ids=ids,
            hashes=hashes,
            now=now,
        )
        connection.execute("SET LOCAL session_replication_role = origin")
    return {
        **ids,
        **hashes,
        "project_id": project_id,
        "owner_id": owner_id,
        "workflow_output": workflow_output,
    }


def _insert_child(
    connection: psycopg.Connection[object],
    *,
    project_id: UUID,
    owner_id: UUID,
    ids: dict[str, UUID],
    hashes: dict[str, str],
    now: datetime,
) -> None:
    connection.execute(
        """INSERT INTO synthetic_lab_model_call_children(
               project_id, child_job_id, parent_job_id, parent_job_kind,
               parent_task_input_hash, parent_lease_token,
               parent_fencing_generation, step_key, step_key_hash,
               model_job_version, fact_snapshot_id, fact_snapshot_hash,
               profile_version_id, profile_hash,
               runtime_prompt_release_id, runtime_prompt_release_hash,
               prompt_binding_id, prompt_binding_version,
               prompt_frozen_state_id, prompt_state_version,
               prompt_release_id, prompt_release_version,
               prompt_release_hash, prompt_program_kind, prompt_purpose,
               admitted_by, prompt_model_policy_hash, provider,
               adapter_release_id, adapter_release_hash, model_release_id,
               model_release_hash, configured_model, execution_backend,
               workflow_release_id, workflow_release_hash,
               backend_lineage_source, runtime_manifest_id,
               runtime_manifest_hash, runtime_option_id, runtime_option_hash,
               search_mode, prompt_bundle_hash, structured_input_hash,
               portable_output_schema_hash, application_output_schema_hash,
               task_artifact_uri, task_artifact_hash, deterministic_seed,
               max_output_tokens, child_input_hash, outbox_id, created_at
           ) VALUES (
               %s, %s, %s, 'style.profile.build', %s, %s, 1,
               'style-profile:build:v1', %s, 1, %s, %s, %s, %s,
               %s, %s, %s, 1, %s, 1, %s, 1, %s, 'style_profile',
               'synthetic_lab.style_profile', %s, %s, 'deepseek',
               'deepseek-adapter-v1', %s, 'deepseek-release-v1', %s,
               'deepseek-chat', 'dify', %s, %s, 'runtime_admission',
               %s, %s, %s, %s, NULL, %s, %s, %s, %s,
               's3://geo-test/style-profile-child.json', %s, 1, 8192,
               %s, %s, %s
           )""",
        (
            project_id,
            ids["child_job_id"],
            ids["parent_job_id"],
            hashes["parent_input"],
            ids["parent_lease_token"],
            _hash("style-profile-step"),
            ids["fact_snapshot_id"],
            hashes["fact_snapshot"],
            ids["profile_version_id"],
            hashes["profile"],
            ids["prompt_release_id"],
            hashes["prompt_release"],
            uuid4(),
            uuid4(),
            ids["prompt_release_id"],
            hashes["prompt_release"],
            owner_id,
            _hash("prompt-policy"),
            _hash("adapter-release"),
            _hash("model-release"),
            ids["workflow_release_id"],
            hashes["workflow_release"],
            uuid4(),
            _hash("runtime-manifest"),
            uuid4(),
            _hash("runtime-option"),
            _hash("prompt-bundle"),
            _hash("structured-input"),
            _hash("portable-schema"),
            _hash("application-schema"),
            _hash("task-artifact"),
            _hash("child-input"),
            uuid4(),
            now,
        ),
    )


def _style_output(
    fixture: dict[str, object], workflow_output: object
) -> StyleProfileBuildOutput:
    assert isinstance(workflow_output, dict)
    profile_summary = json.dumps(
        workflow_output,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return StyleProfileBuildOutput(
        project_id=fixture["project_id"],
        profile_version_id=fixture["profile_version_id"],
        profile_hash=fixture["profile"],
        artifact_hash=canonical_hash(workflow_output),
        model_call_ids=(),
        workflow_attempt_ids=(fixture["business_attempt_id"],),
        profile_summary=profile_summary,
    )


def _matches_child(
    database_url: str,
    fixture: dict[str, object],
    output: StyleProfileBuildOutput,
) -> bool:
    _result_type, payload, _payload_hash = encode_object(output)
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            "SELECT geo_synthetic_style_profile_result_matches_child(%s, %s, %s)",
            (
                fixture["project_id"],
                fixture["parent_job_id"],
                Jsonb(payload),
            ),
        ).fetchone()
        assert row is not None
        return bool(row[0])


def _assert_result_inserted_before_deferred_completion(
    database_url: str,
    fixture: dict[str, object],
    output: StyleProfileBuildOutput,
) -> None:
    with psycopg.connect(database_url) as connection:
        result_id = _insert_parent_result(connection, fixture, output)
        row = connection.execute(
            "SELECT count(*) FROM synthetic_lab_execution_results WHERE id = %s",
            (result_id,),
        ).fetchone()
        assert row is not None and row[0] == 1
        connection.rollback()


def _assert_result_rejected(
    database_url: str,
    fixture: dict[str, object],
    output: StyleProfileBuildOutput,
) -> None:
    with psycopg.connect(database_url) as connection:
        with pytest.raises(psycopg.Error, match="changed its frozen build identity"):
            _insert_parent_result(connection, fixture, output)


def _insert_parent_result(
    connection: psycopg.Connection[object],
    fixture: dict[str, object],
    output: StyleProfileBuildOutput,
) -> UUID:
    result_type, payload, payload_hash = encode_object(output)
    result_id = uuid4()
    connection.execute(
        """INSERT INTO synthetic_lab_execution_results(
               id, project_id, job_id, result_type, result_payload,
               result_payload_hash, result_hash, lease_token,
               fencing_generation, fact_snapshot_id, fact_snapshot_hash,
               profile_version_id, profile_hash, prompt_release_id,
               prompt_release_hash
           ) VALUES (
               %s, %s, %s, %s, %s, %s, %s, %s, 1,
               %s, %s, %s, %s, %s, %s
           )""",
        (
            result_id,
            fixture["project_id"],
            fixture["parent_job_id"],
            result_type,
            Jsonb(payload),
            payload_hash,
            output.result_hash,
            fixture["parent_lease_token"],
            fixture["fact_snapshot_id"],
            fixture["fact_snapshot"],
            fixture["profile_version_id"],
            fixture["profile"],
            fixture["prompt_release_id"],
            fixture["prompt_release"],
        ),
    )
    return result_id


def _set_attempt_snapshot(
    database_url: str, fixture: dict[str, object], snapshot_id: UUID
) -> None:
    with psycopg.connect(database_url) as connection:
        connection.execute("SET LOCAL session_replication_role = replica")
        connection.execute(
            """UPDATE dify_workflow_execution_attempts
               SET published_snapshot_id = %s
               WHERE id = %s""",
            (snapshot_id, fixture["business_attempt_id"]),
        )
        connection.execute("SET LOCAL session_replication_role = origin")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _database_url(base: str, database_name: str) -> str:
    parsed = urlsplit(base)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database_name}", "", ""))
