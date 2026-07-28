from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
import pytest

from geo_core.jobs.postgres import LostJobLease, PostgresDurableJobStore, WorkerLease
from geo_core.secrets import SecretVersionHandle
from geo_core.workflow_runtime import (
    PostgresWorkflowRuntimeCatalog,
    PostgresWorkflowRuntimeRepository,
    PublishedWorkflowSnapshot,
    WorkflowConfigurationError,
)
from geo_core.workflow_runtime.contracts import canonical_json_hash, canonical_json_text
from tests.integration.placement_worker_support import cleanup_projects, login_url, seed_project


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


@pytest.mark.parametrize(
    "value",
    [
        {"x": 1e-6, "y": 1.0, "z": 1e20, "negative_zero": -0.0},
        {"澳洲": "墨尔本", "a": [True, None, 0.1], "é": "café"},
        {"z": {"b": 2, "a": 1}, "a": []},
    ],
)
def test_dify_canonical_json_is_identical_in_python_and_postgres(
    value: dict[str, object],
) -> None:
    with psycopg.connect(ADMIN_URL) as connection:
        row = connection.execute(
            """SELECT geo_dify_canonical_text(%s::jsonb),
                      encode(digest(convert_to(geo_dify_canonical_text(%s::jsonb),
                                               'UTF8'), 'sha256'), 'hex')""",
            (Jsonb(value), Jsonb(value)),
        ).fetchone()
    assert row is not None
    assert row[0] == canonical_json_text(value)
    assert row[1] == canonical_json_hash(value)


def test_common_decimal_keeps_its_pre_fencing_hash() -> None:
    value = {"score": 0.1}
    assert canonical_json_text(value) == '{"score":0.1}'
    assert canonical_json_hash(value) == (
        "5ad4ab8d7a53f2ab00f96de87cb7dcbb68034ac77b7720fd6a90e9a37400d883"
    )


def test_dify_runtime_requires_real_canary_and_preserves_project_and_lease_boundaries() -> None:
    suffix = uuid4().hex[:10]
    app_login = f"geo_dify_app_{suffix}"
    worker_login = f"geo_dify_worker_{suffix}"
    app_password = uuid4().hex
    worker_password = uuid4().hex
    seeded_projects: list[dict[str, UUID]] = []
    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                sql.Identifier(app_login), sql.Literal(app_password)
            )
        )
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_worker").format(
                sql.Identifier(worker_login), sql.Literal(worker_password)
            )
        )
        project = seed_project(admin, suffix=f"dify-runtime-{suffix}")
        other = seed_project(admin, suffix=f"dify-runtime-other-{suffix}")
        seeded_projects.extend((project, other))
        prompt, secret = _seed_frozen_prompt_and_secret(admin, project)
        admin.commit()

    app_url = login_url(ADMIN_URL, user=app_login, password=app_password)
    worker_url = login_url(ADMIN_URL, user=worker_login, password=worker_password)
    catalog = PostgresWorkflowRuntimeCatalog(app_url)
    store = PostgresDurableJobStore(lambda: psycopg.connect(worker_url))
    repository = PostgresWorkflowRuntimeRepository(store)
    try:
        release_id = catalog.register_release(
            project_id=project["project"],
            purpose="knowledge.question_generation",
            prompt_program_id=prompt["program"],
            prompt_release_id=prompt["release"],
            dify_app_id="integration-app",
            dify_workflow_id="integration-workflow",
            dsl_hash="1" * 64,
            registered_workflow_hash="a" * 64,
            registered_snapshot_hash="b" * 64,
            configured_model="deepseek-chat",
            model_provider="langgenius/deepseek/deepseek",
            api_secret_handle=SecretVersionHandle(
                reference_id=secret,
                project_id=project["project"],
                purpose="workflow_runtime.dify",
                version=1,
            ),
            created_by=project["owner"],
        )
        assert catalog.register_release(
            project_id=project["project"],
            purpose="knowledge.question_generation",
            prompt_program_id=prompt["program"],
            prompt_release_id=prompt["release"],
            dify_app_id="integration-app",
            dify_workflow_id="integration-workflow",
            dsl_hash="1" * 64,
            registered_workflow_hash="a" * 64,
            registered_snapshot_hash="b" * 64,
            configured_model="deepseek-chat",
            model_provider="langgenius/deepseek/deepseek",
            api_secret_handle=SecretVersionHandle(
                reference_id=secret,
                project_id=project["project"],
                purpose="workflow_runtime.dify",
                version=1,
            ),
            created_by=project["owner"],
        ) == release_id

        with pytest.raises(psycopg.errors.CheckViolation, match="successful canary"):
            catalog.activate_release(
                project_id=project["project"],
                release_id=release_id,
                activated_by=project["owner"],
                reason="must not activate before canary",
            )

        release = repository.get_release(
            project_id=project["project"], release_id=release_id
        )
        observed_at = datetime.now(UTC)
        published_snapshot_id = repository.record_published_snapshot(
            release=release,
            snapshot=PublishedWorkflowSnapshot(
                purpose=release.purpose,
                app_id=release.dify_app_id,
                workflow_id=release.dify_workflow_id,
                workflow_hash="a" * 64,
                snapshot_hash="b" * 64,
                prompt_nodes=(
                    {
                        "node_id": "llm-1",
                        "model_provider": release.model_provider,
                        "model_name": release.configured_model,
                        "messages": [],
                    },
                ),
                input_variables=({"name": "geo_context_json"},),
                graph_nodes=(
                    {"node_id": "llm-1", "type": "llm", "title": "Prompt"},
                ),
                published_at=observed_at,
                observed_at=observed_at,
            ),
        )
        failed_attempt = repository.begin_canary_attempt(
            release=release,
            published_snapshot_id=published_snapshot_id,
            context_hash="2" * 64,
            request_hash="3" * 64,
        )
        repository.finish_canary_attempt(
            project_id=project["project"],
            attempt_id=failed_attempt,
            values={
                "status": "failed",
                "http_status": 503,
                "error_classification": "retryable",
                "error_code": "dify_unavailable",
                "error_message": "integration failure",
                "retryable": True,
            },
        )
        with pytest.raises(psycopg.errors.CheckViolation, match="successful canary"):
            catalog.activate_release(
                project_id=project["project"],
                release_id=release_id,
                activated_by=project["owner"],
                reason="a failed canary is not evidence",
            )

        successful_attempt = repository.begin_canary_attempt(
            release=release,
            published_snapshot_id=published_snapshot_id,
            context_hash="4" * 64,
            request_hash="5" * 64,
        )
        repository.finish_canary_attempt(
            project_id=project["project"],
            attempt_id=successful_attempt,
            values={
                "status": "succeeded",
                "dify_task_id": "task-integration",
                "dify_run_id": f"run-{suffix}",
                "reported_workflow_id": "integration-workflow",
                "output_hash": "6" * 64,
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_steps": 3,
                "elapsed_seconds": 0.5,
                "http_status": 200,
            },
        )
        binding_id = catalog.activate_release(
            project_id=project["project"],
            release_id=release_id,
            activated_by=project["owner"],
            reason="successful integration canary",
        )
        assert catalog.activate_release(
            project_id=project["project"],
            release_id=release_id,
            activated_by=project["owner"],
            reason="idempotent activation",
        ) == binding_id

        active = repository.resolve_active(
            project_id=project["project"], purpose="knowledge.question_generation"
        )
        assert active is not None
        assert active.id == release_id
        assert active.prompt_system_template == "Frozen integration system Prompt."
        assert active.binding_version == 1
        card = next(
            item
            for item in catalog.list_cards(project_id=project["project"])
            if item.purpose == "knowledge.question_generation"
        )
        assert card.activation_status == "active"
        assert card.last_attempt_status == "succeeded"
        assert all(
            item.backend == "native"
            for item in catalog.list_cards(project_id=other["project"])
        )
        with pytest.raises(WorkflowConfigurationError, match="not found"):
            repository.get_release(project_id=other["project"], release_id=release_id)

        job_id = uuid4()
        with psycopg.connect(ADMIN_URL) as admin:
            admin.execute(
                """INSERT INTO durable_jobs (
                       id, project_id, kind, input_hash, idempotency_key
                   ) VALUES (%s, %s, 'knowledge.question.generate', %s, %s)""",
                (job_id, project["project"], "7" * 64, f"dify-runtime-{suffix}"),
            )
            admin.commit()
        claim = store.claim(
            job_id=job_id,
            project_id=project["project"],
            expected_kind="knowledge.question.generate",
            worker_id="dify-integration-worker",
            lease_for=timedelta(seconds=30),
        )
        assert claim.lease is not None
        business_attempt = repository.begin_business_attempt(
            claim.lease,
            release=active,
            published_snapshot_id=published_snapshot_id,
            context_hash="8" * 64,
            request_hash="9" * 64,
        )
        stale_lease = WorkerLease(
            claim.lease.job_id,
            claim.lease.project_id,
            claim.lease.kind,
            claim.lease.worker_id,
            uuid4(),
            claim.lease.fencing_generation + 1,
            claim.lease.attempt_count,
            claim.lease.max_attempts,
        )
        with pytest.raises(LostJobLease, match="fenced"):
            repository.finish_business_attempt(
                stale_lease,
                attempt_id=business_attempt,
                values={
                    "status": "failed",
                    "error_classification": "cancelled",
                    "error_code": "stale_lease",
                    "error_message": "must not persist",
                    "retryable": False,
                },
            )
        business_output = {
            "questions": [{"text": "What should I compare?"}],
            # Provider JSON commonly contains floating-point scores. The application
            # and PostgreSQL finish RPC must hash every valid JSON number identically.
            "score": 1e-6,
            "estimated_reach": 1e20,
        }
        business_response_hash = canonical_json_hash(business_output)
        repository.finish_business_attempt(
            claim.lease,
            attempt_id=business_attempt,
            values={
                "status": "succeeded",
                "dify_task_id": "business-task",
                "dify_run_id": f"business-run-{suffix}",
                "reported_workflow_id": "integration-workflow",
                "output_hash": business_response_hash,
                "output": business_output,
                "response_hash": business_response_hash,
                "configured_model": "deepseek-chat",
                "provider_reported_model": "deepseek-v4-flash",
                "prompt_tokens": 11,
                "completion_tokens": 22,
                "total_steps": 3,
                "elapsed_seconds": 0.6,
                "http_status": 200,
            },
        )
        recovered = repository.load_successful_business_result(
            claim.lease,
            release=active,
            context_hash="8" * 64,
            request_hash="9" * 64,
        )
        assert recovered is not None
        assert recovered.output == business_output
        assert recovered.response_hash == business_response_hash
        assert recovered.provider_reported_model == "deepseek-v4-flash"
        with pytest.raises(WorkflowConfigurationError, match="already finalized"):
            repository.finish_business_attempt(
                claim.lease,
                attempt_id=business_attempt,
                values={
                    "status": "failed",
                    "error_classification": "provider",
                    "error_code": "second_terminal_write",
                    "error_message": "must fail",
                    "retryable": False,
                },
            )

        with psycopg.connect(ADMIN_URL) as admin:
            with pytest.raises(
                psycopg.errors.ObjectNotInPrerequisiteState, match="append-only"
            ):
                admin.execute(
                    "UPDATE dify_workflow_releases SET configured_model = 'changed' WHERE id = %s",
                    (release_id,),
                )
            admin.rollback()

        replacement_id = catalog.register_release(
            project_id=project["project"],
            purpose="knowledge.question_generation",
            prompt_program_id=prompt["program"],
            prompt_release_id=prompt["release"],
            dify_app_id="integration-app",
            dify_workflow_id="integration-workflow",
            dsl_hash="1" * 64,
            registered_workflow_hash="c" * 64,
            registered_snapshot_hash="d" * 64,
            configured_model="deepseek-chat",
            model_provider="langgenius/deepseek/deepseek",
            api_secret_handle=SecretVersionHandle(
                reference_id=secret,
                project_id=project["project"],
                purpose="workflow_runtime.dify",
                version=1,
            ),
            created_by=project["owner"],
        )
        assert replacement_id != release_id
        replacement = repository.get_release(
            project_id=project["project"], release_id=replacement_id
        )
        assert replacement.version == 2
        assert replacement.release_hash != release.release_hash
        replacement_snapshot = PublishedWorkflowSnapshot(
            purpose=replacement.purpose,
            app_id=replacement.dify_app_id,
            workflow_id=replacement.dify_workflow_id,
            workflow_hash="c" * 64,
            snapshot_hash="d" * 64,
            prompt_nodes=(
                {
                    "node_id": "llm-2",
                    "model_provider": replacement.model_provider,
                    "model_name": replacement.configured_model,
                    "messages": [],
                },
            ),
            input_variables=({"name": "geo_context_json"},),
            graph_nodes=({"node_id": "llm-2", "type": "llm", "title": "Prompt"},),
            published_at=observed_at + timedelta(seconds=1),
            observed_at=observed_at + timedelta(seconds=1),
        )
        with pytest.raises(
            WorkflowConfigurationError,
            match="differs from its registered GEO Release",
        ):
            catalog.record_published_snapshot(
                project_id=project["project"],
                release_id=release_id,
                snapshot=replacement_snapshot,
            )
        replacement_snapshot_id = repository.record_published_snapshot(
            release=replacement,
            snapshot=replacement_snapshot,
        )
        replacement_canary = repository.begin_canary_attempt(
            release=replacement,
            published_snapshot_id=replacement_snapshot_id,
            context_hash="a" * 64,
            request_hash="b" * 64,
        )
        repository.finish_canary_attempt(
            project_id=project["project"],
            attempt_id=replacement_canary,
            values={
                "status": "succeeded",
                "dify_task_id": "replacement-task",
                "dify_run_id": f"replacement-run-{suffix}",
                "reported_workflow_id": "integration-workflow",
                "output_hash": "c" * 64,
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_steps": 3,
                "elapsed_seconds": 0.5,
                "http_status": 200,
            },
        )
        catalog.activate_release(
            project_id=project["project"],
            release_id=replacement_id,
            activated_by=project["owner"],
            reason="same Dify Workflow ID with a newly enrolled published graph",
        )
        assert repository.resolve_active(
            project_id=project["project"], purpose="knowledge.question_generation"
        ).id == replacement_id
        with psycopg.connect(ADMIN_URL) as admin:
            identities = admin.execute(
                """SELECT release_id, workflow_hash, snapshot_hash
                   FROM dify_workflow_release_snapshot_pins
                   WHERE project_id = %s AND release_id IN (%s, %s)""",
                (project["project"], release_id, replacement_id),
            ).fetchall()
        assert set(identities) == {
            (release_id, "a" * 64, "b" * 64),
            (replacement_id, "c" * 64, "d" * 64),
        }
    finally:
        with psycopg.connect(ADMIN_URL) as admin:
            cleanup_projects(
                admin,
                projects=seeded_projects,
                tenant_ids=[item["tenant"] for item in seeded_projects],
                app_login=app_login,
                worker_login=worker_login,
            )
            admin.commit()


def _seed_frozen_prompt_and_secret(
    connection: psycopg.Connection, project: dict[str, UUID]
) -> tuple[dict[str, UUID], UUID]:
    prompt = {
        "program": uuid4(),
        "release": uuid4(),
        "binding": uuid4(),
        "test_set": uuid4(),
    }
    state_ids = [uuid4() for _ in range(4)]
    secret_id = uuid4()
    connection.execute("SET LOCAL session_replication_role = replica")
    connection.execute(
        """INSERT INTO secret_master_key_versions (
               master_key_version, algorithm, status, canary_nonce,
               canary_ciphertext, created_at, activated_at
           ) VALUES (1, 'AES-256-GCM', 'encrypt_decrypt', %s, %s,
                     clock_timestamp(), clock_timestamp())
           ON CONFLICT (master_key_version) DO NOTHING""",
        (b"n" * 12, b"c" * 17),
    )
    connection.execute(
        """INSERT INTO secret_references (
               id, project_id, purpose, aggregate_version, current_version,
               created_by, created_at, updated_at
           ) VALUES (%s, %s, 'workflow_runtime.dify', 2, 1, %s,
                     clock_timestamp(), clock_timestamp())""",
        (secret_id, project["project"], project["owner"]),
    )
    connection.execute(
        """INSERT INTO secret_versions (
               reference_id, project_id, purpose, version, ciphertext,
               data_nonce, wrapped_data_key, wrap_nonce, master_key_version,
               algorithm, created_at, status, created_by, verified_by,
               verified_at, activated_by, activated_at
           ) VALUES (
               %s, %s, 'workflow_runtime.dify', 1, %s, %s, %s, %s, 1,
               'AES-256-GCM', clock_timestamp(), 'active', %s, %s,
               clock_timestamp(), %s, clock_timestamp()
           )""",
        (
            secret_id,
            project["project"],
            b"x" * 17,
            b"n" * 12,
            b"k" * 48,
            b"w" * 12,
            project["owner"],
            project["reviewer"],
            project["reviewer"],
        ),
    )
    connection.execute(
        """INSERT INTO prompt_programs (
               id, project_id, program_kind, purpose, owner_id
           ) VALUES (
               %s, %s, 'question_generation', 'knowledge.question_generation', %s
           )""",
        (prompt["program"], project["project"], project["owner"]),
    )
    connection.execute(
        """INSERT INTO prompt_program_releases (
               id, project_id, program_id, program_kind, purpose, version, owner_id,
               system_template, user_template, variable_schema_version, variable_schema,
               input_schema_version, input_schema, output_schema_version, output_schema,
               output_schema_hash, application_output_schema_version,
               application_output_schema, application_output_schema_hash,
               model_policy_version, model_policy, model_policy_hash,
               test_set_id, test_set_version, test_set_hash, compiler_version,
               system_template_hash, user_template_hash, release_hash
           ) VALUES (
               %s, %s, %s, 'question_generation', 'knowledge.question_generation', 1, %s,
               'Frozen integration system Prompt.',
               'Use this request: {{request_json}}',
               'v1', '{}'::jsonb, 'v1', '{}'::jsonb, 'v1', '{}'::jsonb,
               %s, 'v1', '{}'::jsonb, %s, 'v1', '{}'::jsonb, %s,
               %s, 1, %s, 'integration-v1', %s, %s, %s
           )""",
        (
            prompt["release"],
            project["project"],
            prompt["program"],
            project["owner"],
            "1" * 64,
            "2" * 64,
            "3" * 64,
            prompt["test_set"],
            "4" * 64,
            "5" * 64,
            "6" * 64,
            "7" * 64,
        ),
    )
    statuses = ("draft", "tested", "approved", "frozen")
    for index, (state_id, status) in enumerate(zip(state_ids, statuses, strict=True), 1):
        connection.execute(
            """INSERT INTO prompt_program_release_states (
                   id, project_id, release_id, release_hash, version,
                   previous_state_id, status, acted_by, acted_at, evidence_ref
               ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                         clock_timestamp(), %s)""",
            (
                state_id,
                project["project"],
                prompt["release"],
                "7" * 64,
                index,
                state_ids[index - 2] if index > 1 else None,
                status,
                project["owner"],
                None if status == "draft" else f"integration:{status}",
            ),
        )
    connection.execute(
        """INSERT INTO prompt_program_bindings (
               id, project_id, purpose, program_kind, program_id, release_id,
               release_version, release_hash, frozen_state_id, binding_version,
               previous_binding_id, bound_by, bound_at
           ) VALUES (
               %s, %s, 'knowledge.question_generation', 'question_generation',
               %s, %s, 1, %s, %s, 1, NULL, %s, clock_timestamp()
           )""",
        (
            prompt["binding"],
            project["project"],
            prompt["program"],
            prompt["release"],
            "7" * 64,
            state_ids[-1],
            project["owner"],
        ),
    )
    connection.execute("SET LOCAL session_replication_role = origin")
    return prompt, secret_id
