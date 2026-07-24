from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
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

from geo_core.project_scope import set_project_scope
from geo_core.synthetic_lab.domain import StyleAccessMode, StyleSource
from geo_core.synthetic_lab.ports import LabPrincipal, LabRole
from geo_core.synthetic_lab.postgres import build_synthetic_lab_persistence
from tests.integration.placement_worker_support import login_url, seed_project


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_synthetic_manual_import_preview_approval_and_cleanup_are_fenced() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_synthetic_import_{suffix}"
    admin_url = _database_url(ADMIN_URL, database_name)
    app_login, app_password = f"geo_syn_import_app_{suffix}", uuid4().hex
    worker_login, worker_password = f"geo_syn_import_worker_{suffix}", uuid4().hex
    roles: list[str] = []
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = admin_url
        alembic_command.upgrade(migration, "head")
        alembic_command.downgrade(migration, "0029_model_gateway")
        alembic_command.upgrade(migration, "head")
        with psycopg.connect(admin_url) as admin:
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
            first = seed_project(admin, suffix=f"synthetic-import-{suffix}-a")
            second = seed_project(admin, suffix=f"synthetic-import-{suffix}-b")
            now = datetime.now(UTC)
            admin.execute(
                """SELECT geo_sync_synthetic_artifact_master_key_version(
                       '1', 'encrypt_decrypt', 'AES-256-GCM', %s, %s, %s
                   )""",
                (b"n" * 12, b"c" * 32, now),
            )
        app_url = login_url(admin_url, user=app_login, password=app_password)
        worker_url = login_url(admin_url, user=worker_login, password=worker_password)
        persistence = build_synthetic_lab_persistence(app_url)
        assert persistence is not None
        source = StyleSource(
            id=uuid4(),
            project_id=first["project"],
            source_id=uuid4(),
            revision_number=1,
            channel="reddit",
            access_mode=StyleAccessMode.MANUAL_IMPORT,
            locale="en-AU",
            source_locator_hash=_hash("manual-source-label"),
        )
        persistence.resources.create_style_source(
            principal=LabPrincipal(
                project_id=first["project"],
                actor_id=first["owner"],
                roles=frozenset({LabRole.OPERATOR}),
            ),
            source=source,
            expected_version=0,
            idempotency_key="synthetic-manual-source-v1",
        )

        preview_id, upload_id = uuid4(), uuid4()
        submitted_at = now - timedelta(minutes=2)
        expires_at = submitted_at + timedelta(hours=1)
        values = _preview_values(
            first,
            source=source,
            preview_id=preview_id,
            upload_id=upload_id,
            submitted_at=submitted_at,
            expires_at=expires_at,
        )
        with psycopg.connect(app_url, row_factory=dict_row) as connection:
            set_project_scope(connection, first["project"])
            created = connection.execute(_CREATE_PREVIEW_SQL, values).fetchone()
            assert created is not None
            assert (created["version"], created["status"], created["replayed"]) == (
                1,
                "pending",
                False,
            )
            replay = connection.execute(_CREATE_PREVIEW_SQL, values).fetchone()
            assert replay is not None and replay["replayed"] is True
        changed = list(values)
        changed[-1] = _hash("changed-preview-manifest")
        with psycopg.connect(app_url) as connection:
            set_project_scope(connection, first["project"])
            with pytest.raises(psycopg.Error, match="different content"):
                connection.execute(_CREATE_PREVIEW_SQL, tuple(changed))
            connection.rollback()
            set_project_scope(connection, first["project"])
            with pytest.raises(psycopg.Error):
                connection.execute(
                    "INSERT INTO synthetic_lab_manual_import_preview_states DEFAULT VALUES"
                )

        with psycopg.connect(app_url) as connection:
            set_project_scope(connection, first["project"])
            with pytest.raises(psycopg.Error, match="maker-checker"):
                connection.execute(
                    _FINALIZE_PREVIEW_SQL,
                    (
                        first["project"],
                        preview_id,
                        1,
                        first["owner"],
                        "approved",
                        submitted_at + timedelta(minutes=1),
                        [1],
                        True,
                        True,
                        uuid4(),
                        None,
                        _hash("approve-same-actor-key"),
                        _hash("approve-same-actor-request"),
                    ),
                )

        rejected_at = submitted_at + timedelta(seconds=90)
        reject_values = (
            first["project"],
            preview_id,
            1,
            first["reviewer"],
            "rejected",
            rejected_at,
            [],
            False,
            False,
            None,
            _hash("operator-rejected-preview"),
            _hash("reject-preview-key"),
            _hash("reject-preview-request"),
        )
        with psycopg.connect(app_url, row_factory=dict_row) as connection:
            set_project_scope(connection, first["project"])
            rejected = connection.execute(_FINALIZE_PREVIEW_SQL, reject_values).fetchone()
            assert rejected is not None
            assert (rejected["status"], rejected["version"], rejected["replayed"]) == (
                "rejected",
                2,
                False,
            )
            replay = connection.execute(_FINALIZE_PREVIEW_SQL, reject_values).fetchone()
            assert replay is not None and replay["replayed"] is True
            current = connection.execute(
                """SELECT status, version FROM synthetic_lab_manual_import_preview_current
                   WHERE project_id = %s AND id = %s""",
                (first["project"], preview_id),
            ).fetchone()
            assert current == {"status": "rejected", "version": 2}

        with psycopg.connect(app_url) as connection:
            set_project_scope(connection, second["project"])
            assert connection.execute(
                "SELECT count(*) FROM synthetic_lab_manual_import_preview_current"
            ).fetchone()[0] == 0

        with psycopg.connect(worker_url, row_factory=dict_row) as worker:
            set_project_scope(worker, first["project"])
            cleanup = worker.execute(
                "SELECT * FROM geo_claim_synthetic_manual_import_cleanups(%s, 1, 60)",
                ("synthetic-import-cleaner",),
            ).fetchone()
            assert cleanup is not None
        with psycopg.connect(worker_url) as worker:
            set_project_scope(worker, first["project"])
            with pytest.raises(psycopg.Error, match="fenced"):
                worker.execute(
                    "SELECT geo_complete_synthetic_manual_import_cleanup(%s,%s,%s,%s,%s,%s,%s)",
                    (
                        first["project"],
                        cleanup["cleanup_outbox_id"],
                        cleanup["fencing_generation"] + 1,
                        cleanup["lease_token"],
                        uuid4(),
                        _hash("stale-cleanup-receipt"),
                        datetime.now(UTC),
                    ),
                )
        receipt_id = uuid4()
        deleted_at = datetime.now(UTC)
        with psycopg.connect(worker_url) as worker:
            set_project_scope(worker, first["project"])
            worker.execute(
                "SELECT geo_complete_synthetic_manual_import_cleanup(%s,%s,%s,%s,%s,%s,%s)",
                (
                    first["project"],
                    cleanup["cleanup_outbox_id"],
                    cleanup["fencing_generation"],
                    cleanup["lease_token"],
                    receipt_id,
                    _hash("cleanup-receipt"),
                    deleted_at,
                ),
            )
            assert worker.execute(
                """SELECT status FROM synthetic_lab_manual_import_cleanup_outbox
                   WHERE project_id = %s AND id = %s""",
                (first["project"], cleanup["cleanup_outbox_id"]),
            ).fetchone()[0] == "completed"
            assert worker.execute(
                """SELECT object_deleted, recoverable_body_retained
                   FROM synthetic_lab_manual_import_cleanup_receipts
                   WHERE project_id = %s AND id = %s""",
                (first["project"], receipt_id),
            ).fetchone() == (True, False)
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )
            for role in reversed(roles):
                server.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))


_CREATE_PREVIEW_SQL = """SELECT * FROM geo_create_synthetic_manual_import_preview(
    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
    %s,%s,%s,%s,%s,%s,%s,%s,%s
)"""
_FINALIZE_PREVIEW_SQL = """SELECT * FROM geo_finalize_synthetic_manual_import_preview(
    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
)"""


def _preview_values(
    ids: dict[str, UUID],
    *,
    source: StyleSource,
    preview_id: UUID,
    upload_id: UUID,
    submitted_at: datetime,
    expires_at: datetime,
) -> tuple[object, ...]:
    return (
        ids["project"],
        preview_id,
        source.id,
        source.revision_number,
        source.channel,
        source.locale,
        "review-samples.jsonl",
        "jsonl",
        "authorized_manual_capture",
        _hash("rights-evidence"),
        ids["owner"],
        submitted_at,
        expires_at,
        upload_id,
        (
            f"s3://geo-artifacts/synthetic-lab/manual-import/temporary_upload/"
            f"{ids['project']}/{upload_id}/{_hash('encrypted-upload')}.bin"
        ),
        _hash("encrypted-upload"),
        _hash("plaintext-upload"),
        "1",
        "AES-256-GCM/HKDF-project-artifact/v1",
        "application/vnd.geo.synthetic-manual-import+encrypted",
        512,
        "synthetic-manual-import-preview.v1",
        "synthetic-manual-import-parser.v1",
        "synthetic-manual-import-scanner.v1",
        "synthetic-manual-import-anonymizer.v1",
        2,
        1,
        1,
        _hash("preview-manifest"),
    )


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _database_url(database_url: str, database_name: str) -> str:
    parsed = urlsplit(database_url)
    return urlunsplit(parsed._replace(path=f"/{database_name}"))
