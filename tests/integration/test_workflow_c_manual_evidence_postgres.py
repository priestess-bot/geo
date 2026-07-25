from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
from uuid import uuid4

from alembic import command as alembic_command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest

from geo_api.workflow_c_sampling_contracts import (
    ReviewManualEvidenceRequest,
    SubmitManualEvidenceRequest,
)
from geo_api.workflow_c_sampling_postgres_manual import (
    PostgresWorkflowCManualEvidenceControl,
)
from geo_core.project_scope import set_project_scope
from geo_core.sampling import (
    ManualEvidenceStatus,
    PostgresManualEvidenceRepository,
    PostgresSamplingRunRepository,
    PostgresSamplingSuiteRepository,
    SURFACE_PARSER_RELEASES,
    SurfaceParseOutcome,
)
from geo_core.sampling.manual_artifact_governance import AUTOMATIC_POLICY_KEY
from geo_core.sampling.manual_artifact_storage import (
    IndependentWorkflowCArtifactEncryptor,
    MinioWorkflowCManualArtifactWriter,
)
from geo_core.secrets import EnvelopeCipher, MasterKeyring
from geo_core.workflow_c_artifacts.postgres import (
    PostgresWorkflowCArtifactKeyVault,
    PostgresWorkflowCManualArtifactRepository,
    synchronize_workflow_c_artifact_master_keys,
)
from tests.integration.monitoring_postgres_support import isolated_minio_store
from tests.integration.placement_worker_support import login_url, seed_project
from tests.integration.test_workflow_c_artifact_maintenance_postgres import (
    _create_manual_sampling_lineage,
    _database_url,
    _seed_manual_runtime_option,
)


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_manual_evidence_submit_and_approval_create_one_durable_attempt() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_wfc_manual_evidence_{suffix}"
    database_url = _database_url(ADMIN_URL, database_name)
    app_login, app_password = f"geo_wfc_manual_app_{suffix}", uuid4().hex
    created_database = False
    created_login = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = database_url
        alembic_command.upgrade(migration, "head")
        with psycopg.connect(database_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                    sql.Identifier(app_login), sql.Literal(app_password)
                )
            )
            created_login = True
            project_id = seed_project(admin, suffix=f"wfc-manual-evidence-{suffix}")["project"]
            _seed_manual_runtime_option(
                admin,
                project_id=project_id,
                platform="google",
                adapter_release="manual-google-aio-v1",
            )

        app_url = login_url(database_url, user=app_login, password=app_password)

        def app_connect():
            return psycopg.connect(app_url, row_factory=dict_row)

        now = datetime.now(UTC).replace(microsecond=0)
        cipher = EnvelopeCipher(MasterKeyring(keys={1: b"M" * 32}, active_version=1))
        with psycopg.connect(database_url, row_factory=dict_row) as admin:
            assert synchronize_workflow_c_artifact_master_keys(admin, cipher) == (1,)

        with isolated_minio_store() as objects:
            parser_release = SURFACE_PARSER_RELEASES[0]
            run_id, task_id = _create_manual_sampling_lineage(
                app_connect=app_connect,
                project_id=project_id,
                now=now,
                source_platform="google",
                source_surface="ai_overviews",
                adapter_release="manual-google-aio-v1",
            )
            suites = PostgresSamplingSuiteRepository(connect=app_connect)
            run = PostgresSamplingRunRepository(connect=app_connect).get_run(
                project_id=project_id, run_id=run_id
            )
            suite = suites.get_suite(project_id=project_id, suite_id=run.suite_id)
            task = next(
                item
                for item in PostgresSamplingRunRepository(connect=app_connect).list_tasks(
                    project_id=project_id, run_id=run_id, suite=suite
                )
                if item.id == task_id
            )
            writer = MinioWorkflowCManualArtifactWriter(
                object_store=objects,
                encryptor=IndependentWorkflowCArtifactEncryptor(
                    PostgresWorkflowCArtifactKeyVault(
                        connect=app_connect, cipher=cipher, synchronize=False
                    )
                ),
                repository=PostgresWorkflowCManualArtifactRepository(connect=app_connect),
                clock=lambda: now,
            )
            imports = PostgresManualEvidenceRepository(connect=app_connect)
            control = PostgresWorkflowCManualEvidenceControl(
                imports=imports,
                runs=PostgresSamplingRunRepository(connect=app_connect),
                suites=suites,
                artifact_writer=writer,
                clock=lambda: now,
            )
            approved_payload = SubmitManualEvidenceRequest(
                expected_task_version=task.version,
                content_base64=base64.b64encode(
                    json.dumps(_surface_artifact(parser_release)).encode()
                ).decode("ascii"),
                content_type="application/json",
                governance_policy_option_key=AUTOMATIC_POLICY_KEY,
                evidence_kind="transcript_export",
                pre_redacted_attestation=False,
                device="desktop",
                locale="en-AU",
                captured_at=now - timedelta(seconds=1),
                surface_parser_release_id=parser_release.id,
            )
            submitted = control.submit(
                project_id=project_id,
                run_id=run_id,
                task_id=task_id,
                actor_id="capture-operator",
                idempotency_key="manual-evidence:approve-submit",
                payload=approved_payload,
            )
            replayed_submission = control.submit(
                project_id=project_id,
                run_id=run_id,
                task_id=task_id,
                actor_id="capture-operator",
                idempotency_key="manual-evidence:approve-submit",
                payload=approved_payload,
            )
            assert submitted == replayed_submission
            assert submitted.status is ManualEvidenceStatus.PENDING_REVIEW
            assert submitted.aggregate_version == 1
            assert submitted.surface_parse is not None
            assert submitted.surface_parse.outcome is SurfaceParseOutcome.CAPTURED
            assert submitted.surface_parse.parser_release_hash == parser_release.release_hash
            assert submitted.surface_parse.automated_capture is False
            assert submitted.surface_parse.live_capture_eligible is False

            with app_connect() as connection:
                set_project_scope(connection, project_id)
                artifact = connection.execute(
                    """SELECT status FROM workflow_c_manual_artifacts
                       WHERE project_id = %s AND artifact_id = %s""",
                    (project_id, submitted.artifact_manifest_id),
                ).fetchone()
                attempts = connection.execute(
                    """SELECT count(*) AS count FROM workflow_c_sampling_attempts
                       WHERE project_id = %s""",
                    (project_id,),
                ).fetchone()
                can_insert = connection.execute(
                    """SELECT has_table_privilege(
                           current_user, 'workflow_c_sampling_manual_imports', 'INSERT'
                       ) AS allowed"""
                ).fetchone()
                parsed = connection.execute(
                    """SELECT summary_hash, outcome, summary
                       FROM workflow_c_surface_parse_results
                       WHERE project_id = %s AND manual_import_id = %s""",
                    (project_id, submitted.id),
                ).fetchone()
                can_insert_parse = connection.execute(
                    """SELECT has_table_privilege(
                           current_user, 'workflow_c_surface_parse_results', 'INSERT'
                       ) AS allowed"""
                ).fetchone()
            assert artifact == {"status": "active"}
            assert attempts == {"count": 0}
            assert can_insert == {"allowed": False}
            assert parsed is not None
            assert parsed["outcome"] == "captured"
            assert parsed["summary_hash"] == submitted.surface_parse.summary_hash
            assert "answer_text" not in parsed["summary"]
            assert "citations" not in parsed["summary"]
            assert can_insert_parse == {"allowed": False}

            approved = control.review(
                project_id=project_id,
                import_id=submitted.id,
                actor_id="review-operator",
                idempotency_key="manual-evidence:approve",
                approved=True,
                payload=ReviewManualEvidenceRequest(
                    expected_version=submitted.aggregate_version,
                    reason="capture contains the required AU result",
                ),
            )
            replayed_approval = control.review(
                project_id=project_id,
                import_id=submitted.id,
                actor_id="review-operator",
                idempotency_key="manual-evidence:approve",
                approved=True,
                payload=ReviewManualEvidenceRequest(
                    expected_version=submitted.aggregate_version,
                    reason="capture contains the required AU result",
                ),
            )
            assert approved == replayed_approval
            assert approved.status is ManualEvidenceStatus.APPROVED
            assert approved.aggregate_version == 2

            with app_connect() as connection:
                set_project_scope(connection, project_id)
                attempt = connection.execute(
                    """SELECT status, durable_job_id FROM workflow_c_sampling_attempts
                       WHERE project_id = %s AND id = %s""",
                    (project_id, submitted.attempt_id),
                ).fetchone()
                can_read_spec = connection.execute(
                    """SELECT has_table_privilege(
                           current_user, 'workflow_c_job_specs', 'SELECT'
                       ) AS allowed"""
                ).fetchone()
            with psycopg.connect(database_url, row_factory=dict_row) as admin:
                job_spec = admin.execute(
                    """SELECT kind, spec_payload->>'manual_import_id' AS manual_import_id
                       FROM workflow_c_job_specs
                       WHERE project_id = %s AND job_id = %s""",
                    (project_id, attempt["durable_job_id"] if attempt else None),
                ).fetchone()
                outbox = admin.execute(
                    """SELECT count(*) AS count FROM broker_outbox
                       WHERE project_id = %s AND job_id = %s""",
                    (project_id, attempt["durable_job_id"] if attempt else None),
                ).fetchone()
            assert attempt is not None and attempt["status"] == "queued"
            assert can_read_spec == {"allowed": False}
            assert job_spec == {
                "kind": "sampling.manual_import",
                "manual_import_id": str(submitted.id),
            }
            assert outbox == {"count": 1}

            rejected_task = next(
                item
                for item in PostgresSamplingRunRepository(connect=app_connect).list_tasks(
                    project_id=project_id, run_id=run_id, suite=suite
                )
                if item.id != task_id
            )
            rejected_payload = SubmitManualEvidenceRequest(
                expected_task_version=rejected_task.version,
                content_base64=base64.b64encode(
                    b'{"answer":"insufficient capture"}'
                ).decode("ascii"),
                content_type="application/json",
                governance_policy_option_key=AUTOMATIC_POLICY_KEY,
                evidence_kind="transcript_export",
                pre_redacted_attestation=False,
                device="desktop",
                locale="en-AU",
                captured_at=now - timedelta(seconds=1),
            )
            rejected_import = control.submit(
                project_id=project_id,
                run_id=run_id,
                task_id=rejected_task.id,
                actor_id="capture-operator",
                idempotency_key="manual-evidence:control-reject-submit",
                payload=rejected_payload,
            )
            assert rejected_import.status is ManualEvidenceStatus.PENDING_REVIEW
            rejected = control.review(
                project_id=project_id,
                import_id=rejected_import.id,
                actor_id="review-operator",
                idempotency_key="manual-evidence:control-reject",
                approved=False,
                payload=ReviewManualEvidenceRequest(
                    expected_version=rejected_import.aggregate_version,
                    reason="capture does not show a complete answer",
                ),
            )
            assert rejected.status is ManualEvidenceStatus.REJECTED
            assert rejected.aggregate_version == 2
            with app_connect() as connection:
                set_project_scope(connection, project_id)
                rejected_attempt = connection.execute(
                    """SELECT count(*) AS count FROM workflow_c_sampling_attempts
                       WHERE project_id = %s AND id = %s""",
                    (project_id, rejected_import.attempt_id),
                ).fetchone()
            assert rejected_attempt == {"count": 0}

            with pytest.raises(
                Exception,
                match="cannot downgrade consumer surface parser results after evidence exists",
            ):
                alembic_command.downgrade(migration, "0046_wfc_artifact_encryption")
    finally:
        if created_database:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )
        if created_login:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(app_login)))


def _surface_artifact(release) -> dict[str, object]:
    return {
        "schema_version": "consumer-surface-artifact-v1",
        "platform": release.platform,
        "surface": release.surface.value,
        "final_url": "https://www.google.com/search?q=fixture",
        "page_ready": True,
        "surface_markers": [release.surface_marker],
        "ordinary_result_markers": ["ordinary_results_ready"],
        "answer_blocks": [
            {
                "text": "Australian consumer result",
                "locator": "dom://answer/1",
            }
        ],
        "citations": [
            {
                "url": "https://example.com/official",
                "title": "Official source",
                "position": 1,
                "locator": "dom://citation/1",
            }
        ],
        "blocking_state": None,
        "follow_up_count": 1,
    }
