from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/schema-v2/baseline/0030_knowledge_pipeline.sql"


def _table_blocks(sql: str) -> dict[str, str]:
    return {
        match.group("name"): match.group("body")
        for match in re.finditer(
            r"CREATE TABLE (?P<name>[a-z0-9_]+) \((?P<body>.*?)\n\);",
            sql,
            flags=re.DOTALL,
        )
    }


def _function_blocks(sql: str) -> dict[str, str]:
    return {
        match.group("name"): match.group(0)
        for match in re.finditer(
            r"CREATE(?: OR REPLACE)? FUNCTION (?P<name>[a-z0-9_]+)\(.*?\n\$[a-z0-9_]+\$;",
            sql,
            flags=re.DOTALL,
        )
    }


class SchemaV2KnowledgeContractsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sql = MIGRATION.read_text(encoding="utf-8")
        cls.tables = _table_blocks(cls.sql)
        cls.functions = _function_blocks(cls.sql)
        cls.knowledge_tables = {
            name: body
            for name, body in cls.tables.items()
            if name.startswith("knowledge_")
        }

    def test_slice_stops_at_governed_knowledge(self) -> None:
        required = {
            "knowledge_pipeline_runs",
            "knowledge_pipeline_stages",
            "knowledge_import_sources",
            "knowledge_pipeline_jobs",
            "knowledge_job_input_snapshots",
            "knowledge_source_assets",
            "knowledge_source_asset_revisions",
            "knowledge_source_governance_versions",
            "knowledge_source_governance_channels",
            "knowledge_parser_runs",
            "knowledge_blocks",
            "knowledge_tables",
            "knowledge_chunks",
            "knowledge_chunk_embeddings",
            "knowledge_fact_candidates",
            "knowledge_fact_candidate_sources",
            "knowledge_fact_candidate_reviews",
            "knowledge_facts",
            "knowledge_fact_versions",
            "knowledge_fact_version_sources",
            "knowledge_quality_definitions",
            "knowledge_job_quality_definitions",
            "knowledge_quality_runs",
            "knowledge_quality_findings",
            "knowledge_risk_acceptances",
        }
        self.assertTrue(required <= self.knowledge_tables.keys())
        self.assertGreaterEqual(len(self.knowledge_tables), 35)

        for forbidden in (
            "CREATE TABLE prompt_",
            "CREATE TABLE content_",
            "CREATE TABLE brief_",
            "CREATE TABLE evidence_pack",
            "CREATE TABLE generation_",
            "CREATE TABLE delivery_",
            "CREATE TABLE publication_",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.sql)
        self.assertIn("must not\n-- create prompt, brief, evidence-pack", self.sql)

    def test_every_knowledge_table_is_project_scoped_and_force_rls_protected(self) -> None:
        for table_name, body in self.knowledge_tables.items():
            with self.subTest(table_name=table_name):
                self.assertIn("tenant_id uuid NOT NULL", body)
                self.assertIn("project_id uuid NOT NULL", body)
                self.assertRegex(body, r"UNIQUE \(id, project_id\)")
                self.assertRegex(
                    body,
                    r"(?s)FOREIGN KEY \(project_id, tenant_id\).*?"
                    r"REFERENCES projects\(id, tenant_id\)",
                )
                self.assertIn(f"'{table_name}'", self.sql)

        self.assertRegex(
            self.sql,
            r"ALTER TABLE (?:public\.)?%I ENABLE ROW LEVEL SECURITY",
        )
        self.assertRegex(
            self.sql,
            r"ALTER TABLE (?:public\.)?%I FORCE ROW LEVEL SECURITY",
        )
        self.assertIn("public.geo_v2_session_has_project_permission", self.sql)
        self.assertNotIn("TO PUBLIC", self.sql)

    def test_project_owned_references_use_composite_foreign_keys(self) -> None:
        references = list(
            re.finditer(
                r"FOREIGN KEY \((?P<child>[^)]+)\)\s*"
                r"REFERENCES (?P<parent>[a-z0-9_]+)\((?P<parent_cols>[^)]+)\)",
                self.sql,
            )
        )
        self.assertGreaterEqual(len(references), 80)
        for reference in references:
            with self.subTest(parent=reference.group("parent")):
                self.assertIn("project_id", reference.group("child"))
                if reference.group("parent") != "projects":
                    self.assertIn("project_id", reference.group("parent_cols"))

    def test_typed_unions_and_subject_binding_are_relationally_enforced(self) -> None:
        for table_name in (
            "knowledge_import_source_subjects",
            "knowledge_source_subjects",
            "knowledge_chunk_subjects",
        ):
            body = self.knowledge_tables[table_name]
            self.assertIn("subject_entity_id uuid", body)
            self.assertIn("subject_role text NOT NULL", body)
            self.assertIn("'primary_brand'", body)
            self.assertIn("'competitor'", body)
            self.assertIn("'neutral'", body)

        for table_name in (
            "knowledge_fact_candidate_sources",
            "knowledge_fact_version_sources",
        ):
            body = self.knowledge_tables[table_name]
            self.assertIn("num_nonnulls(chunk_id, block_id, table_id, source_revision_id) = 1", body)
            self.assertIn("source_snapshot_hash", body)
            self.assertIn("locator", body)

        quality = self.knowledge_tables["knowledge_quality_runs"]
        self.assertIn(
            "num_nonnulls(source_revision_id, parser_run_id, chunk_id, fact_candidate_id) = 1",
            quality,
        )
        self.assertIn("knowledge_source_subject_entity_kind", self.sql)
        self.assertIn("knowledge_candidate_subject_entity_kind", self.sql)

    def test_history_is_append_only_and_heads_have_guarded_transitions(self) -> None:
        immutable_tables = (
            "knowledge_source_asset_revisions",
            "knowledge_source_governance_versions",
            "knowledge_source_channels",
            "knowledge_source_subjects",
            "knowledge_parser_runs",
            "knowledge_blocks",
            "knowledge_tables",
            "knowledge_chunks",
            "knowledge_chunk_embeddings",
            "knowledge_fact_candidate_sources",
            "knowledge_fact_candidate_reviews",
            "knowledge_fact_versions",
            "knowledge_fact_version_sources",
            "knowledge_quality_runs",
            "knowledge_quality_findings",
            "knowledge_risk_acceptances",
        )
        for table_name in immutable_tables:
            with self.subTest(table_name=table_name):
                self.assertIn(f"'{table_name}'", self.sql)
        self.assertIn("rows are immutable after insert", self.sql)
        self.assertIn("source asset identity is immutable", self.sql)
        self.assertIn("fact identity is immutable", self.sql)
        self.assertIn("one pending-to-terminal review transition", self.sql)
        self.assertIn("current governance does not govern current source revision", self.sql)

    def test_durable_job_has_snapshot_quality_and_lease_fencing_contracts(self) -> None:
        jobs = self.knowledge_tables["knowledge_pipeline_jobs"]
        for column in (
            "input_hash text NOT NULL",
            "parent_job_id uuid",
            "replay_nonce integer",
            "lease_owner text",
            "lease_token uuid",
            "lease_expires_at timestamptz",
            "cancel_requested_at timestamptz",
            "finalizing_result_hash text",
            "result_hash text",
        ):
            self.assertIn(column, jobs)
        for status in (
            "'queued'",
            "'running'",
            "'finalizing'",
            "'succeeded'",
            "'failed'",
            "'cancelled'",
            "'dead_lettered'",
        ):
            self.assertIn(status, jobs)

        create = self.functions["geo_v2_create_knowledge_job"]
        self.assertIn("knowledge_job_input_snapshots", create)
        self.assertIn("required_quality_definition_ids", create)
        self.assertIn("governance_version_ids", create)
        self.assertIn("pg_advisory_xact_lock", create)
        self.assertIn("forbidden credential-like key", create)
        self.assertIn("unsupported top-level fields", create)

        for name in (
            "geo_v2_claim_knowledge_job",
            "geo_v2_heartbeat_knowledge_job",
            "geo_v2_begin_finalizing_knowledge_job",
            "geo_v2_complete_knowledge_job",
            "geo_v2_fail_knowledge_job",
            "geo_v2_ack_knowledge_job_cancel",
            "geo_v2_replay_knowledge_job",
        ):
            self.assertIn(name, self.functions)
        self.assertIn("FOR UPDATE OF job SKIP LOCKED", self.functions["geo_v2_claim_knowledge_job"])
        self.assertIn("lease_expires_at <= statement_timestamp()", self.functions["geo_v2_claim_knowledge_job"])
        self.assertIn("lease_token = p_lease_token", self.sql)
        self.assertIn("knowledge job lease is lost or cancellation is pending", self.sql)
        self.assertIn("knowledge result hash does not match canonical payload", self.sql)

    def test_upstream_artifacts_and_quality_are_fail_closed(self) -> None:
        ready = self.functions["geo_v2_knowledge_job_inputs_ready"]
        self.assertIn("upstream.status <> 'succeeded'", ready)
        self.assertIn("artifact.artifact_status <> 'finalized'", ready)
        self.assertIn("governance.external_model_use_allowed", ready)
        self.assertIn("governance.confidentiality = 'restricted'", ready)
        self.assertIn("source_asset.current_governance_version_id", ready)

        complete = self.functions["geo_v2_complete_knowledge_job"]
        self.assertIn("geo_v2_knowledge_quality_certificate_complete", complete)
        self.assertIn("knowledge job artifacts are not finalized", complete)
        certificate = self.functions["geo_v2_knowledge_quality_certificate_complete"]
        self.assertIn("hard_block", certificate)
        self.assertIn("knowledge_risk_acceptances", certificate)
        self.assertIn("target_kind", certificate)

    def test_durable_dispatch_outbox_gets_a_typed_knowledge_extension(self) -> None:
        for marker in (
            "ADD COLUMN knowledge_pipeline_job_id uuid",
            "FOREIGN KEY (knowledge_pipeline_job_id, project_id)",
            "REFERENCES knowledge_pipeline_jobs(id, project_id)",
            "'knowledge_import'",
            "'knowledge_crawl'",
            "'knowledge_parse'",
            "'knowledge_chunk'",
            "'knowledge_embed'",
            "'knowledge_fact_extract'",
            "knowledge_pipeline_job_id = job_id",
            "AFTER INSERT ON knowledge_pipeline_jobs",
        ):
            self.assertIn(marker, self.sql)
        enqueue = self.functions["geo_v2_enqueue_durable_job_dispatch"]
        self.assertIn("'knowledge_' || NEW.job_type", enqueue)
        self.assertIn("knowledge_pipeline_job_id", enqueue)
        self.assertIn("canonical_payload_hash", enqueue)

    def test_security_definer_functions_pin_search_path_and_have_exact_owner_markers(self) -> None:
        definer_names = re.findall(
            r"CREATE(?: OR REPLACE)? FUNCTION ([a-z0-9_]+)\(.*?"
            r"SECURITY DEFINER.*?\$[a-z0-9_]+\$;",
            self.sql,
            flags=re.DOTALL,
        )
        self.assertGreaterEqual(len(definer_names), 25)
        for name in definer_names:
            with self.subTest(function=name):
                self.assertIn("SET search_path = pg_catalog", self.functions[name])

        for role_name in (
            "geo_v2_job_owner",
            "geo_v2_result_owner",
            "geo_v2_job_command_owner",
            "geo_v2_authz_owner",
            "geo_v2_worker",
        ):
            self.assertIn(role_name, self.sql)
        for marker in (
            "runtime or worker has forbidden",
            "$verify_knowledge_exact_owner_acls$",
            "unexpected % % privilege on %",
            "PUBLIC can execute a Schema v2 Knowledge function",
            "Schema v2 job roles must have no role memberships",
        ):
            self.assertIn(marker, self.sql)

        self.assertRegex(
            self.sql,
            r"(?s)GRANT EXECUTE ON FUNCTION geo_v2_claim_knowledge_job\(text, integer, uuid, text\).*?TO geo_v2_worker",
        )
        self.assertRegex(
            self.sql,
            r"(?s)GRANT EXECUTE ON FUNCTION geo_v2_create_knowledge_job\(.*?\).*?TO geo_v2_runtime",
        )
        self.assertNotRegex(self.sql, r"GRANT (?:SELECT|INSERT|UPDATE|DELETE).*?TO geo_v2_worker")

    def test_review_and_approved_projection_preserve_governance_lineage(self) -> None:
        review = self.functions["geo_v2_review_knowledge_fact_candidate"]
        for marker in (
            "producer_row.status <> 'succeeded'",
            "candidate submitter cannot approve or reject",
            "knowledge review idempotency conflict",
            "p_expected_current_version_id",
            "p_base_statement_hash",
            "knowledge_fact_version_sources",
            "source_asset.current_governance_version_id",
        ):
            self.assertIn(marker, review)

        approved = self.functions["geo_v2_read_approved_knowledge"]
        for marker in (
            "fact.status = 'active'",
            "version_row.id = fact.current_version_id",
            "source_asset.status = 'active'",
            "current_governance.id = source_asset.current_governance_version_id",
            "current_governance.public_adaptation_allowed",
            "current_governance.external_model_use_allowed",
            "p_publication_channel",
        ):
            self.assertIn(marker, approved)
        self.assertIn("geo_v2_create_knowledge_governance_version", self.functions)
        self.assertIn("geo_v2_set_knowledge_source_status", self.functions)
        self.assertIn("geo_v2_withdraw_knowledge_fact", self.functions)


if __name__ == "__main__":
    unittest.main()
