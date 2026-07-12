from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def _run(command: list[str], *, env: dict[str, str]) -> dict[str, object]:
    completed = subprocess.run(command, env=env, text=True, capture_output=True, check=False)
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-2000:],
        "stderr_tail": completed.stderr[-2000:],
    }


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _load_artifact(path: Path, *, label: str) -> tuple[dict[str, object] | None, dict[str, object]]:
    if not path.is_file():
        return None, {"name": label, "returncode": 1, "missing": [f"artifact not found: {path}"]}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, {"name": label, "returncode": 1, "missing": [f"invalid artifact: {exc}"]}
    result = dict(loaded) if isinstance(loaded, dict) else None
    status = str((result or {}).get("status") or "")
    return result, {
        "name": label,
        "returncode": 0 if status in {"pass", "passed"} else 1,
        "artifact": str(path),
        "status": status or "missing",
    }


def _contains(path: str, *needles: str) -> dict[str, object]:
    content = _read(path)
    missing = [needle for needle in needles if needle not in content]
    return {
        "name": path,
        "returncode": 0 if not missing else 1,
        "missing": missing,
        "checked": len(needles),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the GEO knowledge production full-pipeline smoke suite.")
    parser.add_argument("--skip-qdrant", action="store_true")
    parser.add_argument("--skip-live", action="store_true")
    parser.add_argument("--skip-heavy-components", action="store_true")
    parser.add_argument("--reuse-qdrant-artifact")
    parser.add_argument("--reuse-live-artifact")
    parser.add_argument("--reuse-heavy-artifact")
    parser.add_argument("--api-base", default=os.getenv("GENO_LIVE_API_BASE", "http://localhost:18003"))
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://localhost:18006"))
    parser.add_argument("--artifact", default="/tmp/geo-production-full-pipeline-smoke.json")
    args = parser.parse_args(argv)
    run_id = f"geo-full-pipeline-{uuid4().hex}"
    started_at = datetime.now(UTC)
    env = os.environ.copy()
    checks: list[dict[str, object]] = []
    checks.extend(
        [
            _contains(
                "infra/db/migrations/up/0023_knowledge_pipeline_orchestration.sql",
                "knowledge_pipeline_runs",
                "knowledge_pipeline_stages",
                "knowledge_import_jobs",
                "crawl_jobs",
                "knowledge_source_assets",
                "knowledge_parser_runs",
                "chunk_jobs",
                "embedding_jobs",
                "knowledge_blocks",
                "knowledge_tables",
                "knowledge_ocr_spans",
                "knowledge_page_snapshots",
                "knowledge_chunks",
                "fact_extraction_jobs",
                "knowledge_fact_candidates",
                "localized_knowledge_facts",
                "prompt_generation_jobs",
                "content_generation_jobs",
                "knowledge_trace_refs",
                "knowledge_quality_findings",
                "knowledge_quality_gate_runs",
                "quality_summary",
                "superseded",
                "needs_reextract",
                "accepted_risk",
            ),
            _contains(
                "infra/db/migrations/up/0028_knowledge_pipeline_production_contract.sql",
                "parser_strategy",
                "precheck_result",
                "fallback_reason",
                "prompt_generation_templates_status_check",
                "published",
                "knowledge_quality_gates_runtime_manage",
            ),
            _contains(
                "packages/geno_core/geno_core/knowledge_pipeline.py",
                "PIPELINE_STAGE_KEYS",
                "JOB_TABLES",
                "archive_knowledge_source_asset",
                "create_asset_from_stored_object",
                "create_parser_artifact_asset",
                "parse_bytes",
                "_parse_with_docling",
                "_parse_with_unstructured",
                "_parse_with_tika",
                "_parse_with_markitdown",
                "set_maintenance_scope",
                "source_config_text",
                "reuse_source_asset",
                "get_pipeline_run_detail",
                "get_import_job_detail",
                "review_fact_candidate",
                "enqueue_generation_for_approved_facts",
                "QdrantKnowledgeStore",
                "LocalBgeM3Embedder",
                "GeoParserAdapter",
                "crawl_with_crawl4ai",
                "refresh_project_pipeline_states",
                "geo_knowledge_chunks_bge_m3_v1",
            ),
            _contains(
                "workers/knowledge_worker/run_knowledge_pipeline.py",
                "_process_import_job",
                "_process_crawl_job",
                "_process_parser_run",
                "_load_asset_bytes",
                "build_object_store_from_env",
                "create_parser_artifact_asset",
                "_process_chunk_job",
                "_process_embedding_job",
                "_process_fact_extraction_job",
                "_process_prompt_generation_job",
                "_process_content_generation_job",
                "deepseek_extract_knowledge_facts",
                "deepseek_generate_knowledge_application",
                "knowledge_trace_refs",
                "waiting_human_review",
                "embedding_backend",
                "parser_quality_gate",
                "traceability_gate",
            ),
            _contains(
                "apps/api/geno_api/main.py",
                "/v1/knowledge/pipeline-runs/runtime",
                "/v1/knowledge/import-jobs/runtime",
                "/v1/knowledge/import-jobs/runtime/{import_job_id}/files",
                "/v1/knowledge/parser-runs/runtime",
                "/v1/knowledge/blocks/runtime",
                "/v1/knowledge/tables/runtime",
                "/v1/knowledge/ocr-spans/runtime",
                "/v1/knowledge/page-snapshots/runtime",
                "/v1/knowledge/source-assets/runtime/{source_asset_id}/download",
                "_parse_multipart_form",
                "multipart/form-data",
                "archive_knowledge_source_asset",
                "/v1/knowledge/fact-candidates/runtime",
                "/v1/knowledge/prompt-candidates/runtime",
                "/v1/knowledge/content-drafts/runtime",
                "review_runtime_knowledge_fact_candidate",
            ),
            _contains(
                "apps/admin-web/app/projects/[project_id]/ProjectActions.tsx",
                "KnowledgePipelineCreateForm",
                "type=\"file\"",
                "source_files",
                "multiple",
                "knowledgeFileQueue",
                "Docling",
                "MinerU",
                "KnowledgeFactCandidateReviewForm",
                "KnowledgeFactExtractionForm",
                "PromptGenerationPanel",
                "reviewKnowledgeFactCandidateAction",
            ),
            _contains(
                "apps/admin-web/app/projects/[project_id]/actions.ts",
                "runtimeMultipartRequest",
                "source_files",
                "defer_start",
                "/v1/knowledge/import-jobs/runtime/",
                "/files",
            ),
            _contains(
                "apps/admin-web/app/projects/[project_id]/page.tsx",
                "KnowledgeProcessingPanel",
                "KnowledgeChunksPanel",
                "KnowledgeTracePanel",
                "/v1/knowledge/parser-runs/runtime",
                "/v1/knowledge/blocks/runtime",
                "knowledgeChunkWorkbench",
                "chunk_quality_flag",
                "factCandidates",
                "qualityGateRuns",
            ),
            _contains(
                "scripts/run_knowledge_pipeline_live_e2e.py",
                "duplicate file reuses stored object",
                "pasted_text and csv_content direct API prechecks pass",
                "pipeline detail aggregates stages jobs assets chunks gates candidates summaries and audit",
                "chunk source/status/type/text filters return the requested chunk",
                "version_invalidation_observed",
                "版本变化标记 stale/needs_reextract",
                '"operational_checks": operational_checks',
            ),
            _contains(
                "scripts/run_frontend_page_click_smoke.py",
                "chunk_query=delivery",
                "source_fact_kind",
                "source-backed Prompt generation scope",
                "source-linked GEO content generation controls",
            ),
            _contains(
                "scripts/run_frontend_knowledge_lifecycle_smoke.py",
                "frontend_import_precheck_and_start",
                "frontend_fact_candidate_review",
                "frontend_prompt_review_and_import",
                "frontend_content_review_and_export",
                "frontend_knowledge_search",
                "run_knowledge_pipeline.py",
            ),
            _contains(
                "infra/docker-compose.yml",
                "qdrant:",
                "knowledge-worker:",
                "GENO_DEEPSEEK_API_KEY_FILE",
                "QDRANT_URL",
                "deepseek_api_key.txt",
            ),
        ]
    )
    heavy_artifact_path = Path(args.reuse_heavy_artifact or "/tmp/geo-knowledge-heavy-components-full.json")
    heavy_result: dict[str, object] | None = None
    if args.reuse_heavy_artifact:
        heavy_result, heavy_check = _load_artifact(heavy_artifact_path, label="reused heavy component artifact")
        checks.append(heavy_check)
    elif not args.skip_heavy_components:
        heavy_check = _run(
            [
                sys.executable,
                str(ROOT / "scripts/run_knowledge_heavy_components_smoke.py"),
                "--artifact",
                str(heavy_artifact_path),
            ],
            env=env,
        )
        checks.append(heavy_check)
        if heavy_artifact_path.exists():
            loaded = json.loads(heavy_artifact_path.read_text(encoding="utf-8"))
            heavy_result = dict(loaded) if isinstance(loaded, dict) else None
    qdrant_result: dict[str, object] | None = None
    if args.reuse_qdrant_artifact:
        qdrant_result, qdrant_check = _load_artifact(
            Path(args.reuse_qdrant_artifact),
            label="reused Qdrant artifact",
        )
        checks.append(qdrant_check)
    elif not args.skip_qdrant:
        qdrant_check = _run([sys.executable, str(ROOT / "scripts/run_knowledge_qdrant_smoke.py")], env=env)
        checks.append(qdrant_check)
        default_qdrant_artifact = ROOT / "tmp/knowledge-qdrant-smoke-latest.json"
        if default_qdrant_artifact.is_file():
            qdrant_result, _ = _load_artifact(default_qdrant_artifact, label="Qdrant artifact")
    live_artifact_path = Path(args.reuse_live_artifact or "/tmp/geo-knowledge-live-e2e.json")
    live_result: dict[str, object] | None = None
    if args.reuse_live_artifact:
        live_result, live_check = _load_artifact(live_artifact_path, label="reused live pipeline artifact")
        checks.append(live_check)
    elif not args.skip_live:
        live_check = _run(
            [
                sys.executable,
                str(ROOT / "scripts/run_knowledge_pipeline_live_e2e.py"),
                "--api-base",
                args.api_base,
                "--qdrant-url",
                args.qdrant_url,
                "--artifact",
                str(live_artifact_path),
            ],
            env=env,
        )
        checks.append(live_check)
        if live_artifact_path.exists():
            loaded = json.loads(live_artifact_path.read_text(encoding="utf-8"))
            live_result = dict(loaded) if isinstance(loaded, dict) else None
    live_acceptance = list((live_result or {}).get("acceptance_checks") or [])
    live_acceptance_passed = bool(live_acceptance) and len(live_acceptance) == 36 and all(
        bool(item.get("passed")) for item in live_acceptance if isinstance(item, dict)
    )
    live_operational = list((live_result or {}).get("operational_checks") or [])
    live_operational_passed = bool(live_operational) and all(
        bool(item.get("passed")) for item in live_operational if isinstance(item, dict)
    )
    if not args.skip_live and not live_acceptance_passed:
        checks.append(
            {
                "name": "36-item live acceptance",
                "returncode": 1,
                "missing": [
                    item.get("name")
                    for item in live_acceptance
                    if isinstance(item, dict) and not item.get("passed")
                ] or ["live artifact missing exactly 36 passing acceptance checks"],
            }
        )
    if not args.skip_live and not live_operational_passed:
        checks.append(
            {
                "name": "live operational contracts",
                "returncode": 1,
                "missing": [
                    item.get("name")
                    for item in live_operational
                    if isinstance(item, dict) and not item.get("passed")
                ] or ["live artifact missing passing operational contract checks"],
            }
        )
    passed = all(item["returncode"] == 0 for item in checks)
    checklist = [
        "pipeline schema and stage contract present",
        "file/url/text/csv ingestion job contract present",
        "multipart file upload and object store archive contract present",
        "real parser adapter routing contract present",
        "parse/OCR/table virtual stage contract present",
        "chunk and BGE-M3 embedding contract present",
        "Qdrant payload filter contract present",
        "fact candidate extraction and human review contract present",
        "approved fact gate before Prompt/content generation present",
        "Prompt candidate generation/review contract present",
        "GEO content draft generation/review contract present",
        "knowledge_trace_refs evidence chain contract present",
        "quality findings/gate run contract present",
        "frontend import/processing/chunk/quality/trace entry points present",
        "Docling/MinerU/Unstructured/MarkItDown/Tika/Crawl4AI/BGE-M3 real component pass" if not args.skip_heavy_components else "heavy components skipped by explicit flag",
        "Qdrant smoke pass" if not args.skip_qdrant else "Qdrant smoke skipped by explicit flag",
        "real import-to-approved-Prompt/content pipeline pass" if not args.skip_live else "live pipeline skipped by explicit flag",
        "duplicate/precheck/detail/filter operational contracts pass" if not args.skip_live else "live operational contracts skipped by explicit flag",
    ]
    artifact = {
        "status": "pass" if passed else "fail",
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "checks": checks,
        "checklist": checklist,
        "live_pipeline": live_result,
        "heavy_components": heavy_result,
        "qdrant": qdrant_result,
    }
    artifact_path = Path(args.artifact)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(artifact, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
