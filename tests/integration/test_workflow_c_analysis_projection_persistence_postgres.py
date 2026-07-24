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
from geo_core.workflow_c_job_specs import PostgresWorkflowCJobSpecRepository
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
    created_database = False
    created_roles = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = database_url
        command.upgrade(migration, "head")
        command.downgrade(migration, "0069_metric_snapshot_rpc")
        command.upgrade(migration, "head")
        with psycopg.connect(database_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_worker").format(
                    sql.Identifier(worker_login), sql.Literal(worker_password)
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

        store = PostgresDurableJobStore(worker_connect)
        specs = PostgresWorkflowCJobSpecRepository(worker_connect)
        comparison = _comparison()
        comparison_job_id = _seed_analysis_job(
            database_url,
            project_id=project["project"],
            kind="workflow_c.analysis.comparison",
            payload={
                "schema_version": 1,
                "kind": "workflow_c.analysis.comparison",
                "comparison": {"inputs": [_comparison_value(comparison)]},
            },
        )
        with store.open_project(project["project"]) as worker:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                worker.execute("INSERT INTO workflow_c_comparison_families DEFAULT VALUES")
            worker.rollback()
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                worker.execute("INSERT INTO workflow_c_drift_reports DEFAULT VALUES")
            worker.rollback()

        comparison_claim = store.claim(
            job_id=comparison_job_id,
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
        drift_job_id = _seed_analysis_job(
            database_url,
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
        )
        drift_claim = store.claim(
            job_id=drift_job_id,
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

        with psycopg.connect(database_url) as admin:
            assert admin.execute(
                """SELECT status FROM durable_jobs WHERE project_id = %s AND id = %s""",
                (project["project"], comparison_job_id),
            ).fetchone() == ("succeeded",)
            assert admin.execute(
                """SELECT status FROM durable_jobs WHERE project_id = %s AND id = %s""",
                (project["project"], drift_job_id),
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


def _seed_analysis_job(
    database_url: str,
    *,
    project_id: object,
    kind: str,
    payload: dict[str, object],
) -> object:
    job_id = uuid4()
    spec_hash = _json_hash(payload)
    with psycopg.connect(database_url) as admin:
        admin.execute("SET session_replication_role = replica")
        try:
            admin.execute(
                """INSERT INTO durable_jobs(
                       id, project_id, kind, status, input_hash, idempotency_key,
                       next_run_at, max_attempts
                   ) VALUES (%s, %s, %s, 'queued', %s, %s, clock_timestamp(), 3)""",
                (job_id, project_id, kind, spec_hash, f"analysis-projection:{job_id}"),
            )
            admin.execute(
                """INSERT INTO workflow_c_job_specs(
                       project_id, job_id, kind, spec_hash, spec_payload, created_at
                   ) VALUES (%s, %s, %s, %s, %s::jsonb, clock_timestamp())""",
                (project_id, job_id, kind, spec_hash, json.dumps(payload, sort_keys=True)),
            )
        finally:
            admin.execute("SET session_replication_role = origin")
        admin.commit()
    return job_id


def _json_hash(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _database_url(base: str, database_name: str) -> str:
    parsed = urlsplit(base)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database_name}", "", ""))
