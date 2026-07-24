from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import os
from pathlib import Path
from typing import Any, Literal
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
from geo_core.workflow_c_reports import (
    AdvanceWorkflowCReportSnapshot,
    CreateWorkflowCReportSnapshot,
    PostgresWorkflowCApprovedReportSnapshots,
    WorkflowCReportApprovalError,
)
from tests.integration.placement_worker_support import login_url, seed_project


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()
METHODOLOGY = (
    "Observational monitoring only; results are non-causal and do not prove that a "
    "placement caused any change."
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_workflow_c_customer_projection_is_approved_only_and_source_rechecked() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_workflow_c_reports_{suffix}"
    target_url = _database_url(ADMIN_URL, database_name)
    app_login, password = f"geo_workflow_c_reports_{suffix}", uuid4().hex
    created_database = False
    created_role = False
    first: dict[str, UUID] | None = None
    second: dict[str, UUID] | None = None
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = target_url
        command.upgrade(migration, "head")
        now = datetime.now(UTC).replace(microsecond=0)
        with psycopg.connect(target_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                    sql.Identifier(app_login), sql.Literal(password)
                )
            )
            created_role = True
            first = seed_project(admin, suffix=f"workflow-c-report-{suffix}-a")
            second = seed_project(admin, suffix=f"workflow-c-report-{suffix}-b")
            source = _seed_report_source(admin, seeded=first, now=now, marker="first")

        app_url = login_url(target_url, user=app_login, password=password)
        repository = PostgresWorkflowCApprovedReportSnapshots(
            lambda: psycopg.connect(app_url, row_factory=dict_row)
        )
        draft = repository.create_draft(_draft(first, source, now=now))
        review = repository.advance(_advance(draft, status="in_review", now=now))
        approved = repository.advance(_advance(review, status="approved", now=now))
        assert approved.status == "approved"
        assert _approved(repository, first, source) == (draft.report_id,)

        with psycopg.connect(target_url) as admin:
            admin.execute(
                """UPDATE workflow_c_semantic_metric_snapshots
                   SET evidence_status = 'insufficient_evidence'
                   WHERE project_id = %s AND snapshot_hash = %s""",
                (first["project"], source["semantic_snapshot_hash"]),
            )
        assert _approved(repository, first, source) == ()

        with psycopg.connect(target_url) as admin:
            admin.execute(
                """UPDATE workflow_c_semantic_metric_snapshots
                   SET evidence_status = 'complete'
                   WHERE project_id = %s AND snapshot_hash = %s""",
                (first["project"], source["semantic_snapshot_hash"]),
            )
        assert _approved(repository, first, source) == (draft.report_id,)

        stale = repository.advance(
            _advance(approved, status="stale", now=now, reason="semantic_source_changed")
        )
        assert stale.status == "stale"
        assert _approved(repository, first, source) == ()

        pending = repository.create_draft(_draft(first, source, now=now))
        in_review = repository.advance(_advance(pending, status="in_review", now=now))
        with psycopg.connect(target_url) as admin:
            admin.execute(
                """UPDATE workflow_c_semantic_metric_snapshots
                   SET evidence_status = 'insufficient_evidence'
                   WHERE project_id = %s AND snapshot_hash = %s""",
                (first["project"], source["semantic_snapshot_hash"]),
            )
        with pytest.raises(WorkflowCReportApprovalError, match="insufficient-evidence"):
            repository.advance(_advance(in_review, status="approved", now=now))
        with psycopg.connect(app_url) as app:
            set_project_scope(app, first["project"])
            with pytest.raises(psycopg.errors.CheckViolation, match="Customer eligible"):
                app.execute(
                    """INSERT INTO workflow_c_report_snapshot_versions(
                           project_id, report_id, version, status, campaign_id,
                           monitoring_report_id, monitoring_report_hash, semantic_snapshot_hash,
                           source_kind, approved_safe_payload, approved_safe_payload_hash,
                           version_hash, actor_id, reason, occurred_at
                       )
                       SELECT project_id, report_id, 3, 'approved', campaign_id,
                              monitoring_report_id, monitoring_report_hash, semantic_snapshot_hash,
                              source_kind, approved_safe_payload, approved_safe_payload_hash,
                              %s, actor_id, NULL, %s
                         FROM workflow_c_report_snapshot_versions
                        WHERE project_id = %s AND report_id = %s AND version = 2""",
                    (
                        _hash("attempted-direct-approved-version"),
                        now,
                        first["project"],
                        pending.report_id,
                    ),
                )
            app.rollback()

        with psycopg.connect(app_url) as app:
            set_project_scope(app, second["project"])
            assert app.execute(
                """SELECT count(*) FROM workflow_c_report_snapshot_versions
                   WHERE report_id = %s""",
                (draft.report_id,),
            ).fetchone()[0] == 0
            app.rollback()
            set_project_scope(app, first["project"])
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                app.execute(
                    """UPDATE workflow_c_report_snapshot_versions
                       SET status = 'approved'
                       WHERE project_id = %s AND report_id = %s""",
                    (first["project"], draft.report_id),
                )
            app.rollback()
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
                server.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(app_login)))


def _approved(
    repository: PostgresWorkflowCApprovedReportSnapshots,
    seeded: dict[str, UUID],
    source: dict[str, UUID | str],
) -> tuple[UUID, ...]:
    return tuple(
        report.id
        for report in repository.list_approved_reports(
            project_id=seeded["project"], campaign_id=_uuid(source, "campaign")
        )
    )


def _draft(
    seeded: dict[str, UUID], source: dict[str, UUID | str], *, now: datetime
) -> CreateWorkflowCReportSnapshot:
    return CreateWorkflowCReportSnapshot(
        report_id=uuid4(),
        project_id=seeded["project"],
        campaign_id=_uuid(source, "campaign"),
        monitoring_report_id=_uuid(source, "monitoring_report"),
        monitoring_report_hash=_text(source, "monitoring_report_hash"),
        semantic_snapshot_hash=_text(source, "semantic_snapshot_hash"),
        source_kind="provider_api",
        approved_safe_payload={
            "headline": "Approved Australian evidence",
            "mention_rate": "0.8",
        },
        actor_id=seeded["owner"],
        occurred_at=now,
    )


def _advance(
    version: Any,
    *,
    status: Literal["in_review", "approved", "stale", "superseded", "revoked"],
    now: datetime,
    reason: str | None = None,
) -> AdvanceWorkflowCReportSnapshot:
    return AdvanceWorkflowCReportSnapshot(
        report_id=version.report_id,
        project_id=version.project_id,
        expected_version=version.version,
        status=status,
        actor_id=version.actor_id,
        occurred_at=now,
        reason=reason,
    )


def _seed_report_source(
    connection: Any,
    *,
    seeded: dict[str, UUID],
    now: datetime,
    marker: str,
) -> dict[str, UUID | str]:
    project_id = seeded["project"]
    campaign_id = uuid4()
    policy_id, suite_id, run_id = uuid4(), uuid4(), uuid4()
    semantic_snapshot_hash = _hash(f"semantic:{marker}")
    protocol_id, metric_snapshot_id, monitoring_report_id = uuid4(), uuid4(), uuid4()
    policy_hash = _hash(f"policy:{marker}")
    suite_hash = _hash(f"suite:{marker}")
    report_hash = _hash(f"report:{marker}")
    stratum_hash = _hash(f"stratum:{marker}")
    protocol_stratum = {
        "capture_method": "provider_api",
        "platform": "openai",
        "platform_detail": None,
        "surface": "openai_api",
        "surface_kind": "provider_api",
        "surface_detail": None,
        "engine": "chatgpt",
        "configured_model": {"state": "disclosed", "value": "workflow-c-test"},
        "reported_model": {"state": "not_disclosed", "value": None},
        "locale": "en-AU",
        "region": "AU",
        "language": "en",
        "device": "desktop",
        "client_kind": "api",
        "search_enabled": True,
        "search_mode": "live_web",
    }
    # This fixture constructs an immutable historical source, not a new live
    # Sampling workflow.  Keep the bypass local to its transaction so current
    # admission and aggregate triggers remain covered by their dedicated tests.
    connection.execute("SET LOCAL session_replication_role = replica")
    connection.execute(
        """INSERT INTO geo_campaigns(
               id, project_id, market_profile_id, primary_product_entity_id, name, status, created_by
           ) VALUES (%s, %s, %s, %s, %s, 'active', %s)""",
        (
            campaign_id,
            project_id,
            seeded["market"],
            seeded["entity"],
            f"Workflow C report {marker}",
            seeded["owner"],
        ),
    )
    connection.execute(
        """INSERT INTO workflow_c_sampling_admission_policies(
               id, project_id, revision, status, effective_authorization_state,
               platform, capture_method, adapter_release, location_control,
               location_evidence_hash, authorization_reference, created_by,
               authorized_purposes,
               definition_hash, policy_version, valid_until, quota_remaining,
               daily_task_limit, minimum_request_interval_seconds, max_concurrency,
               aggregate_version, payload, created_at, updated_at
           ) VALUES (%s, %s, 1, 'draft', 'not_assessed',
                     'openai', 'provider_api', 'fixture-v1', 'country', %s,
                     'fixture:historical-report-source', %s, %s::jsonb,
                     %s, 'test-v1', %s, 1, 1, 0, 1, 1, '{}'::jsonb, %s, %s)""",
        (
            policy_id,
            project_id,
            _hash(f"location:{marker}"),
            str(seeded["owner"]),
            Jsonb(["geo_measurement"]),
            policy_hash,
            now + timedelta(days=1),
            now,
            now,
        ),
    )
    connection.execute(
        """INSERT INTO workflow_c_sampling_suites(
               id, project_id, suite_hash, admission_policy_id, admission_policy_hash,
               source_stratum_hash, capture_method, planned_task_count,
               minimum_valid_repeats, payload, frozen_at
           ) VALUES (%s, %s, %s, %s, %s, %s, 'provider_api', 1, 3, '{}'::jsonb, %s)""",
        (suite_id, project_id, suite_hash, policy_id, policy_hash, stratum_hash, now),
    )
    connection.execute(
        """INSERT INTO workflow_c_sampling_runs(
               id, project_id, suite_id, suite_hash, admission_policy_id,
               admission_policy_hash, admission_grant_hash, purpose, status,
               reserved_task_count, admitted_not_before, authorization_valid_until,
               version, payload, created_at
           ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'geo_measurement', 'completed',
                     0, %s, %s, 1, '{}'::jsonb, %s)""",
        (
            run_id,
            project_id,
            suite_id,
            suite_hash,
            policy_id,
            policy_hash,
            _hash(f"grant:{marker}"),
            now - timedelta(minutes=1),
            now + timedelta(days=1),
            now,
        ),
    )
    connection.execute(
        """INSERT INTO workflow_c_semantic_metric_snapshots(
               snapshot_hash, project_id, run_id, input_set_hash, metric_suite_hash,
               source_stratum_hash, capture_method, evidence_status, warning_ratio,
               test_only, synthetic, payload, computed_at, approved_at
           ) VALUES (%s, %s, %s, %s, %s, %s, 'provider_api', 'complete', 0,
                     false, false, '{}'::jsonb, %s, %s)""",
        (
            semantic_snapshot_hash,
            project_id,
            run_id,
            _hash(f"input:{marker}"),
            _hash(f"metric-suite:{marker}"),
            stratum_hash,
            now - timedelta(minutes=1),
            now,
        ),
    )
    connection.execute(
        """INSERT INTO monitoring_protocols(
               id, project_id, campaign_id, market_profile_id, name, platform,
               locale, device, sample_size, window_days, status, created_by,
               source_strata_snapshot, source_strata_hash,
               minimum_valid_repeats, statistics_method_version
           ) VALUES (%s, %s, %s, %s, %s, 'chatgpt_search', 'en-AU', 'desktop',
                     3, 1, 'draft', %s, %s,
                     geo_source_strata_v3_inventory_hash(%s), 3,
                     'geo-observation-statistics-v2')""",
        (
            protocol_id,
            project_id,
            campaign_id,
            seeded["market"],
            f"Protocol {marker}",
            seeded["owner"],
            Jsonb([protocol_stratum]),
            Jsonb([protocol_stratum]),
        ),
    )
    # The report snapshot references a legacy Monitoring Report only for immutable
    # report-hash lineage. Its Customer eligibility is decided by the separately
    # governed Workflow C semantic snapshot below, so do not fabricate a v2 metric
    # membership manifest just to construct this historical source row.
    connection.execute(
        """INSERT INTO monitoring_metric_snapshots(
               id, project_id, protocol_id, campaign_id, measurement_window,
               expected_sample_count, eligible_sample_count, recommendation_share,
               product_mention_share, placement_citation_share,
               qualified_destination_coverage, verified_placement_coverage,
               competitive_delta, status, confounded_reasons, input_hash,
               statistics_contract_version,
               method_version, computed_by, computed_at
           ) VALUES (%s, %s, %s, %s, 'ad_hoc', 1, 1, 0.8, 0.8, 0, 0, 0, 0,
                     'complete', ARRAY[]::text[], %s, 'legacy-v1',
                     'workflow-c-test-v1', %s, %s)""",
        (
            metric_snapshot_id,
            project_id,
            protocol_id,
            campaign_id,
            _hash(f"metric:{marker}"),
            seeded["owner"],
            now,
        ),
    )
    connection.execute(
        """INSERT INTO monitoring_reports(
               id, project_id, protocol_id, campaign_id, metric_snapshot_id,
               title, body, methodology_statement, report_hash, status,
               generated_by, generated_at
           ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'draft', %s, %s)""",
        (
            monitoring_report_id,
            project_id,
            protocol_id,
            campaign_id,
            metric_snapshot_id,
            f"Workflow C report {marker}",
            "Approved workflow C evidence.",
            METHODOLOGY,
            report_hash,
            seeded["owner"],
            now,
        ),
    )
    return {
        "campaign": campaign_id,
        "monitoring_report": monitoring_report_id,
        "monitoring_report_hash": report_hash,
        "semantic_snapshot_hash": semantic_snapshot_hash,
    }


def _uuid(values: dict[str, UUID | str], key: str) -> UUID:
    value = values[key]
    assert isinstance(value, UUID)
    return value


def _text(values: dict[str, UUID | str], key: str) -> str:
    value = values[key]
    assert isinstance(value, str)
    return value


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _database_url(base: str, database_name: str) -> str:
    parsed = urlsplit(base)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database_name}", "", ""))
