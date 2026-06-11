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

        self.assertEqual(scheduler["build"]["dockerfile"], "apps/api/Dockerfile")
        self.assertEqual(scheduler["command"], ["python", "scripts/run_browser_fidelity_scheduler.py"])
        self.assertEqual(scheduler["environment"]["DATABASE_URL"], RUNTIME_DATABASE_URL)
        self.assertNotIn("GENO_RUNTIME_DB_POOL_ENABLED", scheduler["environment"])
        self.assertEqual(scheduler["environment"]["OBJECT_STORE_ENDPOINT"], "http://minio:9000")
        self.assertEqual(scheduler["environment"]["GENO_BROWSER_FIDELITY_EXECUTE"], "0")
        self.assertEqual(scheduler["environment"]["GENO_BROWSER_FIDELITY_PERSIST_PLAN"], "1")
        self.assertIn("postgres", scheduler["depends_on"])
        self.assertIn("minio", scheduler["depends_on"])

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
        self.assertIn("CREATE TABLE project_brand_assets", init_sql)
        self.assertIn("preview_url text", init_sql)
        self.assertIn("scan_status text NOT NULL DEFAULT 'pending'", init_sql)
        self.assertIn("scan_checked_at timestamptz", init_sql)
        self.assertIn("scan_method_version text", init_sql)
        self.assertIn("scan_notes text", init_sql)
        self.assertIn('"project_brand_assets"', db_smoke_source)
        self.assertIn('"scan_status"', db_smoke_source)

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

    def test_browser_fidelity_plan_make_target_outputs_machine_readable_json(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

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
        self.assertIn("ci-local:", makefile)
        self.assertIn("runtime-e2e", makefile)
        self.assertIn("browser-fidelity-plan:", makefile)
        self.assertIn(
            "\t@PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --plan-browser-fidelity-sampling",
            makefile,
        )
        self.assertIn("browser-fidelity-scheduler-plan:", makefile)
        self.assertIn("browser-fidelity-scheduler-run:", makefile)
        self.assertIn("docker-config-scheduler:", makefile)
        self.assertIn("docker-config-observability:", makefile)
        self.assertIn("docker-config-db-smoke:", makefile)
        self.assertIn("db-smoke:", makefile)
        self.assertIn("docker compose -p geno-db-smoke -f infra/docker-compose.yml --profile db-smoke run --rm db-smoke", makefile)
        self.assertIn("ci-local: quality test web-build docker-config docker-config-llm docker-config-scheduler docker-config-observability docker-config-db-smoke db-smoke runtime-e2e", makefile)

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
