from __future__ import annotations

import base64
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
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from geo_core.project_scope import set_project_scope
from tests.integration.placement_worker_support import login_url, seed_project


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_metric_parent_admission_atomically_creates_encrypted_children_and_wakeups() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_metric_parent_{suffix}"
    database_url = _database_url(ADMIN_URL, database_name)
    worker_login, password = f"geo_metric_parent_{suffix}", uuid4().hex
    created_database = False
    created_role = False
    now = datetime.now(UTC).replace(microsecond=0)
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = database_url
        command.upgrade(migration, "head")
        command.downgrade(migration, "0065_metric_output_projection")
        command.upgrade(migration, "head")

        with psycopg.connect(database_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_worker").format(
                    sql.Identifier(worker_login), sql.Literal(password)
                )
            )
            created_role = True
            project = seed_project(admin, suffix=f"metric-parent-{suffix}")
            parent = _seed_parent_lineage(admin, project=project, now=now)
            admin.commit()

        worker_url = login_url(database_url, user=worker_login, password=password)
        batch_id = uuid4()
        first_child, second_child = uuid4(), uuid4()
        payload = [
            {
                "id": str(batch_id),
                "run_id": str(parent["run_id"]),
                "observation_id": str(parent["observation_id"]),
                "ordinal": 1,
                "planned_batch_count": 1,
                "plans_hash": _hash("plans"),
                "input_set_hash": _hash("input-set"),
                "metric_suite_hash": _hash("metric-suite"),
                "children": [
                    _child_payload(
                        child_id=first_child,
                        candidate_id=uuid4(),
                        ordinal=1,
                        evaluator_id="judge-a",
                        parent=parent,
                    ),
                    _child_payload(
                        child_id=second_child,
                        candidate_id=uuid4(),
                        ordinal=2,
                        evaluator_id="judge-b",
                        parent=parent,
                    ),
                ],
            }
        ]
        payload = _finalize_payload(payload)
        with psycopg.connect(worker_url, row_factory=dict_row) as worker:
            set_project_scope(worker, project["project"])
            rows = worker.execute(
                """SELECT * FROM geo_admit_workflow_c_metric_judge_batches(
                       %s, %s, %s, 1, %s, %s::jsonb
                   )""",
                (
                    project["project"],
                    parent["job_id"],
                    parent["lease_token"],
                    parent["input_hash"],
                    Jsonb(payload),
                ),
            ).fetchall()
            assert rows == [{"batch_id": batch_id, "child_count": 2}]
            persisted = worker.execute(
                """SELECT child.child_job_id, child.task_hash, job.input_hash, spec.spec_hash,
                              spec.spec_payload, child.status
                       FROM workflow_c_metric_model_children AS child
                       JOIN durable_jobs AS job
                         ON job.project_id = child.project_id AND job.id = child.child_job_id
                       JOIN workflow_c_job_specs AS spec
                         ON spec.project_id = child.project_id AND spec.job_id = child.child_job_id
                      WHERE child.project_id = %s AND child.batch_id = %s
                      ORDER BY child.ordinal""",
                (project["project"], batch_id),
            ).fetchall()
            assert [item["child_job_id"] for item in persisted] == [first_child, second_child]
            assert all(
                item["task_hash"] == item["input_hash"]
                and item["task_hash"] != item["spec_hash"]
                and item["status"] == "queued"
                for item in persisted
            )
            assert all(
                set(item["spec_payload"]) == {"schema_version", "kind", "metric_model_child"}
                and item["spec_payload"]["metric_model_child"]["task_hash"]
                == item["task_hash"]
                for item in persisted
            )
            assert worker.execute(
                """SELECT count(*) FROM broker_outbox
                      WHERE project_id = %s AND job_id IN (%s, %s)""",
                (project["project"], first_child, second_child),
            ).fetchone()["count"] == 2
            worker.commit()
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                worker.execute("UPDATE workflow_c_metric_model_children SET status = 'failed'")
            worker.rollback()

            set_project_scope(worker, project["project"])
            with pytest.raises(psycopg.errors.UniqueViolation, match="already admitted"):
                worker.execute(
                    """SELECT * FROM geo_admit_workflow_c_metric_judge_batches(
                           %s, %s, %s, 1, %s, %s::jsonb
                       )""",
                    (
                        project["project"],
                        parent["job_id"],
                        parent["lease_token"],
                        parent["input_hash"],
                        Jsonb(payload),
                    ),
                )
            worker.rollback()

        with psycopg.connect(database_url) as admin:
            assert admin.execute(
                """SELECT count(*) FROM workflow_c_metric_judge_batches
                      WHERE project_id = %s AND parent_job_id = %s""",
                (project["project"], parent["job_id"]),
            ).fetchone() == (1,)
            assert admin.execute(
                """SELECT count(*) FROM workflow_c_metric_model_children
                      WHERE project_id = %s AND parent_job_id = %s""",
                (project["project"], parent["job_id"]),
            ).fetchone() == (2,)
    finally:
        if created_database:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )
        if created_role:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(worker_login)))


def _seed_parent_lineage(
    connection: psycopg.Connection, *, project: dict[str, UUID], now: datetime
) -> dict[str, UUID | str]:
    parent_job_id, lease_token, run_id, observation_id = uuid4(), uuid4(), uuid4(), uuid4()
    program_id, release_id, state_id, binding_id = uuid4(), uuid4(), uuid4(), uuid4()
    manifest_id, option_id = uuid4(), uuid4()
    release_hash, manifest_hash, option_hash = _hash("prompt-release"), _hash("runtime-manifest"), _hash("runtime-option")
    parent_spec = {
        "schema_version": 1,
        "kind": "workflow_c.analysis.semantic_metrics",
        "semantic_metrics": {"fixture": "parent"},
    }
    input_hash = _json_hash(parent_spec)
    connection.execute("SET session_replication_role = replica")
    try:
        connection.execute(
            """INSERT INTO workflow_c_artifact_master_key_versions(
                   master_key_version, status, algorithm, canary_nonce,
                   canary_ciphertext, created_at
               ) VALUES (1, 'encrypt_decrypt', 'AES-256-GCM', %s, %s, %s)""",
            (b"n" * 12, b"c" * 17, now),
        )
        connection.execute(
            """INSERT INTO durable_jobs(
                   id, project_id, kind, status, input_hash, idempotency_key, next_run_at,
                   lease_owner, lease_token, lease_expires_at, heartbeat_at, fencing_generation
               ) VALUES (%s, %s, 'workflow_c.analysis.semantic_metrics', 'running', %s, %s, %s,
                         'metric-parent', %s, %s, %s, 1)""",
            (
                parent_job_id,
                project["project"],
                input_hash,
                f"metric-parent:{parent_job_id}",
                now,
                lease_token,
                now + timedelta(hours=1),
                now,
            ),
        )
        connection.execute(
            """INSERT INTO workflow_c_job_specs(
                   project_id, job_id, kind, spec_hash, spec_payload, created_at
               ) VALUES (%s, %s, 'workflow_c.analysis.semantic_metrics', %s, %s::jsonb, %s)""",
            (project["project"], parent_job_id, input_hash, Jsonb(parent_spec), now),
        )
        connection.execute(
            """INSERT INTO workflow_c_sampling_runs(
                   id, project_id, suite_id, suite_hash, admission_policy_id,
                   admission_policy_hash, admission_grant_hash, purpose, status,
                   reserved_task_count, admitted_not_before, authorization_valid_until,
                   version, payload, created_at
               ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'geo_measurement', 'completed',
                         1, %s, %s, 1, '{}'::jsonb, %s)""",
            (
                run_id,
                project["project"],
                uuid4(),
                _hash("sampling-suite"),
                uuid4(),
                _hash("sampling-policy"),
                _hash("sampling-grant"),
                now - timedelta(minutes=1),
                now + timedelta(days=1),
                now,
            ),
        )
        connection.execute(
            """INSERT INTO workflow_c_sampling_observations(
                   id, project_id, run_id, task_id, attempt_id, task_key, source_stratum_hash,
                   status, observation_hash, actual_location_json, evidence_json, payload, observed_at
               ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'complete', %s,
                         '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, %s)""",
            (
                observation_id,
                project["project"],
                run_id,
                uuid4(),
                uuid4(),
                _hash("sampling-task"),
                _hash("sampling-source"),
                _hash("sampling-observation"),
                now,
            ),
        )
        connection.execute(
            """INSERT INTO prompt_programs(
                   id, project_id, program_kind, purpose, owner_id, created_at
               ) VALUES (%s, %s, 'metric_judge', 'monitoring.metric_judge', %s, %s)""",
            (program_id, project["project"], project["owner"], now),
        )
        connection.execute(
            """INSERT INTO prompt_program_releases(
                   id, project_id, program_id, program_kind, purpose, version, owner_id,
                   system_template, user_template, variable_schema_version, variable_schema,
                   input_schema_version, input_schema, output_schema_version, output_schema,
                   output_schema_hash, application_output_schema_version,
                   application_output_schema, application_output_schema_hash,
                   model_policy_version, model_policy, model_policy_hash, test_set_id,
                   test_set_version, test_set_hash, compiler_version, system_template_hash,
                   user_template_hash, release_hash, created_at
               ) VALUES (%s, %s, %s, 'metric_judge', 'monitoring.metric_judge', 1, %s,
                         'system', 'user', 'v1', '{}'::jsonb, 'v1', '{}'::jsonb,
                         'v1', '{}'::jsonb, %s, 'v1', '{}'::jsonb, %s,
                         'v1', '{}'::jsonb, %s, %s, 1, %s, 'compiler-v1',
                         %s, %s, %s, %s)""",
            (
                release_id,
                project["project"],
                program_id,
                project["owner"],
                _hash("portable-schema"),
                _hash("application-schema"),
                _hash("model-policy"),
                uuid4(),
                _hash("test-set"),
                _hash("system-template"),
                _hash("user-template"),
                release_hash,
                now,
            ),
        )
        connection.execute(
            """INSERT INTO prompt_program_release_states(
                   id, project_id, release_id, release_hash, version, previous_state_id,
                   status, acted_by, acted_at, evidence_ref, created_at
               ) VALUES (%s, %s, %s, %s, 2, %s, 'frozen', %s, %s,
                         'minio://evidence/prompt-frozen.json', %s)""",
            (state_id, project["project"], release_id, release_hash, uuid4(), project["reviewer"], now, now),
        )
        connection.execute(
            """INSERT INTO prompt_program_bindings(
                   id, project_id, purpose, program_kind, program_id, release_id,
                   release_version, release_hash, frozen_state_id, binding_version,
                   bound_by, bound_at, created_at
               ) VALUES (%s, %s, 'monitoring.metric_judge', 'metric_judge', %s, %s,
                         1, %s, %s, 1, %s, %s, %s)""",
            (binding_id, project["project"], program_id, release_id, release_hash, state_id, project["reviewer"], now, now),
        )
        connection.execute(
            """INSERT INTO model_gateway_runtime_manifests(
                   project_id, id, manifest_hash, schema_version, status, policy_version_id,
                   policy_version_hash, source_artifact_hash, option_count, prepared_by,
                   prepared_at, approved_by, approved_at, approval_evidence_reference,
                   approval_evidence_sha256
               ) VALUES (%s, %s, %s, 2, 'approved', %s, %s, %s, 1, %s, %s, %s, %s,
                         'minio://evidence/runtime.json', %s)""",
            (
                project["project"], manifest_id, manifest_hash, uuid4(), _hash("policy"),
                _hash("source-artifact"), project["owner"], now, project["reviewer"], now,
                _hash("runtime-evidence"),
            ),
        )
        connection.execute(
            """INSERT INTO model_gateway_runtime_options(
                   project_id, id, manifest_id, provider, adapter_release_id,
                   adapter_release_hash, model_release_id, model_release_hash,
                   secret_reference_id, secret_purpose, provider_config_hash,
                   allowed_purposes, allowed_search_modes, option_hash, created_at
               ) VALUES (%s, %s, %s, 'openai', 'fixture-adapter', %s,
                         'fixture-model', %s, %s, 'model_provider.openai', %s,
                         ARRAY['monitoring.metric_judge'], '[null]'::jsonb, %s, %s)""",
            (
                project["project"], option_id, manifest_id, _hash("adapter"),
                _hash("model"), uuid4(), _hash("provider-config"), option_hash, now,
            ),
        )
    finally:
        connection.execute("SET session_replication_role = origin")
    return {
        "job_id": parent_job_id,
        "lease_token": lease_token,
        "input_hash": input_hash,
        "run_id": run_id,
        "observation_id": observation_id,
        "binding_id": binding_id,
        "state_id": state_id,
        "release_id": release_id,
        "release_hash": release_hash,
        "manifest_id": manifest_id,
        "manifest_hash": manifest_hash,
        "option_id": option_id,
        "option_hash": option_hash,
    }


def _child_payload(
    *, child_id: UUID, candidate_id: UUID, ordinal: int, evaluator_id: str,
    parent: dict[str, UUID | str],
) -> dict[str, object]:
    task_hash = _hash(f"task:{child_id}")
    spec = {
        "schema_version": 1,
        "kind": "workflow_c.metric_judge",
        "metric_model_child": {
            "child_job_id": str(child_id),
            "parent_job_id": str(parent["job_id"]),
            "batch_id": "__batch_id__",
            "role": "metric_judge",
            "parent_input_hash": parent["input_hash"],
            "task_hash": task_hash,
        },
    }
    return {
        "id": str(child_id), "candidate_id": str(candidate_id), "ordinal": ordinal,
        "evaluator_id": evaluator_id,
        "runtime_selection_id": str(parent["option_id"]),
        "runtime_manifest_id": str(parent["manifest_id"]),
        "runtime_manifest_hash": parent["manifest_hash"],
        "runtime_option_id": str(parent["option_id"]),
        "runtime_option_hash": parent["option_hash"],
        "prompt_binding_id": str(parent["binding_id"]), "prompt_binding_version": 1,
        "prompt_frozen_state_id": str(parent["state_id"]), "prompt_state_version": 2,
        "prompt_release_id": str(parent["release_id"]), "prompt_release_version": 1,
        "prompt_release_hash": parent["release_hash"],
        "prompt_purpose": "monitoring.metric_judge", "prompt_bundle_hash": _hash("bundle"),
        "portable_output_schema_hash": _hash("portable-schema"),
        "application_output_schema_hash": _hash("application-schema"),
        "task_ciphertext": _base64(b"ciphertext"), "task_data_nonce": _base64(b"a" * 12),
        "task_wrapped_data_key": _base64(b"wrapped-key"), "task_wrap_nonce": _base64(b"b" * 12),
        "task_master_key_version": 1, "task_algorithm": "AES-256-GCM", "task_hash": task_hash,
        "spec_hash": "", "spec_payload": spec,
    }


def _finalize_payload(payload: list[dict[str, object]]) -> list[dict[str, object]]:
    batch_id = payload[0]["id"]
    children = payload[0]["children"]
    assert isinstance(children, list)
    for child in children:
        assert isinstance(child, dict)
        spec = child["spec_payload"]
        assert isinstance(spec, dict)
        ref = spec["metric_model_child"]
        assert isinstance(ref, dict)
        ref["batch_id"] = batch_id
        child["spec_hash"] = _json_hash(spec)
    return payload


def _base64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _database_url(base: str, database_name: str) -> str:
    parsed = urlsplit(base)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database_name}", "", ""))
