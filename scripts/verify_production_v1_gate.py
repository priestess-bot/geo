from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
CHECKLIST_PATH = ROOT / "docs/GEO-Production-v1执行进度-checklist-2026-07-05.md"
PLAN_PATH = ROOT / "docs/GEO-Production-v1完整规划-2026-07-05.md"
CONNECTOR_REAL_SMOKE_PATH = ROOT / "tmp/connector-real-smoke/latest.json"
FRONTEND_PAGE_CLICK_SMOKE_PATH = ROOT / "tmp/frontend-page-click-smoke/latest.json"
FRONTEND_KNOWLEDGE_LIFECYCLE_SMOKE_PATH = ROOT / "tmp/frontend-knowledge-lifecycle-smoke/latest.json"
FULL_PROJECT_LIFECYCLE_SMOKE_PATH = ROOT / "tmp/full-project-lifecycle-smoke/latest.json"
PROMPTFOO_KNOWLEDGE_EVAL_PATH = ROOT / "tmp/promptfoo-knowledge-eval/latest.json"


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


def _check_absent(name: str, relative: str, needle: str) -> Check:
    return Check(name, "pass" if not _contains(relative, needle) else "fail", f"{relative}: {needle}")


def _check_regex(name: str, relative: str, pattern: str) -> Check:
    return Check(name, "pass" if _regex_contains(relative, pattern) else "fail", f"{relative}: /{pattern}/")


def _pending(name: str, detail: str) -> Check:
    return Check(name, "pending", detail)


def _fail(name: str, detail: str) -> Check:
    return Check(name, "fail", detail)


def _pass(name: str, detail: str) -> Check:
    return Check(name, "pass", detail)


def _runtime_artifact_checks(path: Path, prefix: str, report: dict[str, object]) -> list[Check]:
    run_id = str(report.get("run_id") or "").strip()
    checks = [
        _pass(f"{prefix}_run_id", run_id) if run_id else _fail(f"{prefix}_run_id", "run_id is missing")
    ]
    timestamp_value = report.get("finished_at") or report.get("completed_at") or report.get("started_at")
    if not isinstance(timestamp_value, str) or not timestamp_value.strip():
        checks.append(_fail(f"{prefix}_artifact_fresh", "runtime timestamp is missing"))
        return checks
    try:
        timestamp = datetime.fromisoformat(timestamp_value.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
    except ValueError:
        checks.append(_fail(f"{prefix}_artifact_fresh", f"invalid timestamp: {timestamp_value}"))
        return checks
    age_seconds = (datetime.now(UTC) - timestamp.astimezone(UTC)).total_seconds()
    if -300 <= age_seconds <= 86_400:
        checks.append(
            _pass(
                f"{prefix}_artifact_fresh",
                f"{path.relative_to(ROOT)} age_seconds={round(age_seconds)}",
            )
        )
    else:
        checks.append(
            _fail(
                f"{prefix}_artifact_fresh",
                f"{path.relative_to(ROOT)} age_seconds={round(age_seconds)}; expected <= 86400",
            )
        )
    return checks


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


def _check_checklist_status(item: str, accepted_statuses: set[str]) -> Check:
    if not CHECKLIST_PATH.exists():
        return _fail(f"{item}_checklist_status", "checklist file is missing")
    for line in _read(CHECKLIST_PATH).splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 5 and cells[0] == item:
            status = cells[4]
            if status in accepted_statuses:
                return _pass(f"{item}_checklist_status", f"{item} is {status}")
            accepted = ", ".join(sorted(accepted_statuses))
            return _pending(f"{item}_checklist_status", f"{item} is {status}; expected one of: {accepted}")
    return _fail(f"{item}_checklist_status", f"{item} missing from checklist")


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
    checks.append(_check_contains("connector_secret_refs_table_exists", "infra/db/migrations/up/0018_connector_secret_refs.sql", "CREATE TABLE IF NOT EXISTS connector_secret_refs"))
    checks.append(_check_contains("connector_secret_refs_store_encrypted_secret", "infra/db/migrations/up/0018_connector_secret_refs.sql", "encrypted_secret text NOT NULL"))
    checks.append(_check_contains("connector_secret_store_adapter_exists", "packages/geno_core/geno_core/security/secrets.py", "def encrypt_connector_secret"))
    checks.append(_check_contains("connector_secret_api_exists", "apps/api/geno_api/main.py", "/v1/connectors/runtime/secrets"))
    checks.append(_check_contains("access_log_redacts_secret_body", "apps/api/geno_api/access_logging.py", "redact_secret_text"))
    checks.append(_check_contains("connector_secret_api_masks_raw_secret_test", "tests/test_api_contracts.py", "test_runtime_connector_secret_endpoint_masks_raw_secret"))
    checks.append(_check_contains("connector_secret_permission_test", "tests/test_api_contracts.py", "test_runtime_connector_secret_endpoint_requires_manage_role"))
    checks.append(_check_contains("access_log_secret_body_redaction_test", "tests/test_api_contracts.py", "test_runtime_http_access_log_redacts_secret_request_body_artifacts"))
    return checks


def _gate_report_traceability() -> list[Check]:
    return [
        *_gate_checklist(),
        _check_contains("report_mentions_traceability_chain", "packages/geno_core/geno_core/report.py", "ReportExport -> VisibilityScoreSnapshot -> ScoreContribution"),
        _check_contains("traceability_module_exists", "packages/geno_core/geno_core/traceability.py", "TraceabilityBundle"),
        _check_contains("report_evidence_table_exists", "infra/db/migrations/up/0001_init.sql", "CREATE TABLE report_evidence"),
        _check_contains("score_contributions_table_exists", "infra/db/migrations/up/0001_init.sql", "CREATE TABLE score_contributions"),
        _check_contains("evidence_asset_metadata_migration_exists", "infra/db/migrations/up/0019_evidence_asset_metadata.sql", "ADD COLUMN IF NOT EXISTS project_id uuid"),
        _check_contains("evidence_asset_content_type_exists", "infra/db/migrations/up/0019_evidence_asset_metadata.sql", "ADD COLUMN IF NOT EXISTS content_type text"),
        _check_contains("evidence_asset_size_exists", "infra/db/migrations/up/0019_evidence_asset_metadata.sql", "ADD COLUMN IF NOT EXISTS byte_size bigint"),
        _check_contains("evidence_asset_project_scope_index_exists", "infra/db/migrations/up/0019_evidence_asset_metadata.sql", "idx_evidence_assets_project_scope"),
        _check_contains("runtime_evidence_asset_input_model_exists", "packages/geno_core/geno_core/models.py", "class RuntimeEvidenceAssetInput"),
        _check_contains("runtime_evidence_asset_model_exists", "packages/geno_core/geno_core/models.py", "class RuntimeEvidenceAsset"),
        _check_contains("evidence_asset_repository_method_exists", "packages/geno_core/geno_core/repository.py", "def save_runtime_evidence_asset"),
        _check_contains("raw_evidence_records_write_scoped_assets", "packages/geno_core/geno_core/repository.py", "JOIN projects p ON p.id = ar.project_id"),
        _check_contains("evidence_created_audit_exists", "packages/geno_core/geno_core/repository.py", "event_type=\"evidence.created\""),
        _check_contains("s3_compatible_store_exists", "packages/geno_core/geno_core/object_store.py", "class S3CompatibleObjectStore"),
        _check_contains("object_store_download_exists", "packages/geno_core/geno_core/object_store.py", "def get_object"),
        _check_contains("object_store_hash_mismatch_rejected", "packages/geno_core/geno_core/object_store.py", "Object content hash mismatch"),
        _check_contains("archive_evidence_bytes_exists", "packages/geno_core/geno_core/object_store.py", "def archive_evidence_bytes"),
        _check_contains("minio_compose_service_exists", "infra/docker-compose.yml", "minio/minio"),
        _check_contains("evidence_metadata_migration_runs_in_compose", "infra/docker-compose.yml", "0019_evidence_asset_metadata.sql"),
        _check_contains("evidence_asset_metadata_test_exists", "tests/test_core_contracts.py", "test_evidence_asset_metadata_migration_is_additive_and_scoped"),
        _check_contains("evidence_asset_repository_test_exists", "tests/test_core_contracts.py", "test_postgres_repository_saves_runtime_evidence_asset_with_scope_link_and_audit"),
        _check_contains("object_store_round_trip_test_exists", "tests/test_core_contracts.py", "test_s3_compatible_object_store_upload_download_and_hash_mismatch"),
        _check_contains("archive_evidence_bytes_test_exists", "tests/test_core_contracts.py", "test_archive_evidence_bytes_returns_runtime_evidence_asset_input"),
        _check_contains("report_traceability_smoke_exists", "packages/geno_core/geno_core/traceability.py", "def verify_report_traceability_smoke"),
        _check_contains("report_traceability_smoke_result_exists", "packages/geno_core/geno_core/traceability.py", "class ReportTraceabilitySmokeResult"),
        _check_contains("report_traceability_broken_link_test_exists", "tests/test_core_contracts.py", "test_report_traceability_smoke_passes_and_fails_on_broken_links"),
        _check_contains("analysis_output_contract_exists", "packages/geno_core/geno_core/analysis_contract.py", "def build_answer_analysis_output_contract"),
        _check_contains("analysis_human_override_exists", "packages/geno_core/geno_core/analysis_contract.py", "def apply_human_review_override"),
        _check_contains("analysis_output_contract_test_exists", "tests/test_core_contracts.py", "test_answer_analysis_output_contract_exposes_p0_fields_without_unearned_metrics"),
        _check_contains("analysis_human_override_test_exists", "tests/test_core_contracts.py", "test_human_review_override_versions_analysis_and_preserves_original_parser_output"),
        _check_contains("production_v1_formula_exists", "packages/geno_core/geno_core/scoring.py", "visibility_v1.0"),
        _check_contains("production_v1_formula_weights_exist", "packages/geno_core/geno_core/scoring.py", "VISIBILITY_V1_0"),
        _check_contains("production_v1_formula_test_exists", "tests/test_core_contracts.py", "test_production_v1_scoring_formula_is_versioned_and_uses_explicit_denominators"),
        _check_contains("score_contribution_trace_test_exists", "tests/test_core_contracts.py", "test_score_snapshot_contributions_trace_each_component_to_answer_runs"),
        _check_contains("report_export_schema_exists", "packages/geno_core/geno_core/models.py", "class ReportExport"),
        _check_contains("report_export_repository_insert_is_immutable", "packages/geno_core/geno_core/repository.py", "ON CONFLICT (id) DO NOTHING"),
        _check_contains("report_export_artifacts_use_fixed_snapshot_test_exists", "tests/test_core_contracts.py", "test_report_export_artifacts_are_generated_from_one_fixed_snapshot"),
        _check_contains("report_markdown_generation_exists", "packages/geno_core/geno_core/report.py", "def _build_markdown_report"),
        _check_contains("report_csv_generation_exists", "packages/geno_core/geno_core/report.py", "def _build_csv_evidence"),
        _check_contains("report_pdf_generation_exists", "packages/geno_core/geno_core/report.py", "def render_markdown_pdf"),
        _check_contains("report_artifact_archive_exists", "packages/geno_core/geno_core/object_store.py", "def archive_report_artifacts"),
        _check_contains("report_artifact_archive_test_exists", "tests/test_core_contracts.py", "test_report_artifacts_archive_to_s3_compatible_store"),
    ]


def _gate_customer_access_negative() -> list[Check]:
    return [
        *_gate_checklist(),
        _check_contains("customer_portal_token_table_exists", "infra/db/migrations/up/0015_customer_portal_launch_access_logs.sql", "CREATE TABLE IF NOT EXISTS customer_portal_tokens"),
        _check_contains("customer_portal_token_rls_exists", "infra/db/migrations/up/0015_customer_portal_launch_access_logs.sql", "customer_portal_tokens_runtime_project_isolation"),
        _check_contains("artifact_route_reads_session_cookie", "apps/customer-web/app/api/report-artifact/route.ts", "GENO_RUNTIME_SESSION"),
        _check_contains("artifact_route_uses_session_header", "apps/customer-web/app/api/report-artifact/route.ts", "X-GENO-Session-Token"),
        _check_absent("artifact_route_avoids_legacy_portal_token_exchange", "apps/customer-web/app/api/report-artifact/route.ts", "/v1/customer-portal/access"),
        _check_absent("artifact_route_avoids_actor_header_impersonation", "apps/customer-web/app/api/report-artifact/route.ts", "X-GENO-Actor-Id"),
        _check_contains("artifact_route_marks_customer_portal_access", "apps/customer-web/app/api/report-artifact/route.ts", "X-GENO-Customer-Portal-Access"),
        _check_contains("customer_report_center_exists", "apps/customer-web/app/portal/[module]/page.tsx", "报告交付"),
        _check_contains("customer_report_center_lists_reports", "apps/customer-web/app/portal/[module]/page.tsx", "runtime?.reports.records"),
        _check_contains("customer_report_center_downloads_markdown", "apps/customer-web/app/portal/[module]/page.tsx", "artifactHref(reportId, \"markdown\""),
        _check_contains("customer_report_center_downloads_csv", "apps/customer-web/app/portal/[module]/page.tsx", "artifactHref(reportId, \"csv\""),
        _check_contains("customer_report_center_downloads_pdf", "apps/customer-web/app/portal/[module]/page.tsx", "artifactHref(reportId, \"pdf\""),
        _check_contains("report_management_status_aliases_api", "apps/api/geno_api/main.py", "REPORT_MANAGEMENT_STATUS_ALIASES"),
        _check_contains("report_management_status_aliases_repository", "packages/geno_core/geno_core/repository.py", "REPORT_MANAGEMENT_STATUS_ALIASES"),
        _check_contains("report_management_lifecycle_alias_api_test", "tests/test_api_contracts.py", "test_runtime_report_management_endpoint_maps_publish_revoke_lifecycle_aliases"),
        _check_contains("report_management_lifecycle_alias_repository_test", "tests/test_core_contracts.py", "test_postgres_repository_maps_report_publish_revoke_aliases_and_rejects_invalid_status"),
        _check_contains("report_artifact_checks_latest_management_status", "apps/api/geno_api/main.py", "get_report_export_latest_management_status"),
        _check_contains("report_artifact_requires_client_ready_for_customers", "apps/api/geno_api/main.py", "CUSTOMER_PORTAL_REPORT_READY_STATUS"),
        _check_contains("published_report_allowed_runtime_test", "tests/test_api_contracts.py", "test_runtime_report_artifact_customer_portal_allows_published_report"),
        _check_contains("unpublished_report_denied_runtime_test", "tests/test_api_contracts.py", "test_runtime_report_artifact_customer_portal_denies_unpublished_reports"),
        _check_contains("revoked_report_denied_runtime_test", "tests/test_api_contracts.py", "test_runtime_report_artifact_customer_portal_denies_revoked_reports"),
        _check_contains("viewer_direct_report_denied_runtime_test", "tests/test_api_contracts.py", "test_runtime_report_artifact_viewer_role_denies_unpublished_report_without_portal_header"),
        _check_contains("cross_project_report_denied_runtime_test", "tests/test_api_contracts.py", "test_runtime_report_artifact_customer_portal_denies_cross_project_actor"),
        _check_contains("evidence_asset_summary_endpoint_exists", "apps/api/geno_api/main.py", "/v1/evidence-assets/runtime/{evidence_asset_id}/summary"),
        _check_contains("evidence_asset_download_endpoint_exists", "apps/api/geno_api/main.py", "/v1/evidence-assets/runtime/{evidence_asset_id}/download"),
        _check_contains("evidence_asset_summary_hides_bucket_test", "tests/test_api_contracts.py", "test_runtime_evidence_asset_summary_hides_direct_bucket_url"),
        _check_contains("evidence_asset_download_proxy_test", "tests/test_api_contracts.py", "test_runtime_evidence_asset_download_proxies_object_store_for_internal_role"),
        _check_contains("customer_raw_evidence_denied_test", "tests/test_api_contracts.py", "test_runtime_evidence_asset_customer_portal_cannot_download_raw_asset"),
        _check_contains("cross_project_evidence_denied_test", "tests/test_api_contracts.py", "test_runtime_evidence_asset_cross_project_download_denied"),
        _check_contains("evidence_download_uses_object_store_proxy", "apps/api/geno_api/main.py", "X-GENO-Evidence-Asset-Proxy"),
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
        _check_contains(
            "connector_contract_exists",
            "packages/geno_core/geno_core/connector_contract.py",
            "class ProductionConnectorBackend",
        ),
        _check_contains(
            "connector_request_contract_exists",
            "packages/geno_core/geno_core/connector_contract.py",
            "class ConnectorRequest",
        ),
        _check_contains(
            "connector_recorded_harness_exists",
            "packages/geno_core/geno_core/connector_contract.py",
            "class RecordedConnectorHarness",
        ),
        _check_contains(
            "connector_registry_exists",
            "packages/geno_core/geno_core/connector_contract.py",
            "class ConnectorRegistry",
        ),
        _check_contains(
            "connector_contract_tests_exist",
            "tests/test_connector_contracts.py",
            "test_recorded_harness_supports_openai_perplexity_and_google_manual",
        ),
        _check_contains(
            "connector_failure_sanitized_test_exists",
            "tests/test_connector_contracts.py",
            "test_recorded_failure_is_sanitized_and_classified",
        ),
        _check_contains("openai_collector_exists", "packages/geno_core/geno_core/collectors.py", "class OpenAIWebSearchCollector"),
        _check_contains("openai_responses_endpoint", "packages/geno_core/geno_core/collectors.py", "https://api.openai.com/v1/responses"),
        _check_contains(
            "openai_connector_backend_exists",
            "packages/geno_core/geno_core/production_connectors.py",
            "class OpenAIWebSearchConnectorBackend",
        ),
        _check_contains(
            "openai_connector_success_test_exists",
            "tests/test_connector_contracts.py",
            "test_openai_connector_backend_collects_responses_api_payload",
        ),
        _check_contains(
            "openai_connector_failure_test_exists",
            "tests/test_connector_contracts.py",
            "test_openai_connector_backend_classifies_provider_auth_failure",
        ),
        _check_contains("perplexity_collector_exists", "packages/geno_core/geno_core/collectors.py", "class PerplexitySonarCollector"),
        _check_contains(
            "perplexity_connector_backend_exists",
            "packages/geno_core/geno_core/production_connectors.py",
            "class PerplexitySonarConnectorBackend",
        ),
        _check_contains(
            "perplexity_connector_success_test_exists",
            "tests/test_connector_contracts.py",
            "test_perplexity_connector_backend_collects_sonar_payload",
        ),
        _check_contains(
            "perplexity_connector_rate_limit_test_exists",
            "tests/test_connector_contracts.py",
            "test_perplexity_connector_backend_classifies_rate_limit_failure",
        ),
        _check_contains("google_manual_backfill_exists", "apps/api/geno_api/main.py", "/v1/evidence-runs/runtime/manual-backfill"),
        _check_contains(
            "google_manual_connector_backend_exists",
            "packages/geno_core/geno_core/production_connectors.py",
            "class GoogleManualBackfillConnectorBackend",
        ),
        _check_contains(
            "google_manual_connector_success_test_exists",
            "tests/test_connector_contracts.py",
            "test_google_manual_connector_backend_collects_jsonl_backfill",
        ),
        _check_contains(
            "google_manual_connector_missing_file_test_exists",
            "tests/test_connector_contracts.py",
            "test_google_manual_connector_backend_reports_missing_backfill_file",
        ),
    ]
    checks.extend(
        [
            _check_contains("connector_real_smoke_script_exists", "scripts/run_connector_real_smoke.py", "DEFAULT_MODEL = \"deepseek-v4-flash\""),
            _check_contains("connector_real_smoke_uses_deepseek_endpoint", "scripts/run_connector_real_smoke.py", "https://api.deepseek.com/chat/completions"),
            _check_contains("connector_real_smoke_reads_key_file", "scripts/run_connector_real_smoke.py", "deepseek_api_key.txt"),
            _check_contains("connector_real_smoke_redacts_raw_key", "scripts/run_connector_real_smoke.py", "report contains the raw API key"),
            _check_contains("connector_real_smoke_make_target_runs_script", "Makefile", "scripts/run_connector_real_smoke.py"),
        ]
    )
    if CONNECTOR_REAL_SMOKE_PATH.exists():
        try:
            report = json.loads(CONNECTOR_REAL_SMOKE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            checks.append(_fail("connector_real_smoke_artifact_valid_json", str(exc)))
            return checks
        status = str(report.get("status") or "")
        model = str(report.get("model") or "")
        provider = str(report.get("provider") or "")
        summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
        checks.append(
            _pass("connector_real_smoke_artifact_exists", str(CONNECTOR_REAL_SMOKE_PATH.relative_to(ROOT)))
        )
        checks.extend(_runtime_artifact_checks(CONNECTOR_REAL_SMOKE_PATH, "connector_real_smoke", report))
        checks.append(
            _pass("connector_real_smoke_artifact_passed", "status=passed")
            if status == "passed"
            else _fail("connector_real_smoke_artifact_passed", f"status={status}")
        )
        checks.append(
            _pass("connector_real_smoke_model_is_v4_flash", model)
            if model == "deepseek-v4-flash"
            else _fail("connector_real_smoke_model_is_v4_flash", model or "missing model")
        )
        checks.append(
            _pass("connector_real_smoke_provider_is_deepseek", provider)
            if provider == "deepseek"
            else _fail("connector_real_smoke_provider_is_deepseek", provider or "missing provider")
        )
        checks.append(
            _pass("connector_real_smoke_three_prompts_passed", json.dumps(summary, ensure_ascii=False))
            if int(summary.get("pass") or 0) >= 3 and int(summary.get("fail") or 0) == 0
            else _fail("connector_real_smoke_three_prompts_passed", json.dumps(summary, ensure_ascii=False))
        )
        raw_artifact = CONNECTOR_REAL_SMOKE_PATH.read_text(encoding="utf-8", errors="ignore")
        key_path = ROOT / "deepseek_api_key.txt"
        if key_path.exists():
            api_key = key_path.read_text(encoding="utf-8").strip()
            checks.append(
                _fail("connector_real_smoke_artifact_no_raw_key", "raw key leaked in artifact")
                if api_key and api_key in raw_artifact
                else _pass("connector_real_smoke_artifact_no_raw_key", "artifact does not contain raw DeepSeek key")
            )
    else:
        checks.append(_fail("connector_real_smoke_artifact_exists", str(CONNECTOR_REAL_SMOKE_PATH.relative_to(ROOT))))
    return checks


def _gate_frontend_page_click() -> list[Check]:
    checks = [
        *_gate_checklist(),
        _check_contains("frontend_page_click_script_exists", "scripts/run_frontend_page_click_smoke.py", "def run_smoke"),
        _check_contains("frontend_page_click_uses_playwright", "scripts/run_frontend_page_click_smoke.py", "sync_playwright"),
        _check_contains("frontend_page_click_checks_admin_pages", "scripts/run_frontend_page_click_smoke.py", "/development-board"),
        _check_contains("frontend_page_click_checks_launch_connectors", "scripts/run_frontend_page_click_smoke.py", "basic_tab=launch"),
        _check_contains("frontend_page_click_checks_connector_test_ui", "scripts/run_frontend_page_click_smoke.py", "deepseek-v4-flash"),
        _check_contains("frontend_page_click_checks_operation_tabs", "scripts/run_frontend_page_click_smoke.py", "operation_tab=quality"),
        _check_absent("frontend_page_click_does_not_require_retired_connector_ops_tab", "scripts/run_frontend_page_click_smoke.py", "operation_tab=connectors"),
        _check_contains("frontend_page_click_checks_customer_pages", "scripts/run_frontend_page_click_smoke.py", "/portal/traceability"),
        _check_absent("frontend_page_click_does_not_require_retired_dashboard", "scripts/run_frontend_page_click_smoke.py", '"/?tab=next"'),
        _check_contains("frontend_page_click_detects_framework_overlay", "scripts/run_frontend_page_click_smoke.py", "framework error overlay detected"),
        _check_contains("frontend_page_click_make_target_runs_script", "Makefile", "scripts/run_frontend_page_click_smoke.py"),
    ]
    if FRONTEND_PAGE_CLICK_SMOKE_PATH.exists():
        try:
            report = json.loads(FRONTEND_PAGE_CLICK_SMOKE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            checks.append(_fail("frontend_page_click_artifact_valid_json", str(exc)))
            return checks
        status = str(report.get("status") or "")
        summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
        checks.append(_pass("frontend_page_click_artifact_exists", str(FRONTEND_PAGE_CLICK_SMOKE_PATH.relative_to(ROOT))))
        checks.extend(_runtime_artifact_checks(FRONTEND_PAGE_CLICK_SMOKE_PATH, "frontend_page_click", report))
        checks.append(
            _pass("frontend_page_click_artifact_passed", "status=passed")
            if status == "passed"
            else _fail("frontend_page_click_artifact_passed", f"status={status}")
        )
        checks.append(
            _pass("frontend_page_click_has_page_coverage", json.dumps(summary, ensure_ascii=False))
            if int(summary.get("pass") or 0) >= 25 and int(summary.get("fail") or 0) == 0
            else _fail("frontend_page_click_has_page_coverage", json.dumps(summary, ensure_ascii=False))
        )
    else:
        checks.append(_fail("frontend_page_click_artifact_exists", str(FRONTEND_PAGE_CLICK_SMOKE_PATH.relative_to(ROOT))))
    return checks


def _gate_full_project_lifecycle() -> list[Check]:
    required_steps = {
        "create_project",
        "read_project",
        "update_project",
        "negative_start_before_ready",
        "project_status_action_flow",
        "project_lifecycle_pause_restore",
        "negative_invalid_project_action",
        "brand_competitor_crud",
        "connector_secret_masking",
        "connector_test_launch_config",
        "project_member_crud",
        "invitation_revoke_regenerate",
        "prompt_import_update_export",
        "negative_invalid_prompt_csv",
        "knowledge_import_search",
        "negative_invalid_knowledge_csv",
        "manual_backfill_single_csv",
        "negative_manual_backfill_missing_prompt",
        "deepseek_collection_analysis_scoring",
        "runtime_outputs_exist",
        "report_publish_download_revoke",
        "report_job_fidelity",
        "action_plan_update",
        "ops_views_audit_exports",
        "negative_cross_project_backfill",
    }
    checks = [
        *_gate_checklist(),
        _check_contains(
            "full_lifecycle_script_exists",
            "scripts/run_full_project_lifecycle_smoke.py",
            "def _run(",
        ),
        _check_contains(
            "full_lifecycle_creates_runtime_project",
            "scripts/run_full_project_lifecycle_smoke.py",
            '"/v1/projects/runtime"',
        ),
        _check_contains(
            "full_lifecycle_checks_crud",
            "scripts/run_full_project_lifecycle_smoke.py",
            "project_member_crud",
        ),
        _check_contains(
            "full_lifecycle_checks_negative_branches",
            "scripts/run_full_project_lifecycle_smoke.py",
            "negative_cross_project_backfill",
        ),
        _check_contains(
            "full_lifecycle_checks_report_lifecycle",
            "scripts/run_full_project_lifecycle_smoke.py",
            "report_publish_download_revoke",
        ),
        _check_contains(
            "full_lifecycle_make_target_runs_script",
            "Makefile",
            "scripts/run_full_project_lifecycle_smoke.py",
        ),
    ]
    if FULL_PROJECT_LIFECYCLE_SMOKE_PATH.exists():
        try:
            report = json.loads(FULL_PROJECT_LIFECYCLE_SMOKE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            checks.append(_fail("full_lifecycle_artifact_valid_json", str(exc)))
            return checks
        status = str(report.get("status") or "")
        summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
        steps = report.get("steps") if isinstance(report.get("steps"), list) else []
        passed_steps = {
            str(step.get("name"))
            for step in steps
            if isinstance(step, dict) and str(step.get("status")) == "pass"
        }
        skipped_critical_steps = sorted(
            str(step.get("name"))
            for step in steps
            if isinstance(step, dict)
            and str(step.get("name")) in {"connector_secret_masking", "deepseek_collection_analysis_scoring"}
            and isinstance(step.get("data"), dict)
            and bool(step["data"].get("skipped"))
        )
        missing_steps = sorted(required_steps - passed_steps)
        checks.append(_pass("full_lifecycle_artifact_exists", str(FULL_PROJECT_LIFECYCLE_SMOKE_PATH.relative_to(ROOT))))
        checks.extend(_runtime_artifact_checks(FULL_PROJECT_LIFECYCLE_SMOKE_PATH, "full_lifecycle", report))
        checks.append(
            _pass("full_lifecycle_artifact_passed", "status=passed")
            if status == "passed"
            else _fail("full_lifecycle_artifact_passed", f"status={status}")
        )
        checks.append(
            _pass("full_lifecycle_no_skipped_critical_steps", "critical steps executed")
            if not skipped_critical_steps
            else _fail("full_lifecycle_no_skipped_critical_steps", f"skipped={skipped_critical_steps}")
        )
        checks.append(
            _pass("full_lifecycle_step_coverage", json.dumps(summary, ensure_ascii=False))
            if not missing_steps and int(summary.get("fail") or 0) == 0
            else _fail("full_lifecycle_step_coverage", f"missing={missing_steps}; summary={json.dumps(summary, ensure_ascii=False)}")
        )
    else:
        checks.append(_fail("full_lifecycle_artifact_exists", str(FULL_PROJECT_LIFECYCLE_SMOKE_PATH.relative_to(ROOT))))
    return checks


def _gate_ops() -> list[Check]:
    return [
        *_gate_checklist(),
        _check_contains("ops_router_registered", "apps/api/geno_api/main.py", "register_ops_routes(app)"),
        _check_contains("health_endpoint_exists", "apps/api/geno_api/ops_routes.py", "@router.get(\"/health\")"),
        _check_contains("ready_endpoint_exists", "apps/api/geno_api/ops_routes.py", "@router.get(\"/ready\")"),
        _check_contains("metrics_endpoint_exists", "apps/api/geno_api/ops_routes.py", "@router.get(\"/metrics\")"),
        _check_contains("runtime_metrics_middleware_exists", "apps/api/geno_api/main.py", "runtime_metrics_middleware"),
        _check_contains("prometheus_scrapes_metrics", "infra/prometheus/prometheus.yml", "metrics_path: /metrics"),
        _check_contains("grafana_prometheus_datasource_exists", "infra/grafana/provisioning/datasources/prometheus.yml", "http://prometheus:9090"),
        _check_contains("observability_compose_profile_exists", "infra/docker-compose.yml", "profiles:\n      - observability"),
        _check_contains("runtime_alert_api_exists", "apps/api/geno_api/main.py", "/v1/runtime-alerts"),
        _check_contains("runtime_alert_notification_worker_exists", "infra/docker-compose.yml", "runtime-alert-notification-worker"),
        _check_contains("runtime_alert_escalation_worker_exists", "infra/docker-compose.yml", "runtime-alert-escalation-worker"),
        _check_contains("ops_smoke_script_exists", "scripts/verify_ops_smoke.py", "def build_ops_smoke_report"),
        _check_contains("ops_runtime_smoke_exists", "scripts/run_ops_runtime_smoke.py", "def run_ops_runtime_smoke"),
        _check_contains("ops_make_target_runs_runtime_smoke", "Makefile", "run --rm ops-runtime-smoke"),
    ]


def _gate_backup() -> list[Check]:
    return [
        *_gate_checklist(),
        _check_contains("postgres_volume_exists", "infra/docker-compose.yml", "postgres_data"),
        _check_contains("minio_volume_exists", "infra/docker-compose.yml", "minio_data"),
        _check_contains("latest_market_neutral_migration_runs", "infra/docker-compose.yml", "0024_market_neutral_defaults.sql"),
        _check_contains("backup_smoke_script_exists", "scripts/verify_backup_smoke.py", "def build_backup_smoke_report"),
        _check_contains("backup_script_checks_postgres_restore", "scripts/verify_backup_smoke.py", "postgres_runtime_restore"),
        _check_contains("backup_script_checks_object_restore", "scripts/verify_backup_smoke.py", "object_runtime_restore"),
        _check_contains("backup_make_target_runs_postgres_restore", "Makefile", "run --rm backup-postgres-smoke"),
        _check_contains("backup_make_target_runs_object_restore", "Makefile", "run --rm backup-object-smoke"),
    ]


def _gate_official_ui_contract() -> list[Check]:
    customer_module = _read(ROOT / "apps/customer-web/app/portal/[module]/page.tsx")
    customer_json_dumps = re.findall(r"JSON\.stringify|<pre>", customer_module)
    checks = [
        *_gate_checklist(),
        _check_contains("admin_operations_tab_exists", "apps/admin-web/app/projects/[project_id]/page.tsx", '{ id: "operations", label: "运营工作台" }'),
        _check_contains("admin_operations_panel_exists", "apps/admin-web/app/projects/[project_id]/page.tsx", "function OperationsPanel"),
        _check_absent("admin_connector_secret_panel_removed_from_operations", "apps/admin-web/app/projects/[project_id]/page.tsx", "ConnectorSecretPanel"),
        _check_contains("admin_launch_connector_config_wired", "apps/admin-web/app/projects/[project_id]/ProjectActions.tsx", "ConnectorConfigCard"),
        _check_contains("admin_launch_connector_test_action_wired", "apps/admin-web/app/projects/[project_id]/ProjectActions.tsx", "testConnectorAction"),
        _check_contains("admin_launch_connector_deepseek_fallback_wired", "apps/admin-web/app/projects/[project_id]/ProjectActions.tsx", "deepseek-v4-flash"),
        _check_contains("admin_google_backfill_panel_wired", "apps/admin-web/app/projects/[project_id]/page.tsx", "ManualBackfillPanel"),
        _check_contains("admin_human_review_panel_wired", "apps/admin-web/app/projects/[project_id]/page.tsx", "HumanReviewPanel"),
        _check_contains("admin_report_center_panel_wired", "apps/admin-web/app/projects/[project_id]/page.tsx", "ReportCenterPanel"),
        _check_contains("admin_action_plan_panel_wired", "apps/admin-web/app/projects/[project_id]/page.tsx", "ActionPlanPanel"),
        _check_contains("admin_brand_assets_panel_wired", "apps/admin-web/app/projects/[project_id]/page.tsx", "BrandAssetsPanel"),
        _check_contains("admin_quality_ops_panel_wired", "apps/admin-web/app/projects/[project_id]/page.tsx", "QualityOpsPanel"),
        _check_contains("admin_connector_secret_action_exists", "apps/admin-web/app/projects/[project_id]/actions.ts", "/v1/connectors/runtime/secrets"),
        _check_contains("admin_manual_backfill_action_exists", "apps/admin-web/app/projects/[project_id]/actions.ts", "/v1/evidence-runs/runtime/manual-backfill"),
        _check_contains("admin_human_review_action_exists", "apps/admin-web/app/projects/[project_id]/actions.ts", "/v1/human-reviews/runtime"),
        _check_contains("admin_report_lifecycle_action_exists", "apps/admin-web/app/projects/[project_id]/actions.ts", "/management-events"),
        _check_contains("admin_report_job_action_exists", "apps/admin-web/app/projects/[project_id]/actions.ts", "/v1/report-export-jobs/runtime"),
        _check_contains("admin_action_plan_mutation_exists", "apps/admin-web/app/projects/[project_id]/actions.ts", "/v1/action-plans/runtime/"),
        _check_contains("admin_content_draft_review_action_exists", "apps/admin-web/app/projects/[project_id]/actions.ts", "/v1/knowledge/content-drafts/runtime/"),
        _check_contains("admin_distribution_backfill_action_exists", "apps/admin-web/app/projects/[project_id]/actions.ts", "/v1/manual-distribution-records/runtime/"),
        _check_contains("admin_content_review_form_exists", "apps/admin-web/app/projects/[project_id]/ProjectActions.tsx", "ContentDraftReviewForm"),
        _check_contains("admin_distribution_backfill_form_exists", "apps/admin-web/app/projects/[project_id]/ProjectActions.tsx", "ManualDistributionBackfillForm"),
        _check_contains("api_content_draft_review_endpoint_exists", "apps/api/geno_api/main.py", "/v1/knowledge/content-drafts/runtime/{content_draft_id}/review"),
        _check_contains("api_distribution_backfill_endpoint_exists", "apps/api/geno_api/main.py", "/v1/manual-distribution-records/runtime/{distribution_record_id}/backfill"),
        _check_contains("api_content_draft_review_test_exists", "tests/test_api_contracts.py", "test_runtime_content_draft_review_endpoint_passes_payload"),
        _check_contains("api_distribution_backfill_test_exists", "tests/test_api_contracts.py", "test_runtime_manual_distribution_backfill_endpoint_passes_payload"),
        _check_contains("customer_portal_key_value_grid_exists", "apps/customer-web/app/portal/[module]/page.tsx", "function KeyValueGrid"),
        _check_contains("customer_portal_record_list_exists", "apps/customer-web/app/portal/[module]/page.tsx", "function RecordList"),
        _check_contains("customer_portal_structured_traceability_exists", "apps/customer-web/app/portal/[module]/page.tsx", "Traceability Bundle"),
        _check_contains("customer_portal_structured_action_summary_exists", "apps/customer-web/app/portal/[module]/page.tsx", "行动建议"),
        _check_contains("customer_portal_handoff_no_pilot_copy", "apps/customer-web/app/portal/[module]/page.tsx", "正式交付包准备状态"),
        _check_contains("customer_portal_structured_css_exists", "apps/customer-web/app/globals.css", ".kvGrid"),
    ]
    if customer_json_dumps:
        checks.append(_fail("customer_portal_has_no_json_dump", "Customer portal module still contains JSON.stringify or <pre>"))
    else:
        checks.append(_pass("customer_portal_has_no_json_dump", "Customer portal module renders structured components"))
    project_actions = _read(ROOT / "apps/admin-web/app/projects/[project_id]/ProjectActions.tsx")
    if "后端尚未提供内容审核/Distribution URL 回填 mutation" in project_actions:
        checks.append(_fail("admin_content_workbench_no_missing_mutation_copy", "Content workbench still claims missing mutation"))
    else:
        checks.append(_pass("admin_content_workbench_no_missing_mutation_copy", "Content workbench exposes explicit review and distribution forms"))
    return checks


def _gate_development_board_truth() -> list[Check]:
    return [
        *_gate_checklist(),
        _check_contains("development_board_reads_commit_column", "apps/admin-web/app/development-board/page.tsx", "commit: string"),
        _check_contains("development_board_has_production_ready_flag", "apps/admin-web/app/development-board/page.tsx", "productionReady: boolean"),
        _check_absent("development_board_commit_is_not_completion_blocker", "apps/admin-web/app/development-board/page.tsx", "commit hash 未填写"),
        _check_contains("development_board_completion_uses_production_ready", "apps/admin-web/app/development-board/page.tsx", "checklist.totals.productionReady"),
        _check_contains("development_board_shows_blockers", "apps/admin-web/app/development-board/page.tsx", "developmentBlockers"),
        _check_contains("development_board_warning_metric_exists", "apps/admin-web/app/development-board/page.tsx", "待补正式证据"),
        _check_contains("development_board_absorbs_retired_dashboard", "apps/admin-web/app/development-board/page.tsx", "18006 独立 Dashboard 不再作为默认入口"),
        _check_contains("development_board_shows_gate_evidence", "apps/admin-web/app/development-board/page.tsx", "make production-v1-final-gate"),
        _check_contains("development_board_shows_artifacts", "apps/admin-web/app/development-board/page.tsx", "tmp/frontend-page-click-smoke/latest.json"),
        _check_contains(
            "development_board_shows_knowledge_lifecycle_artifact",
            "apps/admin-web/app/development-board/page.tsx",
            "tmp/frontend-knowledge-lifecycle-smoke/latest.json",
        ),
        _check_contains(
            "development_board_shows_knowledge_pipeline_artifact",
            "apps/admin-web/app/development-board/page.tsx",
            "tmp/geo-production-full-pipeline-smoke/latest.json",
        ),
        _check_contains(
            "development_board_shows_current_documents",
            "apps/admin-web/app/development-board/page.tsx",
            "GEO-Production-v1正式可用性复查报告-2026-07-05.md",
        ),
        _check_contains(
            "development_board_shows_current_progress",
            "apps/admin-web/app/development-board/page.tsx",
            "GEO-当前项目进度汇报-2026-07-10.md",
        ),
        _check_contains(
            "development_board_shows_knowledge_plan",
            "apps/admin-web/app/development-board/page.tsx",
            "GEO-知识库解析与生成工作流规划-2026-07-08.md",
        ),
        _check_contains("development_board_production_status_css_exists", "apps/admin-web/app/globals.css", "statusPill-production"),
        _check_contains("development_board_blocker_css_exists", "apps/admin-web/app/globals.css", ".developmentBlockers"),
        _check_contains("development_board_doc_panel_css_exists", "apps/admin-web/app/globals.css", ".developmentDocPanel"),
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
    )
    return [
        *_gate_checklist(),
        _check_contains("runtime_e2e_script_exists", "scripts/verify_runtime_e2e.py", "def main()"),
        _check_contains("action_plan_p0_action_types_exist", "packages/geno_core/geno_core/action_plan.py", "ACTION_PLAN_P0_ACTION_TYPES"),
        _check_contains("action_plan_p0_generates_private_actions_test", "tests/test_core_contracts.py", "test_action_plan_p0_minimal_generates_three_deterministic_private_actions"),
        _check_contains("action_model_customer_visible_default", "packages/geno_core/geno_core/models.py", "customer_visible: bool = False"),
        _check_contains("action_model_score_contribution_links", "packages/geno_core/geno_core/models.py", "score_contribution_ids: tuple[str, ...] = ()"),
        _check_contains("action_contract_migration_exists", "infra/db/migrations/up/0020_action_recommendation_contract.sql", "ADD COLUMN IF NOT EXISTS action_type"),
        _check_contains("action_repository_persists_customer_visibility", "packages/geno_core/geno_core/repository.py", "customer_visible"),
        _check_contains("retest_p0_delta_test_exists", "tests/test_core_contracts.py", "test_retest_p0_minimal_compares_before_after_delta_for_same_prompt_set"),
        _check_contains("retest_comparison_audit_exists", "packages/geno_core/geno_core/action_plan.py", "retest_comparison_created"),
        *[_check_checklist_status(item, {"Done", "Verifying"}) for item in required],
        *_gate_full_project_lifecycle(),
    ]


def _gate_enablement_e2e() -> list[Check]:
    return [
        *_gate_checklist(),
        _check_contains("knowledge_module_exists", "packages/geno_core/geno_core/knowledge.py", "build_localized_knowledge_facts"),
        _check_contains("knowledge_approved_status_contract_exists", "packages/geno_core/geno_core/knowledge.py", "KNOWLEDGE_FACT_APPROVED_STATUS"),
        _check_contains("knowledge_search_filters_approved_only", "packages/geno_core/geno_core/knowledge.py", "fact.status != KNOWLEDGE_FACT_APPROVED_STATUS"),
        _check_contains("runtime_knowledge_search_filters_approved_only", "packages/geno_core/geno_core/repository.py", "KNOWLEDGE_FACT_APPROVED_STATUS"),
        _check_contains("runtime_knowledge_search_api_exists", "apps/api/geno_api/main.py", "def runtime_knowledge_fact_search"),
        _check_contains("content_drafts_model_exists", "packages/geno_core/geno_core/models.py", "class ContentDraft"),
        _check_contains("content_review_pending_contract_exists", "packages/geno_core/geno_core/knowledge.py", "CONTENT_REVIEW_PENDING_STATUS"),
        _check_contains("runtime_content_engines_api_exists", "apps/api/geno_api/main.py", "def runtime_content_engines"),
        _check_contains("runtime_content_export_api_exists", "apps/api/geno_api/main.py", "def runtime_content_engines_export_csv"),
        _check_contains("distribution_model_exists", "packages/geno_core/geno_core/models.py", "class ManualDistributionRecord"),
        _check_contains(
            "manual_distribution_backfill_contract_exists",
            "packages/geno_core/geno_core/knowledge.py",
            "backfill_manual_distribution_record",
        ),
        _check_contains(
            "manual_distribution_no_auto_publish_contract_exists",
            "packages/geno_core/geno_core/knowledge.py",
            "no automatic publishing in Production v1",
        ),
        _check_contains(
            "enablement_v1_contract_test_exists",
            "tests/test_core_contracts.py",
            "test_enablement_v1_uses_only_approved_facts_and_manual_distribution_backfill",
        ),
        _check_contains(
            "runtime_content_export_api_test_exists",
            "tests/test_api_contracts.py",
            "test_runtime_content_engines_export_endpoint_returns_csv_with_hash_headers",
        ),
        _check_contains(
            "runtime_knowledge_search_api_test_exists",
            "tests/test_api_contracts.py",
            "test_runtime_knowledge_fact_search_endpoint_passes_query",
        ),
        _check_contains("knowledge_pipeline_repository_exists", "packages/geno_core/geno_core/knowledge_pipeline.py", "class KnowledgePipelineRepository"),
        _check_contains("knowledge_pipeline_api_exists", "apps/api/geno_api/main.py", "/v1/knowledge/pipeline-runs/runtime"),
        _check_contains("knowledge_pipeline_admin_panel_exists", "apps/admin-web/app/projects/[project_id]/ProjectActions.tsx", "KnowledgePipelineCreateForm"),
        _check_contains("knowledge_pipeline_contract_tests_exist", "tests/test_knowledge_pipeline_contracts.py", "KnowledgePipelineContractTest"),
        _check_contains("knowledge_pipeline_live_e2e_exists", "scripts/run_knowledge_pipeline_live_e2e.py", "def main"),
    ]


def _gate_knowledge_application() -> list[Check]:
    return [
        *_gate_checklist(),
        _check_contains("knowledge_pipeline_schema_exists", "infra/db/migrations/up/0023_knowledge_pipeline_orchestration.sql", "CREATE TABLE IF NOT EXISTS knowledge_pipeline_runs"),
        _check_contains("knowledge_pipeline_stages_exist", "infra/db/migrations/up/0023_knowledge_pipeline_orchestration.sql", "CREATE TABLE IF NOT EXISTS knowledge_pipeline_stages"),
        _check_contains("knowledge_trace_refs_exist", "infra/db/migrations/up/0023_knowledge_pipeline_orchestration.sql", "CREATE TABLE IF NOT EXISTS knowledge_trace_refs"),
        _check_contains("knowledge_quality_gates_exist", "infra/db/migrations/up/0023_knowledge_pipeline_orchestration.sql", "CREATE TABLE IF NOT EXISTS knowledge_quality_gate_runs"),
        _check_contains("knowledge_active_fact_migration_exists", "infra/db/migrations/up/0027_knowledge_pipeline_consolidation.sql", "status = 'active'"),
        _check_contains("knowledge_template_seed_exists", "infra/db/migrations/up/0027_knowledge_pipeline_consolidation.sql", "citation_gap_prompt_v1"),
        _check_contains("knowledge_pipeline_migrations_run", "infra/docker-compose.yml", "0027_knowledge_pipeline_consolidation.sql"),
        _check_contains("knowledge_url_private_network_guard_exists", "packages/geno_core/geno_core/knowledge_application.py", "blocked_private_network"),
        _check_contains("knowledge_adapter_contract_exists", "scripts/run_knowledge_component.py", "geo-parser-adapter-v1"),
        _check_contains("knowledge_docling_adapter_exists", "scripts/run_knowledge_component.py", "def _parse_docling"),
        _check_contains("knowledge_mineru_adapter_exists", "scripts/run_knowledge_component.py", "def _parse_mineru"),
        _check_contains("knowledge_crawl4ai_adapter_exists", "scripts/run_knowledge_component.py", "AsyncWebCrawler"),
        _check_contains("knowledge_bge_adapter_exists", "scripts/run_knowledge_component.py", "SentenceTransformer"),
        _check_contains("knowledge_deepseek_default_model_exists", "packages/geno_core/geno_core/knowledge_application.py", "deepseek-v4-flash"),
        _check_contains("knowledge_deepseek_extract_adapter_exists", "packages/geno_core/geno_core/knowledge_application.py", "def deepseek_extract_knowledge_facts"),
        _check_contains("knowledge_deepseek_generate_adapter_exists", "packages/geno_core/geno_core/knowledge_application.py", "def deepseek_generate_knowledge_application"),
        _check_contains("knowledge_deepseek_key_file_fallback_exists", "packages/geno_core/geno_core/knowledge_application.py", "deepseek_api_key.txt"),
        _check_contains("knowledge_pipeline_repository_exists", "packages/geno_core/geno_core/knowledge_pipeline.py", "class KnowledgePipelineRepository"),
        _check_contains("knowledge_pipeline_idempotent_start_exists", "packages/geno_core/geno_core/knowledge_pipeline.py", "create a versioned rerun"),
        _check_contains("knowledge_partial_thresholds_exist", "workers/knowledge_worker/run_knowledge_pipeline.py", "EMBEDDING_MIN_SUCCESS_RATIO"),
        _check_contains("knowledge_worker_exists", "workers/knowledge_worker/run_knowledge_pipeline.py", "def run_once"),
        _check_contains("knowledge_pipeline_api_create_exists", "apps/api/geno_api/main.py", "/v1/knowledge/pipeline-runs/runtime"),
        _check_contains("knowledge_import_file_api_exists", "apps/api/geno_api/main.py", "/v1/knowledge/import-jobs/runtime/{import_job_id}/files"),
        _check_contains("knowledge_quality_api_exists", "apps/api/geno_api/main.py", "/v1/knowledge/quality-gate-runs/runtime"),
        _check_contains("knowledge_prompt_api_exists", "apps/api/geno_api/main.py", "/v1/knowledge/prompt-generation-jobs/runtime"),
        _check_contains("knowledge_content_api_exists", "apps/api/geno_api/main.py", "/v1/knowledge/content-generation-jobs/runtime"),
        _check_contains("admin_knowledge_import_wired", "apps/admin-web/app/projects/[project_id]/ProjectActions.tsx", "KnowledgePipelineCreateForm"),
        _check_contains("admin_knowledge_processing_wired", "apps/admin-web/app/projects/[project_id]/page.tsx", "KnowledgeProcessingPanel"),
        _check_contains("admin_knowledge_chunk_trace_wired", "apps/admin-web/app/projects/[project_id]/page.tsx", "KnowledgeTracePanel"),
        _check_absent("admin_does_not_call_legacy_knowledge_application", "apps/admin-web/app/projects/[project_id]/page.tsx", "/v1/knowledge-applications/runtime"),
        _check_contains("knowledge_pipeline_contract_tests_exist", "tests/test_knowledge_pipeline_contracts.py", "KnowledgePipelineContractTest"),
        _check_contains("knowledge_pipeline_live_e2e_exists", "scripts/run_knowledge_pipeline_live_e2e.py", "full_rebuild"),
        _check_contains("knowledge_full_pipeline_smoke_exists", "scripts/run_geo_production_full_pipeline_smoke.py", "real import-to-approved-Prompt/content pipeline pass"),
        _check_contains("knowledge_heavy_components_smoke_exists", "scripts/run_knowledge_heavy_components_smoke.py", "sentence_transformers_bge_m3"),
        _check_contains("promptfoo_knowledge_eval_script_exists", "scripts/run_promptfoo_knowledge_eval.py", "promptfoo-compatible-local-eval"),
    ]


def _gate_promptfoo_knowledge_eval() -> list[Check]:
    checks = [
        *_gate_checklist(),
        _check_contains("promptfoo_knowledge_eval_script_exists", "scripts/run_promptfoo_knowledge_eval.py", "def build_eval_report"),
        _check_contains("promptfoo_knowledge_eval_uses_v4_flash", "scripts/run_promptfoo_knowledge_eval.py", "deepseek-v4-flash"),
        _check_contains("promptfoo_knowledge_eval_checks_approved_fact", "scripts/run_promptfoo_knowledge_eval.py", "uses_approved_fact"),
        _check_contains("promptfoo_knowledge_eval_checks_pending_fact_exclusion", "scripts/run_promptfoo_knowledge_eval.py", "excludes_pending_review_fact"),
        _check_contains("promptfoo_knowledge_eval_make_target_runs_script", "Makefile", "scripts/run_promptfoo_knowledge_eval.py"),
    ]
    if PROMPTFOO_KNOWLEDGE_EVAL_PATH.exists():
        try:
            report = json.loads(PROMPTFOO_KNOWLEDGE_EVAL_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            checks.append(_fail("promptfoo_knowledge_eval_artifact_valid_json", str(exc)))
            return checks
        status = str(report.get("status") or "")
        model = str(report.get("model") or "")
        summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
        checks.append(_pass("promptfoo_knowledge_eval_artifact_exists", str(PROMPTFOO_KNOWLEDGE_EVAL_PATH.relative_to(ROOT))))
        checks.extend(_runtime_artifact_checks(PROMPTFOO_KNOWLEDGE_EVAL_PATH, "promptfoo_knowledge_eval", report))
        checks.append(
            _pass("promptfoo_knowledge_eval_artifact_passed", "status=passed")
            if status == "passed"
            else _fail("promptfoo_knowledge_eval_artifact_passed", f"status={status}")
        )
        checks.append(
            _pass("promptfoo_knowledge_eval_model_is_v4_flash", model)
            if model == "deepseek-v4-flash"
            else _fail("promptfoo_knowledge_eval_model_is_v4_flash", model or "missing model")
        )
        checks.append(
            _pass("promptfoo_knowledge_eval_all_checks_passed", json.dumps(summary, ensure_ascii=False))
            if int(summary.get("pass") or 0) >= 3 and int(summary.get("fail") or 0) == 0
            else _fail("promptfoo_knowledge_eval_all_checks_passed", json.dumps(summary, ensure_ascii=False))
        )
    else:
        checks.append(_fail("promptfoo_knowledge_eval_artifact_exists", str(PROMPTFOO_KNOWLEDGE_EVAL_PATH.relative_to(ROOT))))
    return checks


def _gate_frontend_knowledge_click() -> list[Check]:
    checks = [
        *_gate_checklist(),
        _check_contains(
            "frontend_knowledge_lifecycle_script_exists",
            "scripts/run_frontend_knowledge_lifecycle_smoke.py",
            "def run(args: argparse.Namespace)",
        ),
        _check_contains(
            "frontend_knowledge_lifecycle_uses_playwright",
            "scripts/run_frontend_knowledge_lifecycle_smoke.py",
            "sync_playwright",
        ),
        _check_contains(
            "frontend_knowledge_lifecycle_runs_real_worker",
            "scripts/run_frontend_knowledge_lifecycle_smoke.py",
            "run_knowledge_pipeline.py",
        ),
        _check_contains(
            "frontend_knowledge_lifecycle_make_target",
            "Makefile",
            "scripts/run_frontend_knowledge_lifecycle_smoke.py",
        ),
        _check_contains("frontend_click_covers_project_detail", "scripts/run_frontend_page_click_smoke.py", "/projects/"),
        _check_contains("admin_knowledge_panel_visible", "apps/admin-web/app/projects/[project_id]/ProjectActions.tsx", "知识库看板"),
        _check_contains("admin_knowledge_import_visible", "apps/admin-web/app/projects/[project_id]/ProjectActions.tsx", "创建完整知识库 Pipeline"),
        _check_contains("admin_knowledge_crawl_visible", "apps/admin-web/app/projects/[project_id]/ProjectActions.tsx", "站点深度抓取"),
        _check_contains("admin_knowledge_extract_visible", "apps/admin-web/app/projects/[project_id]/ProjectActions.tsx", "开始事实抽取"),
        _check_contains("admin_knowledge_generate_visible", "apps/admin-web/app/projects/[project_id]/ProjectActions.tsx", "生成提问 Prompt 候选"),
        _check_contains("admin_prompt_candidate_review_visible", "apps/admin-web/app/projects/[project_id]/ProjectActions.tsx", "审核候选 Prompt"),
        _check_contains("admin_prompt_candidate_import_visible", "apps/admin-web/app/projects/[project_id]/ProjectActions.tsx", "导入已批准 Prompt"),
        _check_contains("admin_knowledge_css_exists", "apps/admin-web/app/globals.css", ".knowledgePanel"),
        _check_contains(
            "admin_knowledge_web_contract_test_exists",
            "tests/test_web_console_contracts.py",
            "test_admin_project_page_surfaces_knowledge_pipeline_workbench",
        ),
    ]
    if not FRONTEND_PAGE_CLICK_SMOKE_PATH.exists():
        checks.append(_fail("frontend_knowledge_click_artifact_exists", str(FRONTEND_PAGE_CLICK_SMOKE_PATH.relative_to(ROOT))))
        return checks
    try:
        report = json.loads(FRONTEND_PAGE_CLICK_SMOKE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        checks.append(_fail("frontend_knowledge_click_artifact_valid_json", str(exc)))
        return checks
    checks.extend(_runtime_artifact_checks(FRONTEND_PAGE_CLICK_SMOKE_PATH, "frontend_knowledge_click", report))
    page_checks = report.get("checks") if isinstance(report.get("checks"), list) else []
    passed_routes = {
        str(item.get("route"))
        for item in page_checks
        if isinstance(item, dict)
        and item.get("status") == "pass"
        and ("tab=knowledge" in str(item.get("route")) or "tab=prompts" in str(item.get("route")))
    }
    checks.append(
        _pass("frontend_knowledge_click_route_coverage", f"routes={len(passed_routes)}")
        if len(passed_routes) >= 9
        else _fail("frontend_knowledge_click_route_coverage", f"routes={sorted(passed_routes)}")
    )
    if not FRONTEND_KNOWLEDGE_LIFECYCLE_SMOKE_PATH.exists():
        checks.append(
            _fail(
                "frontend_knowledge_lifecycle_artifact_exists",
                str(FRONTEND_KNOWLEDGE_LIFECYCLE_SMOKE_PATH.relative_to(ROOT)),
            )
        )
        return checks
    try:
        lifecycle = json.loads(FRONTEND_KNOWLEDGE_LIFECYCLE_SMOKE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        checks.append(_fail("frontend_knowledge_lifecycle_artifact_valid_json", str(exc)))
        return checks
    checks.append(
        _pass(
            "frontend_knowledge_lifecycle_artifact_exists",
            str(FRONTEND_KNOWLEDGE_LIFECYCLE_SMOKE_PATH.relative_to(ROOT)),
        )
    )
    checks.extend(
        _runtime_artifact_checks(
            FRONTEND_KNOWLEDGE_LIFECYCLE_SMOKE_PATH,
            "frontend_knowledge_lifecycle",
            lifecycle,
        )
    )
    status = str(lifecycle.get("status") or "")
    checks.append(
        _pass("frontend_knowledge_lifecycle_artifact_passed", "status=passed")
        if status == "passed"
        else _fail("frontend_knowledge_lifecycle_artifact_passed", f"status={status}")
    )
    required_steps = {
        "frontend_import_precheck_and_start",
        "frontend_view_pipeline_processing",
        "frontend_fact_candidate_review",
        "frontend_prompt_generation",
        "frontend_prompt_review_and_import",
        "frontend_content_generation",
        "frontend_content_review_and_export",
        "frontend_knowledge_search",
    }
    passed_steps = {
        str(item.get("name"))
        for item in lifecycle.get("steps") or []
        if isinstance(item, dict) and item.get("status") == "pass"
    }
    missing_steps = sorted(required_steps - passed_steps)
    checks.append(
        _pass("frontend_knowledge_lifecycle_step_coverage", f"steps={len(passed_steps)}")
        if not missing_steps
        else _fail("frontend_knowledge_lifecycle_step_coverage", f"missing={missing_steps}")
    )
    return checks


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
    "knowledge-application-smoke": _gate_knowledge_application,
    "knowledge-pipeline-smoke": _gate_knowledge_application,
    "promptfoo-knowledge-eval": _gate_promptfoo_knowledge_eval,
    "frontend-knowledge-click-smoke": _gate_frontend_knowledge_click,
    "no-fixture-production-smoke": _gate_no_fixture_production,
    "no-secret-leak-smoke": _gate_no_secret_leak,
    "report-traceability-smoke": _gate_report_traceability,
    "customer-access-negative-smoke": _gate_customer_access_negative,
    "connector-real-smoke": _gate_connector_real,
    "frontend-page-click-smoke": _gate_frontend_page_click,
    "full-project-lifecycle-smoke": _gate_full_project_lifecycle,
    "official-ui-contract-smoke": _gate_official_ui_contract,
    "development-board-truth-smoke": _gate_development_board_truth,
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
