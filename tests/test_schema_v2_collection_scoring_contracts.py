from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/schema-v2/baseline/0020_collection_geo_scoring.sql"


def _table_blocks(sql: str) -> dict[str, str]:
    return {
        match.group("name"): match.group("body")
        for match in re.finditer(
            r"CREATE TABLE (?P<name>[a-z0-9_]+) \((?P<body>.*?)\n\);",
            sql,
            flags=re.DOTALL,
        )
    }


class SchemaV2CollectionScoringContractsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sql = MIGRATION.read_text(encoding="utf-8")
        cls.tables = _table_blocks(cls.sql)

    def test_scope_is_complete_and_excludes_adjacent_slices(self) -> None:
        required_tables = {
            "product_entities",
            "product_entity_aliases",
            "monitoring_queries",
            "monitoring_query_entities",
            "collection_runs",
            "collection_run_queries",
            "collection_jobs",
            "durable_job_dispatch_outbox",
            "collection_run_summaries",
            "answer_runs",
            "raw_answers",
            "answer_citations",
            "evidence_assets",
            "artifact_finalize_outbox",
            "answer_analyses",
            "collection_costs",
            "model_call_logs",
            "visibility_weight_profiles",
            "visibility_weight_profile_components",
            "visibility_score_runs",
            "visibility_score_snapshots",
            "visibility_score_dimensions",
            "score_contributions",
            "source_graphs",
            "source_nodes",
            "source_graph_edges",
            "source_gaps",
            "competitor_benchmarks",
            "action_recommendations",
            "action_tasks",
            "retest_runs",
            "retest_comparisons",
            "review_assignments",
        }
        self.assertTrue(required_tables <= self.tables.keys())

        for forbidden in (
            "CREATE TABLE prompt_questions",
            "CREATE TABLE knowledge_",
            "CREATE TABLE content_",
            "CREATE TABLE report_",
            "CREATE TABLE runtime_notifications",
            "CREATE TABLE integration_connectors",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.sql)

        self.assertIn("Stable GEO observation targets", self.sql)
        self.assertIn("never a prompt-template or writing-rule source of truth", self.sql)
        self.assertNotIn("prompt.import", self.sql)

    def test_every_domain_table_has_project_scope_and_composite_integrity(self) -> None:
        self.assertGreaterEqual(len(self.tables), 40)
        for table_name, body in self.tables.items():
            with self.subTest(table_name=table_name):
                self.assertIn("tenant_id uuid NOT NULL", body)
                self.assertIn("project_id uuid NOT NULL", body)
                self.assertIn("FOREIGN KEY (project_id, tenant_id)", body)
                self.assertIn("REFERENCES projects(id, tenant_id)", body)
                self.assertRegex(body, r"UNIQUE \(id, project_id\)")

        for foreign_key in re.finditer(
            r"FOREIGN KEY \((?P<child>[^)]+)\)\s*"
            r"REFERENCES (?P<parent>[a-z0-9_]+)\((?P<parent_cols>[^)]+)\)",
            self.sql,
        ):
            with self.subTest(parent=foreign_key.group("parent")):
                self.assertIn("project_id", foreign_key.group("child"))
                if foreign_key.group("parent") != "projects":
                    self.assertIn("project_id", foreign_key.group("parent_cols"))

    def test_identifier_collections_are_normalized_as_junction_tables(self) -> None:
        self.assertNotRegex(self.sql, r"\buuid\[\]")
        self.assertNotRegex(self.sql, r"\b[a-z0-9_]+_ids\s+(?:jsonb|text\[\]|uuid\[\])")
        for junction_table in (
            "monitoring_query_entities",
            "collection_run_queries",
            "raw_answer_evidence_assets",
            "answer_citation_evidence_assets",
            "visibility_score_run_analyses",
            "score_contribution_evidence_assets",
            "source_node_citations",
            "source_gap_citations",
            "source_gap_score_contributions",
            "competitor_benchmark_contributions",
            "action_source_gaps",
            "action_score_contributions",
            "action_competitor_benchmarks",
            "retest_run_queries",
        ):
            with self.subTest(junction_table=junction_table):
                self.assertIn(f"CREATE TABLE {junction_table}", self.sql)

    def test_all_project_tables_force_rls_and_use_session_permissions(self) -> None:
        self.assertIn("ALTER TABLE %I ENABLE ROW LEVEL SECURITY", self.sql)
        self.assertIn("ALTER TABLE %I FORCE ROW LEVEL SECURITY", self.sql)
        self.assertIn("public.geno_v2_session_has_project_permission", self.sql)
        self.assertIn("FOR SELECT TO geno_v2_runtime", self.sql)
        self.assertIn("FOR INSERT TO geno_v2_runtime", self.sql)
        self.assertNotIn("TO PUBLIC", self.sql)
        for table_name in self.tables:
            with self.subTest(table_name=table_name):
                self.assertIn(f"'{table_name}'", self.sql)

    def test_each_durable_queue_has_atomic_reclaim_and_fenced_mutations(self) -> None:
        for queue, singular in (
            ("collection_jobs", "collection_job"),
            ("visibility_score_runs", "visibility_score_run"),
            ("retest_runs", "retest_run"),
        ):
            with self.subTest(queue=queue):
                block = self.tables[queue]
                for column in (
                    "lease_owner text",
                    "lease_token uuid",
                    "lease_expires_at timestamptz",
                    "heartbeat_at timestamptz",
                    "attempt_count integer",
                    "max_attempts integer",
                ):
                    self.assertIn(column, block)
                for status in (
                    "'queued'",
                    "'running'",
                    "'succeeded'",
                    "'failed'",
                    "'cancelled'",
                    "'dead_lettered'",
                ):
                    self.assertIn(status, block)
                self.assertIn("parent_job_id uuid", block)
                self.assertIn("replay_nonce integer", block)
                self.assertIn("cancel_requested_at timestamptz", block)
                for operation in ("claim", "heartbeat", "complete", "fail"):
                    self.assertIn(f"geno_v2_{operation}_{singular}", self.sql)

        self.assertEqual(self.sql.count("FOR UPDATE OF "), 5)
        self.assertEqual(self.sql.count("SKIP LOCKED"), 5)
        self.assertEqual(self.sql.count("lease_token = gen_random_uuid()"), 5)
        self.assertGreaterEqual(self.sql.count("lease_expires_at <= statement_timestamp()"), 6)
        self.assertGreaterEqual(self.sql.count("lease_token = p_lease_token"), 9)
        self.assertGreaterEqual(self.sql.count("lease_owner = btrim(p_worker_id)"), 12)
        self.assertIn("MUST NOT hold that transaction open", self.sql)
        self.assertIn("USING ERRCODE = '55000'", self.sql)
        self.assertIn("geno_v2_ack_collection_job_cancel", self.sql)
        self.assertIn("geno_v2_ack_visibility_score_run_cancel", self.sql)
        self.assertIn("geno_v2_ack_retest_run_cancel", self.sql)
        self.assertIn("geno_v2_replay_collection_job", self.sql)
        self.assertIn("geno_v2_replay_visibility_score_run", self.sql)
        self.assertIn("geno_v2_replay_retest_run", self.sql)
        self.assertEqual(self.sql.count("EXCEPTION WHEN unique_violation"), 3)

    def test_dispatch_outbox_is_an_atomic_typed_wakeup_projection(self) -> None:
        block = self.tables["durable_job_dispatch_outbox"]
        for typed_reference, parent_table in (
            ("collection_job_id", "collection_jobs"),
            ("visibility_score_run_id", "visibility_score_runs"),
            ("retest_run_id", "retest_runs"),
        ):
            with self.subTest(typed_reference=typed_reference):
                self.assertIn(f"{typed_reference} uuid", block)
                self.assertIn(
                    f"FOREIGN KEY ({typed_reference}, project_id)", block
                )
                self.assertIn(f"REFERENCES {parent_table}(id, project_id)", block)
        self.assertIn("durable_dispatch_job_discriminator", block)
        self.assertIn("UNIQUE (job_kind, job_id)", block)
        for status in ("'pending'", "'dispatching'", "'dispatched'", "'dead_letter'"):
            self.assertIn(status, block)
        for table_name in ("collection_jobs", "visibility_score_runs", "retest_runs"):
            self.assertIn(f"AFTER INSERT ON {table_name}", self.sql)
        for operation in ("claim", "heartbeat", "complete", "fail"):
            self.assertIn(f"geno_v2_{operation}_durable_job_dispatch", self.sql)
        self.assertIn("geno_v2_enqueue_durable_job_dispatch", self.sql)
        self.assertNotIn("geno_v2_replay_durable_job_dispatch", self.sql)
        self.assertNotIn("geno_v2_cancel_durable_job_dispatch", self.sql)
        self.assertIn("runtime has forbidden durable dispatch outbox DML", self.sql)

    def test_worker_and_result_boundaries_are_independent_of_user_sessions(self) -> None:
        for role_name in (
            "geno_v2_worker",
            "geno_v2_job_owner",
            "geno_v2_result_owner",
            "geno_v2_job_command_owner",
        ):
            self.assertIn(f"'{role_name}'", self.sql)
        self.assertIn("NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE", self.sql)
        self.assertIn("ALTER ROLE geno_v2_worker_login PASSWORD NULL", self.sql)
        self.assertIn("GRANT geno_v2_worker TO geno_v2_worker_login", self.sql)
        self.assertIn("WITH ADMIN FALSE, INHERIT FALSE, SET TRUE", self.sql)
        self.assertIn("Schema v2 job roles must have no role memberships", self.sql)
        self.assertIn("OWNER TO geno_v2_job_owner", self.sql)
        self.assertIn("OWNER TO geno_v2_result_owner", self.sql)
        self.assertIn("TO geno_v2_worker", self.sql)
        self.assertNotIn("prompt.import", self.sql)

        worker_region = self.sql[
            self.sql.index("CREATE FUNCTION geno_v2_claim_collection_job") :
            self.sql.index("CREATE TRIGGER visibility_weight_profiles_guard_used_update")
        ]
        for permission_name in ("'collection.run'", "'score.configure'", "'retest.run'"):
            self.assertNotIn(permission_name, worker_region.split("CREATE FUNCTION geno_v2_request_")[0])

        self.assertIn("FOR UPDATE;", self.sql)
        self.assertIn("public.geno_v2_persist_collection_result(\n        locked_job", self.sql)
        self.assertIn("public.geno_v2_persist_visibility_score_result(\n        locked_run", self.sql)
        self.assertIn("public.geno_v2_persist_retest_result(\n        locked_run", self.sql)
        self.assertNotRegex(
            self.sql,
            r"jsonb_build_object\('lease_token'|input_refs[^\n]*lease_token",
        )
        self.assertIn("runtime has forbidden result-table DML", self.sql)
        self.assertIn("worker has forbidden % on %", self.sql)

    def test_traceability_and_review_contracts_are_exact(self) -> None:
        self.assertIn("claim_inventory_complete boolean NOT NULL", self.tables["answer_analyses"])
        self.assertIn("claim_inventory_reviewed_by text", self.tables["answer_analyses"])
        self.assertIn("public_disclosure_allowed boolean NOT NULL", self.tables["answer_citations"])
        self.assertIn("FOREIGN KEY (answer_analysis_id, project_id)", self.tables["score_contributions"])
        self.assertIn("snapshot_hash text NOT NULL", self.tables["visibility_score_snapshots"])
        self.assertIn("num_nonnulls(", self.tables["review_assignments"])
        self.assertIn("submitted_for_review_by", self.tables["review_assignments"])
        self.assertIn("reviewer_id <> submitted_for_review_by", self.tables["review_assignments"])
        self.assertIn("visibility_score_snapshots_immutable_update", self.sql)
        self.assertIn("retest_comparisons_immutable_update", self.sql)

    def test_all_generated_tables_have_narrow_writer_reachability(self) -> None:
        generated_tables = (
            "collection_run_summaries",
            "evidence_assets",
            "artifact_finalize_outbox",
            "answer_analyses",
            "collection_costs",
            "model_call_logs",
            "visibility_score_dimensions",
            "score_contributions",
            "source_graphs",
            "source_nodes",
            "source_graph_edges",
            "source_gaps",
            "competitor_benchmarks",
            "action_recommendations",
            "action_tasks",
        )
        result_grant = self.sql.split("GRANT INSERT ON answer_runs", 1)[1].split(
            "TO geno_v2_result_owner;", 1
        )[0]
        for table_name in generated_tables:
            with self.subTest(table_name=table_name):
                if table_name == "collection_run_summaries":
                    self.assertIn(
                        "GRANT SELECT, INSERT, UPDATE ON collection_run_summaries",
                        self.sql,
                    )
                else:
                    self.assertIn(table_name, result_grant)
        self.assertIn("geno_v2_refresh_collection_run_summary", self.sql)
        self.assertIn("geno_v2_claim_artifact_finalize", self.sql)
        self.assertIn("artifact_status = ''finalized''", self.sql)
        self.assertIn("geno_v2_require_finalized_score_evidence", self.sql)
        self.assertIn("asset.artifact_status = 'finalized'", self.sql)
        self.assertIn("GRANT INSERT ON durable_job_dispatch_outbox", self.sql)


if __name__ == "__main__":
    unittest.main()
