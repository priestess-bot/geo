from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from alembic import command as alembic_command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest

from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.domain import StyleProfileStatus, StyleProfileVersion
from geo_core.synthetic_lab.execution_contracts import (
    FrozenPromptRef,
    StyleProfileBuildOutput,
    SyntheticExecutionError,
)
from geo_core.synthetic_lab.ports import (
    LabPrincipal,
    LabRole,
    StaticRuntimeInputPort,
    SyntheticLabPersistenceError,
    VersionedAggregate,
)
from geo_core.synthetic_lab.postgres import build_synthetic_lab_persistence
from geo_core.synthetic_lab.postgres_api_reads import PostgresSyntheticApiReads
from geo_core.synthetic_lab.postgres_execution import build_synthetic_execution_repository
from geo_core.synthetic_lab.postgres_manual_import import PostgresManualImportService
from tests.integration.model_gateway_postgres_fixtures import (
    active_provider_secret,
    register_openai_runtime,
)
from tests.integration.placement_worker_support import login_url, seed_project
from tests.integration.style_profile_native_result_support import (
    StyleNativeDatabase,
    build_style_task,
    complete_native_child,
    seed_style_prompt,
)


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


@pytest.fixture
def database() -> StyleNativeDatabase:
    suffix = uuid4().hex[:10]
    database_name = f"geo_style_native_{suffix}"
    target_url = _database_url(ADMIN_URL, database_name)
    app_login, app_password = f"geo_style_app_{suffix}", uuid4().hex
    worker_login, worker_password = f"geo_style_worker_{suffix}", uuid4().hex
    roles: list[str] = []
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = target_url
        alembic_command.upgrade(migration, "head")
        with psycopg.connect(target_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                    sql.Identifier(app_login), sql.Literal(app_password)
                )
            )
            roles.append(app_login)
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_worker").format(
                    sql.Identifier(worker_login), sql.Literal(worker_password)
                )
            )
            roles.append(worker_login)
            ids = seed_project(admin, suffix=f"style-native-{suffix}")
        yield StyleNativeDatabase(
            admin_url=target_url,
            app_url=login_url(target_url, user=app_login, password=app_password),
            worker_url=login_url(target_url, user=worker_login, password=worker_password),
            ids=ids,
        )
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )
            for role in reversed(roles):
                server.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))


def test_native_style_profile_result_requires_exact_child_and_gateway_lineage(
    database: StyleNativeDatabase,
    tmp_path: Path,
) -> None:
    project_id = database.ids["project"]
    principal = LabPrincipal(
        project_id=project_id,
        actor_id=database.ids["owner"],
        roles=frozenset({LabRole.OPERATOR}),
    )
    _secret_api, provider_secret = active_provider_secret(
        app_url=database.app_url,
        ids=database.ids,
        directory=tmp_path,
    )
    runtime = register_openai_runtime(
        app_url=database.app_url,
        ids=database.ids,
        provider_secret_handle=provider_secret,
        approved_at=datetime.now(UTC),
        allowed_purposes=("synthetic_lab.style_profile",),
        required_purpose="synthetic_lab.style_profile",
        search_mode=None,
    )
    task = build_style_task(
        project_id,
        requested_by=principal.actor_id,
        runtime=runtime,
    )
    seed_style_prompt(database.admin_url, task)
    persistence = build_synthetic_lab_persistence(database.app_url)
    assert persistence is not None
    enqueued = persistence.execution.enqueue(
        principal=principal,
        task=task,
        outbox_id=uuid4(),
        runtime_inputs=StaticRuntimeInputPort(task.runtime_inputs),
        prompts=_CurrentPrompts(),
        idempotency_key="style-profile-native:parent:v1",
    )
    assert not enqueued.replayed and enqueued.result.input_hash == task.input_hash

    store = PostgresDurableJobStore(
        lambda: psycopg.connect(database.worker_url, row_factory=dict_row)
    )
    claimed = store.claim(
        job_id=task.job_id,
        project_id=project_id,
        expected_kind="style.profile.build",
        worker_id="style-profile-parent-worker",
        lease_for=timedelta(minutes=2),
    )
    assert claimed.disposition == "claimed" and claimed.lease is not None
    lease = claimed.lease
    output, child_job_id = complete_native_child(
        database=database,
        directory=tmp_path,
        task=task,
        parent_lease=lease,
        runtime=runtime,
    )
    assert "\\u2013" in (output.profile_summary or "")
    repository = build_synthetic_execution_repository(database.worker_url)
    invalid = _invalid_outputs(output)
    for candidate in invalid:
        with store.fenced_transaction(lease) as connection:
            with pytest.raises(
                SyntheticExecutionError,
                match="PostgreSQL rejected Synthetic execution finalization",
            ):
                repository.finalize(
                    connection=connection,
                    lease=lease,
                    task=task,
                    output=candidate,
                    runtime=task.runtime_inputs,
                )
    with store.fenced_transaction(lease) as connection:
        repository.finalize(
            connection=connection,
            lease=lease,
            task=task,
            output=output,
            runtime=task.runtime_inputs,
        )
        store.complete_in_transaction(
            connection,
            lease,
            result_ref=f"synthetic://result/{output.result_hash}",
            details={"result_hash": output.result_hash},
        )

    profile = StyleProfileVersion(
        id=task.profile_version_id,
        project_id=project_id,
        profile_id=task.profile_id,
        version_number=task.version_number,
        channel=task.channel,
        locale=task.locale,
        corpus_hash=task.corpus_hash,
        profile_hash=task.runtime_inputs.profile_hash,
        prompt_release_id=task.prompt.release_id,
        prompt_release_hash=task.prompt.release_hash,
        approved_sample_count=task.approved_sample_count,
        status=StyleProfileStatus.DRAFT,
    )
    with persistence.uow_factory(project_id=project_id) as unit_of_work:
        unit_of_work.aggregates.stage(
            VersionedAggregate(
                project_id=project_id,
                kind="style_profile",
                resource_id=profile.id,
                version=1,
                submitted_by=principal.actor_id,
                payload=profile,
            ),
            expected_version=0,
        )
        unit_of_work.commit()
    reads = PostgresSyntheticApiReads(
        lambda: psycopg.connect(database.app_url, row_factory=dict_row)
    )
    candidate = reads.profile_build_candidate(
        project_id,
        profile_version_id=profile.id,
        profile_hash=profile.profile_hash,
        bound_by=principal.actor_id,
    )
    assert candidate is not None and candidate.output == output
    submitted = persistence.review.submit_profile(
        principal=principal,
        profile=profile,
        build_binding=candidate.binding,
        expected_version=1,
        idempotency_key="style-profile-native:submit:v1",
    )
    assert submitted.result.status is StyleProfileStatus.IN_REVIEW
    _assert_persisted_lineage(database, task.job_id, child_job_id, profile.id)


def test_postgres_profile_examples_rejects_fewer_than_24_eligible_rows(
    database: StyleNativeDatabase,
) -> None:
    sample_ids = tuple(uuid4() for _ in range(23))
    manifest_id, request_id = uuid4(), uuid4()
    with psycopg.connect(database.admin_url) as connection:
        connection.execute("SET LOCAL session_replication_role = replica")
        for index, sample_id in enumerate(sample_ids, 1):
            normalized_hash = canonical_hash(f"eligible-example:{index}")
            connection.execute(
                """INSERT INTO synthetic_lab_imported_samples(
                       id, project_id, manifest_id, request_id, row_number,
                       channel, locale, style_source_revision_id,
                       source_revision_number, collection_run_id,
                       normalized_text_hash, source_locator_hash,
                       source_artifact_hash, source_rights, rights_evidence_hash,
                       language_reviewer_id, language_reviewed_at,
                       short_example_eligible, short_example_exclusion_codes
                   ) VALUES (%s, %s, %s, %s, %s, 'reddit', 'en-AU', %s, 1, %s,
                             %s, %s, %s, 'public_reference', %s, %s,
                             clock_timestamp(), true, ARRAY[]::text[])""",
                (
                    sample_id,
                    database.ids["project"],
                    manifest_id,
                    request_id,
                    index,
                    uuid4(),
                    uuid4(),
                    normalized_hash,
                    canonical_hash(f"locator:{index}"),
                    canonical_hash(f"source:{index}"),
                    canonical_hash(f"rights:{index}"),
                    database.ids["reviewer"],
                ),
            )
            connection.execute(
                """INSERT INTO synthetic_lab_imported_sample_artifacts(
                       project_id, sample_id, object_uri, object_hash,
                       plaintext_hash, key_version, algorithm, media_type,
                       byte_size, created_at
                   ) VALUES (%s, %s, %s, %s, %s, '1',
                             'AES-256-GCM/HKDF-project-artifact/v1',
                             'application/vnd.geo.synthetic-manual-import+encrypted',
                             128, clock_timestamp())""",
                (
                    database.ids["project"],
                    sample_id,
                    "s3://integration/synthetic-lab/manual-import/"
                    f"anonymized_sample/{sample_id}.bin",
                    canonical_hash(f"ciphertext:{index}"),
                    normalized_hash,
                ),
            )
    service = PostgresManualImportService(
        connection_factory=lambda: psycopg.connect(
            database.app_url, row_factory=dict_row
        ),
        artifacts=_NoArtifacts(),  # type: ignore[arg-type]
    )
    with pytest.raises(
        SyntheticLabPersistenceError,
        match=r"found 23 .* requires 24.*approve 1 more eligible sample",
    ):
        service.load_profile_examples(
            project_id=database.ids["project"],
            sample_ids=sample_ids,
        )


def _invalid_outputs(
    output: StyleProfileBuildOutput,
) -> tuple[StyleProfileBuildOutput, ...]:
    summary = json.loads(output.profile_summary or "{}")
    summary["voice_traits"] = ["tampered"]
    return (
        replace(output, model_call_ids=(uuid4(),)),
        replace(output, model_call_ids=(), workflow_attempt_ids=(uuid4(),)),
        replace(
            output,
            profile_summary=json.dumps(
                summary, ensure_ascii=True, sort_keys=True, separators=(",", ":")
            ),
            artifact_hash=canonical_hash(summary),
        ),
    )


def _assert_persisted_lineage(
    database: StyleNativeDatabase,
    parent_job_id: UUID,
    child_job_id: UUID,
    profile_version_id: UUID,
) -> None:
    with psycopg.connect(database.admin_url) as connection:
        row = connection.execute(
            """SELECT binding.verification_status, binding.binding_source,
                      binding.rebuild_required, lineage.child_job_id,
                      parent.status, child.status
               FROM synthetic_lab_style_profile_build_bindings AS binding
               JOIN durable_jobs AS parent
                 ON parent.id = binding.execution_job_id
                AND parent.project_id = binding.project_id
               JOIN synthetic_lab_model_call_children AS lineage
                 ON lineage.parent_job_id = binding.execution_job_id
                AND lineage.project_id = binding.project_id
               JOIN durable_jobs AS child
                 ON child.id = lineage.child_job_id
                AND child.project_id = lineage.project_id
               WHERE binding.project_id = %s AND binding.profile_version_id = %s""",
            (database.ids["project"], profile_version_id),
        ).fetchone()
        assert row == (
            "verified",
            "runtime_review",
            False,
            child_job_id,
            "succeeded",
            "succeeded",
        )
        assert parent_job_id != child_job_id
        with pytest.raises(psycopg.Error, match="immutable"):
            connection.execute(
                """UPDATE synthetic_lab_style_profile_build_bindings
                   SET artifact_hash = %s
                   WHERE project_id = %s AND profile_version_id = %s""",
                ("0" * 64, database.ids["project"], profile_version_id),
            )


class _CurrentPrompts:
    def assert_current(self, frozen: FrozenPromptRef) -> None:
        del frozen


class _NoArtifacts:
    def load(self, _reference: object) -> bytearray:
        raise AssertionError("insufficient example count must fail before decryption")


def _database_url(database_url: str, database_name: str) -> str:
    parsed = urlsplit(database_url)
    return urlunsplit(parsed._replace(path=f"/{database_name}"))
