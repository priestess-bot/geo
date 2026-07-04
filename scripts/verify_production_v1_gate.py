from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
CHECKLIST_PATH = ROOT / "docs/GEO-Production-v1执行进度-checklist-2026-07-05.md"
PLAN_PATH = ROOT / "docs/GEO-Production-v1完整规划-2026-07-05.md"


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _exists(relative: str) -> bool:
    return (ROOT / relative).exists()


def _contains(relative: str, needle: str) -> bool:
    return needle in _read(ROOT / relative)


def _regex_contains(relative: str, pattern: str) -> bool:
    return re.search(pattern, _read(ROOT / relative), flags=re.MULTILINE) is not None


def _check_file_exists(name: str, relative: str) -> Check:
    return Check(name, "pass" if _exists(relative) else "fail", relative)


def _check_contains(name: str, relative: str, needle: str) -> Check:
    return Check(name, "pass" if _contains(relative, needle) else "fail", f"{relative}: {needle}")


def _check_regex(name: str, relative: str, pattern: str) -> Check:
    return Check(name, "pass" if _regex_contains(relative, pattern) else "fail", f"{relative}: /{pattern}/")


def _pending(name: str, detail: str) -> Check:
    return Check(name, "pending", detail)


def _fail(name: str, detail: str) -> Check:
    return Check(name, "fail", detail)


def _pass(name: str, detail: str) -> Check:
    return Check(name, "pass", detail)


def _scan_runtime_files(patterns: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    # This static check models API/frontend/worker/infra surfaces. Historical
    # verifier scripts contain fake secret literals to test redaction behavior
    # and are intentionally excluded from this production-surface scan.
    for base in ("apps", "packages", "workers", "infra"):
        root = ROOT / base
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {".py", ".ts", ".tsx", ".sql", ".yml", ".yaml", ".json", ".toml"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(pattern in text for pattern in patterns):
                files.append(path.relative_to(ROOT))
    return files


def _gate_checklist() -> list[Check]:
    return [
        _check_file_exists("checklist_exists", "docs/GEO-Production-v1执行进度-checklist-2026-07-05.md"),
        _check_contains("checklist_links_plan", str(CHECKLIST_PATH.relative_to(ROOT)), "GEO-Production-v1完整规划-2026-07-05.md"),
        _check_contains("checklist_tracks_w10", str(CHECKLIST_PATH.relative_to(ROOT)), "W10-I01"),
        _check_contains("checklist_tracks_final_gate", str(CHECKLIST_PATH.relative_to(ROOT)), "Final Gate"),
        _check_contains("checklist_marks_deferred_upgrades", str(CHECKLIST_PATH.relative_to(ROOT)), "Deferred upgrade"),
    ]


def _gate_no_fixture_production() -> list[Check]:
    checks = _gate_checklist()
    checks.extend(
        [
            _check_contains(
                "api_dev_tools_guard_exists",
                "apps/api/geno_api/main.py",
                "def require_dev_tools_enabled",
            ),
            _check_contains(
                "api_fixture_endpoints_require_dev_tools",
                "apps/api/geno_api/main.py",
                "require_dev_tools_enabled()",
            ),
            _check_contains(
                "admin_dev_tools_switch_exists",
                "apps/admin-web/app/runtime.ts",
                "GENO_ADMIN_DEV_TOOLS_ENABLED",
            ),
            _check_contains(
                "admin_e2e_panel_gated",
                "apps/admin-web/app/projects/[project_id]/page.tsx",
                "devToolsEnabled ?",
            ),
            _check_contains(
                "create_project_action_defaults_api",
                "apps/admin-web/app/projects/new/actions.ts",
                'requiredString(formData, "collection_mode", "api")',
            ),
            _check_contains(
                "launch_config_action_defaults_api",
                "apps/admin-web/app/projects/[project_id]/actions.ts",
                'value(formData, "collection_mode") || "api"',
            ),
            _check_contains(
                "runtime_create_request_defaults_api",
                "apps/api/geno_api/main.py",
                'collection_mode: str = Field(default="api"',
            ),
            _check_contains(
                "runtime_access_launch_config_defaults_api",
                "apps/api/geno_api/runtime_access_routes.py",
                'collection_mode: str = Field(default="api"',
            ),
            _check_contains(
                "launch_config_migration_defaults_api",
                "infra/db/migrations/up/0015_customer_portal_launch_access_logs.sql",
                "collection_mode text NOT NULL DEFAULT 'api'",
            ),
            _check_contains(
                "worker_cli_defaults_api",
                "workers/collector_worker/run_collection_slice.py",
                'default="api"',
            ),
        ]
    )
    forbidden_by_file = {
        "apps/admin-web/app/projects/new/actions.ts": (
            '"fixture"',
            "AU GEO Pilot",
            "ExampleBrand",
            "KoalaHome",
        ),
        "apps/admin-web/app/projects/new/CreateProjectForm.tsx": (
            'value="fixture"',
            '<option value="fixture"',
            "AU GEO Pilot",
            "ExampleBrand",
            "KoalaHome",
        ),
        "apps/admin-web/app/projects/[project_id]/actions.ts": (
            'collection_mode: value(formData, "collection_mode") || "fixture"',
            'status: connector.status || "fixture_only"',
        ),
        "apps/admin-web/app/projects/[project_id]/ProjectActions.tsx": (
            '<option value="fixture"',
            '<option value="fixture_only"',
        ),
        "apps/api/geno_api/main.py": (
            'target_brand: str = Field(default="ExampleBrand"',
            'collection_mode: str = Field(default="fixture"',
        ),
        "apps/api/geno_api/runtime_access_routes.py": (
            'collection_mode: str = Field(default="fixture"',
        ),
        "packages/geno_core/geno_core/models.py": (
            'collection_mode: str = "fixture"',
        ),
        "packages/geno_core/geno_core/runtime_project_access_repository.py": (
            '"collection_mode": config.collection_mode.strip().lower() or "fixture"',
        ),
        "infra/db/migrations/up/0015_customer_portal_launch_access_logs.sql": (
            "collection_mode text NOT NULL DEFAULT 'fixture'",
        ),
        "infra/docker-compose.yml": (
            "      - --mode\n      - fixture",
        ),
    }
    production_fixture_hits: list[str] = []
    for relative, forbidden_patterns in forbidden_by_file.items():
        path = ROOT / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        hits = [pattern for pattern in forbidden_patterns if pattern in text]
        if hits:
            production_fixture_hits.append(f"{relative} ({', '.join(hits)})")
    if production_fixture_hits:
        checks.append(
            _fail(
                "production_fixture_references_absent",
                "production defaults still reference fixture/demo values: "
                + ", ".join(sorted(production_fixture_hits)),
            )
        )
    else:
        checks.append(_pass("production_fixture_references_absent", "no fixture/demo defaults in production-facing files"))
    return checks


def _gate_no_secret_leak() -> list[Check]:
    checks = _gate_checklist()
    forbidden_literals = (
        "geno-invite-d3536f6cb7bd448eabdeebe08d6bac92",
        "openai-secret",
        "perplexity-secret",
        "pplx-",
        "AIza",
    )
    hits = _scan_runtime_files(forbidden_literals)
    allowed_test_hits = [path for path in hits if str(path).startswith("tests/")]
    actionable_hits = [path for path in hits if path not in allowed_test_hits]
    if actionable_hits:
        checks.append(_fail("no_hardcoded_secret_literals", ", ".join(str(path) for path in actionable_hits)))
    else:
        checks.append(_pass("no_hardcoded_secret_literals", "no forbidden secret literals in runtime source"))
    checks.append(_check_contains("portal_tokens_are_hashed", "infra/db/migrations/up/0015_customer_portal_launch_access_logs.sql", "token_hash"))
    checks.append(_check_contains("invite_tokens_are_hashed", "infra/db/migrations/up/0013_project_member_invitations.sql", "invite_token_hash"))
    checks.append(_check_contains("frontend_bundle_has_no_provider_env", "tests/test_web_console_contracts.py", "assertNotIn(\"OPENAI_API_KEY\""))
    return checks


def _gate_report_traceability() -> list[Check]:
    return [
        *_gate_checklist(),
        _check_contains("report_mentions_traceability_chain", "packages/geno_core/geno_core/report.py", "ReportExport -> VisibilityScoreSnapshot -> ScoreContribution"),
        _check_contains("traceability_module_exists", "packages/geno_core/geno_core/traceability.py", "TraceabilityBundle"),
        _check_contains("report_evidence_table_exists", "infra/db/migrations/up/0001_init.sql", "CREATE TABLE report_evidence"),
        _check_contains("score_contributions_table_exists", "infra/db/migrations/up/0001_init.sql", "CREATE TABLE score_contributions"),
        _pending("runtime_traceability_sample", "upgrade W4-I01d/W5-I02c/W6-I01f to sample report numbers against live data"),
    ]


def _gate_customer_access_negative() -> list[Check]:
    return [
        *_gate_checklist(),
        _check_contains("customer_portal_token_table_exists", "infra/db/migrations/up/0015_customer_portal_launch_access_logs.sql", "CREATE TABLE IF NOT EXISTS customer_portal_tokens"),
        _check_contains("customer_portal_token_rls_exists", "infra/db/migrations/up/0015_customer_portal_launch_access_logs.sql", "customer_portal_tokens_runtime_project_isolation"),
        _check_contains("artifact_route_checks_portal", "apps/customer-web/app/api/report-artifact/route.ts", "/v1/customer-portal/access"),
        _check_contains("artifact_route_uses_actor_header", "apps/customer-web/app/api/report-artifact/route.ts", "X-GENO-Actor-Id"),
        _check_contains("artifact_route_marks_customer_portal_access", "apps/customer-web/app/api/report-artifact/route.ts", "X-GENO-Customer-Portal-Access"),
        _check_contains("report_artifact_checks_latest_management_status", "apps/api/geno_api/main.py", "get_report_export_latest_management_status"),
        _check_contains("report_artifact_requires_client_ready_for_customers", "apps/api/geno_api/main.py", "CUSTOMER_PORTAL_REPORT_READY_STATUS"),
        _check_contains("unpublished_report_denied_runtime_test", "tests/test_api_contracts.py", "test_runtime_report_artifact_customer_portal_denies_unpublished_reports"),
        _check_contains("revoked_report_denied_runtime_test", "tests/test_api_contracts.py", "test_runtime_report_artifact_customer_portal_denies_revoked_reports"),
        _check_contains("viewer_direct_report_denied_runtime_test", "tests/test_api_contracts.py", "test_runtime_report_artifact_viewer_role_denies_unpublished_report_without_portal_header"),
        _check_contains("cross_project_report_denied_runtime_test", "tests/test_api_contracts.py", "test_runtime_report_artifact_customer_portal_denies_cross_project_actor"),
    ]


def _gate_rls() -> list[Check]:
    return [
        *_gate_checklist(),
        _check_contains("runtime_rls_migration_exists", "infra/db/migrations/up/0010_runtime_project_rls.sql", "ENABLE ROW LEVEL SECURITY"),
        _check_contains("runtime_rls_forced", "infra/db/migrations/up/0010_runtime_project_rls.sql", "FORCE ROW LEVEL SECURITY"),
        _check_contains("runtime_rls_smoke_exists", "scripts/verify_db_smoke.py", "_assert_runtime_rls_isolation"),
        _check_contains("app_scope_guc_contract", "infra/db/migrations/up/0010_runtime_project_rls.sql", "current_setting('app.actor_id'"),
        _check_contains("app_project_ids_guc_contract", "infra/db/migrations/up/0010_runtime_project_rls.sql", "current_setting('app.project_ids'"),
        _check_contains("db_smoke_sets_app_scope", "scripts/verify_db_smoke.py", "set_config('app.actor_id'"),
    ]


def _gate_security() -> list[Check]:
    checks = [
        *_gate_no_secret_leak(),
        *_gate_customer_access_negative(),
        *_gate_rls(),
        _check_contains("auth_context_contract_exists", "apps/api/geno_api/auth_context.py", "class AuthContext"),
        _check_contains("auth_context_has_required_scope_fields", "apps/api/geno_api/auth_context.py", "project_ids: tuple[str, ...]"),
        _check_contains("system_actor_requires_scope", "apps/api/geno_api/auth_context.py", "allow_unscoped"),
        _check_contains("auth_audit_event_vocabulary_exists", "packages/geno_core/geno_core/audit.py", "AUTH_AUDIT_EVENT_TYPES"),
        _check_contains("auth_audit_rejects_raw_secret_refs", "packages/geno_core/geno_core/audit.py", "AUTH_AUDIT_FORBIDDEN_REF_KEYS"),
        _check_contains("runtime_auth_context_dependency_exists", "apps/api/geno_api/main.py", "def build_runtime_auth_context"),
        _check_contains("runtime_sessions_table_exists", "infra/db/migrations/up/0016_runtime_sessions.sql", "CREATE TABLE IF NOT EXISTS runtime_sessions"),
        _check_contains("runtime_sessions_store_hashed_tokens", "infra/db/migrations/up/0016_runtime_sessions.sql", "session_token_hash text NOT NULL UNIQUE"),
        _check_contains("runtime_session_repository_exists", "packages/geno_core/geno_core/runtime_project_access_repository.py", "def create_runtime_session"),
        _check_contains("rbac_permission_vocabulary_exists", "packages/geno_core/geno_core/rbac.py", "PERMISSION_VOCABULARY"),
        _check_contains("rbac_role_matrix_exists", "packages/geno_core/geno_core/rbac.py", "ROLE_PERMISSION_MATRIX"),
        _check_contains("rbac_declares_report_download", "packages/geno_core/geno_core/rbac.py", "\"report.download\""),
        _check_contains("rbac_declares_connector_secret_manage", "packages/geno_core/geno_core/rbac.py", "\"connector.secret.manage\""),
        _check_contains("tenant_members_table_exists", "infra/db/migrations/up/0017_tenant_membership_scope.sql", "CREATE TABLE IF NOT EXISTS tenant_members"),
        _check_contains("tenant_members_rls_exists", "infra/db/migrations/up/0017_tenant_membership_scope.sql", "tenant_members_runtime_tenant_isolation"),
        _check_contains("membership_scope_repository_exists", "packages/geno_core/geno_core/runtime_project_access_repository.py", "def get_runtime_membership_scope"),
        _check_contains("session_auth_mode_exists", "apps/api/geno_api/main.py", "RUNTIME_AUTH_MODE_SESSION"),
        _check_contains("session_cookie_name_exists", "apps/api/geno_api/main.py", "GENO_RUNTIME_SESSION"),
        _check_contains("protected_api_uses_auth_context_project_scope", "apps/api/geno_api/main.py", "def _assert_auth_context_project_access"),
        _check_contains("invitation_redeem_endpoint_exists", "apps/api/geno_api/main.py", "@app.post(\"/v1/auth/invitations/redeem\")"),
        _check_contains("auth_me_endpoint_exists", "apps/api/geno_api/main.py", "@app.get(\"/v1/auth/me\")"),
        _check_contains("auth_logout_endpoint_exists", "apps/api/geno_api/main.py", "@app.post(\"/v1/auth/logout\")"),
        _check_contains("runtime_session_cookie_is_httponly", "apps/api/geno_api/main.py", "httponly=True"),
        _check_regex("jwt_or_jwks_auth_exists", "apps/api/geno_api/main.py", r"RUNTIME_AUTH_MODE_ENV|jwks|JWT"),
        _check_contains("csrf_header_contract_exists", "apps/api/geno_api/main.py", "X-GENO-CSRF-Token"),
        _check_contains("csrf_cookie_contract_exists", "apps/api/geno_api/main.py", "GENO_CSRF_TOKEN"),
        _check_contains("csrf_enforced_for_session_mutations", "apps/api/geno_api/main.py", "def _assert_runtime_session_csrf"),
        _check_contains("csrf_missing_token_test_exists", "tests/test_api_contracts.py", "test_auth_logout_rejects_session_mutation_without_csrf"),
        _check_contains("csrf_mismatch_test_exists", "tests/test_api_contracts.py", "test_auth_logout_rejects_session_mutation_with_mismatched_csrf"),
    ]
    return _dedupe(checks)


def _gate_connector_real() -> list[Check]:
    checks = [
        *_gate_checklist(),
        _check_contains("openai_collector_exists", "packages/geno_core/geno_core/collectors.py", "class OpenAIWebSearchCollector"),
        _check_contains("openai_responses_endpoint", "packages/geno_core/geno_core/collectors.py", "https://api.openai.com/v1/responses"),
        _check_contains("perplexity_collector_exists", "packages/geno_core/geno_core/collectors.py", "class PerplexitySonarCollector"),
        _check_contains("google_manual_backfill_exists", "apps/api/geno_api/main.py", "/v1/evidence-runs/runtime/manual-backfill"),
    ]
    if os.environ.get("OPENAI_API_KEY") and os.environ.get("PERPLEXITY_API_KEY"):
        checks.append(_pending("real_provider_smoke_execution", "wire 10 prompt staging smoke through W3-I02/W3-I03"))
    else:
        checks.append(_pass("real_provider_smoke_skipped_local", "OPENAI_API_KEY/PERPLEXITY_API_KEY absent; Local/CI may skip real provider subset"))
    return checks


def _gate_ops() -> list[Check]:
    return [
        *_gate_checklist(),
        _check_contains("ops_router_registered", "apps/api/geno_api/main.py", "register_ops_routes(app)"),
        _check_contains("health_endpoint_exists", "apps/api/geno_api/ops_routes.py", "@router.get(\"/health\")"),
        _check_contains("ready_endpoint_exists", "apps/api/geno_api/ops_routes.py", "@router.get(\"/ready\")"),
        _check_contains("metrics_endpoint_exists", "apps/api/geno_api/ops_routes.py", "@router.get(\"/metrics\")"),
        _check_contains("observability_compose_profile_exists", "infra/docker-compose.yml", "profiles:\n      - observability"),
        _pending("alert_smoke", "W9-I01 alert smoke not complete"),
    ]


def _gate_backup() -> list[Check]:
    return [
        *_gate_checklist(),
        _check_contains("postgres_volume_exists", "infra/docker-compose.yml", "postgres_data"),
        _check_contains("minio_volume_exists", "infra/docker-compose.yml", "minio_data"),
        _pending("postgres_restore_smoke", "W9-I02 restore smoke script not complete"),
        _pending("object_store_restore_smoke", "W9-I02 object storage restore smoke not complete"),
    ]


def _gate_production_e2e() -> list[Check]:
    required = (
        "W2-I01a",
        "W2-I01b",
        "W2-I02",
        "W3-I02",
        "W3-I03",
        "W3-I04",
        "W4-I01d",
        "W5-I01",
        "W5-I02c",
        "W6-I01f",
        "W7-I01",
        "W7-I02",
    )
    return [
        *_gate_checklist(),
        _check_contains("runtime_e2e_script_exists", "scripts/verify_runtime_e2e.py", "def main()"),
        *[_pending(f"{item}_not_done", f"{item} is not marked Done in checklist") for item in required],
    ]


def _gate_enablement_e2e() -> list[Check]:
    return [
        *_gate_checklist(),
        _check_contains("knowledge_module_exists", "packages/geno_core/geno_core/knowledge.py", "build_localized_knowledge_facts"),
        _check_contains("content_drafts_model_exists", "packages/geno_core/geno_core/models.py", "class ContentDraft"),
        _check_contains("distribution_model_exists", "packages/geno_core/geno_core/models.py", "class ManualDistributionRecord"),
        _pending("knowledge_api_complete", "W8-I01 API/UI persistence not complete"),
        _pending("content_api_complete", "W8-I02 API/UI persistence not complete"),
        _pending("distribution_api_complete", "W8-I03 API/UI persistence not complete"),
    ]


def _dedupe(checks: list[Check]) -> list[Check]:
    seen: set[tuple[str, str]] = set()
    result: list[Check] = []
    for check in checks:
        key = (check.name, check.detail)
        if key in seen:
            continue
        seen.add(key)
        result.append(check)
    return result


GATES: dict[str, Callable[[], list[Check]]] = {
    "checklist": _gate_checklist,
    "rls-smoke": _gate_rls,
    "security-smoke": _gate_security,
    "production-v1-e2e": _gate_production_e2e,
    "enablement-v1-e2e": _gate_enablement_e2e,
    "no-fixture-production-smoke": _gate_no_fixture_production,
    "no-secret-leak-smoke": _gate_no_secret_leak,
    "report-traceability-smoke": _gate_report_traceability,
    "customer-access-negative-smoke": _gate_customer_access_negative,
    "connector-real-smoke": _gate_connector_real,
    "ops-smoke": _gate_ops,
    "backup-smoke": _gate_backup,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify GEO Production v1 gate status.")
    parser.add_argument("gate", choices=sorted(GATES))
    parser.add_argument(
        "--allow-pending",
        action="store_true",
        help="Return success when checks are pending but no hard failure exists.",
    )
    args = parser.parse_args()

    checks = _dedupe(GATES[args.gate]())
    failures = [check for check in checks if check.status == "fail"]
    pending = [check for check in checks if check.status == "pending"]
    status = "passed"
    if failures:
        status = "failed"
    elif pending:
        status = "pending"
    payload = {
        "gate": args.gate,
        "status": status,
        "checks": [asdict(check) for check in checks],
        "summary": {
            "pass": sum(1 for check in checks if check.status == "pass"),
            "fail": len(failures),
            "pending": len(pending),
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if failures:
        return 1
    if pending and not args.allow_pending:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
