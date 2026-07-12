from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import patch

from geno_core.knowledge_pipeline import (
    DEFAULT_EMBEDDING_MODEL,
    JOB_TABLES,
    KnowledgePipelineRepository,
    PIPELINE_STAGE_KEYS,
    GeoParserAdapter,
    archive_knowledge_source_asset,
    deterministic_embedding,
    payload_hash,
    precheck_knowledge_source,
    source_config_text,
)
from geno_core.knowledge_application import deepseek_generate_knowledge_application
from workers.knowledge_worker.run_knowledge_pipeline import (
    CRAWL_MIN_SUCCESS_PAGES,
    CRAWL_MIN_SUCCESS_RATIO,
    EMBEDDING_MIN_SUCCESS_RATIO,
    FACT_MIN_CANDIDATE_COUNT,
    _chunk_quality_flags,
    _ensure_target_brand_in_markdown,
    _parser_quality_findings,
)


class KnowledgePipelineContractTest(unittest.TestCase):
    @staticmethod
    def _psycopg_modules() -> dict[str, ModuleType]:
        psycopg_module = ModuleType("psycopg")
        rows_module = ModuleType("psycopg.rows")
        rows_module.dict_row = object()  # type: ignore[attr-defined]
        psycopg_module.rows = rows_module  # type: ignore[attr-defined]
        return {"psycopg": psycopg_module, "psycopg.rows": rows_module}

    def test_stage_contract_uses_quality_summary_and_virtual_ocr_table_stages(self) -> None:
        self.assertIn("quality_summary", PIPELINE_STAGE_KEYS)
        self.assertIn("ocr", PIPELINE_STAGE_KEYS)
        self.assertIn("table_extract", PIPELINE_STAGE_KEYS)
        self.assertNotIn("quality_check", PIPELINE_STAGE_KEYS)

    def test_generated_content_markdown_always_names_target_brand(self) -> None:
        self.assertEqual(
            _ensure_target_brand_in_markdown(
                "## Delivery\n\nFree metro delivery over AUD 99.",
                target_brand="KoalaHome",
                title="KoalaHome GEO FAQ draft",
            ),
            "# KoalaHome GEO FAQ draft\n\n## Delivery\n\nFree metro delivery over AUD 99.",
        )
        existing = "## KoalaHome delivery\n\nFree metro delivery over AUD 99."
        self.assertEqual(
            _ensure_target_brand_in_markdown(
                existing,
                target_brand="KoalaHome",
                title="KoalaHome GEO FAQ draft",
            ),
            existing,
        )

    def test_production_contract_migration_covers_parser_template_and_rls_fields(self) -> None:
        consolidation = Path(
            "infra/db/migrations/up/0027_knowledge_pipeline_consolidation.sql"
        ).read_text(encoding="utf-8")
        migration = Path("infra/db/migrations/up/0028_knowledge_pipeline_production_contract.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn("pg_get_constraintdef(oid) LIKE '%published%'", consolidation)
        self.assertNotIn("'active', '{\"intent_type\"", consolidation)
        for required in (
            "precheck_result",
            "fallback_reason",
            "output_asset_ids",
            "prompt_generation_templates_status_check",
            "CHECK (status IN ('draft', 'published', 'archived'))",
            "knowledge_quality_gates_runtime_read",
            "knowledge_quality_gates_runtime_manage",
        ):
            self.assertIn(required, migration)
        drop_constraint = migration.index(
            "DROP CONSTRAINT IF EXISTS prompt_generation_templates_status_check"
        )
        migrate_status = migration.index(
            "SET status = CASE WHEN status = 'active' THEN 'published' ELSE status END"
        )
        add_constraint = migration.index(
            "ADD CONSTRAINT prompt_generation_templates_status_check"
        )
        self.assertLess(drop_constraint, migrate_status)
        self.assertLess(migrate_status, add_constraint)

    def test_mineru_reproducible_requirements_include_runtime_geometry_dependencies(self) -> None:
        requirements = Path("apps/api/knowledge-heavy/mineru-requirements.txt").read_text(encoding="utf-8")
        self.assertIn("pyclipper==1.4.0", requirements)
        self.assertIn("shapely==2.1.2", requirements)

    def test_heavy_runtime_pins_compatible_cpu_models_and_container_safe_paths(self) -> None:
        dockerfile = Path("workers/knowledge_worker/Dockerfile.heavy").read_text(encoding="utf-8")
        docling = Path("apps/api/knowledge-heavy/docling-requirements.txt").read_text(encoding="utf-8")
        smoke = Path("scripts/run_knowledge_heavy_components_smoke.py").read_text(encoding="utf-8")
        self.assertIn("docling==2.111.0", docling)
        self.assertIn("torch==2.6.0 torchvision==0.21.0", dockerfile)
        self.assertIn("torch==2.6.0", dockerfile)
        self.assertIn("libgl1", dockerfile)
        self.assertIn("TIKA_SERVER_JAR=file:///opt/tika/tika-server-standard.jar", dockerfile)
        self.assertIn("TIKA_LOG_PATH=/tmp/geo-tika", dockerfile)
        self.assertNotIn("ROOT.parents[2]", smoke)

    def test_db_polling_job_tables_are_explicit_not_universal_queue(self) -> None:
        self.assertIn("knowledge_import_jobs", JOB_TABLES)
        self.assertIn("knowledge_parser_runs", JOB_TABLES)
        self.assertIn("embedding_jobs", JOB_TABLES)
        self.assertNotIn("jobs", JOB_TABLES)

    def test_prompt_generation_uses_runtime_prompt_table_and_failure_recovery_rolls_back(self) -> None:
        worker = Path("workers/knowledge_worker/run_knowledge_pipeline.py").read_text(encoding="utf-8")
        repository = Path("packages/geno_core/geno_core/knowledge_pipeline.py").read_text(encoding="utf-8")
        self.assertIn("SELECT text FROM prompt_questions", worker)
        self.assertNotIn("SELECT text FROM prompts ", worker)
        fail_job = repository[repository.index("    def fail_job(") : repository.index("    def run_ready_pipeline_once(")]
        self.assertIn("self.connection.rollback()", fail_job)

    def test_live_knowledge_e2e_respects_api_page_size_contract(self) -> None:
        script = Path("scripts/run_knowledge_pipeline_live_e2e.py").read_text(encoding="utf-8")
        self.assertNotIn('"limit": 300', script)
        self.assertNotIn('"limit": 500', script)
        self.assertIn("def _run_worker_until_pipeline_ready(", script)
        self.assertIn("pending_count == 0", script)
        self.assertIn("job_statuses={job_statuses}", script)

    def test_pipeline_scheduler_never_runs_unstarted_or_already_running_pipeline(self) -> None:
        repository = Path("packages/geno_core/geno_core/knowledge_pipeline.py").read_text(encoding="utf-8")
        self.assertIn("AND status IN ('queued', 'running', 'waiting_human_review')", repository)
        self.assertIn("WHERE status = 'queued'", repository)
        self.assertNotIn("WHERE status IN ('queued', 'running')", repository)

    def test_full_rebuild_enqueues_prompt_and_content_generation_after_fact_review(self) -> None:
        repository = Path("packages/geno_core/geno_core/knowledge_pipeline.py").read_text(encoding="utf-8")
        self.assertIn('in {"full_ingestion", "full_rebuild"}', repository)
        self.assertIn('{"full_ingestion", "full_rebuild", "prompt_generation"}', repository)
        self.assertIn('{"full_ingestion", "full_rebuild", "content_generation"}', repository)

    def test_deepseek_generation_retries_invalid_json_content_once(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_post(
            endpoint: str,
            *,
            headers: dict[str, str],
            payload: dict[str, object],
            timeout_seconds: float,
        ) -> dict[str, object]:
            calls.append(payload)
            content = "truncated response" if len(calls) == 1 else json.dumps(
                {"content_markdown": "Grounded content", "prompt_candidates": [{"text": "Grounded Prompt"}]}
            )
            return {
                "status_code": 200,
                "body": json.dumps({"choices": [{"message": {"content": content}}]}).encode(),
                "charset": "utf-8",
            }

        output = deepseek_generate_knowledge_application(
            api_key="test-key",
            target_brand="KoalaHome",
            category="homewares",
            market_code="AU",
            facts=(),
            prompts=(),
            generation_type="prompt_candidates",
            content_type="prompt",
            target_platform="chatgpt",
            intent_type="brand_visibility",
            city="Sydney",
            competitor=None,
            quantity=1,
            http_post=fake_post,
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(output["prompt_candidates"][0]["text"], "Grounded Prompt")
        self.assertEqual(calls[1]["max_tokens"], 4096)

    def test_rechunk_version_invalidation_serializes_pipeline_uuid_as_text(self) -> None:
        worker = Path("workers/knowledge_worker/run_knowledge_pipeline.py").read_text(encoding="utf-8")
        self.assertEqual(
            worker.count('"replacement_pipeline_run_id": str(job.get("pipeline_run_id") or "")'),
            2,
        )

    def test_parser_adapter_outputs_geo_contract(self) -> None:
        output = GeoParserAdapter().parse(text="First fact. Second fact.", source_asset_id="asset-1")
        self.assertEqual(output["adapter"]["adapter_version"], "geo-parser-adapter-v1")
        self.assertGreaterEqual(len(output["blocks"]), 1)
        self.assertIn("quality_signals", output)

    def test_parser_adapter_routes_binary_sources_through_real_adapter_contract(self) -> None:
        output = GeoParserAdapter().parse_bytes(
            content=b"# KoalaHome\n\nFree metro delivery over A$99.",
            filename="koalahome.md",
            content_type="text/markdown",
            source_asset_id="asset-1",
            requested_engine="auto",
        )
        self.assertEqual(output["adapter"]["adapter_version"], "geo-parser-adapter-v1")
        self.assertIn(output["adapter"]["engine"], {"markitdown", "unstructured", "tika", "text_fallback"})
        self.assertGreaterEqual(len(output["blocks"]), 1)

    def test_csv_parser_emits_normalized_table_contract(self) -> None:
        output = GeoParserAdapter().parse_bytes(
            content=b"subject,predicate,value\nKoalaHome,returns,30 days\n",
            filename="facts.csv",
            content_type="text/csv",
            source_asset_id="asset-csv",
            requested_engine="markitdown",
        )
        self.assertEqual(output["adapter"]["engine"], "python_csv")
        self.assertEqual(output["tables"][0]["row_count"], 2)
        self.assertEqual(output["tables"][0]["column_count"], 3)
        self.assertEqual(output["tables"][0]["table_json"]["rows"][1][0], "KoalaHome")
        self.assertTrue(any(item.get("artifact_type") == "parser_markdown" for item in output["artifacts"]))

    def test_binary_parser_failure_never_decodes_pdf_as_plain_text(self) -> None:
        adapter = GeoParserAdapter()
        failure = RuntimeError("adapter unavailable")
        with (
            patch.object(adapter, "_parse_with_docling", side_effect=failure),
            patch.object(adapter, "_parse_with_mineru", side_effect=failure),
            patch.object(adapter, "_parse_with_tika", side_effect=failure),
            patch.object(adapter, "_parse_with_markitdown", side_effect=failure),
            patch.object(adapter, "parse") as plain_text_parse,
        ):
            with self.assertRaisesRegex(RuntimeError, "all production parser adapters failed"):
                adapter.parse_bytes(
                    content=b"%PDF-1.4 binary payload",
                    filename="brand-manual.pdf",
                    content_type="application/pdf",
                    source_asset_id="asset-pdf",
                    requested_engine="auto",
                )
        plain_text_parse.assert_not_called()

    def test_empty_adapter_output_falls_through_to_next_real_adapter(self) -> None:
        adapter = GeoParserAdapter()
        empty = {
            "adapter": {"engine": "markitdown"},
            "blocks": [],
            "tables": [],
            "ocr_spans": [],
        }
        usable = {
            "adapter": {"engine": "unstructured"},
            "blocks": [{"text": "Source-backed delivery policy"}],
            "tables": [],
            "ocr_spans": [],
        }
        with (
            patch.object(adapter, "_parse_with_markitdown", return_value=empty),
            patch.object(adapter, "_parse_with_unstructured", return_value=usable),
        ):
            output = adapter.parse_bytes(
                content=b"delivery policy",
                filename="policy.md",
                content_type="text/markdown",
                source_asset_id="asset-1",
            )
        self.assertEqual(output["adapter"]["engine"], "unstructured")
        self.assertEqual(output["adapter"]["fallback_from_engines"], ["markitdown"])
        self.assertTrue(any(item["code"] == "adapter_fallback_used" for item in output["quality_signals"]))

    def test_source_precheck_blocks_secrets_and_unsupported_files(self) -> None:
        secret = precheck_knowledge_source(
            filename="connector.txt",
            content=b"api_key=sk-production-secret-value-123456",
            content_type="text/plain",
        )
        unsupported = precheck_knowledge_source(
            filename="archive.exe",
            content=b"binary",
            content_type="application/octet-stream",
        )
        self.assertFalse(secret["accepted"])
        self.assertIn("possible_secret", {item["code"] for item in secret["findings"]})
        self.assertFalse(unsupported["accepted"])
        self.assertIn("unsupported_file_type", {item["code"] for item in unsupported["findings"]})

    def test_source_precheck_recommends_ocr_and_warns_on_pii(self) -> None:
        image = precheck_knowledge_source(
            filename="scan.png",
            content=b"\x89PNG\r\n\x1a\n",
            content_type="image/png",
        )
        text = precheck_knowledge_source(
            filename="contacts.md",
            content=b"Support: customer@example.com",
            content_type="text/markdown",
        )
        self.assertEqual(image["recommended_adapter"], "mineru")
        self.assertTrue(image["requires_ocr"])
        self.assertTrue(text["accepted"])
        self.assertIn("possible_pii", {item["code"] for item in text["findings"]})

    def test_source_text_contract_accepts_frontend_and_direct_api_field_names(self) -> None:
        for field_name in ("text", "pasted_text", "raw_text", "csv_content"):
            with self.subTest(field_name=field_name):
                self.assertEqual(source_config_text({field_name: "  source-backed fact  "}), "source-backed fact")
        self.assertEqual(source_config_text({"text": "", "csv_content": "a,b\n1,2"}), "a,b\n1,2")

    def test_partial_success_thresholds_match_production_plan(self) -> None:
        self.assertEqual(CRAWL_MIN_SUCCESS_PAGES, 1)
        self.assertEqual(CRAWL_MIN_SUCCESS_RATIO, 0.3)
        self.assertEqual(EMBEDDING_MIN_SUCCESS_RATIO, 0.8)
        self.assertEqual(FACT_MIN_CANDIDATE_COUNT, 1)

    def test_archive_knowledge_source_asset_uses_object_store_contract(self) -> None:
        class Store:
            def put_object(self, *, key: str, content: bytes, content_type: str, expected_hash: str):
                self.key = key
                self.content = content
                self.content_type = content_type
                self.expected_hash = expected_hash
                return type(
                    "Stored",
                    (),
                    {
                        "uri": f"s3://geo-test/{key}",
                        "bucket": "geo-test",
                        "key": key,
                        "content_type": content_type,
                        "content_hash": expected_hash,
                        "etag": "etag-test",
                    },
                )()

        store = Store()
        stored = archive_knowledge_source_asset(
            project_id="project-1",
            pipeline_run_id="run-1",
            import_job_id="job-1",
            filename="品牌 手册.pdf",
            content=b"manual",
            content_type="application/pdf",
            store=store,  # type: ignore[arg-type]
        )
        self.assertIn("knowledge-source-assets/project-1/run-1/job-1/", stored.key)
        self.assertTrue(stored.key.endswith("-pdf") or ".pdf" in stored.key)
        self.assertEqual(store.content, b"manual")

    def test_embedding_contract_defaults_to_bge_m3_with_deterministic_fallback(self) -> None:
        self.assertEqual(DEFAULT_EMBEDDING_MODEL, "BAAI/bge-m3")
        vector = deterministic_embedding("KoalaHome delivery")
        self.assertEqual(len(vector), 1024)
        self.assertEqual(vector, deterministic_embedding("KoalaHome delivery"))

    def test_payload_hash_is_stable(self) -> None:
        self.assertEqual(payload_hash({"b": 2, "a": 1}), payload_hash({"a": 1, "b": 2}))

    def test_chunk_quality_detects_structure_topic_and_language_problems(self) -> None:
        flags = _chunk_quality_flags(
            "Shipping delivery returns refunds pricing discount warranty support privacy cookie policy",
            source_present=True,
            chunk_type="text",
            duplicate=False,
            locale="zh-CN",
        )
        self.assertIn("chunk_mixed_topics", flags)
        self.assertIn("chunk_language_mismatch", flags)
        self.assertIn("chunk_contains_navigation", flags)

    def test_parser_quality_detects_empty_and_garbled_outputs(self) -> None:
        empty = _parser_quality_findings({"blocks": [], "pages": [], "tables": [], "ocr_spans": []})
        garbled = _parser_quality_findings(
            {
                "blocks": [{"block_index": 1, "text": "bad����text", "page_number": None}],
                "pages": [{"page_number": 1}],
                "tables": [],
                "ocr_spans": [],
            }
        )
        self.assertIn("parser_empty_text", {finding["finding_type"] for finding in empty})
        self.assertIn("parser_garbled_text", {finding["finding_type"] for finding in garbled})
        self.assertIn("parser_missing_page_number", {finding["finding_type"] for finding in garbled})

    def test_filtered_chunk_query_uses_whitelisted_parameterized_sql(self) -> None:
        class Cursor:
            def __init__(self, statements: list[tuple[str, tuple[object, ...]]]) -> None:
                self.statements = statements
                self.last_statement = ""

            def __enter__(self) -> "Cursor":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def execute(self, statement: str, params: tuple[object, ...]) -> None:
                self.last_statement = statement
                self.statements.append((statement, params))

            def fetchone(self) -> dict[str, object]:
                return {"total_count": 1}

            def fetchall(self) -> list[dict[str, object]]:
                return [{"id": "chunk-1", "text": "delivery policy"}]

        class Connection:
            def __init__(self) -> None:
                self.statements: list[tuple[str, tuple[object, ...]]] = []

            def cursor(self, **_kwargs: object) -> Cursor:
                return Cursor(self.statements)

        connection = Connection()
        with patch.dict(sys.modules, self._psycopg_modules()):
            page = KnowledgePipelineRepository(connection).list_chunks(
                project_id="11111111-1111-1111-1111-111111111111",
                limit=20,
                offset=0,
                filters={
                    "import_job_id": "22222222-2222-2222-2222-222222222222",
                    "status": "active",
                },
                quality_flag="chunk_duplicate",
                query="delivery",
            )
        rendered = "\n".join(statement for statement, _ in connection.statements)
        self.assertEqual(page["total_count"], 1)
        self.assertIn("t.import_job_id = %s::uuid", rendered)
        self.assertIn("%s = ANY(t.quality_flags)", rendered)
        self.assertIn("t.text ILIKE %s", rendered)
        self.assertNotIn("delivery policy'", rendered)

    def test_upload_contract_reuses_duplicate_objects_and_details_are_aggregated(self) -> None:
        api_source = Path("apps/api/geno_api/main.py").read_text(encoding="utf-8")
        repository_source = Path("packages/geno_core/geno_core/knowledge_pipeline.py").read_text(encoding="utf-8")
        live_e2e_source = Path("scripts/run_knowledge_pipeline_live_e2e.py").read_text(encoding="utf-8")
        full_smoke_source = Path("scripts/run_geo_production_full_pipeline_smoke.py").read_text(encoding="utf-8")
        self.assertIn("knowledge_repository.reuse_source_asset(", api_source)
        self.assertNotIn('precheck["accepted"] = False', api_source)
        self.assertIn("get_pipeline_run_detail", api_source)
        self.assertIn("get_import_job_detail", api_source)
        self.assertIn("quality_gate_runs", repository_source)
        self.assertIn("knowledge.pipeline_run_queued", repository_source)
        self.assertIn("duplicate file reuses stored object", live_e2e_source)
        self.assertIn("pasted_text and csv_content direct API prechecks pass", live_e2e_source)
        self.assertIn("chunk source/status/type/text filters", live_e2e_source)
        self.assertIn("version_invalidation_observed", live_e2e_source)
        self.assertIn("版本变化标记 stale/needs_reextract", live_e2e_source)
        self.assertIn("live operational contracts", full_smoke_source)

    def test_maintenance_scope_disables_runtime_project_rls_for_worker_session(self) -> None:
        class Cursor:
            def __init__(self, statements: list[tuple[str, tuple[object, ...]]]) -> None:
                self.statements = statements

            def __enter__(self) -> "Cursor":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
                self.statements.append((sql, params))

        class Connection:
            def __init__(self) -> None:
                self.statements: list[tuple[str, tuple[object, ...]]] = []

            def cursor(self) -> Cursor:
                return Cursor(self.statements)

            def commit(self) -> None:
                self.statements.append(("COMMIT", ()))

        connection = Connection()
        KnowledgePipelineRepository(connection).set_maintenance_scope(worker_id="knowledge-worker")
        rendered = "\n".join(statement for statement, _ in connection.statements)
        self.assertIn("app.rls_enabled", rendered)
        self.assertIn("geno.runtime_project_access_control", rendered)
        self.assertIn("'false'", rendered)

    def test_pipeline_job_tables_include_generation_jobs_but_no_global_queue(self) -> None:
        self.assertIn("fact_extraction_jobs", JOB_TABLES)
        self.assertIn("prompt_generation_jobs", JOB_TABLES)
        self.assertIn("content_generation_jobs", JOB_TABLES)
        self.assertNotIn("knowledge_pipeline_runs", JOB_TABLES)

    def test_quality_risk_acceptance_requires_timezone_and_future_expiry(self) -> None:
        repository = KnowledgePipelineRepository(object())
        with self.assertRaisesRegex(ValueError, "timezone"):
            repository.accept_quality_gate_risk(
                project_id="project-1",
                gate_run_id="gate-1",
                accepted_by="operator-1",
                reason="temporary parser tolerance",
                expires_at=datetime(2030, 1, 1),
            )
        with self.assertRaisesRegex(ValueError, "future"):
            repository.accept_quality_gate_risk(
                project_id="project-1",
                gate_run_id="gate-1",
                accepted_by="operator-1",
                reason="temporary parser tolerance",
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
            )

    def test_pipeline_start_is_idempotent_while_already_queued_or_running(self) -> None:
        class Cursor:
            def __init__(self, row: dict[str, object]) -> None:
                self.row = row
                self.statements: list[str] = []

            def __enter__(self) -> "Cursor":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def execute(self, statement: str, _params: tuple[object, ...]) -> None:
                self.statements.append(statement)

            def fetchone(self) -> dict[str, object]:
                return self.row

        class Connection:
            def __init__(self, row: dict[str, object]) -> None:
                self.cursor_value = Cursor(row)

            def cursor(self, **_kwargs: object) -> Cursor:
                return self.cursor_value

        running = {"id": "run-1", "status": "running", "project_id": "project-1"}
        connection = Connection(running)
        with patch.dict(sys.modules, self._psycopg_modules()):
            result = KnowledgePipelineRepository(connection).start_pipeline_run("run-1")
        self.assertEqual(result, running)
        self.assertEqual(len(connection.cursor_value.statements), 1)

    def test_completed_pipeline_requires_a_new_versioned_rerun(self) -> None:
        class Cursor:
            def __enter__(self) -> "Cursor":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def execute(self, _statement: str, _params: tuple[object, ...]) -> None:
                return None

            def fetchone(self) -> dict[str, object]:
                return {"id": "run-1", "status": "succeeded", "project_id": "project-1"}

        class Connection:
            def cursor(self, **_kwargs: object) -> Cursor:
                return Cursor()

        with patch.dict(sys.modules, self._psycopg_modules()):
            with self.assertRaisesRegex(ValueError, "create a versioned rerun"):
                KnowledgePipelineRepository(Connection()).start_pipeline_run("run-1")


if __name__ == "__main__":
    unittest.main()
