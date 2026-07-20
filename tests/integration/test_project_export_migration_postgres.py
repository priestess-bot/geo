from __future__ import annotations

import os
from uuid import UUID, uuid4

from alembic import command
import psycopg
import pytest
from sqlalchemy.exc import DBAPIError

from geo_core.project_scope import set_project_scope
from tests.integration.test_batch2_migrations_postgres import (
    _seed_legacy_fixture,
    _sha256,
    _temporary_database,
)


ADMIN_URL = os.getenv("GEO_ACCESS_TEST_ADMIN_DATABASE_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not ADMIN_URL,
        reason="GEO_ACCESS_TEST_ADMIN_DATABASE_URL is required",
    ),
]


def _insert_export(
    connection: psycopg.Connection[object],
    *,
    project_id: UUID,
    requested_by: UUID,
    audience: str = "admin",
    campaign_id: UUID | None = None,
) -> tuple[UUID, str, str]:
    job_id = uuid4()
    input_hash = _sha256(f"project-export-input:{job_id}")
    manifest_hash = _sha256(f"project-export-manifest:{job_id}")
    connection.execute(
        """INSERT INTO durable_jobs
             (id, project_id, campaign_id, kind, input_hash, idempotency_key)
           VALUES (%s, %s, %s, 'project.export', %s, %s)""",
        (job_id, project_id, campaign_id, input_hash, f"project-export:{job_id}"),
    )
    connection.execute(
        """INSERT INTO project_export_specs
             (job_id, project_id, campaign_id, audience, requested_by, input_hash)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (job_id, project_id, campaign_id, audience, requested_by, input_hash),
    )
    campaign = str(campaign_id) if campaign_id is not None else "all-campaigns"
    storage_key = (
        f"project-exports/{project_id}/{audience}/{campaign}/{manifest_hash}.zip"
    )
    connection.execute(
        """INSERT INTO project_export_artifacts
             (job_id, project_id, campaign_id, audience, storage_key,
              artifact_uri, content_hash, manifest_hash, byte_count,
              file_count, finalized_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1024, 10,
                   clock_timestamp())""",
        (
            job_id,
            project_id,
            campaign_id,
            audience,
            storage_key,
            f"s3://geo-test/{storage_key}",
            _sha256(f"project-export-archive:{job_id}"),
            manifest_hash,
        ),
    )
    return job_id, input_hash, manifest_hash


def test_project_export_migration_round_trip_contract_and_fail_closed_down() -> None:
    with _temporary_database() as (database_url, configuration):
        command.upgrade(configuration, "0011_runtime_health")
        with psycopg.connect(database_url) as admin:
            fixture = _seed_legacy_fixture(admin)

        command.upgrade(configuration, "0020_project_exports")
        with psycopg.connect(database_url) as admin:
            assert admin.execute(
                "SELECT count(*) FROM project_export_specs"
            ).fetchone()[0] == 0
            assert admin.execute(
                "SELECT input_hash FROM monitoring_metric_snapshots WHERE id = %s",
                (fixture["metric"],),
            ).fetchone()[0] == _sha256("legacy-metric")

        command.downgrade(configuration, "0019_knowledge_question_sets")
        with psycopg.connect(database_url) as admin:
            assert admin.execute(
                "SELECT to_regclass('public.project_export_specs')"
            ).fetchone()[0] is None
            assert admin.execute(
                "SELECT input_hash FROM monitoring_metric_snapshots WHERE id = %s",
                (fixture["metric"],),
            ).fetchone()[0] == _sha256("legacy-metric")
        command.upgrade(configuration, "0020_project_exports")

        with psycopg.connect(database_url) as admin:
            job_id, input_hash, manifest_hash = _insert_export(
                admin,
                project_id=fixture["project"],
                campaign_id=fixture["campaign"],
                requested_by=fixture["owner"],
                audience="customer",
            )
            admin.commit()
            assert admin.execute(
                """SELECT spec.input_hash, artifact.manifest_hash,
                          artifact.byte_count, artifact.file_count
                   FROM project_export_specs spec
                   JOIN project_export_artifacts artifact
                     ON artifact.job_id = spec.job_id
                    AND artifact.project_id = spec.project_id
                   WHERE spec.job_id = %s""",
                (job_id,),
            ).fetchone() == (input_hash, manifest_hash, 1024, 10)

            invalid_job = uuid4()
            admin.execute(
                """INSERT INTO durable_jobs
                     (id, project_id, campaign_id, kind, input_hash, idempotency_key)
                   VALUES (%s, %s, %s, 'project.export', %s, %s)""",
                (
                    invalid_job,
                    fixture["project"],
                    fixture["campaign"],
                    _sha256("expected-input"),
                    f"project-export:{invalid_job}",
                ),
            )
            admin.commit()
            with pytest.raises(
                psycopg.errors.CheckViolation,
                match="exact project.export Job scope and input hash",
            ):
                with admin.transaction():
                    admin.execute(
                        """INSERT INTO project_export_specs
                             (job_id, project_id, campaign_id, audience,
                              requested_by, input_hash)
                           VALUES (%s, %s, %s, 'admin', %s, %s)""",
                        (
                            invalid_job,
                            fixture["project"],
                            fixture["campaign"],
                            fixture["owner"],
                            _sha256("forged-input"),
                        ),
                    )
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
                with admin.transaction():
                    admin.execute(
                        "UPDATE project_export_artifacts SET byte_count = 2048 WHERE job_id = %s",
                        (job_id,),
                    )

        with pytest.raises(DBAPIError, match="project export jobs or artifacts exist"):
            command.downgrade(configuration, "0019_knowledge_question_sets")


def test_project_export_migration_rls_and_role_matrix() -> None:
    with _temporary_database() as (database_url, configuration):
        command.upgrade(configuration, "0011_runtime_health")
        with psycopg.connect(database_url) as admin:
            fixture = _seed_legacy_fixture(admin)
        command.upgrade(configuration, "0020_project_exports")

        other_project = uuid4()
        with psycopg.connect(database_url) as admin:
            admin.execute(
                "INSERT INTO projects(id, tenant_id, name) VALUES (%s, %s, 'Other export project')",
                (other_project, fixture["tenant"]),
            )
            _insert_export(
                admin,
                project_id=fixture["project"],
                requested_by=fixture["owner"],
            )
            _insert_export(
                admin,
                project_id=other_project,
                requested_by=fixture["owner"],
            )
            admin.commit()
            assert admin.execute(
                """SELECT relname, relrowsecurity, relforcerowsecurity
                   FROM pg_class
                   WHERE relname = ANY(%s)
                   ORDER BY relname""",
                (["project_export_specs", "project_export_artifacts"],),
            ).fetchall() == [
                ("project_export_artifacts", True, True),
                ("project_export_specs", True, True),
            ]
            assert admin.execute(
                """SELECT
                     has_table_privilege('geo_app', 'project_export_specs', 'INSERT'),
                     has_table_privilege('geo_app', 'project_export_artifacts', 'INSERT'),
                     has_table_privilege('geo_worker', 'project_export_specs', 'INSERT'),
                     has_table_privilege('geo_worker', 'project_export_artifacts', 'INSERT'),
                     has_table_privilege('geo_readonly', 'project_export_specs', 'SELECT')"""
            ).fetchone() == (True, False, False, True, True)

        with psycopg.connect(database_url) as scoped:
            with scoped.transaction():
                scoped.execute("SET LOCAL ROLE geo_app")
                set_project_scope(scoped, fixture["project"])
                assert scoped.execute(
                    "SELECT count(*) FROM project_export_specs"
                ).fetchone()[0] == 1
                assert scoped.execute(
                    "SELECT count(*) FROM project_export_artifacts"
                ).fetchone()[0] == 1
            with scoped.transaction():
                scoped.execute("SET LOCAL ROLE geo_app")
                set_project_scope(scoped, other_project)
                assert scoped.execute(
                    "SELECT count(*) FROM project_export_specs"
                ).fetchone()[0] == 1
            with scoped.transaction():
                scoped.execute("SET LOCAL ROLE geo_app")
                set_project_scope(scoped, uuid4())
                assert scoped.execute(
                    "SELECT count(*) FROM project_export_specs"
                ).fetchone()[0] == 0
