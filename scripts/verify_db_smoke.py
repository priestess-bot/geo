from __future__ import annotations

import json
import os
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row


EXPECTED_TABLES = (
    "market_profiles",
    "industry_profiles",
    "tenants",
    "projects",
    "project_members",
    "project_member_invitations",
    "prompt_questions",
    "geo_samples",
    "answer_runs",
    "raw_answers",
    "answer_citations",
    "evidence_assets",
    "collector_logs",
    "answer_analyses",
    "llm_call_logs",
    "source_graphs",
    "source_gaps",
    "competitor_benchmarks",
    "action_recommendations",
    "retest_schedules",
    "retest_comparisons",
    "api_browser_fidelity_checks",
    "localized_knowledge_facts",
    "knowledge_fact_embeddings",
    "content_drafts",
    "integration_connectors",
    "manual_distribution_records",
    "evidence_links",
    "runtime_saved_views",
    "project_brand_kits",
    "project_brand_assets",
    "score_weight_configs",
    "human_review_records",
    "runtime_alert_events",
    "traceability_bundles",
    "visibility_score_snapshots",
    "collection_costs",
    "collection_run_summaries",
    "audit_events",
    "report_exports",
    "report_export_jobs",
    "runtime_notifications",
    "runtime_notification_subscriptions",
    "runtime_notification_deliveries",
    "score_contributions",
    "source_graph_evidence",
    "score_snapshot_runs",
    "report_evidence",
    "brand_entities",
    "competitor_entities",
    "entity_aliases",
    "entity_alias_candidate_reviews",
)

CRITICAL_COLUMNS = {
    "report_exports": ("method_disclosure", "markdown_url", "pdf_url", "csv_url"),
    "collection_run_summaries": (
        "total_duration_ms",
        "average_duration_ms",
        "collector_backend_ids",
    ),
    "collection_costs": ("duration_ms",),
    "visibility_score_snapshots": ("component_weights_snapshot",),
    "knowledge_fact_embeddings": ("embedding", "content_hash"),
    "api_browser_fidelity_checks": ("payload_hash", "answer_run_ids"),
    "score_weight_configs": ("weights", "updated_by"),
    "human_review_records": ("target_type", "review_status", "decision"),
    "runtime_alert_events": ("alert_id", "alert_type", "source", "source_id", "status", "metadata"),
    "entity_alias_candidate_reviews": (
        "candidate_id",
        "decision",
        "reviewed_by",
        "assigned_to",
        "assignment_status",
        "due_at",
        "priority",
        "evidence_answer_run_ids",
        "evidence_urls",
        "payload",
    ),
    "project_brand_kits": ("logo_url", "footer_text"),
    "project_brand_assets": (
        "asset_type",
        "asset_url",
        "category",
        "preview_url",
        "content_hash",
        "storage_version",
        "status",
        "scan_status",
        "scan_checked_at",
        "scan_method_version",
        "scan_notes",
    ),
    "report_export_jobs": (
        "status",
        "artifact_type",
        "template",
        "filters",
        "attempt_count",
        "max_attempts",
        "lease_expires_at",
        "next_attempt_at",
        "artifact_url",
    ),
    "runtime_notifications": (
        "notification_type",
        "severity",
        "target_type",
        "target_id",
        "recipient_role",
        "status",
        "payload",
        "read_at",
    ),
    "runtime_notification_subscriptions": (
        "channel",
        "endpoint_url",
        "event_types",
        "severity_threshold",
        "status",
    ),
    "runtime_notification_deliveries": (
        "notification_id",
        "subscription_id",
        "status",
        "attempt_count",
        "max_attempts",
        "lease_expires_at",
        "next_attempt_at",
        "response_status",
        "response_body_hash",
    ),
    "llm_call_logs": ("estimated_cost", "latency_ms", "status"),
    "project_member_invitations": (
        "email",
        "role",
        "status",
        "invite_token_hash",
        "invited_by",
        "expires_at",
        "metadata",
    ),
}

EXPECTED_FUNCTIONS = (
    "geno_runtime_rls_enabled",
    "geno_runtime_actor_id",
    "geno_runtime_project_id",
    "geno_runtime_can_access_project",
)

EXPECTED_RLS_TABLES = (
    "projects",
    "project_members",
    "project_member_invitations",
    "prompt_questions",
    "answer_runs",
    "raw_answers",
    "answer_citations",
    "evidence_assets",
    "collector_logs",
    "answer_analyses",
    "source_graphs",
    "source_gaps",
    "competitor_benchmarks",
    "action_recommendations",
    "retest_schedules",
    "retest_comparisons",
    "api_browser_fidelity_checks",
    "localized_knowledge_facts",
    "knowledge_fact_embeddings",
    "content_drafts",
    "integration_connectors",
    "manual_distribution_records",
    "evidence_links",
    "runtime_saved_views",
    "project_brand_kits",
    "project_brand_assets",
    "score_weight_configs",
    "human_review_records",
    "runtime_alert_events",
    "traceability_bundles",
    "visibility_score_snapshots",
    "collection_costs",
    "collection_run_summaries",
    "audit_events",
    "report_exports",
    "report_export_jobs",
    "runtime_notifications",
    "runtime_notification_subscriptions",
    "runtime_notification_deliveries",
    "brand_entities",
    "competitor_entities",
    "llm_call_logs",
    "score_contributions",
    "score_snapshot_runs",
    "source_graph_evidence",
    "report_evidence",
    "entity_aliases",
    "entity_alias_candidate_reviews",
)

EXPECTED_POLICIES = (
    "projects_runtime_project_isolation",
    "project_members_runtime_project_isolation",
    "project_member_invitations_runtime_project_isolation",
    "answer_runs_runtime_project_isolation",
    "raw_answers_runtime_project_isolation",
    "score_contributions_runtime_project_isolation",
    "entity_aliases_runtime_project_isolation",
    "entity_alias_candidate_reviews_runtime_project_isolation",
)


def _database_url(env_name: str) -> str:
    value = os.environ.get(env_name, "").strip()
    if not value:
        raise RuntimeError(f"{env_name} is required for DB smoke verification")
    return value


def _query_all(connection: psycopg.Connection[Any], sql: str, params: tuple[object, ...] = ()) -> list[dict[str, Any]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]


def _query_one(connection: psycopg.Connection[Any], sql: str, params: tuple[object, ...] = ()) -> dict[str, Any]:
    rows = _query_all(connection, sql, params)
    if len(rows) != 1:
        raise AssertionError(f"Expected exactly one row, got {len(rows)} for query: {sql}")
    return rows[0]


def _assert_extensions(connection: psycopg.Connection[Any]) -> tuple[str, ...]:
    rows = _query_all(
        connection,
        "SELECT extname FROM pg_extension WHERE extname IN ('uuid-ossp', 'vector') ORDER BY extname",
    )
    found = tuple(row["extname"] for row in rows)
    missing = sorted({"uuid-ossp", "vector"} - set(found))
    if missing:
        raise AssertionError(f"Missing required PostgreSQL extensions: {missing}")
    return found


def _assert_tables(connection: psycopg.Connection[Any]) -> tuple[str, ...]:
    rows = _query_all(
        connection,
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """,
    )
    found = tuple(row["table_name"] for row in rows)
    missing = sorted(set(EXPECTED_TABLES) - set(found))
    if missing:
        raise AssertionError(f"Missing expected migrated tables: {missing}")
    return found


def _assert_columns(connection: psycopg.Connection[Any]) -> dict[str, tuple[str, ...]]:
    rows = _query_all(
        connection,
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
        """,
    )
    by_table: dict[str, set[str]] = {}
    for row in rows:
        by_table.setdefault(row["table_name"], set()).add(row["column_name"])

    verified: dict[str, tuple[str, ...]] = {}
    for table, columns in CRITICAL_COLUMNS.items():
        missing = sorted(set(columns) - by_table.get(table, set()))
        if missing:
            raise AssertionError(f"Missing critical columns on {table}: {missing}")
        verified[table] = tuple(columns)
    return verified


def _assert_runtime_role_and_functions(connection: psycopg.Connection[Any]) -> dict[str, Any]:
    role = _query_one(
        connection,
        "SELECT rolname, rolbypassrls FROM pg_roles WHERE rolname = 'geno_runtime_app'",
    )
    if role["rolbypassrls"]:
        raise AssertionError("geno_runtime_app must not bypass row level security")

    rows = _query_all(
        connection,
        """
        SELECT p.proname
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public' AND p.proname = ANY(%s)
        ORDER BY p.proname
        """,
        (list(EXPECTED_FUNCTIONS),),
    )
    found = tuple(row["proname"] for row in rows)
    missing = sorted(set(EXPECTED_FUNCTIONS) - set(found))
    if missing:
        raise AssertionError(f"Missing runtime RLS helper functions: {missing}")
    return {"role": role["rolname"], "role_bypass_rls": role["rolbypassrls"], "functions": found}


def _assert_rls_policies(connection: psycopg.Connection[Any]) -> dict[str, Any]:
    rows = _query_all(
        connection,
        """
        SELECT relname, relrowsecurity, relforcerowsecurity
        FROM pg_class
        JOIN pg_namespace ON pg_namespace.oid = pg_class.relnamespace
        WHERE pg_namespace.nspname = 'public'
          AND relkind = 'r'
          AND relname = ANY(%s)
        ORDER BY relname
        """,
        (list(EXPECTED_RLS_TABLES),),
    )
    by_table = {row["relname"]: row for row in rows}
    missing = sorted(set(EXPECTED_RLS_TABLES) - set(by_table))
    if missing:
        raise AssertionError(f"Missing expected RLS tables: {missing}")
    weak_tables = [
        table
        for table, row in by_table.items()
        if not row["relrowsecurity"] or not row["relforcerowsecurity"]
    ]
    if weak_tables:
        raise AssertionError(f"Tables without enabled+forced RLS: {sorted(weak_tables)}")

    policies = _query_all(
        connection,
        """
        SELECT policyname
        FROM pg_policies
        WHERE schemaname = 'public'
        ORDER BY policyname
        """,
    )
    policy_names = tuple(row["policyname"] for row in policies)
    missing_policies = sorted(set(EXPECTED_POLICIES) - set(policy_names))
    if missing_policies:
        raise AssertionError(f"Missing expected RLS policies: {missing_policies}")
    return {
        "rls_table_count": len(by_table),
        "policy_count": len(policy_names),
        "sample_policies": tuple(EXPECTED_POLICIES),
    }


def _seed_rls_fixture(connection: psycopg.Connection[Any]) -> dict[str, str]:
    tenant_id = str(uuid4())
    visible_project_id = str(uuid4())
    isolated_project_id = str(uuid4())
    visible_prompt_id = str(uuid4())
    isolated_prompt_id = str(uuid4())
    actor_id = "db-smoke-owner"
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tenants (id, name, slug)
            VALUES (%s, %s, %s)
            """,
            (tenant_id, "DB Smoke Tenant", f"db-smoke-{tenant_id}"),
        )
        for project_id, name, brand in (
            (visible_project_id, "DB Smoke Visible Project", "Visible DB Smoke Brand"),
            (isolated_project_id, "DB Smoke Isolated Project", "Isolated DB Smoke Brand"),
        ):
            cursor.execute(
                """
                INSERT INTO projects (
                  id, tenant_id, name, market_code, industry_code, target_brand,
                  category, prompt_version, status
                )
                VALUES (%s, %s, %s, 'AU', 'dtc_ecommerce', %s, 'DTC ecommerce', 'db-smoke-v1', 'configured')
                """,
                (project_id, tenant_id, name, brand),
            )
        cursor.execute(
            """
            INSERT INTO project_members (id, project_id, user_id, role)
            VALUES (%s, %s, %s, 'owner')
            """,
            (str(uuid4()), visible_project_id, actor_id),
        )
        for prompt_id, project_id, text in (
            (visible_prompt_id, visible_project_id, "DB smoke visible prompt"),
            (isolated_prompt_id, isolated_project_id, "DB smoke isolated prompt"),
        ):
            cursor.execute(
                """
                INSERT INTO prompt_questions (
                  id, project_id, market_code, industry_code, text, intent_type, city,
                  language, target_brand, competitors, priority, intent_weight,
                  prompt_version, status
                )
                VALUES (
                  %s, %s, 'AU', 'dtc_ecommerce', %s, 'brand_awareness', 'Sydney',
                  'en-AU', 'Visible DB Smoke Brand', '[]'::jsonb, 1, 1.0,
                  'db-smoke-v1', 'active'
                )
                """,
                (prompt_id, project_id, text),
            )
    connection.commit()
    return {
        "tenant_id": tenant_id,
        "visible_project_id": visible_project_id,
        "isolated_project_id": isolated_project_id,
        "actor_id": actor_id,
    }


def _cleanup_rls_fixture(connection: psycopg.Connection[Any], fixture: dict[str, str]) -> None:
    project_ids = (fixture["visible_project_id"], fixture["isolated_project_id"])
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM prompt_questions WHERE project_id = ANY(%s)", (list(project_ids),))
        cursor.execute("DELETE FROM project_members WHERE project_id = ANY(%s)", (list(project_ids),))
        cursor.execute("DELETE FROM projects WHERE id = ANY(%s)", (list(project_ids),))
        cursor.execute("DELETE FROM tenants WHERE id = %s", (fixture["tenant_id"],))
    connection.commit()


def _assert_runtime_rls_isolation(admin_url: str, runtime_url: str) -> dict[str, Any]:
    fixture: dict[str, str] | None = None
    with psycopg.connect(admin_url) as admin_connection:
        fixture = _seed_rls_fixture(admin_connection)
        try:
            with psycopg.connect(runtime_url) as runtime_connection:
                with runtime_connection.cursor(row_factory=dict_row) as cursor:
                    cursor.execute("SELECT current_user AS current_user")
                    runtime_user = cursor.fetchone()["current_user"]
                    cursor.execute("SELECT set_config('geno.runtime_project_access_control', '1', false)")
                    cursor.execute(
                        "SELECT set_config('geno.runtime_actor_id', %s, false)",
                        (fixture["actor_id"],),
                    )
                    cursor.execute(
                        "SELECT set_config('geno.runtime_project_id', %s, false)",
                        (fixture["visible_project_id"],),
                    )
                    cursor.execute("SELECT geno_runtime_rls_enabled() AS enabled")
                    rls_enabled = bool(cursor.fetchone()["enabled"])
                    cursor.execute("SELECT count(*)::int AS count FROM projects")
                    visible_projects = int(cursor.fetchone()["count"])
                    cursor.execute(
                        "SELECT count(*)::int AS count FROM projects WHERE id = %s",
                        (fixture["visible_project_id"],),
                    )
                    fixture_project_visible = int(cursor.fetchone()["count"])
                    cursor.execute(
                        "SELECT count(*)::int AS count FROM projects WHERE id = %s",
                        (fixture["isolated_project_id"],),
                    )
                    isolated_project_visible = int(cursor.fetchone()["count"])
                    cursor.execute("SELECT count(*)::int AS count FROM prompt_questions")
                    visible_prompts = int(cursor.fetchone()["count"])
                    cursor.execute(
                        "SELECT count(*)::int AS count FROM prompt_questions WHERE project_id = %s",
                        (fixture["isolated_project_id"],),
                    )
                    isolated_prompts_visible = int(cursor.fetchone()["count"])
            if runtime_user != "geno_runtime_app":
                raise AssertionError(f"Expected runtime user geno_runtime_app, got {runtime_user}")
            if not rls_enabled:
                raise AssertionError("Runtime RLS GUC did not enable project access control")
            if visible_projects != 1 or fixture_project_visible != 1:
                raise AssertionError(
                    f"Expected exactly one visible project, got visible={visible_projects} fixture={fixture_project_visible}"
                )
            if isolated_project_visible != 0 or isolated_prompts_visible != 0:
                raise AssertionError(
                    "RLS isolation failed: isolated project or prompt was visible to the runtime actor"
                )
            if visible_prompts != 1:
                raise AssertionError(f"Expected exactly one visible prompt, got {visible_prompts}")
            return {
                "runtime_user": runtime_user,
                "rls_enabled": rls_enabled,
                "visible_projects": visible_projects,
                "fixture_project_visible": fixture_project_visible,
                "isolated_project_visible": isolated_project_visible,
                "visible_prompts": visible_prompts,
                "isolated_prompts_visible": isolated_prompts_visible,
            }
        finally:
            _cleanup_rls_fixture(admin_connection, fixture)


def _run() -> dict[str, Any]:
    admin_url = _database_url("DATABASE_URL")
    runtime_url = os.environ.get("RUNTIME_DATABASE_URL", "").strip() or admin_url
    with psycopg.connect(admin_url) as connection:
        return {
            "status": "passed",
            "extensions": _assert_extensions(connection),
            "table_count": len(_assert_tables(connection)),
            "critical_columns": _assert_columns(connection),
            "runtime_role": _assert_runtime_role_and_functions(connection),
            "rls": _assert_rls_policies(connection),
            "runtime_project_rls": _assert_runtime_rls_isolation(admin_url, runtime_url),
        }


def main() -> int:
    try:
        print(json.dumps(_run(), indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
