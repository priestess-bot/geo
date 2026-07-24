from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from alembic import command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest

from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.project_scope import set_project_scope
from geo_core.statistical_methods import (
    ComparisonInput,
    DriftObservation,
    FrozenComparisonProtocol,
    PairedObservation,
    StatisticalStratum,
)
from geo_core.workflow_c_analysis_worker import (
    PostgresWorkflowCComparisonOperation,
    PostgresWorkflowCDriftOperation,
)
from geo_core.workflow_c_analysis_reads import PostgresWorkflowCAnalysisReadRepository
from geo_core.workflow_c_job_specs import (
    PostgresWorkflowCJobSpecRepository,
    PostgresWorkflowCJobSpecWriter,
)
from geo_api.workflow_c_analysis_postgres_runtime import PostgresWorkflowCAnalysisRuntime
from geo_api.workflow_c_presenters import comparison_family_response, drift_report_response
from tests.integration.placement_worker_support import login_url, seed_project


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_restricted_worker_persists_comparison_and_drift_only_through_fenced_rpcs() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_analysis_persist_{suffix}"
    database_url = _database_url(ADMIN_URL, database_name)
    worker_login = f"geo_analysis_worker_{suffix}"
    worker_password = uuid4().hex
    app_login = f"geo_analysis_app_{suffix}"
    app_password = uuid4().hex
    created_database = False
    created_roles = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = database_url
        command.upgrade(migration, "head")
        command.downgrade(migration, "0070_analysis_projection_rpc")
        command.upgrade(migration, "head")
        with psycopg.connect(database_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_worker").format(
                    sql.Identifier(worker_login), sql.Literal(worker_password)
                )
            )
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                    sql.Identifier(app_login), sql.Literal(app_password)
                )
            )
            created_roles = True
            project = seed_project(admin, suffix=f"analysis-persist-{suffix}")
            admin.commit()

        def worker_connect():
            return psycopg.connect(
                login_url(database_url, user=worker_login, password=worker_password),
                row_factory=dict_row,
            )

        def app_connect():
            return psycopg.connect(
                login_url(database_url, user=app_login, password=app_password),
                row_factory=dict_row,
            )

        store = PostgresDurableJobStore(worker_connect)
        specs = PostgresWorkflowCJobSpecRepository(worker_connect)
        writer = PostgresWorkflowCJobSpecWriter(app_connect)
        comparison = _comparison()
        malformed = {
            "schema_version": 1,
            "kind": "workflow_c.analysis.comparison",
            "comparison": {"inputs": []},
        }
        with app_connect() as app:
            set_project_scope(app, project["project"])
            with pytest.raises(
                psycopg.errors.InvalidParameterValue, match="enqueue input is invalid"
            ):
                app.execute(
                    """SELECT * FROM geo_enqueue_workflow_c_job_spec(
                           %s, %s, %s, %s::jsonb, %s, %s
                       )""",
                    (
                        project["project"],
                        "workflow_c.analysis.comparison",
                        _json_hash(malformed),
                        json.dumps(malformed, separators=(",", ":"), sort_keys=True),
                        "analysis-projection:malformed",
                        3,
                    ),
                )
            app.rollback()
        comparison_job = writer.enqueue(
            project_id=project["project"],
            kind="workflow_c.analysis.comparison",
            payload={
                "schema_version": 1,
                "kind": "workflow_c.analysis.comparison",
                "comparison": {"inputs": [_comparison_value(comparison)]},
            },
            idempotency_key="analysis-projection:comparison",
        )
        with store.open_project(project["project"]) as worker:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                worker.execute("INSERT INTO workflow_c_comparison_families DEFAULT VALUES")
            worker.rollback()
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                worker.execute("INSERT INTO workflow_c_drift_reports DEFAULT VALUES")
            worker.rollback()

        comparison_claim = store.claim(
            job_id=comparison_job.job_id,
            project_id=project["project"],
            expected_kind="workflow_c.analysis.comparison",
            worker_id="analysis-projection-persistence",
            lease_for=timedelta(seconds=60),
        )
        assert comparison_claim.lease is not None
        comparison_result = PostgresWorkflowCComparisonOperation(
            store=store,
            specs=specs,
            lease_for=timedelta(seconds=60),
        ).execute(comparison_claim.lease)
        assert comparison_result["status"] == "complete"

        stratum = comparison.protocol.stratum
        drift_job = writer.enqueue(
            project_id=project["project"],
            kind="workflow_c.analysis.drift",
            payload={
                "schema_version": 1,
                "kind": "workflow_c.analysis.drift",
                "drift": {
                    "source_snapshot_hash": "1" * 64,
                    "target_snapshot_hash": "2" * 64,
                    "baseline": [
                        _drift_value(DriftObservation("baseline-1", stratum, Decimal("0")))
                    ],
                    "current": [
                        _drift_value(DriftObservation("current-1", stratum, Decimal("0.2")))
                    ],
                },
            },
            idempotency_key="analysis-projection:drift",
        )
        drift_claim = store.claim(
            job_id=drift_job.job_id,
            project_id=project["project"],
            expected_kind="workflow_c.analysis.drift",
            worker_id="analysis-projection-persistence",
            lease_for=timedelta(seconds=60),
        )
        assert drift_claim.lease is not None
        drift_result = PostgresWorkflowCDriftOperation(
            store=store,
            specs=specs,
            lease_for=timedelta(seconds=60),
        ).execute(drift_claim.lease)
        assert drift_result["status"] == "complete"

        durable_analysis = PostgresWorkflowCAnalysisRuntime(
            reads=PostgresWorkflowCAnalysisReadRepository(connect=app_connect)
        )
        comparison_projection = durable_analysis.get_comparison_family(
            project_id=project["project"], family_hash=comparison_result["family_hash"]
        )
        comparison_response = comparison_family_response(project["project"], comparison_projection)
        assert comparison_response.family_hash == comparison_result["family_hash"]
        assert comparison_response.results[0].result_hash
        drift_projection = durable_analysis.get_drift_report(
            project_id=project["project"], report_hash=drift_result["report_hash"]
        )
        drift_response = drift_report_response(project["project"], drift_projection)
        assert drift_response.report_hash == drift_result["report_hash"]
        assert durable_analysis.list_comparison_families(project_id=uuid4()) == ()
        assert durable_analysis.list_drift_reports(project_id=uuid4()) == ()

        with psycopg.connect(database_url) as admin:
            assert admin.execute(
                """SELECT status FROM durable_jobs WHERE project_id = %s AND id = %s""",
                (project["project"], comparison_job.job_id),
            ).fetchone() == ("succeeded",)
            assert admin.execute(
                """SELECT status FROM durable_jobs WHERE project_id = %s AND id = %s""",
                (project["project"], drift_job.job_id),
            ).fetchone() == ("succeeded",)
            assert admin.execute(
                """SELECT count(*) FROM workflow_c_comparison_results
                     WHERE project_id = %s AND family_hash = %s""",
                (project["project"], comparison_result["family_hash"]),
            ).fetchone() == (1,)
            assert admin.execute(
                """SELECT count(*) FROM workflow_c_drift_reports
                     WHERE project_id = %s AND report_hash = %s""",
                (project["project"], drift_result["report_hash"]),
            ).fetchone() == (1,)
    finally:
        if created_database:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )
        if created_roles:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(worker_login))
                )
                server.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(app_login)))


def _comparison() -> ComparisonInput:
    stratum = StatisticalStratum(
        provider="openai",
        reported_model="model-v1",
        capture_method="provider_api",
        locale="en-AU",
        region="AU",
        source_composition_hash="c" * 64,
        sampling_source_stratum_hash="d" * 64,
        question_cluster="purchase",
    )
    protocol = FrozenComparisonProtocol(
        protocol_hash="a" * 64,
        question_set_hash="b" * 64,
        baseline_version="baseline-v1",
        candidate_version="candidate-v2",
        metric_key="recommendation",
        metric_method_version="metric-v1",
        comparison_id="comparison-one",
        family="primary-family",
        stratum=stratum,
        alpha=Decimal("0.05"),
        delta=Decimal("0.05"),
        target_power=Decimal("0.80"),
        precision=Decimal("0.10"),
        min_pairs=3,
        power_plan_hash="e" * 64,
        a_priori_design_power=Decimal("0.90"),
        power_method_version="a-priori-design-power-v1",
        minimum_completion_ratio=Decimal("0.80"),
        bootstrap_iterations=100,
        bootstrap_method="paired-bootstrap-percentile-v1",
        correction_method="holm-v1",
        simultaneous_interval_method="paired-bootstrap-percentile-bonferroni-family-v1",
    )
    return ComparisonInput(
        protocol=protocol,
        sampling_source_stratum_hash=stratum.sampling_source_stratum_hash,
        planned_pair_count=3,
        pairs=tuple(
            PairedObservation(
                pair_id=f"pair-{index}",
                question_id=f"question-{index}",
                question_cluster=stratum.question_cluster,
                stratum_hash=stratum.stratum_hash,
                sampling_source_stratum_hash=stratum.sampling_source_stratum_hash,
                capture_method=stratum.capture_method,
                baseline=Decimal("0"),
                candidate=Decimal("0.1"),
            )
            for index in range(1, 4)
        ),
    )


def _comparison_value(value: ComparisonInput) -> dict[str, object]:
    protocol = dict(value.protocol.canonical_value())
    protocol.pop("seed_hex")
    return {
        "protocol": protocol,
        "sampling_source_stratum_hash": value.sampling_source_stratum_hash,
        "planned_pair_count": value.planned_pair_count,
        "pairs": [item.canonical_value() for item in value.pairs],
    }


def _drift_value(value: DriftObservation) -> dict[str, object]:
    return {
        "observation_id": value.observation_id,
        "stratum": value.stratum.canonical_value(),
        "effect": str(value.effect),
    }


def _json_hash(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _database_url(base: str, database_name: str) -> str:
    parsed = urlsplit(base)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database_name}", "", ""))
