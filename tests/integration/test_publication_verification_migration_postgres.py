from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import os
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from alembic import command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb
import pytest
from sqlalchemy.engine import URL

from geo_core.project_scope import set_project_scope
from tests.integration.runtime_database_support import runtime_role_url
from tests.integration.placement_worker_support import seed_project
from tests.integration.test_placement_operations_postgres import _seed_publication_lineage


ROOT = Path(__file__).resolve().parents[2]
ADMIN_URL = os.getenv("GEO_ACCESS_TEST_ADMIN_DATABASE_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not ADMIN_URL,
        reason="GEO_ACCESS_TEST_ADMIN_DATABASE_URL is required",
    ),
]


@contextmanager
def _temporary_database() -> Iterator[tuple[str, Config]]:
    database_name = f"geo_verification_{uuid4().hex[:12]}"
    admin_parameters = conninfo_to_dict(ADMIN_URL)
    maintenance_url = make_conninfo(**{**admin_parameters, "dbname": "postgres"})
    database_url = make_conninfo(**{**admin_parameters, "dbname": database_name})
    sqlalchemy_url = URL.create(
        "postgresql+psycopg",
        username=admin_parameters.get("user"),
        password=admin_parameters.get("password"),
        host=admin_parameters.get("host"),
        port=int(admin_parameters["port"]) if admin_parameters.get("port") else None,
        database=database_name,
    ).render_as_string(hide_password=False)
    with psycopg.connect(maintenance_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    configuration = Config(ROOT / "alembic.ini")
    configuration.attributes["geo_database_url_override"] = sqlalchemy_url
    try:
        yield database_url, configuration
    finally:
        with psycopg.connect(maintenance_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )


def test_verification_attempt_migration_round_trip_rls_and_append_only_contract() -> None:
    with _temporary_database() as (database_url, configuration):
        command.upgrade(configuration, "0015_observation_statistics_v2")
        ids = {
            name: uuid4()
            for name in (
                "destination",
                "campaign",
                "opportunity",
                "package",
                "bundle",
                "version",
                "publication",
                "query",
                "job",
                "task",
            )
        }
        submission_id = uuid4()
        with psycopg.connect(database_url) as admin:
            seeded = seed_project(admin, suffix=f"verification-{uuid4().hex[:10]}")
            _seed_publication_lineage(admin, seeded, ids)
            admin.execute(
                """INSERT INTO publication_submissions
                     (id, project_id, publication_request_id, submitted_url, status,
                      submitted_at, verification_result, idempotency_key, payload_hash,
                      submitted_by, campaign_id, opportunity_id, destination_id)
                   VALUES (%s, %s, %s, 'https://reddit.com/verification-fixture',
                           'submitted', clock_timestamp(), '{"legacy":true}'::jsonb,
                           %s, %s, %s, %s, %s, %s)""",
                (
                    submission_id,
                    seeded["project"],
                    ids["publication"],
                    f"verification-submission-{submission_id}",
                    "a" * 64,
                    seeded["owner"],
                    ids["campaign"],
                    ids["opportunity"],
                    ids["destination"],
                ),
            )
            admin.execute(
                """INSERT INTO durable_jobs
                     (id, project_id, campaign_id, kind, input_hash, idempotency_key,
                      attempt_count)
                   VALUES (%s, %s, %s, 'publication.verify', %s, %s, 1)""",
                (
                    ids["job"],
                    seeded["project"],
                    ids["campaign"],
                    "b" * 64,
                    f"verification-job-{ids['job']}",
                ),
            )
            admin.execute(
                """INSERT INTO verification_job_specs
                     (job_id, project_id, campaign_id, opportunity_id, submission_id)
                   VALUES (%s, %s, %s, %s, %s)""",
                (
                    ids["job"],
                    seeded["project"],
                    ids["campaign"],
                    ids["opportunity"],
                    submission_id,
                ),
            )
            admin.commit()

        command.upgrade(configuration, "0016_publication_verification")
        with psycopg.connect(database_url) as admin:
            assert admin.execute(
                "SELECT count(*) FROM publication_verification_attempts"
            ).fetchone()[0] == 0
            assert admin.execute(
                "SELECT verification_result FROM publication_submissions WHERE id = %s",
                (submission_id,),
            ).fetchone()[0] == {"legacy": True}

        command.downgrade(configuration, "0015_observation_statistics_v2")
        with psycopg.connect(database_url) as admin:
            assert admin.execute(
                "SELECT to_regclass('public.publication_verification_attempts')"
            ).fetchone()[0] is None
            assert admin.execute(
                "SELECT verification_result FROM publication_submissions WHERE id = %s",
                (submission_id,),
            ).fetchone()[0] == {"legacy": True}
        command.upgrade(configuration, "0016_publication_verification")

        worker_url = runtime_role_url(database_url, user="geo_worker_dev")
        app_url = runtime_role_url(database_url, user="geo_app_dev")
        check_names = (
            "input_contract",
            "public_url",
            "redirect_policy",
            "http_2xx",
            "html_response",
            "approved_content",
            "required_disclosures",
            "expected_links",
        )
        checks = [
            {"name": name, "passed": True, "failure_code": None}
            for name in check_names
        ]
        insert_sql = """INSERT INTO publication_verification_attempts
             (project_id, campaign_id, opportunity_id, submission_id, job_id,
              attempt_number, verifier_version, outcome, checked_at, status_code,
              final_url, metadata_hash, body_hash, visible_text_hash,
              content_rule_hash, verification_rule_hash, redirect_count,
              checks, failures, error_code, failure_disposition, result_hash)
           VALUES
             (%(project_id)s, %(campaign_id)s, %(opportunity_id)s,
              %(submission_id)s, %(job_id)s, %(attempt_number)s,
              'publication-url-verifier-v2', 'passed', %(checked_at)s, 200,
              'https://reddit.com/verification-fixture', %(metadata_hash)s,
              %(body_hash)s, %(visible_text_hash)s, %(content_rule_hash)s,
              %(verification_rule_hash)s, 0, %(checks)s, '[]'::jsonb,
              NULL, NULL, %(result_hash)s)
           RETURNING id"""
        parameters = {
            "project_id": seeded["project"],
            "campaign_id": ids["campaign"],
            "opportunity_id": ids["opportunity"],
            "submission_id": submission_id,
            "job_id": ids["job"],
            "attempt_number": 1,
            "checked_at": datetime.now(UTC),
            "metadata_hash": "c" * 64,
            "body_hash": "d" * 64,
            "visible_text_hash": "e" * 64,
            "content_rule_hash": "f" * 64,
            "verification_rule_hash": "1" * 64,
            "checks": Jsonb(checks),
            "result_hash": "2" * 64,
        }
        with psycopg.connect(worker_url) as worker:
            set_project_scope(worker, seeded["project"])
            with pytest.raises(psycopg.errors.CheckViolation):
                with worker.transaction():
                    worker.execute(
                        insert_sql,
                        {**parameters, "checks": Jsonb(checks[:-1])},
                    )
            with pytest.raises(psycopg.errors.CheckViolation):
                with worker.transaction():
                    worker.execute(insert_sql, {**parameters, "attempt_number": 2})
            attempt_id = worker.execute(insert_sql, parameters).fetchone()[0]
            worker.commit()
            set_project_scope(worker, seeded["project"])
            assert worker.execute(
                "SELECT outcome, result_hash FROM publication_verification_attempts WHERE id = %s",
                (attempt_id,),
            ).fetchone() == ("passed", "2" * 64)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                worker.execute(
                    "UPDATE publication_verification_attempts SET redirect_count = 1 WHERE id = %s",
                    (attempt_id,),
                )
            worker.rollback()
            set_project_scope(worker, seeded["project"])
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                worker.execute(
                    "DELETE FROM publication_verification_attempts WHERE id = %s",
                    (attempt_id,),
                )
            worker.rollback()

        with psycopg.connect(app_url) as app:
            set_project_scope(app, seeded["project"])
            assert app.execute(
                "SELECT count(*) FROM publication_verification_attempts"
            ).fetchone()[0] == 1
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                app.execute("INSERT INTO publication_verification_attempts DEFAULT VALUES")
            app.rollback()
            set_project_scope(app, uuid4())
            assert app.execute(
                "SELECT count(*) FROM publication_verification_attempts"
            ).fetchone()[0] == 0

        with psycopg.connect(database_url) as admin:
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
                admin.execute(
                    "UPDATE publication_verification_attempts SET redirect_count = 1 WHERE id = %s",
                    (attempt_id,),
                )
            admin.rollback()
            grants = {
                (row[0], row[1])
                for row in admin.execute(
                    """SELECT grantee, privilege_type
                       FROM information_schema.role_table_grants
                       WHERE table_name = 'publication_verification_attempts'
                         AND grantee IN ('geo_app','geo_worker','geo_readonly')"""
                )
            }
            assert grants == {
                ("geo_app", "SELECT"),
                ("geo_worker", "INSERT"),
                ("geo_worker", "SELECT"),
                ("geo_readonly", "SELECT"),
            }

        with pytest.raises(Exception, match="publication verification attempts exist"):
            command.downgrade(configuration, "0015_observation_statistics_v2")
        with psycopg.connect(database_url) as admin:
            assert admin.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()[0] == "0016_publication_verification"
            assert admin.execute(
                "SELECT count(*) FROM publication_verification_attempts WHERE id = %s",
                (attempt_id,),
            ).fetchone()[0] == 1
