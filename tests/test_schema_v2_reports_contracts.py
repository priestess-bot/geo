from pathlib import Path
import unittest


SQL = Path("infra/db/schema-v2/baseline/0040_reports_notifications_integrations.sql").read_text(
    encoding="utf-8"
)


class SchemaV2ReportsContractsTest(unittest.TestCase):
    def test_report_export_keeps_stable_project_scoped_identity(self) -> None:
        self.assertIn("CREATE TABLE report_exports", SQL)
        self.assertIn("CONSTRAINT report_exports_id_project_unique UNIQUE (id, project_id)", SQL)
        self.assertIn("report_version_id", SQL)

    def test_outbox_preserves_typed_knowledge_branches_and_adds_report(self) -> None:
        for kind in (
            "knowledge_import",
            "knowledge_crawl",
            "knowledge_parse",
            "knowledge_chunk",
            "knowledge_embed",
            "knowledge_fact_extract",
            "report_generation",
        ):
            self.assertIn(repr(kind), SQL)
        self.assertIn("knowledge_pipeline_job_id", SQL)
        self.assertIn("report_generation_job_id", SQL)
        self.assertIn("TG_TABLE_NAME='report_generation_jobs'", SQL)

    def test_report_lineage_uses_project_composite_foreign_keys(self) -> None:
        self.assertIn("REFERENCES knowledge_fact_versions(id, project_id)", SQL)
        self.assertIn("REFERENCES visibility_score_snapshots(id, project_id)", SQL)
        self.assertIn("REFERENCES retest_runs(id, project_id)", SQL)
        self.assertIn("REFERENCES action_recommendations(id, project_id)", SQL)

    def test_integrations_store_only_opaque_secret_references(self) -> None:
        self.assertIn("secret_reference text", SQL)
        self.assertIn("secret_reference ~ '^[a-z]", SQL)
        self.assertNotIn("secret_value", SQL)

    def test_notification_delivery_has_reclaim_and_fencing_contract(self) -> None:
        for function in (
            "geo_v2_claim_notification_delivery",
            "geo_v2_heartbeat_notification_delivery",
            "geo_v2_complete_notification_delivery",
            "geo_v2_fail_notification_delivery",
        ):
            self.assertIn(function, SQL)
        self.assertIn("lease_expires_at<=statement_timestamp()", SQL)
        self.assertIn("lease_token", SQL)

    def test_report_generation_has_reclaim_and_fencing_contract(self) -> None:
        for function in (
            "geo_v2_claim_report_generation_job",
            "geo_v2_heartbeat_report_generation_job",
            "geo_v2_complete_report_generation_job",
            "geo_v2_fail_report_generation_job",
        ):
            self.assertIn(function, SQL)
        self.assertIn("report completion rejected by lease or lineage", SQL)
        self.assertIn("geo_v2_create_report_generation_job", SQL)
        self.assertIn("geo_v2_persist_report_generation_result", SQL)
        self.assertIn("report_versions_generation_job_project_fkey", SQL)
        self.assertIn("pg_advisory_xact_lock", SQL)

    def test_portal_uses_customer_safe_function_without_runtime_table_policy(self) -> None:
        self.assertIn("CREATE FUNCTION geo_v2_read_portal_reports", SQL)
        self.assertIn("role_item.role_name='client_viewer'", SQL)
        self.assertNotIn("_runtime_read", SQL)

    def test_all_new_project_tables_are_forced_rls(self) -> None:
        for table in (
            "reports",
            "report_versions",
            "report_exports",
            "report_generation_jobs",
            "integration_connectors",
            "notifications",
            "notification_deliveries",
            "portal_report_visibility",
        ):
            self.assertIn(table, SQL)
        self.assertIn("FORCE ROW LEVEL SECURITY", SQL)


if __name__ == "__main__":
    unittest.main()
