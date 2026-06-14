from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - local CI image currently provides PyYAML.
    yaml = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DATABASE_URL = "postgresql://geno_runtime_app:geno_runtime_app@postgres:5432/geno"


@unittest.skipIf(yaml is None, "PyYAML is required for compose/config contract checks")
class InfraContractsTest(unittest.TestCase):
    def _compose_config(self, *profiles: str) -> dict[str, object]:
        command = ["docker", "compose", "-f", "infra/docker-compose.yml"]
        for profile in profiles:
            command.extend(["--profile", profile])
        command.append("config")
        result = subprocess.run(
            command,
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return yaml.safe_load(result.stdout)

    def test_litellm_profile_wires_proxy_and_judge_worker(self) -> None:
        config = self._compose_config("llm-gateway")
        services = config["services"]
        litellm = services["litellm"]
        worker = services["collector-worker-litellm"]

        self.assertEqual(litellm["image"], "docker.litellm.ai/berriai/litellm:main-latest")
        self.assertIn("--config", litellm["command"])
        self.assertIn("/app/config.yaml", litellm["command"])
        self.assertIn("--port", litellm["command"])
        self.assertIn("4000", litellm["command"])
        self.assertEqual(litellm["environment"]["LITELLM_MASTER_KEY"], "sk-geno-local")
        self.assertIn("4000", {str(port["published"]) for port in litellm["ports"]})
        self.assertTrue(
            any(volume["target"] == "/app/config.yaml" and volume["read_only"] for volume in litellm["volumes"])
        )

        self.assertEqual(worker["environment"]["LITELLM_BASE_URL"], "http://litellm:4000")
        self.assertEqual(worker["environment"]["LITELLM_API_KEY"], "sk-geno-local")
        self.assertNotIn("GENO_RUNTIME_DB_POOL_ENABLED", worker["environment"])
        self.assertIn("--judge-gateway", worker["command"])
        self.assertIn("litellm", worker["command"])
        self.assertIn("--judge-model", worker["command"])
        self.assertIn("geno-gpt-4.1-mini", worker["command"])
        self.assertIn("litellm", worker["depends_on"])

    def test_runtime_e2e_profile_wires_verifier_to_postgres_and_minio(self) -> None:
        config = self._compose_config("e2e")
        services = config["services"]
        verifier = services["runtime-e2e"]

        self.assertEqual(verifier["build"]["dockerfile"], "apps/api/Dockerfile")
        self.assertIn("python", verifier["command"])
        self.assertIn("scripts/verify_runtime_e2e.py", verifier["command"])
        self.assertEqual(verifier["environment"]["DATABASE_URL"], RUNTIME_DATABASE_URL)
        self.assertNotIn("GENO_RUNTIME_DB_POOL_ENABLED", verifier["environment"])
        self.assertEqual(verifier["environment"]["OBJECT_STORE_ENDPOINT"], "http://minio:9000")
        self.assertEqual(verifier["environment"]["OBJECT_STORE_BUCKET"], "geno-reports")
        self.assertEqual(verifier["environment"]["OBJECT_STORE_ACCESS_KEY"], "minio")
        self.assertEqual(verifier["environment"]["OBJECT_STORE_SECRET_KEY"], "minio123")
        self.assertIn("postgres", verifier["depends_on"])
        self.assertIn("minio", verifier["depends_on"])

    def test_db_smoke_profile_wires_verifier_to_admin_and_runtime_postgres_roles(self) -> None:
        config = self._compose_config("db-smoke")
        services = config["services"]
        verifier = services["db-smoke"]

        self.assertEqual(verifier["build"]["dockerfile"], "apps/api/Dockerfile")
        self.assertIn("python", verifier["command"])
        self.assertIn("scripts/verify_db_smoke.py", verifier["command"])
        self.assertEqual(verifier["environment"]["DATABASE_URL"], "postgresql://geno:geno@postgres:5432/geno")
        self.assertEqual(verifier["environment"]["RUNTIME_DATABASE_URL"], RUNTIME_DATABASE_URL)
        self.assertNotIn("OBJECT_STORE_ENDPOINT", verifier["environment"])
        self.assertIn("postgres", verifier["depends_on"])
        self.assertNotIn("minio", verifier["depends_on"])

    def test_scheduler_profile_wires_browser_fidelity_scheduler(self) -> None:
        config = self._compose_config("scheduler")
        services = config["services"]
        scheduler = services["browser-fidelity-scheduler"]
        alert_worker = services["runtime-alert-notification-worker"]
        escalation_worker = services["runtime-alert-escalation-worker"]
        alias_assignment_worker = services["entity-alias-assignment-notification-worker"]
        alias_assignment_escalation_worker = services["entity-alias-assignment-escalation-worker"]
        alias_assignment_reassignment_worker = services["entity-alias-assignment-reassignment-worker"]

        self.assertEqual(scheduler["build"]["dockerfile"], "apps/api/Dockerfile")
        self.assertEqual(scheduler["command"], ["python", "scripts/run_browser_fidelity_scheduler.py"])
        self.assertEqual(scheduler["environment"]["DATABASE_URL"], RUNTIME_DATABASE_URL)
        self.assertNotIn("GENO_RUNTIME_DB_POOL_ENABLED", scheduler["environment"])
        self.assertEqual(scheduler["environment"]["OBJECT_STORE_ENDPOINT"], "http://minio:9000")
        self.assertEqual(scheduler["environment"]["GENO_BROWSER_FIDELITY_EXECUTE"], "0")
        self.assertEqual(scheduler["environment"]["GENO_BROWSER_FIDELITY_PERSIST_PLAN"], "1")
        self.assertIn("postgres", scheduler["depends_on"])
        self.assertIn("minio", scheduler["depends_on"])

        self.assertEqual(alert_worker["build"]["dockerfile"], "apps/api/Dockerfile")
        self.assertEqual(alert_worker["environment"]["DATABASE_URL"], RUNTIME_DATABASE_URL)
        self.assertEqual(alert_worker["environment"]["GENO_RUNTIME_ALERT_MARKET_CODE"], "AU")
        self.assertNotIn("GENO_RUNTIME_DB_POOL_ENABLED", alert_worker["environment"])
        self.assertIn("workers/notification_worker/run_runtime_alert_notifications.py", alert_worker["command"])
        self.assertIn("--market-code", alert_worker["command"])
        self.assertIn("AU", alert_worker["command"])
        self.assertIn("--max-projects", alert_worker["command"])
        self.assertIn("50", alert_worker["command"])
        self.assertIn("postgres", alert_worker["depends_on"])

        self.assertEqual(escalation_worker["build"]["dockerfile"], "apps/api/Dockerfile")
        self.assertEqual(escalation_worker["environment"]["DATABASE_URL"], RUNTIME_DATABASE_URL)
        self.assertEqual(escalation_worker["environment"]["GENO_RUNTIME_ALERT_MARKET_CODE"], "AU")
        self.assertEqual(
            escalation_worker["environment"]["GENO_RUNTIME_ALERT_ESCALATION_THRESHOLDS"],
            "critical=4,high=24",
        )
        self.assertNotIn("GENO_RUNTIME_DB_POOL_ENABLED", escalation_worker["environment"])
        self.assertIn("workers/notification_worker/run_runtime_alert_escalations.py", escalation_worker["command"])
        self.assertIn("--severity-threshold-hours", escalation_worker["command"])
        self.assertIn("critical=4,high=24", escalation_worker["command"])
        self.assertIn("postgres", escalation_worker["depends_on"])

        self.assertEqual(alias_assignment_worker["build"]["dockerfile"], "apps/api/Dockerfile")
        self.assertEqual(alias_assignment_worker["environment"]["DATABASE_URL"], RUNTIME_DATABASE_URL)
        self.assertEqual(alias_assignment_worker["environment"]["GENO_ENTITY_ALIAS_ASSIGNMENT_MARKET_CODE"], "AU")
        self.assertNotIn("GENO_RUNTIME_DB_POOL_ENABLED", alias_assignment_worker["environment"])
        self.assertIn("workers/notification_worker/run_entity_alias_assignment_notifications.py", alias_assignment_worker["command"])
        self.assertIn("--market-code", alias_assignment_worker["command"])
        self.assertIn("AU", alias_assignment_worker["command"])
        self.assertIn("--max-projects", alias_assignment_worker["command"])
        self.assertIn("50", alias_assignment_worker["command"])
        self.assertIn("postgres", alias_assignment_worker["depends_on"])

        self.assertEqual(alias_assignment_escalation_worker["build"]["dockerfile"], "apps/api/Dockerfile")
        self.assertEqual(alias_assignment_escalation_worker["environment"]["DATABASE_URL"], RUNTIME_DATABASE_URL)
        self.assertEqual(
            alias_assignment_escalation_worker["environment"]["GENO_ENTITY_ALIAS_ASSIGNMENT_MARKET_CODE"],
            "AU",
        )
        self.assertNotIn("GENO_RUNTIME_DB_POOL_ENABLED", alias_assignment_escalation_worker["environment"])
        self.assertIn(
            "workers/notification_worker/run_entity_alias_assignment_escalations.py",
            alias_assignment_escalation_worker["command"],
        )
        self.assertIn("--market-code", alias_assignment_escalation_worker["command"])
        self.assertIn("AU", alias_assignment_escalation_worker["command"])
        self.assertIn("--max-projects", alias_assignment_escalation_worker["command"])
        self.assertIn("50", alias_assignment_escalation_worker["command"])
        self.assertIn("postgres", alias_assignment_escalation_worker["depends_on"])

        self.assertEqual(alias_assignment_reassignment_worker["build"]["dockerfile"], "apps/api/Dockerfile")
        self.assertEqual(alias_assignment_reassignment_worker["environment"]["DATABASE_URL"], RUNTIME_DATABASE_URL)
        self.assertEqual(
            alias_assignment_reassignment_worker["environment"]["GENO_ENTITY_ALIAS_ASSIGNMENT_MARKET_CODE"],
            "AU",
        )
        self.assertEqual(
            alias_assignment_reassignment_worker["environment"]["GENO_ENTITY_ALIAS_ASSIGNMENT_REASSIGN_TO"],
            "runtime-console",
        )
        self.assertNotIn("GENO_RUNTIME_DB_POOL_ENABLED", alias_assignment_reassignment_worker["environment"])
        self.assertIn(
            "workers/notification_worker/run_entity_alias_assignment_reassignments.py",
            alias_assignment_reassignment_worker["command"],
        )
        self.assertIn("--assigned-to", alias_assignment_reassignment_worker["command"])
        self.assertIn("runtime-console", alias_assignment_reassignment_worker["command"])
        self.assertIn("--from-assignment-status", alias_assignment_reassignment_worker["command"])
        self.assertIn("escalated", alias_assignment_reassignment_worker["command"])
        self.assertIn("postgres", alias_assignment_reassignment_worker["depends_on"])

    def test_observability_profile_wires_prometheus_and_grafana(self) -> None:
        config = self._compose_config("observability")
        services = config["services"]
        prometheus = services["prometheus"]
        grafana = services["grafana"]

        self.assertEqual(prometheus["image"], "prom/prometheus:v3.0.1")
        self.assertIn("--config.file=/etc/prometheus/prometheus.yml", prometheus["command"])
        self.assertIn("9090", {str(port["published"]) for port in prometheus["ports"]})
        self.assertTrue(
            any(volume["target"] == "/etc/prometheus/prometheus.yml" and volume["read_only"] for volume in prometheus["volumes"])
        )
        self.assertIn("api", prometheus["depends_on"])

        self.assertEqual(grafana["image"], "grafana/grafana:11.4.0")
        self.assertEqual(grafana["environment"]["GF_SECURITY_ADMIN_USER"], "admin")
        self.assertEqual(grafana["environment"]["GF_SECURITY_ADMIN_PASSWORD"], "admin")
        self.assertIn("3001", {str(port["published"]) for port in grafana["ports"]})
        self.assertTrue(
            any(volume["target"] == "/etc/grafana/provisioning" and volume["read_only"] for volume in grafana["volumes"])
        )
        self.assertIn("prometheus", grafana["depends_on"])

    def test_observability_config_scrapes_api_metrics_and_provisions_datasource(self) -> None:
        prometheus_config = yaml.safe_load((ROOT / "infra/prometheus/prometheus.yml").read_text(encoding="utf-8"))
        scrape_configs = {item["job_name"]: item for item in prometheus_config["scrape_configs"]}
        api_scrape = scrape_configs["geno-api"]
        self.assertEqual(api_scrape["metrics_path"], "/metrics")
        self.assertEqual(api_scrape["static_configs"][0]["targets"], ["api:8000"])

        grafana_datasource = yaml.safe_load(
            (ROOT / "infra/grafana/provisioning/datasources/prometheus.yml").read_text(encoding="utf-8")
        )
        datasource = grafana_datasource["datasources"][0]
        self.assertEqual(datasource["name"], "GENO Prometheus")
        self.assertEqual(datasource["type"], "prometheus")
        self.assertEqual(datasource["url"], "http://prometheus:9090")
        self.assertTrue(datasource["isDefault"])

    def test_report_export_jobs_migration_is_covered_by_rls_and_db_smoke(self) -> None:
        init_sql = (ROOT / "infra/db/migrations/up/0001_init.sql").read_text(encoding="utf-8")
        rls_sql = (ROOT / "infra/db/migrations/up/0010_runtime_project_rls.sql").read_text(encoding="utf-8")
        rls_down_sql = (ROOT / "infra/db/migrations/down/0010_runtime_project_rls.down.sql").read_text(encoding="utf-8")
        db_smoke_source = (ROOT / "scripts/verify_db_smoke.py").read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE report_export_jobs", init_sql)
        self.assertIn("idx_report_export_jobs_project", init_sql)
        self.assertIn("idx_report_export_jobs_claim", init_sql)
        self.assertIn("attempt_count integer NOT NULL DEFAULT 0", init_sql)
        self.assertIn("max_attempts integer NOT NULL DEFAULT 3", init_sql)
        self.assertIn("lease_expires_at timestamptz", init_sql)
        self.assertIn("next_attempt_at timestamptz", init_sql)
        self.assertIn("'report_export_jobs'", rls_sql)
        self.assertIn("'report_export_jobs'", rls_down_sql)
        self.assertIn('"report_export_jobs"', db_smoke_source)
        self.assertIn("CREATE TABLE runtime_notifications", init_sql)
        self.assertIn("idx_runtime_notifications_project", init_sql)
        self.assertIn("idx_runtime_notifications_target", init_sql)
        self.assertIn("recipient_role text NOT NULL DEFAULT 'project_member'", init_sql)
        self.assertIn("'runtime_notifications'", rls_sql)
        self.assertIn("'runtime_notifications'", rls_down_sql)
        self.assertIn('"runtime_notifications"', db_smoke_source)
        self.assertIn("CREATE TABLE runtime_notification_subscriptions", init_sql)
        self.assertIn("CREATE TABLE runtime_notification_deliveries", init_sql)
        self.assertIn("event_types text[] NOT NULL DEFAULT ARRAY['report_export_job']", init_sql)
        self.assertIn("response_body_hash text", init_sql)
        self.assertIn("idx_runtime_notification_subscriptions_project", init_sql)
        self.assertIn("idx_runtime_notification_deliveries_project", init_sql)
        self.assertIn("idx_runtime_notification_deliveries_claim", init_sql)
        self.assertIn("idx_runtime_notification_deliveries_notification", init_sql)
        self.assertIn("'runtime_notification_subscriptions'", rls_sql)
        self.assertIn("'runtime_notification_deliveries'", rls_sql)
        self.assertIn("'runtime_notification_subscriptions'", rls_down_sql)
        self.assertIn("'runtime_notification_deliveries'", rls_down_sql)
        self.assertIn('"runtime_notification_subscriptions"', db_smoke_source)
        self.assertIn('"runtime_notification_deliveries"', db_smoke_source)
        self.assertIn("CREATE TABLE runtime_alert_events", init_sql)
        self.assertIn("idx_runtime_alert_events_project", init_sql)
        self.assertIn("idx_runtime_alert_events_alert", init_sql)
        self.assertIn("alert_id text NOT NULL", init_sql)
        self.assertIn("metadata jsonb NOT NULL DEFAULT '{}'::jsonb", init_sql)
        self.assertIn("'runtime_alert_events'", rls_sql)
        self.assertIn("'runtime_alert_events'", rls_down_sql)
        self.assertIn('"runtime_alert_events"', db_smoke_source)
        self.assertIn("CREATE TABLE project_brand_assets", init_sql)
        self.assertIn("preview_url text", init_sql)
        self.assertIn("scan_status text NOT NULL DEFAULT 'pending'", init_sql)
        self.assertIn("scan_checked_at timestamptz", init_sql)
        self.assertIn("scan_method_version text", init_sql)
        self.assertIn("scan_notes text", init_sql)
        self.assertIn('"project_brand_assets"', db_smoke_source)
        self.assertIn('"scan_status"', db_smoke_source)
        self.assertIn("CREATE TABLE entity_alias_candidate_reviews", init_sql)
        self.assertIn("idx_entity_alias_candidate_reviews_project", init_sql)
        self.assertIn("idx_entity_alias_candidate_reviews_assignment", init_sql)
        self.assertIn("assigned_to text", init_sql)
        self.assertIn("assignment_status text NOT NULL DEFAULT 'unassigned'", init_sql)
        self.assertIn("due_at timestamptz", init_sql)
        self.assertIn("UNIQUE(project_id, candidate_id)", init_sql)
        self.assertIn("0012_entity_alias_candidate_review_assignments.sql", "\n".join(sorted(p.name for p in (ROOT / "infra/db/migrations/up").glob("*.sql"))))
        self.assertIn("'entity_alias_candidate_reviews'", rls_sql)
        self.assertIn("'entity_alias_candidate_reviews'", rls_down_sql)
        self.assertIn('"entity_alias_candidate_reviews"', db_smoke_source)
        self.assertIn('"candidate_id"', db_smoke_source)
        self.assertIn('"assignment_status"', db_smoke_source)

    def test_litellm_config_uses_env_secrets_and_geno_model_aliases(self) -> None:
        config = yaml.safe_load((ROOT / "infra/litellm_config.yaml").read_text(encoding="utf-8"))
        model_list = {item["model_name"]: item["litellm_params"] for item in config["model_list"]}

        self.assertEqual(model_list["geno-gpt-4.1-mini"]["model"], "openai/gpt-4.1-mini")
        self.assertEqual(model_list["geno-gpt-4.1-mini"]["api_key"], "os.environ/OPENAI_API_KEY")
        self.assertEqual(model_list["geno-text-embedding-3-small"]["model"], "openai/text-embedding-3-small")
        self.assertEqual(model_list["geno-text-embedding-3-small"]["api_key"], "os.environ/OPENAI_API_KEY")
        self.assertEqual(config["general_settings"]["master_key"], "os.environ/LITELLM_MASTER_KEY")

    def test_api_service_enables_runtime_database_pool(self) -> None:
        config = self._compose_config()
        api = config["services"]["api"]

        self.assertEqual(api["environment"]["DATABASE_URL"], RUNTIME_DATABASE_URL)
        self.assertEqual(api["environment"]["GENO_RUNTIME_DB_POOL_ENABLED"], "1")
        self.assertEqual(api["environment"]["GENO_RUNTIME_DB_POOL_MAX_SIZE"], "10")
        self.assertEqual(api["environment"]["GENO_RUNTIME_DB_POOL_TIMEOUT_SECONDS"], "5")

    def test_api_image_includes_runtime_e2e_verifier(self) -> None:
        dockerfile = (ROOT / "apps/api/Dockerfile").read_text(encoding="utf-8")

        self.assertIn("COPY scripts ./scripts", dockerfile)
        self.assertIn("ENV PYTHONPATH=/app:/app/packages/geno_core:/app/apps/api", dockerfile)

    def test_runtime_project_rls_migration_uses_guc_context_and_project_policies(self) -> None:
        migration = (ROOT / "infra/db/migrations/up/0010_runtime_project_rls.sql").read_text(encoding="utf-8")
        rollback = (ROOT / "infra/db/migrations/down/0010_runtime_project_rls.down.sql").read_text(encoding="utf-8")

        self.assertIn("CREATE OR REPLACE FUNCTION geno_runtime_can_access_project", migration)
        self.assertIn("CREATE ROLE geno_runtime_app LOGIN PASSWORD 'geno_runtime_app'", migration)
        self.assertIn("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO geno_runtime_app", migration)
        self.assertIn("current_setting('geno.runtime_actor_id', true)", migration)
        self.assertIn("current_setting('geno.runtime_project_id', true)", migration)
        self.assertIn("ALTER TABLE projects FORCE ROW LEVEL SECURITY", migration)
        self.assertIn("projects_runtime_project_isolation", migration)
        self.assertIn("project_members_runtime_project_isolation", migration)
        self.assertIn("'collection_run_summaries'", migration)
        self.assertIn("raw_answers_runtime_project_isolation", migration)
        self.assertIn("entity_aliases_runtime_project_isolation", migration)
        self.assertIn("DROP FUNCTION IF EXISTS geno_runtime_can_access_project(uuid)", rollback)
        self.assertIn("DROP ROLE IF EXISTS geno_runtime_app", rollback)

    def test_project_member_invitation_migration_is_project_scoped_and_auditable(self) -> None:
        migration = (ROOT / "infra/db/migrations/up/0013_project_member_invitations.sql").read_text(encoding="utf-8")
        rollback = (ROOT / "infra/db/migrations/down/0013_project_member_invitations.down.sql").read_text(
            encoding="utf-8"
        )
        db_smoke_source = (ROOT / "scripts/verify_db_smoke.py").read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS project_member_invitations", migration)
        self.assertIn("project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE", migration)
        self.assertIn("invite_token_hash text NOT NULL", migration)
        self.assertIn("UNIQUE(project_id, email, role, status)", migration)
        self.assertIn("idx_project_member_invitations_project_status", migration)
        self.assertIn("ALTER TABLE project_member_invitations FORCE ROW LEVEL SECURITY", migration)
        self.assertIn("project_member_invitations_runtime_project_isolation", migration)
        self.assertIn("geno_runtime_can_access_project(project_id)", migration)
        self.assertIn("DROP TABLE IF EXISTS project_member_invitations", rollback)
        self.assertIn('"project_member_invitations"', db_smoke_source)
        self.assertIn('"invite_token_hash"', db_smoke_source)
        self.assertIn('"project_member_invitations_runtime_project_isolation"', db_smoke_source)

    def test_project_member_invitation_acceptance_migration_is_token_scoped(self) -> None:
        migration = (ROOT / "infra/db/migrations/up/0014_project_member_invitation_acceptance.sql").read_text(
            encoding="utf-8"
        )
        rollback = (ROOT / "infra/db/migrations/down/0014_project_member_invitation_acceptance.down.sql").read_text(
            encoding="utf-8"
        )
        db_smoke_source = (ROOT / "scripts/verify_db_smoke.py").read_text(encoding="utf-8")

        self.assertIn("CREATE OR REPLACE FUNCTION geno_runtime_invitation_token_hash", migration)
        self.assertIn("current_setting('geno.runtime_invitation_token_hash', true)", migration)
        self.assertIn("CREATE OR REPLACE FUNCTION geno_runtime_can_accept_project_invitation", migration)
        self.assertIn("invite_token_hash = geno_runtime_invitation_token_hash()", migration)
        self.assertIn("status = 'pending'", migration)
        self.assertIn("status IN ('pending', 'accepted')", migration)
        self.assertIn("DROP FUNCTION IF EXISTS geno_runtime_can_accept_project_invitation(uuid)", rollback)
        self.assertIn("DROP FUNCTION IF EXISTS geno_runtime_invitation_token_hash()", rollback)
        self.assertIn('"geno_runtime_invitation_token_hash"', db_smoke_source)
        self.assertIn('"geno_runtime_can_accept_project_invitation"', db_smoke_source)

    def test_browser_fidelity_plan_make_target_outputs_machine_readable_json(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        google_env_example = (ROOT / ".env.au-p0b-google.example").read_text(encoding="utf-8")

        self.assertIn("install-dev-deps:", makefile)
        self.assertIn("python3 -m pip install -r requirements-dev.txt", makefile)
        self.assertIn("lint-python:", makefile)
        self.assertIn("python3 -m ruff check apps/api packages workers scripts tests", makefile)
        self.assertIn("compile-python:", makefile)
        self.assertIn(
            "python3 -m compileall apps/api/geno_api packages/geno_core/geno_core workers scripts tests",
            makefile,
        )
        self.assertIn("web-typecheck:", makefile)
        self.assertIn("npm --prefix apps/web run typecheck", makefile)
        self.assertIn("quality: lint-python compile-python web-typecheck", makefile)
        self.assertIn("web-build:", makefile)
        self.assertIn("npm --prefix apps/web run build", makefile)
        self.assertIn("docs/runtime_preflight/*.md", gitignore)
        self.assertIn("ci-local:", makefile)
        self.assertIn("runtime-e2e", makefile)
        self.assertIn("browser-fidelity-plan:", makefile)
        self.assertIn("au-p0b-google-runbook:", makefile)
        self.assertIn("scripts/build_au_p0b_google_spike_runbook.py", makefile)
        self.assertIn("verify-au-p0b-google-runbook:", makefile)
        self.assertIn("scripts/verify_au_p0b_google_spike_runbook.py", makefile)
        self.assertIn("verify-au-p0a-env-template:", makefile)
        self.assertIn("scripts/verify_au_p0a_env_template.py", makefile)
        self.assertIn("au-p0a-env-bootstrap:", makefile)
        self.assertIn("scripts/bootstrap_au_p0a_env_file.py", makefile)
        self.assertIn("GENO_AU_P0A_ENV_BOOTSTRAP_OUTPUT_PATH", makefile)
        self.assertIn("verify-au-p0a-env-bootstrap:", makefile)
        self.assertIn("scripts/verify_au_p0a_env_file_bootstrap.py", makefile)
        self.assertIn("verify-au-p0b-google-env-template:", makefile)
        self.assertIn("scripts/verify_au_p0b_google_env_template.py", makefile)
        self.assertIn("au-p0b-google-env-bootstrap:", makefile)
        self.assertIn("scripts/bootstrap_au_p0b_google_env_file.py", makefile)
        self.assertIn("GENO_AU_P0B_GOOGLE_ENV_BOOTSTRAP_OUTPUT_PATH", makefile)
        self.assertIn("verify-au-p0b-google-env-bootstrap:", makefile)
        self.assertIn("scripts/verify_au_p0b_google_env_file_bootstrap.py", makefile)
        self.assertIn("au-p0b-google-runbook-dry-run:", makefile)
        self.assertIn("scripts/run_au_p0b_google_spike_runbook.py", makefile)
        self.assertIn("verify-au-p0b-google-runbook-execution:", makefile)
        self.assertIn("scripts/verify_au_p0b_google_spike_runbook_execution.py", makefile)
        self.assertIn("au-p0b-google-status:", makefile)
        self.assertIn("scripts/build_au_p0b_google_spike_status_report.py", makefile)
        self.assertIn("verify-au-p0b-google-status:", makefile)
        self.assertIn("scripts/verify_au_p0b_google_spike_status_report.py", makefile)
        self.assertIn("au-p0b-google-package:", makefile)
        self.assertIn("scripts/build_au_p0b_google_evidence_package.py", makefile)
        self.assertIn("verify-au-p0b-google-package:", makefile)
        self.assertIn("scripts/verify_au_p0b_google_evidence_package.py", makefile)
        self.assertIn("GENO_AU_P0B_GOOGLE_PACKAGE_OUTPUT_PATH", makefile)
        self.assertIn("au-p0b-google-execution-checklist:", makefile)
        self.assertIn("scripts/build_au_p0b_google_execution_checklist.py", makefile)
        self.assertIn("GENO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH", makefile)
        self.assertIn("verify-au-p0b-google-execution-checklist:", makefile)
        self.assertIn("scripts/verify_au_p0b_google_execution_checklist.py", makefile)
        self.assertIn("au-p0b-google-environment-request:", makefile)
        self.assertIn("scripts/build_au_p0b_google_environment_request_packet.py", makefile)
        self.assertIn("GENO_AU_P0B_GOOGLE_ENVIRONMENT_REQUEST_OUTPUT_PATH", makefile)
        self.assertIn("verify-au-p0b-google-environment-request:", makefile)
        self.assertIn("scripts/verify_au_p0b_google_environment_request_packet.py", makefile)
        self.assertIn("au-p0b-google-manual-backfill-request:", makefile)
        self.assertIn("scripts/build_au_p0b_google_manual_backfill_request_packet.py", makefile)
        self.assertIn("GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_REQUEST_OUTPUT_PATH", makefile)
        self.assertIn("verify-au-p0b-google-manual-backfill-request:", makefile)
        self.assertIn("scripts/verify_au_p0b_google_manual_backfill_request_packet.py", makefile)
        self.assertIn("au-p0b-google-phase-execution-request:", makefile)
        self.assertIn("scripts/build_au_p0b_google_phase_execution_request_packet.py", makefile)
        self.assertIn("GENO_AU_P0B_GOOGLE_PHASE_EXECUTION_REQUEST_OUTPUT_PATH", makefile)
        self.assertIn("verify-au-p0b-google-phase-execution-request:", makefile)
        self.assertIn("scripts/verify_au_p0b_google_phase_execution_request_packet.py", makefile)
        self.assertIn("au-p0b-google-phase-execution-fulfillment:", makefile)
        self.assertIn("scripts/build_au_p0b_google_phase_execution_fulfillment.py", makefile)
        self.assertIn("GENO_AU_P0B_GOOGLE_PHASE_EXECUTION_FULFILLMENT_OUTPUT_PATH", makefile)
        self.assertIn("verify-au-p0b-google-phase-execution-fulfillment:", makefile)
        self.assertIn("scripts/verify_au_p0b_google_phase_execution_fulfillment.py", makefile)
        self.assertIn("au-p0b-google-phase-execution-clearance:", makefile)
        self.assertIn("scripts/build_au_p0b_google_phase_execution_clearance.py", makefile)
        self.assertIn("GENO_AU_P0B_GOOGLE_PHASE_EXECUTION_CLEARANCE_OUTPUT_PATH", makefile)
        self.assertIn("verify-au-p0b-google-phase-execution-clearance:", makefile)
        self.assertIn("scripts/verify_au_p0b_google_phase_execution_clearance.py", makefile)
        self.assertIn("au-launch-status:", makefile)
        self.assertIn("scripts/build_au_launch_status.py", makefile)
        self.assertIn("verify-au-launch-status:", makefile)
        self.assertIn("scripts/verify_au_launch_status.py", makefile)
        self.assertIn("GENO_AU_LAUNCH_STATUS_OUTPUT_PATH", makefile)
        self.assertIn("au-launch-remediation-plan:", makefile)
        self.assertIn("scripts/build_au_launch_remediation_plan.py", makefile)
        self.assertIn("verify-au-launch-remediation-plan:", makefile)
        self.assertIn("scripts/verify_au_launch_remediation_plan.py", makefile)
        self.assertIn("GENO_AU_LAUNCH_REMEDIATION_PLAN_OUTPUT_PATH", makefile)
        self.assertIn("au-p0a-environment-checklist:", makefile)
        self.assertIn("scripts/build_au_p0a_environment_checklist.py", makefile)
        self.assertIn("GENO_AU_P0A_ENVIRONMENT_CHECKLIST_OUTPUT_PATH", makefile)
        self.assertIn("verify-au-p0a-environment-checklist:", makefile)
        self.assertIn("scripts/verify_au_p0a_environment_checklist.py", makefile)
        self.assertIn("au-p0a-runbook-dry-run:", makefile)
        self.assertIn("scripts/run_au_p0a_runbook.py", makefile)
        self.assertIn("au-p0a-readiness:", makefile)
        self.assertIn("scripts/verify_au_p0a_readiness.py", makefile)
        self.assertIn("au-p0a-status:", makefile)
        self.assertIn("scripts/build_au_p0a_status_report.py", makefile)
        self.assertIn("au-p0a-execution-checklist:", makefile)
        self.assertIn("scripts/build_au_p0a_execution_checklist.py", makefile)
        self.assertIn("GENO_AU_P0A_EXECUTION_CHECKLIST_OUTPUT_PATH", makefile)
        self.assertIn("verify-au-p0a-execution-checklist:", makefile)
        self.assertIn("scripts/verify_au_p0a_execution_checklist.py", makefile)
        self.assertIn("au-p0a-credential-request:", makefile)
        self.assertIn("scripts/build_au_p0a_credential_request_packet.py", makefile)
        self.assertIn("GENO_AU_P0A_CREDENTIAL_REQUEST_OUTPUT_PATH", makefile)
        self.assertIn("verify-au-p0a-credential-request:", makefile)
        self.assertIn("scripts/verify_au_p0a_credential_request_packet.py", makefile)
        self.assertIn("au-p0a-credential-fulfillment:", makefile)
        self.assertIn("scripts/build_au_p0a_credential_fulfillment.py", makefile)
        self.assertIn("GENO_AU_P0A_CREDENTIAL_FULFILLMENT_OUTPUT_PATH", makefile)
        self.assertIn("verify-au-p0a-credential-fulfillment:", makefile)
        self.assertIn("scripts/verify_au_p0a_credential_fulfillment.py", makefile)
        self.assertIn("au-p0b-google-environment-fulfillment:", makefile)
        self.assertIn("scripts/build_au_p0b_google_environment_fulfillment.py", makefile)
        self.assertIn("GENO_AU_P0B_GOOGLE_ENVIRONMENT_FULFILLMENT_OUTPUT_PATH", makefile)
        self.assertIn("verify-au-p0b-google-environment-fulfillment:", makefile)
        self.assertIn("scripts/verify_au_p0b_google_environment_fulfillment.py", makefile)
        self.assertIn("au-p0b-google-environment-clearance:", makefile)
        self.assertIn("scripts/build_au_p0b_google_environment_clearance.py", makefile)
        self.assertIn("GENO_AU_P0B_GOOGLE_ENVIRONMENT_CLEARANCE_OUTPUT_PATH", makefile)
        self.assertIn("verify-au-p0b-google-environment-clearance:", makefile)
        self.assertIn("scripts/verify_au_p0b_google_environment_clearance.py", makefile)
        self.assertIn("au-p0b-google-manual-backfill-fulfillment:", makefile)
        self.assertIn("scripts/build_au_p0b_google_manual_backfill_fulfillment.py", makefile)
        self.assertIn("GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_FULFILLMENT_OUTPUT_PATH", makefile)
        self.assertIn("verify-au-p0b-google-manual-backfill-fulfillment:", makefile)
        self.assertIn("scripts/verify_au_p0b_google_manual_backfill_fulfillment.py", makefile)
        self.assertIn("au-p0b-google-manual-backfill-clearance:", makefile)
        self.assertIn("scripts/build_au_p0b_google_manual_backfill_clearance.py", makefile)
        self.assertIn("GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_CLEARANCE_OUTPUT_PATH", makefile)
        self.assertIn("verify-au-p0b-google-manual-backfill-clearance:", makefile)
        self.assertIn("scripts/verify_au_p0b_google_manual_backfill_clearance.py", makefile)
        self.assertIn("au-p0a-real-batch-request:", makefile)
        self.assertIn("scripts/build_au_p0a_real_batch_request_packet.py", makefile)
        self.assertIn("GENO_AU_P0A_REAL_BATCH_REQUEST_OUTPUT_PATH", makefile)
        self.assertIn("verify-au-p0a-real-batch-request:", makefile)
        self.assertIn("scripts/verify_au_p0a_real_batch_request_packet.py", makefile)
        self.assertIn("au-p0a-real-batch-fulfillment:", makefile)
        self.assertIn("scripts/build_au_p0a_real_batch_fulfillment.py", makefile)
        self.assertIn("GENO_AU_P0A_REAL_BATCH_FULFILLMENT_OUTPUT_PATH", makefile)
        self.assertIn("verify-au-p0a-real-batch-fulfillment:", makefile)
        self.assertIn("scripts/verify_au_p0a_real_batch_fulfillment.py", makefile)
        self.assertIn("au-p0a-real-batch-clearance:", makefile)
        self.assertIn("scripts/build_au_p0a_real_batch_clearance.py", makefile)
        self.assertIn("GENO_AU_P0A_REAL_BATCH_CLEARANCE_OUTPUT_PATH", makefile)
        self.assertIn("verify-au-p0a-real-batch-clearance:", makefile)
        self.assertIn("scripts/verify_au_p0a_real_batch_clearance.py", makefile)
        self.assertIn("--env-file $${GENO_AU_P0A_ENV_FILE:-.env.au-p0a}", makefile)
        self.assertIn("au-handoff-dossier:", makefile)
        self.assertIn("scripts/build_au_handoff_dossier.py", makefile)
        self.assertIn("--p0a-execution-checklist-path $${GENO_AU_P0A_EXECUTION_CHECKLIST_OUTPUT_PATH", makefile)
        self.assertIn("GENO_AU_HANDOFF_DOSSIER_OUTPUT_PATH", makefile)
        self.assertIn("GENO_AU_HANDOFF_DOSSIER_MARKDOWN_PATH", makefile)
        self.assertIn("verify-au-handoff-dossier:", makefile)
        self.assertIn("scripts/verify_au_handoff_dossier.py", makefile)
        self.assertIn("au-customer-handoff-readiness:", makefile)
        self.assertIn("scripts/build_au_customer_handoff_readiness.py", makefile)
        self.assertIn("GENO_AU_CUSTOMER_HANDOFF_READINESS_OUTPUT_PATH", makefile)
        self.assertIn("verify-au-customer-handoff-readiness:", makefile)
        self.assertIn("scripts/verify_au_customer_handoff_readiness.py", makefile)
        self.assertIn("au-customer-handoff-clearance:", makefile)
        self.assertIn("scripts/build_au_customer_handoff_clearance.py", makefile)
        self.assertIn("GENO_AU_CUSTOMER_HANDOFF_CLEARANCE_OUTPUT_PATH", makefile)
        self.assertIn("verify-au-customer-handoff-clearance:", makefile)
        self.assertIn("scripts/verify_au_customer_handoff_clearance.py", makefile)
        self.assertIn("au-next-work-item:", makefile)
        self.assertIn("scripts/build_au_next_work_item_packet.py", makefile)
        self.assertIn("GENO_AU_NEXT_WORK_ITEM_OUTPUT_PATH", makefile)
        self.assertIn("verify-au-next-work-item:", makefile)
        self.assertIn("scripts/verify_au_next_work_item_packet.py", makefile)
        self.assertIn("au-external-dependency-handoff:", makefile)
        self.assertIn("scripts/build_au_external_dependency_handoff.py", makefile)
        self.assertIn("GENO_AU_EXTERNAL_DEPENDENCY_HANDOFF_OUTPUT_PATH", makefile)
        self.assertIn("verify-au-external-dependency-handoff:", makefile)
        self.assertIn("scripts/verify_au_external_dependency_handoff.py", makefile)
        self.assertIn("au-external-dependency-clearance:", makefile)
        self.assertIn("scripts/run_au_external_dependency_clearance.py", makefile)
        self.assertIn("GENO_AU_EXTERNAL_DEPENDENCY_CLEARANCE_OUTPUT_PATH", makefile)
        self.assertIn("verify-au-external-dependency-clearance:", makefile)
        self.assertIn("scripts/verify_au_external_dependency_clearance.py", makefile)
        self.assertIn("--p0c-report-package-path $${GENO_AU_P0C_REPORT_PACKAGE_OUTPUT_PATH", makefile)
        self.assertIn("au-p0c-report-package:", makefile)
        self.assertIn("scripts/build_au_p0c_report_package.py", makefile)
        self.assertIn("verify-au-p0c-report-package:", makefile)
        self.assertIn("scripts/verify_au_p0c_report_package.py", makefile)
        self.assertIn("GENO_AU_P0C_REPORT_PACKAGE_OUTPUT_PATH", makefile)
        self.assertIn("au-p0b-google-manual-template:", makefile)
        self.assertIn("scripts/build_au_p0b_manual_backfill_template.py", makefile)
        self.assertIn("verify-au-p0b-google-manual-backfill:", makefile)
        self.assertIn("scripts/verify_au_p0b_manual_backfill.py", makefile)
        self.assertIn("GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_VERIFICATION_PATH", makefile)
        self.assertIn("au-p0b-google-playwright-env:", makefile)
        self.assertIn("scripts/build_au_p0b_google_playwright_env_report.py", makefile)
        self.assertIn("--env-file $${GENO_AU_P0B_GOOGLE_ENV_FILE:-.env.au-p0b-google}", makefile)
        self.assertIn("verify-au-p0b-google-playwright-env:", makefile)
        self.assertIn("scripts/verify_au_p0b_google_playwright_env_report.py", makefile)
        self.assertIn("au-p0b-google-playwright-smoke:", makefile)
        self.assertIn("scripts/run_au_p0b_google_playwright_smoke.py", makefile)
        self.assertIn("verify-au-p0b-google-playwright-smoke:", makefile)
        self.assertIn("scripts/verify_au_p0b_google_playwright_smoke.py", makefile)
        self.assertIn("au-p0b-google-spike-health:", makefile)
        self.assertIn("--mode google-spike --require-ready-collectors --health-check-only", makefile)
        self.assertIn("GENO_AU_P0B_GOOGLE_SPIKE_HEALTH_OUTPUT_PATH", makefile)
        self.assertIn("au-p0b-google-spike-health-manifest:", makefile)
        self.assertIn("GENO_AU_P0B_GOOGLE_SPIKE_HEALTH_MANIFEST_PATH", makefile)
        self.assertIn("au-p0b-google-spike:", makefile)
        self.assertIn("--require-no-collection-failures --require-google-spike-gates", makefile)
        self.assertIn("GENO_AU_P0B_GOOGLE_SPIKE_PERSIST_ARGS", makefile)
        self.assertIn("GENO_AU_P0B_GOOGLE_SPIKE_OUTPUT_PATH", makefile)
        self.assertIn("au-p0b-google-spike-manifest:", makefile)
        self.assertIn("GENO_AU_P0B_GOOGLE_SPIKE_MANIFEST_PATH", makefile)
        self.assertIn("au-p0b-google-serp-health:", makefile)
        self.assertIn("--mode google-serp-spike", makefile)
        self.assertIn("verify-au-p0b-google-serp-health:", makefile)
        self.assertIn("scripts/verify_au_p0b_google_serp_comparison.py", makefile)
        self.assertIn("au-p0b-google-serp-health-manifest:", makefile)
        self.assertIn("au-p0b-google-serp-fixture:", makefile)
        self.assertIn("--mode google-serp-fixture", makefile)
        self.assertIn("verify-au-p0b-google-serp-fixture:", makefile)
        self.assertIn("--require-comparison-ready", makefile)
        self.assertIn("au-p0b-google-serp-fixture-manifest:", makefile)
        self.assertIn("au-p0b-google-serp-status:", makefile)
        self.assertIn("scripts/build_au_p0b_google_serp_status_report.py", makefile)
        self.assertIn("verify-au-p0b-google-serp-status:", makefile)
        self.assertIn("scripts/verify_au_p0b_google_serp_status_report.py", makefile)
        self.assertIn("au-broader-platform-registry:", makefile)
        self.assertIn("scripts/build_au_broader_platform_registry.py", makefile)
        self.assertIn("verify-au-broader-platform-registry:", makefile)
        self.assertIn("au-retest-scheduler-plan:", makefile)
        self.assertIn("scripts/build_au_retest_scheduler_plan.py", makefile)
        self.assertIn("GENO_AU_RETEST_SCHEDULER_PLAN_OUTPUT_PATH", makefile)
        self.assertIn("verify-au-retest-scheduler-plan:", makefile)
        self.assertIn("scripts/verify_au_retest_scheduler_plan.py", makefile)
        self.assertIn("au-retest-execution-status:", makefile)
        self.assertIn("scripts/build_au_retest_execution_status.py", makefile)
        self.assertIn("GENO_AU_RETEST_EXECUTION_STATUS_OUTPUT_PATH", makefile)
        self.assertIn("verify-au-retest-execution-status:", makefile)
        self.assertIn("scripts/verify_au_retest_execution_status.py", makefile)
        self.assertIn("scripts/verify_au_broader_platform_registry.py", makefile)
        self.assertIn(
            "\t@PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --plan-browser-fidelity-sampling",
            makefile,
        )
        self.assertIn("browser-fidelity-scheduler-plan:", makefile)
        self.assertIn("browser-fidelity-scheduler-run:", makefile)
        self.assertIn("runtime-alert-notification-worker:", makefile)
        self.assertIn(
            "\tPYTHONPATH=packages/geno_core:apps/api python3 workers/notification_worker/run_runtime_alert_notifications.py --market-code $${GENO_RUNTIME_ALERT_MARKET_CODE:-AU}",
            makefile,
        )
        self.assertIn("runtime-alert-escalation-worker:", makefile)
        self.assertIn(
            "\tPYTHONPATH=packages/geno_core:apps/api python3 workers/notification_worker/run_runtime_alert_escalations.py --market-code $${GENO_RUNTIME_ALERT_MARKET_CODE:-AU}",
            makefile,
        )
        self.assertIn("entity-alias-assignment-notification-worker:", makefile)
        self.assertIn(
            "\tPYTHONPATH=packages/geno_core:apps/api python3 workers/notification_worker/run_entity_alias_assignment_notifications.py --market-code $${GENO_ENTITY_ALIAS_ASSIGNMENT_MARKET_CODE:-AU}",
            makefile,
        )
        self.assertIn("entity-alias-assignment-escalation-worker:", makefile)
        self.assertIn(
            "\tPYTHONPATH=packages/geno_core:apps/api python3 workers/notification_worker/run_entity_alias_assignment_escalations.py --market-code $${GENO_ENTITY_ALIAS_ASSIGNMENT_MARKET_CODE:-AU}",
            makefile,
        )
        self.assertIn("entity-alias-assignment-reassignment-worker:", makefile)
        self.assertIn(
            "\tPYTHONPATH=packages/geno_core:apps/api python3 workers/notification_worker/run_entity_alias_assignment_reassignments.py --market-code $${GENO_ENTITY_ALIAS_ASSIGNMENT_MARKET_CODE:-AU} --assigned-to $${GENO_ENTITY_ALIAS_ASSIGNMENT_REASSIGN_TO:-runtime-console}",
            makefile,
        )
        self.assertIn("docker-config-scheduler:", makefile)
        self.assertIn("docker-config-observability:", makefile)
        self.assertIn("docker-config-db-smoke:", makefile)
        self.assertIn("db-smoke:", makefile)
        self.assertIn("docker compose -p geno-db-smoke -f infra/docker-compose.yml --profile db-smoke run --rm db-smoke", makefile)
        self.assertIn("ci-local: quality test web-build docker-config docker-config-llm docker-config-scheduler docker-config-observability docker-config-db-smoke db-smoke runtime-e2e", makefile)
        self.assertIn("!.env.au-p0a.example", gitignore)
        p0a_env_example = (ROOT / ".env.au-p0a.example").read_text(encoding="utf-8")
        for name in (
            "PERPLEXITY_API_KEY=",
            "OPENAI_API_KEY=",
            "DATABASE_URL=postgresql://geno_runtime_app:geno_runtime_app@localhost:5432/geno",
            "GENO_AU_P0A_STATUS_OUTPUT_PATH=docs/runtime_preflight/au-p0a-status-latest.json",
        ):
            self.assertIn(name, p0a_env_example)
        for forbidden in ("sk-", "pplx-", "AIza", "serpapi.com"):
            self.assertNotIn(forbidden, p0a_env_example)
        self.assertIn("!.env.au-p0b-google.example", gitignore)
        self.assertIn("GOOGLE_PLAYWRIGHT_ENABLED=0", google_env_example)
        for name in (
            "GOOGLE_PLAYWRIGHT_PROMPT_SELECTOR=",
            "GOOGLE_PLAYWRIGHT_ANSWER_SELECTOR=",
            "SERP_API_KEY=",
            "SERP_API_ENDPOINT=",
            "MANUAL_BACKFILL_PATH=",
            "DATABASE_URL=",
            "GOOGLE_PLAYWRIGHT_BROWSER_NAME=chromium",
            "GOOGLE_PLAYWRIGHT_TIMEOUT_SECONDS=45",
            "GENO_AU_P0B_GOOGLE_ENV_FILE=.env.au-p0b-google",
            "GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_VERIFICATION_PATH=",
        ):
            self.assertIn(name, google_env_example)
        for forbidden in ("sk-", "AIza", "postgresql://user:pass@", "serpapi.com", "storage_state"):
            self.assertNotIn(forbidden, google_env_example)

    def test_github_ci_runs_runtime_contract_build_compose_and_e2e_gates(self) -> None:
        workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
        job = workflow["jobs"]["contracts-and-runtime"]
        run_steps = [step["run"] for step in job["steps"] if "run" in step]

        self.assertIn("python -m pip install -r requirements-dev.txt", run_steps)
        self.assertIn("npm --prefix apps/web ci", run_steps)
        self.assertIn("make quality", run_steps)
        self.assertIn("make test", run_steps)
        self.assertIn("make web-build", run_steps)
        self.assertIn("make docker-config", run_steps)
        self.assertIn("make docker-config-llm", run_steps)
        self.assertIn("make docker-config-scheduler", run_steps)
        self.assertIn("make docker-config-observability", run_steps)
        self.assertIn("make docker-config-db-smoke", run_steps)
        self.assertIn("make db-smoke", run_steps)
        self.assertIn("make runtime-e2e", run_steps)


if __name__ == "__main__":
    unittest.main()
