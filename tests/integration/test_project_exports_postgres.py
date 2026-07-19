"""F027 PostgreSQL, durable Worker, MinIO, and isolation acceptance tests."""

from __future__ import annotations

from datetime import timedelta
import io
import json
import os
import zipfile
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
import pytest

from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.monitoring.application import MonitoringApplication
from geo_core.monitoring.domain import Device, MeasurementWindow, Platform
from geo_core.monitoring.postgres import PsycopgMonitoringUnitOfWorkFactory
from geo_core.monitoring.source_contract import CaptureMethod
from geo_core.placements.worker_composition import PlacementWorkerDispatcher
from geo_core.project_exports.application import ProjectExportApplication
from geo_core.project_exports.contracts import ProjectExportScope
from geo_core.project_exports.postgres_source import PostgresProjectExportSource
from geo_core.project_exports.recalculation import recalculate_project_export
from geo_core.project_exports.repository import PostgresProjectExportRepository
from geo_core.project_exports.worker import ProjectExportHandler
from tests.integration.monitoring_postgres_support import (
    cleanup as monitoring_cleanup,
    draft,
    isolated_minio_store,
    seed,
    source,
)


APP_URL = os.getenv("GEO_ACCESS_TEST_DATABASE_URL", "").strip()
ADMIN_URL = os.getenv("GEO_ACCESS_TEST_ADMIN_DATABASE_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not APP_URL or not ADMIN_URL,
        reason=(
            "GEO_ACCESS_TEST_DATABASE_URL and " "GEO_ACCESS_TEST_ADMIN_DATABASE_URL are required"
        ),
    ),
]


def test_f027_int_01_admin_customer_durable_minio_export_and_recalculation() -> None:
    fixture = _seed_export_project("f027-int-01")
    worker_role, worker_url = _worker_login()
    try:
        app_factory = _connections(APP_URL)
        worker_factory = _connections(worker_url)
        with isolated_minio_store() as object_store:
            api_repository = PostgresProjectExportRepository(app_factory)
            application = ProjectExportApplication(
                api_repository,
                object_store,
                source=PostgresProjectExportSource(app_factory),
            )
            store = PostgresDurableJobStore(worker_factory)
            worker_repository = PostgresProjectExportRepository(worker_factory, job_store=store)
            dispatcher = PlacementWorkerDispatcher(
                store=store,
                handlers={
                    "project.export": ProjectExportHandler(
                        store=store,
                        repository=worker_repository,
                        source=PostgresProjectExportSource(worker_factory),
                        object_store=object_store,
                        lease_for=timedelta(seconds=30),
                    )
                },
                worker_id="f027-integration",
                lease_for=timedelta(seconds=30),
            )

            admin = application.request_admin(
                fixture["owner_principal"],
                project_id=fixture["project_id"],
                campaign_id=fixture["campaign_id"],
                idempotency_key="f027-admin-campaign",
            )
            admin_result = dispatcher.process(job_id=admin.job_id, project_id=fixture["project_id"])
            assert admin_result["status"] == "succeeded", _job_failure(admin.job_id)
            admin_zip = application.download(
                fixture["owner_principal"],
                project_id=fixture["project_id"],
                job_id=admin.job_id,
                audience=admin.audience,
            )
            admin_files = _unzip(admin_zip.content)
            recalculated = recalculate_project_export(admin_files)
            assert len(recalculated.metrics) == 1
            assert recalculated.metrics[0].eligible_sample_count == 3
            assert recalculated.metrics[0].recommendation_share == 1

            customer_zip = application.download_customer_latest_approved(
                fixture["customer_principal"],
                project_id=fixture["project_id"],
                campaign_id=fixture["campaign_id"],
            )
            customer_files = _unzip(customer_zip.content)
            customer_data = json.loads(customer_files["project-export.json"])
            assert customer_data["audience"] == "customer"
            assert len(customer_data["approved_reports"]) == 1
            assert {item["id"] for item in customer_data["observations"]} == {
                item["observation_id"]
                for item in customer_data["metric_snapshots"][0]["observation_memberships"]
            }
            assert "raw_result" not in customer_files["project-export.json"].decode()
            assert "captured_by" not in customer_files["project-export.json"].decode()
    finally:
        _cleanup_export_project(fixture)
        _drop_role(worker_role)


def test_f027_int_02_project_campaign_rls_and_customer_approved_only_isolation() -> None:
    left = _seed_export_project("f027-int-02-left")
    right = _seed_export_project("f027-int-02-right")
    worker_role, worker_url = _worker_login()
    try:
        source_adapter = PostgresProjectExportSource(_connections(worker_url))
        left_project = source_adapter.load_admin(ProjectExportScope(left["project_id"]))
        left_campaign = source_adapter.load_admin(
            ProjectExportScope(left["project_id"], left["campaign_id"])
        )
        customer = source_adapter.load_customer_latest_approved(
            ProjectExportScope(left["project_id"], left["campaign_id"])
        )

        assert {item.project_id for item in left_project.data.protocols} == {left["project_id"]}
        assert right["project_id"] not in {
            item.project_id for item in left_project.data.observations
        }
        assert {item.campaign_id for item in left_campaign.data.observations} == {
            left["campaign_id"]
        }
        assert left["other_campaign_id"] not in {
            item.campaign_id for item in left_campaign.data.observations
        }
        assert len(customer.data.approved_reports) == 1
        assert {item.id for item in customer.data.observations} == {
            item.observation_id for item in customer.data.metric_observation_memberships
        }

        with pytest.raises(Exception, match="campaign scope"):
            source_adapter.load_admin(ProjectExportScope(left["project_id"], right["campaign_id"]))
    finally:
        _cleanup_export_project(left)
        _cleanup_export_project(right)
        _drop_role(worker_role)


def _seed_export_project(label: str) -> dict[str, object]:
    ids = {
        name: uuid4()
        for name in (
            "tenant",
            "owner",
            "customer",
            "project",
            "foreign_project",
            "market",
            "foreign_market",
            "campaign",
            "other_campaign",
            "product",
        )
    }
    marker = f"{label}-{uuid4().hex[:8]}"
    seed(
        tenant_id=ids["tenant"],
        identity_id=ids["owner"],
        project_id=ids["project"],
        foreign_project_id=ids["foreign_project"],
        market_id=ids["market"],
        foreign_market_id=ids["foreign_market"],
        campaign_id=ids["campaign"],
        other_campaign_id=ids["other_campaign"],
        product_id=ids["product"],
        marker=marker,
    )
    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute(
            """INSERT INTO identities(id, issuer, subject)
               VALUES (%s, 'test', %s)""",
            (ids["customer"], f"customer-{marker}"),
        )
        admin.execute(
            """INSERT INTO project_memberships
                 (tenant_id, project_id, identity_id, role)
               VALUES (%s, %s, %s, 'customer')""",
            (ids["tenant"], ids["project"], ids["customer"]),
        )

    owner = _principal(ids, "owner")
    customer = _principal(ids, "customer")
    service = MonitoringApplication(PsycopgMonitoringUnitOfWorkFactory(APP_URL))
    manual = source(CaptureMethod.MANUAL_UI)
    protocol = service.create_protocol(
        owner,
        project_id=ids["project"],
        campaign_id=ids["campaign"],
        market_profile_id=ids["market"],
        name=f"Export protocol {marker}",
        platform=Platform.CHATGPT_SEARCH,
        locale="en-AU",
        device=Device.DESKTOP,
        sample_size=3,
        minimum_valid_repeats=3,
        window_days=28,
        source_strata=(manual.stratum_key(),),
    )
    suggestion = service.suggest_query(
        owner,
        project_id=ids["project"],
        campaign_id=ids["campaign"],
        protocol_id=protocol.id,
        query_text=f"best product {marker}",
        query_kind="recommendation",
        rationale="F027 exact export fixture",
        query_cluster_key="recommendation",
    )
    query = service.approve_suggestion(
        owner,
        project_id=ids["project"],
        campaign_id=ids["campaign"],
        protocol_id=protocol.id,
        suggestion_id=suggestion.id,
    )
    service.approve_protocol(
        owner,
        project_id=ids["project"],
        campaign_id=ids["campaign"],
        protocol_id=protocol.id,
    )
    frozen = service.freeze_protocol(
        owner,
        project_id=ids["project"],
        campaign_id=ids["campaign"],
        protocol_id=protocol.id,
    )
    for index in range(1, 4):
        service.import_observation(
            owner,
            project_id=ids["project"],
            campaign_id=ids["campaign"],
            protocol_id=frozen.id,
            draft=draft(
                query.monitoring_query_id,
                index,
                eligible=True,
                verified=False,
                source=manual,
            ),
            idempotency_key=f"{marker}-{index}",
        )
    metric = service.compute_metrics(
        owner,
        project_id=ids["project"],
        campaign_id=ids["campaign"],
        protocol_id=frozen.id,
        window=MeasurementWindow.T28,
        source_stratum_hash=manual.stratum_key().canonical_hash(),
        query_cluster_key="recommendation",
    )
    report = service.generate_report(
        owner,
        project_id=ids["project"],
        campaign_id=ids["campaign"],
        metric_snapshot_id=metric.id,
        title=f"Approved export {marker}",
    )
    service.approve_report(
        owner,
        project_id=ids["project"],
        campaign_id=ids["campaign"],
        report_id=report.id,
    )
    return {
        "tenant_id": ids["tenant"],
        "owner_id": ids["owner"],
        "customer_id": ids["customer"],
        "project_id": ids["project"],
        "campaign_id": ids["campaign"],
        "other_campaign_id": ids["other_campaign"],
        "owner_principal": owner,
        "customer_principal": customer,
    }


def _principal(ids: dict[str, UUID], role: str) -> AccessPrincipal:
    identity = ids["owner"] if role == "owner" else ids["customer"]
    return AccessPrincipal(
        identity,
        f"{role}-f027",
        ids["tenant"],
        (MembershipRecord(ids["project"], ids["tenant"], role),),
        "development",
    )


def _connections(database_url: str):
    def connect():
        return psycopg.connect(database_url, row_factory=dict_row)

    return connect


def _worker_login() -> tuple[str, str]:
    role = f"geo_f027_worker_{uuid4().hex[:10]}"
    password = uuid4().hex
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_worker").format(
                sql.Identifier(role), sql.Literal(password)
            )
        )
    values = conninfo_to_dict(ADMIN_URL)
    return role, make_conninfo(**{**values, "user": role, "password": password})


def _drop_role(role: str) -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))


def _cleanup_export_project(values: dict[str, object]) -> None:
    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute("SET LOCAL session_replication_role = 'replica'")
        project_id = values["project_id"]
        admin.execute(
            "DELETE FROM project_export_artifacts WHERE project_id = %s",
            (project_id,),
        )
        admin.execute(
            "DELETE FROM project_export_specs WHERE project_id = %s",
            (project_id,),
        )
        admin.execute("DELETE FROM broker_outbox WHERE project_id = %s", (project_id,))
        admin.execute("DELETE FROM durable_jobs WHERE project_id = %s", (project_id,))
        admin.execute("SET LOCAL session_replication_role = 'origin'")
    monitoring_cleanup(values["tenant_id"], values["owner_id"])
    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute("DELETE FROM identities WHERE id = %s", (values["customer_id"],))


def _unzip(content: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _job_failure(job_id: UUID) -> object:
    with psycopg.connect(ADMIN_URL) as admin:
        return admin.execute(
            "SELECT error_code, error_detail FROM durable_jobs WHERE id = %s",
            (job_id,),
        ).fetchone()
