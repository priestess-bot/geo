from __future__ import annotations

import argparse
import base64
import binascii
import csv
import html
import io
import json
import os
import re
import sys
import time
from typing import Any

from geno_core.durable_jobs import LeaseClaim, LeaseFencedConnection, LeaseGuard, LostLeaseError
from geno_core.knowledge_application import (
    crawl_public_knowledge_url,
    deepseek_extract_knowledge_facts,
    deepseek_generate_knowledge_application,
    load_deepseek_api_key,
    normalize_knowledge_url,
)
from geno_core.knowledge_pipeline import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_MODEL_VERSION,
    DEFAULT_QDRANT_COLLECTION,
    GeoParserAdapter,
    KnowledgePipelineRepository,
    LocalBgeM3Embedder,
    QdrantKnowledgeStore,
    close_knowledge_repository,
    connect_knowledge_pipeline_repository,
    content_hash,
    crawl_with_crawl4ai,
    precheck_knowledge_source,
    source_config_text,
    stable_pipeline_id,
)
from geno_core.object_store import ObjectStoreError, parse_s3_uri
from geno_core.runtime import build_object_store_from_env


CRAWL_MIN_SUCCESS_PAGES = max(1, int(os.getenv("GEO_CRAWL_MIN_SUCCESS_PAGES", "1")))
CRAWL_MIN_SUCCESS_RATIO = min(1.0, max(0.0, float(os.getenv("GEO_CRAWL_MIN_SUCCESS_RATIO", "0.3"))))
EMBEDDING_MIN_SUCCESS_RATIO = min(1.0, max(0.0, float(os.getenv("GEO_EMBEDDING_MIN_SUCCESS_RATIO", "0.8"))))
FACT_MIN_CANDIDATE_COUNT = max(1, int(os.getenv("GEO_FACT_MIN_CANDIDATE_COUNT", "1")))


class FinalizingDescriptorError(RuntimeError):
    pass


def _json(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}


def _dict_cursor(repository: KnowledgePipelineRepository):
    from psycopg.rows import dict_row

    return repository.connection.cursor(row_factory=dict_row)


def _defer_terminal_transaction(repository: KnowledgePipelineRepository) -> None:
    connection = repository.connection
    if isinstance(connection, LeaseFencedConnection):
        connection.defer_commits_until_terminal()


def _text_from_config(config: dict[str, Any]) -> str:
    return source_config_text(config)


def _short_text(value: str, *, limit: int = 360) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit].rstrip()


def _ensure_target_brand_in_markdown(markdown: str, *, target_brand: str, title: str) -> str:
    clean = markdown.strip()
    brand = target_brand.strip()
    if not clean or not brand or brand.casefold() in clean.casefold():
        return clean
    return f"# {title}\n\n{clean}"


def _table_rows(table: dict[str, Any]) -> list[list[str]]:
    table_json = table.get("table_json") if isinstance(table.get("table_json"), dict) else {}
    rows = table_json.get("rows") if isinstance(table_json.get("rows"), list) else []
    return [[str(cell) for cell in row] for row in rows if isinstance(row, list)]


def _table_csv_text(table: dict[str, Any]) -> str:
    stream = io.StringIO()
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerows(_table_rows(table))
    return stream.getvalue()


def _table_html_text(table: dict[str, Any]) -> str:
    table_json = table.get("table_json") if isinstance(table.get("table_json"), dict) else {}
    existing_html = str(table_json.get("html") or "").strip()
    if existing_html:
        return existing_html
    rows = _table_rows(table)
    return "<table>" + "".join(
        "<tr>" + "".join(f"<td>{html.escape(cell)}</td>" for cell in row) + "</tr>" for row in rows
    ) + "</table>"


def _split_chunk_text(text: str, *, max_chars: int = 1800) -> list[str]:
    clean = " ".join(str(text or "").split()).strip()
    if not clean:
        return []
    if len(clean) <= max_chars:
        return [clean]
    sentences = [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+", clean) if part.strip()]
    if len(sentences) <= 1:
        return [clean[index : index + max_chars] for index in range(0, len(clean), max_chars)]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) + 1 > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return chunks


def _chunk_quality_flags(
    text: str,
    *,
    source_present: bool,
    chunk_type: str,
    duplicate: bool,
    locale: str,
) -> list[str]:
    flags: list[str] = []
    lowered = text.lower()
    if len(text) < 40:
        flags.append("chunk_too_short")
    if len(text) > 2000:
        flags.append("chunk_too_long")
    if not source_present:
        flags.append("chunk_no_source")
    if duplicate:
        flags.append("chunk_duplicate")
    if any(marker in lowered for marker in ("cookie policy", "skip to content", "sign in", "navigation menu")):
        flags.append("chunk_contains_navigation")
    if any(marker in lowered for marker in ("all rights reserved", "copyright ©", "privacy | terms")):
        flags.append("chunk_contains_footer")
    if chunk_type == "table" and "|" not in text and "<table" not in lowered:
        flags.append("chunk_table_without_structure")
    replacement_ratio = text.count("�") / max(1, len(text))
    if replacement_ratio > 0.01:
        flags.append("chunk_ocr_low_confidence")
    topic_groups = (
        ("shipping", "delivery", "freight"),
        ("return", "refund", "exchange"),
        ("price", "pricing", "discount"),
        ("warranty", "repair", "support"),
        ("privacy", "cookie", "tracking"),
    )
    if sum(1 for group in topic_groups if any(term in lowered for term in group)) >= 4:
        flags.append("chunk_mixed_topics")
    cjk_ratio = sum(1 for character in text if "\u4e00" <= character <= "\u9fff") / max(1, len(text))
    normalized_locale = locale.lower()
    if (normalized_locale.startswith("zh") and cjk_ratio < 0.02) or (normalized_locale.startswith("en") and cjk_ratio > 0.35):
        flags.append("chunk_language_mismatch")
    return flags


def _model_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _parser_quality_findings(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    blocks = [block for block in (parsed.get("blocks") or []) if isinstance(block, dict)]
    if not any(str(block.get("text") or "").strip() for block in blocks):
        findings.append(
            {"finding_type": "parser_empty_text", "severity": "high", "message": "Parser output contains no usable text blocks.", "metadata": {}}
        )
    for block in blocks:
        block_text = str(block.get("text") or "")
        if block_text.count("�") / max(1, len(block_text)) > 0.01:
            findings.append(
                {"finding_type": "parser_garbled_text", "severity": "warning", "message": "A parser block contains excessive replacement characters.", "metadata": {"block_index": block.get("block_index")}}
            )
        if parsed.get("pages") and block.get("page_number") is None:
            findings.append(
                {"finding_type": "parser_missing_page_number", "severity": "warning", "message": "A paged parser block has no page number.", "metadata": {"block_index": block.get("block_index")}}
            )
    for signal in parsed.get("quality_signals") or []:
        if not isinstance(signal, dict):
            continue
        findings.append(
            {
                "finding_type": str(signal.get("code") or "parser_quality_signal"),
                "severity": "high" if signal.get("severity") == "blocked" else str(signal.get("severity") or "warning"),
                "message": str(signal.get("message") or signal.get("code") or "Parser quality signal"),
                "metadata": signal,
            }
        )
    for span in parsed.get("ocr_spans") or []:
        if not isinstance(span, dict):
            continue
        confidence = float(span.get("confidence") or 0.0)
        if confidence and confidence < 0.75:
            findings.append(
                {
                    "finding_type": "ocr_low_confidence",
                    "severity": "warning",
                    "message": f"OCR confidence {confidence:.4f} is below 0.75.",
                    "metadata": {"ocr_span_id": span.get("id"), "page_number": span.get("page_number")},
                }
            )
        for flag in span.get("quality_flags") or []:
            findings.append(
                {
                    "finding_type": str(flag),
                    "severity": "warning",
                    "message": f"OCR span has quality flag {flag}.",
                    "metadata": {"ocr_span_id": span.get("id"), "page_number": span.get("page_number")},
                }
            )
    for table in parsed.get("tables") or []:
        if not isinstance(table, dict):
            continue
        if int(table.get("row_count") or 0) <= 0 or int(table.get("column_count") or 0) <= 0:
            findings.append(
                {
                    "finding_type": "table_empty",
                    "severity": "warning",
                    "message": "A parsed table has no structured rows or columns.",
                    "metadata": {"table_id": table.get("id"), "page_number": table.get("page_number")},
                }
            )
        if not table.get("page_number"):
            findings.append(
                {
                    "finding_type": "table_missing_page",
                    "severity": "warning",
                    "message": "A parsed table has no source page number.",
                    "metadata": {"table_id": table.get("id")},
                }
            )
        for flag in table.get("quality_flags") or []:
            findings.append(
                {
                    "finding_type": str(flag),
                    "severity": "warning",
                    "message": f"Parsed table has quality flag {flag}.",
                    "metadata": {"table_id": table.get("id"), "page_number": table.get("page_number")},
                }
            )
    return findings


def _require_real_model() -> bool:
    return os.getenv("GENO_KNOWLEDGE_REQUIRE_REAL_MODEL", "false").strip().lower() in {"1", "true", "yes"}


def _update_stage(
    repository: KnowledgePipelineRepository,
    *,
    pipeline_run_id: str | None,
    stage_key: str,
    status: str,
    summary: dict[str, Any] | None = None,
) -> None:
    if not pipeline_run_id:
        return
    with repository.connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE knowledge_pipeline_stages
            SET status = %s,
                started_at = COALESCE(started_at, now()),
                completed_at = CASE WHEN %s IN ('succeeded', 'failed', 'blocked', 'skipped') THEN now() ELSE completed_at END,
                summary = summary || %s::jsonb,
                updated_at = now()
            WHERE pipeline_run_id = %s::uuid AND stage_key = %s
            """,
            (status, status, json.dumps(summary or {}, ensure_ascii=False), pipeline_run_id, stage_key),
        )
        repository.connection.commit()


def _pipeline_run_type(repository: KnowledgePipelineRepository, pipeline_run_id: str | None) -> str:
    if not pipeline_run_id:
        return "full_ingestion"
    with _dict_cursor(repository) as cursor:
        cursor.execute("SELECT run_type FROM knowledge_pipeline_runs WHERE id = %s::uuid", (pipeline_run_id,))
        row = cursor.fetchone() or {}
    return str(row.get("run_type") or "full_ingestion")


def _record_quality_gate(
    repository: KnowledgePipelineRepository,
    *,
    job: dict[str, Any],
    gate_key: str,
    status: str,
    summary: dict[str, Any],
    target_type: str,
    target_id: str,
    finding_type: str | None = None,
    message: str | None = None,
    additional_findings: list[dict[str, Any]] | None = None,
) -> str:
    if status not in {"passed", "warning", "blocked", "failed"}:
        raise ValueError(f"unsupported quality gate result: {status}")
    finding_ids: list[str] = []
    with repository.connection.cursor() as cursor:
        requested_findings = list(additional_findings or [])
        if finding_type and message:
            requested_findings.append(
                {
                    "finding_type": finding_type,
                    "message": message,
                    "severity": "high" if status == "blocked" else "warning",
                    "metadata": summary,
                }
            )
        for finding in requested_findings:
            finding_message = str(finding.get("message") or finding.get("finding_type") or "Quality finding")
            finding_id = stable_pipeline_id(
                "quality-finding", gate_key, target_type, target_id, finding.get("finding_type"), finding_message
            )
            cursor.execute(
                """
                INSERT INTO knowledge_quality_findings (
                  id, project_id, pipeline_run_id, target_type, target_id,
                  finding_type, severity, status, message, evidence_refs, metadata
                ) VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s,
                          %s, %s, 'open', %s, %s::jsonb, %s::jsonb)
                ON CONFLICT (id) DO UPDATE SET
                  severity = EXCLUDED.severity,
                  message = EXCLUDED.message,
                  updated_at = now()
                """,
                (
                    finding_id,
                    job["project_id"],
                    job.get("pipeline_run_id"),
                    target_type,
                    target_id,
                    str(finding.get("finding_type") or "quality_finding"),
                    str(finding.get("severity") or ("high" if status == "blocked" else "warning")),
                    finding_message,
                    json.dumps({"job_type": job.get("job_type"), "job_id": str(job.get("id") or "")}),
                    json.dumps(dict(finding.get("metadata") or summary), ensure_ascii=False),
                ),
            )
            finding_ids.append(finding_id)
        cursor.execute("SELECT id FROM knowledge_quality_gates WHERE gate_key = %s AND status = 'active'", (gate_key,))
        gate_row = cursor.fetchone()
        gate_id = gate_row[0] if gate_row else None
        gate_run_id = stable_pipeline_id("quality-gate-run", job.get("pipeline_run_id"), gate_key, target_type, target_id)
        cursor.execute(
            """
            INSERT INTO knowledge_quality_gate_runs (
              id, project_id, pipeline_run_id, gate_id, gate_key, status,
              summary, finding_ids, started_at, completed_at
            ) VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s, %s,
                      %s::jsonb, %s::uuid[], now(), now())
            ON CONFLICT (id) DO UPDATE SET
              status = EXCLUDED.status,
              summary = EXCLUDED.summary,
              finding_ids = EXCLUDED.finding_ids,
              completed_at = now(),
              updated_at = now()
            """,
            (
                gate_run_id,
                job["project_id"],
                job.get("pipeline_run_id"),
                gate_id,
                gate_key,
                status,
                json.dumps(summary, ensure_ascii=False),
                finding_ids,
            ),
        )
        if job.get("pipeline_run_id"):
            cursor.execute(
                """
                SELECT count(*) FILTER (WHERE status = 'blocked') AS blocked_count,
                       count(*) FILTER (WHERE status = 'failed') AS failed_count,
                       count(*) FILTER (WHERE status = 'warning') AS warning_count,
                       count(*) FILTER (WHERE status = 'passed') AS passed_count
                FROM knowledge_quality_gate_runs
                WHERE pipeline_run_id = %s::uuid
                """,
                (job["pipeline_run_id"],),
            )
            counts = cursor.fetchone()
            counts_payload = {
                "blocked_count": int(counts[0] or 0),
                "failed_count": int(counts[1] or 0),
                "warning_count": int(counts[2] or 0),
                "passed_count": int(counts[3] or 0),
            }
            cursor.execute(
                """
                UPDATE knowledge_pipeline_stages
                SET status = CASE WHEN %s > 0 OR %s > 0 THEN 'blocked' ELSE 'succeeded' END,
                    started_at = COALESCE(started_at, now()), completed_at = now(),
                    summary = %s::jsonb, updated_at = now()
                WHERE pipeline_run_id = %s::uuid AND stage_key = 'quality_summary'
                """,
                (
                    counts_payload["blocked_count"],
                    counts_payload["failed_count"],
                    json.dumps(counts_payload, ensure_ascii=False),
                    job["pipeline_run_id"],
                ),
            )
            if status in {"blocked", "failed"}:
                cursor.execute(
                    """
                    UPDATE knowledge_pipeline_runs
                    SET blocking_quality_gate = %s, failed_step = %s, updated_at = now()
                    WHERE id = %s::uuid
                    """,
                    (gate_key, target_type, job["pipeline_run_id"]),
                )
        repository.connection.commit()
    return gate_run_id


def _process_import_job(repository: KnowledgePipelineRepository, job: dict[str, Any]) -> dict[str, Any]:
    config = _json(job.get("source_config"))
    source_mode = str(job.get("source_mode") or "")
    project_id = str(job["project_id"])
    pipeline_run_id = str(job.get("pipeline_run_id") or "")
    if source_mode == "file":
        with _dict_cursor(repository) as cursor:
            cursor.execute(
                """
                SELECT id
                FROM knowledge_source_assets
                WHERE import_job_id = %s::uuid AND asset_type = 'uploaded_file'
                ORDER BY created_at ASC
                """,
                (job["id"],),
            )
            uploaded_assets = [dict(row) for row in cursor.fetchall()]
            cursor.execute(
                """
                SELECT status
                FROM knowledge_quality_gate_runs
                WHERE id = %s::uuid
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (stable_pipeline_id("quality-gate-run", job.get("pipeline_run_id"), "pre_import_gate", job["id"]),),
            )
            existing_precheck_gate = dict(cursor.fetchone() or {})
        if uploaded_assets:
            result = {"asset_count": len(uploaded_assets), "asset_ids": [str(asset["id"]) for asset in uploaded_assets]}
            if not existing_precheck_gate:
                _defer_terminal_transaction(repository)
                _record_quality_gate(
                    repository,
                    job=job,
                    gate_key="pre_import_gate",
                    status="passed",
                    summary=result,
                    target_type="import_job",
                    target_id=str(job["id"]),
                )
            return result
        text = _text_from_config(config)
        if not text:
            raise ValueError("file import job has no uploaded source asset")
        _defer_terminal_transaction(repository)
        asset = repository.create_asset_from_text(
            project_id=project_id,
            pipeline_run_id=pipeline_run_id or None,
            import_job_id=str(job["id"]),
            asset_type="uploaded_file",
            text=text,
            title=str(config.get("title") or "uploaded file text fallback"),
            source_uri=str(config.get("source_uri") or "") or None,
            created_by=str(job.get("requested_by") or "knowledge-worker"),
            market_code=str(config.get("market_code") or "GLOBAL"),
            locale=str(config.get("locale") or "en"),
            city=str(config.get("city") or "") or None,
            asset_id=stable_pipeline_id(
                "source-asset", job["id"], "uploaded_file", content_hash(text)
            ),
        )
        _enqueue_parser(repository, asset, import_job_id=str(job["id"]))
        result = {"asset_count": 1, "asset_ids": [str(asset["id"])]}
        _record_quality_gate(
            repository,
            job=job,
            gate_key="pre_import_gate",
            status="passed",
            summary=result,
            target_type="import_job",
            target_id=str(job["id"]),
        )
        return result
    if source_mode in {"pasted_text", "csv"}:
        text = _text_from_config(config)
        if not text:
            raise ValueError("import job has no text payload")
        filename = "knowledge.csv" if source_mode == "csv" else "knowledge.txt"
        content_type = "text/csv" if source_mode == "csv" else "text/plain"
        precheck = precheck_knowledge_source(filename=filename, content=text.encode("utf-8"), content_type=content_type)
        repository.record_import_precheck(
            project_id=project_id,
            pipeline_run_id=pipeline_run_id,
            import_job_id=str(job["id"]),
            checked_by="knowledge-worker",
            result=precheck,
        )
        if not bool(precheck.get("accepted")):
            raise ValueError("text knowledge source failed pre-import quality gate")
        _defer_terminal_transaction(repository)
        asset = repository.create_asset_from_text(
            project_id=project_id,
            pipeline_run_id=pipeline_run_id or None,
            import_job_id=str(job["id"]),
            asset_type="uploaded_csv" if source_mode == "csv" else "pasted_text",
            text=text,
            title=str(config.get("title") or f"{source_mode} source"),
            source_uri=str(config.get("source_uri") or "") or None,
            created_by=str(job.get("requested_by") or "knowledge-worker"),
            market_code=str(config.get("market_code") or "GLOBAL"),
            locale=str(config.get("locale") or "en"),
            city=str(config.get("city") or "") or None,
            asset_id=stable_pipeline_id(
                "source-asset", job["id"], source_mode, content_hash(text)
            ),
        )
        _enqueue_parser(repository, asset, import_job_id=str(job["id"]))
        result = {"asset_count": 1, "asset_ids": [str(asset["id"])]}
        return result
    if source_mode in {"url", "url_batch", "site_crawl"}:
        urls = config.get("urls") if isinstance(config.get("urls"), list) else [config.get("url") or config.get("source_url")]
        urls = [str(url).strip() for url in urls if str(url or "").strip()]
        if not urls:
            raise ValueError("import job has no URLs")
        requested_page_budget = max(1, int(config.get("max_pages") or 1))
        total_page_budget = max(requested_page_budget, len(urls))
        base_page_budget, remainder = divmod(total_page_budget, len(urls))
        _defer_terminal_transaction(repository)
        with repository.connection.cursor() as cursor:
            for index, url in enumerate(urls):
                page_budget = base_page_budget + (1 if index < remainder else 0)
                cursor.execute(
                    """
                    INSERT INTO crawl_jobs (
                      id, project_id, pipeline_run_id, import_job_id, source_url, seed_urls,
                      crawl_mode, max_pages, depth_limit, include_patterns, exclude_patterns,
                      respect_robots, metadata
                    )
                    VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s, ARRAY[%s]::text[],
                            %s, %s, %s, %s::text[], %s::text[], %s, %s::jsonb)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        stable_pipeline_id("crawl-job", job["id"], index, url),
                        project_id,
                        pipeline_run_id,
                        str(job["id"]),
                        url,
                        url,
                        str(config.get("crawl_mode") or ("site_depth" if int(config.get("depth_limit") or 0) > 0 else ("url_batch" if source_mode == "url_batch" else "single_url"))),
                        page_budget,
                        int(config.get("depth_limit") or 0),
                        [str(value) for value in (config.get("include_patterns") or [])],
                        [str(value) for value in (config.get("exclude_patterns") or [])],
                        bool(config.get("respect_robots", True)),
                        json.dumps(
                            {
                                "source_mode": source_mode,
                                "requested_total_page_budget": requested_page_budget,
                                "effective_total_page_budget": total_page_budget,
                                "seed_page_budget": page_budget,
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
            repository.connection.commit()
        result = {
            "crawl_job_count": len(urls),
            "urls": urls,
            "requested_total_page_budget": requested_page_budget,
            "effective_total_page_budget": total_page_budget,
        }
        _record_quality_gate(
            repository,
            job=job,
            gate_key="pre_import_gate",
            status="passed",
            summary=result,
            target_type="import_job",
            target_id=str(job["id"]),
        )
        return result
    raise ValueError(f"unsupported source_mode: {source_mode}")


def _enqueue_parser(repository: KnowledgePipelineRepository, asset: dict[str, Any], *, import_job_id: str | None) -> None:
    with repository.connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO knowledge_parser_runs (
              id, project_id, pipeline_run_id, import_job_id, source_asset_id, adapter_engine, adapter_version
            ) VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s::uuid, 'docling', 'geo-parser-adapter-v1')
            ON CONFLICT (id) DO NOTHING
            """,
            (
                stable_pipeline_id("parser-run", asset["id"], import_job_id or ""),
                asset["project_id"],
                asset.get("pipeline_run_id"),
                import_job_id,
                asset["id"],
            ),
        )
        repository.connection.commit()


def _process_crawl_job(repository: KnowledgePipelineRepository, job: dict[str, Any]) -> dict[str, Any]:
    normalized_url = normalize_knowledge_url(str(job["source_url"]))
    try:
        crawled = crawl_with_crawl4ai(
            normalized_url,
            max_pages=max(1, int(job.get("max_pages") or 1)),
            depth_limit=max(0, int(job.get("depth_limit") or 0)),
            crawl_mode=str(job.get("crawl_mode") or "single_url"),
            include_patterns=[str(value) for value in (job.get("include_patterns") or [])],
            exclude_patterns=[str(value) for value in (job.get("exclude_patterns") or [])],
            respect_robots=bool(job.get("respect_robots", True)),
        )
        markdown = str(crawled.get("markdown") or "").strip()
        if not markdown:
            raise RuntimeError("Crawl4AI returned no Markdown")
        pages = [dict(page) for page in (crawled.get("pages") or [crawled]) if isinstance(page, dict)]
        link_graph = dict(crawled.get("link_graph") or {})
        failures = [dict(item) for item in (crawled.get("failures") or []) if isinstance(item, dict)]
        adapter = "crawl4ai"
    except Exception:
        if os.getenv("GEO_ALLOW_CRAWLER_FALLBACK", "false").strip().lower() not in {"1", "true", "yes"}:
            raise
        fallback = crawl_public_knowledge_url(source_url=normalized_url, max_bytes=2_000_000)
        pages = [
            {
                "normalized_url": fallback.normalized_url,
                "title": fallback.title,
                "markdown": fallback.markdown,
                "html": "",
                "screenshot_base64": "",
                "status_code": fallback.status_code,
                "depth": 0,
            }
        ]
        link_graph = {"root": fallback.normalized_url, "edges": []}
        failures = []
        adapter = "http_fallback"

    store = _optional_object_store()
    if store is None and os.getenv("GENO_KNOWLEDGE_REQUIRE_OBJECT_STORE", "false").strip().lower() in {"1", "true", "yes"}:
        raise RuntimeError("knowledge crawl asset archival requires object storage")

    def archive_asset(*, asset_type: str, content: bytes, content_type: str, title: str, source_uri: str) -> dict[str, Any] | None:
        if not content:
            return None
        if store is None:
            return repository.create_asset_from_text(
                project_id=str(job["project_id"]),
                pipeline_run_id=str(job.get("pipeline_run_id") or "") or None,
                import_job_id=str(job.get("import_job_id") or "") or None,
                crawl_job_id=str(job["id"]),
                asset_type=asset_type,
                text=content.decode("utf-8", errors="replace"),
                title=title,
                source_uri=source_uri,
                created_by="knowledge-crawl-worker",
                asset_id=stable_pipeline_id(
                    "crawl-asset", job["id"], source_uri, asset_type, content_hash(content)
                ),
            )
        digest = content_hash(content)
        key = "/".join(
            [
                "knowledge-crawl-assets",
                str(job["project_id"]),
                str(job.get("pipeline_run_id") or "manual"),
                str(job["id"]),
                f"{asset_type}-{digest[:12]}",
            ]
        )
        stored = store.put_object(key=key, content=content, content_type=content_type, expected_hash=digest)
        return repository.create_asset_from_stored_object(
            project_id=str(job["project_id"]),
            pipeline_run_id=str(job.get("pipeline_run_id") or "") or None,
            import_job_id=str(job.get("import_job_id") or "") or None,
            crawl_job_id=str(job["id"]),
            asset_type=asset_type,
            stored=stored,
            title=title,
            source_uri=source_uri,
            created_by="knowledge-crawl-worker",
            metadata={"byte_size": len(content), "adapter": adapter},
            asset_id=stable_pipeline_id(
                "crawl-asset", job["id"], source_uri, asset_type, digest
            ),
        )

    output_assets: list[dict[str, Any]] = []
    markdown_assets: list[dict[str, Any]] = []
    for page_index, page in enumerate(pages):
        page_url = normalize_knowledge_url(str(page.get("normalized_url") or normalized_url))
        page_title = str(page.get("title") or page_url)
        markdown_bytes = str(page.get("markdown") or "").encode("utf-8")
        html_bytes = str(page.get("html") or "").encode("utf-8")
        markdown_asset = archive_asset(
            asset_type="crawled_markdown",
            content=markdown_bytes,
            content_type="text/markdown; charset=utf-8",
            title=f"{page_title} (Markdown)",
            source_uri=page_url,
        )
        html_asset = archive_asset(
            asset_type="crawled_html",
            content=html_bytes,
            content_type="text/html; charset=utf-8",
            title=f"{page_title} (HTML)",
            source_uri=page_url,
        )
        screenshot_value = str(page.get("screenshot_base64") or "")
        if screenshot_value.startswith("data:"):
            screenshot_value = screenshot_value.split(",", 1)[-1]
        screenshot_bytes = b""
        if screenshot_value:
            try:
                screenshot_bytes = base64.b64decode(screenshot_value, validate=True)
            except (ValueError, binascii.Error):
                screenshot_bytes = b""
        screenshot_asset = archive_asset(
            asset_type="screenshot",
            content=screenshot_bytes,
            content_type="image/png",
            title=f"{page_title} (Screenshot)",
            source_uri=page_url,
        )
        for asset in (markdown_asset, html_asset, screenshot_asset):
            if asset:
                output_assets.append(asset)
        if markdown_asset:
            markdown_assets.append(markdown_asset)
            _enqueue_parser(repository, markdown_asset, import_job_id=str(job.get("import_job_id") or "") or None)

    link_graph_asset = archive_asset(
        asset_type="crawl_link_graph",
        content=json.dumps(link_graph, ensure_ascii=False, sort_keys=True).encode("utf-8"),
        content_type="application/json",
        title=f"Crawl link graph: {normalized_url}",
        source_uri=normalized_url,
    )
    if link_graph_asset:
        output_assets.append(link_graph_asset)
    output_asset_ids = [str(asset["id"]) for asset in output_assets]
    _defer_terminal_transaction(repository)
    with repository.connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE crawl_jobs
            SET normalized_url = %s,
                output_asset_ids = %s::uuid[],
                crawled_page_count = %s,
                failed_page_count = %s,
                metadata = metadata || %s::jsonb
            WHERE id = %s::uuid
            """,
            (
                normalized_url,
                output_asset_ids,
                len(markdown_assets),
                len(failures),
                json.dumps({"adapter": adapter, "failures": failures[:20]}, ensure_ascii=False),
                job["id"],
            ),
        )
        repository.connection.commit()
    success_ratio = round(len(markdown_assets) / max(1, len(markdown_assets) + len(failures)), 4)
    crawl_threshold_passed = (
        len(markdown_assets) >= CRAWL_MIN_SUCCESS_PAGES and success_ratio >= CRAWL_MIN_SUCCESS_RATIO
    )
    _update_stage(
        repository,
        pipeline_run_id=str(job.get("pipeline_run_id") or "") or None,
        stage_key="crawl",
        status="succeeded" if crawl_threshold_passed else "blocked",
        summary={"crawled_page_count": len(markdown_assets), "failed_page_count": len(failures)},
    )
    _record_quality_gate(
        repository,
        job=job,
        gate_key="pre_import_gate",
        status="blocked" if not crawl_threshold_passed else ("warning" if failures else "passed"),
        summary={
            "crawled_page_count": len(markdown_assets),
            "failed_page_count": len(failures),
            "success_ratio": success_ratio,
            "minimum_success_pages": CRAWL_MIN_SUCCESS_PAGES,
            "minimum_success_ratio": CRAWL_MIN_SUCCESS_RATIO,
        },
        target_type="crawl_job",
        target_id=str(job["id"]),
        finding_type=(
            "crawl_success_ratio_below_threshold"
            if not crawl_threshold_passed
            else ("crawl_partial_failure" if failures else None)
        ),
        message=(
            "Crawl output is below the production threshold"
            if not crawl_threshold_passed
            else ("Some crawl pages failed" if failures else None)
        ),
    )
    if not crawl_threshold_passed:
        raise RuntimeError("crawl output is below the production success threshold")
    return {
        "asset_ids": output_asset_ids,
        "crawled_page_count": len(markdown_assets),
        "failed_page_count": len(failures),
        "failed_count": len(failures),
        "success_ratio": success_ratio,
        "adapter": adapter,
    }


def _load_asset_text(asset: dict[str, Any]) -> str:
    metadata = _json(asset.get("metadata"))
    return str(metadata.get("text_body") or metadata.get("text_preview") or "")


def _load_asset_bytes(asset: dict[str, Any]) -> bytes:
    object_uri = str(asset.get("object_uri") or "").strip()
    if object_uri:
        store = build_object_store_from_env()
        _bucket, key = parse_s3_uri(object_uri)
        return store.get_object(key=key, expected_hash=str(asset.get("content_hash") or "") or None).content
    text = _load_asset_text(asset)
    if text:
        return text.encode("utf-8")
    raise ValueError("source asset has neither object_uri nor text metadata")


def _process_parser_run(repository: KnowledgePipelineRepository, job: dict[str, Any]) -> dict[str, Any]:
    with _dict_cursor(repository) as cursor:
        cursor.execute("SELECT * FROM knowledge_source_assets WHERE id = %s::uuid", (job["source_asset_id"],))
        asset = cursor.fetchone()
    repository.connection.commit()
    if not asset:
        raise ValueError("source asset not found")
    asset_dict = dict(asset)
    content = _load_asset_bytes(asset_dict)
    filename = str(asset_dict.get("title") or asset_dict.get("source_uri") or "knowledge-source")
    content_type = str(asset_dict.get("content_type") or "text/plain")
    if str(asset_dict.get("object_uri") or "").strip():
        parsed = GeoParserAdapter().parse_bytes(
            content=content,
            filename=filename,
            content_type=content_type,
            source_asset_id=str(asset_dict["id"]),
            requested_engine=str(job.get("adapter_engine") or "auto"),
        )
    else:
        parsed = GeoParserAdapter().parse(
            text=content.decode("utf-8", errors="ignore"),
            source_asset_id=str(asset_dict["id"]),
            engine=str(job.get("adapter_engine") or "text"),
        )
    blocks = parsed["blocks"]
    quality_findings = _parser_quality_findings(parsed)
    parser_json_asset = repository.create_parser_artifact_asset(
        project_id=str(job["project_id"]),
        pipeline_run_id=str(job.get("pipeline_run_id") or "") or None,
        import_job_id=str(job.get("import_job_id") or "") or None,
        source_asset_id=str(asset_dict["id"]),
        parser_run_id=str(job["id"]),
        asset_type="parser_json",
        title=f"{filename}.parser.json",
        content=json.dumps(parsed, ensure_ascii=False, default=str),
        content_type="application/json; charset=utf-8",
        store=_optional_object_store(),
    )
    markdown_artifacts = [artifact for artifact in parsed.get("artifacts", []) if artifact.get("artifact_type") == "parser_markdown"]
    parser_markdown_asset = None
    if markdown_artifacts:
        parser_markdown_asset = repository.create_parser_artifact_asset(
            project_id=str(job["project_id"]),
            pipeline_run_id=str(job.get("pipeline_run_id") or "") or None,
            import_job_id=str(job.get("import_job_id") or "") or None,
            source_asset_id=str(asset_dict["id"]),
            parser_run_id=str(job["id"]),
            asset_type="parser_markdown",
            title=f"{filename}.md",
            content=str(markdown_artifacts[0].get("content") or ""),
            content_type="text/markdown; charset=utf-8",
            store=_optional_object_store(),
        )
    parser_log_asset = repository.create_parser_artifact_asset(
        project_id=str(job["project_id"]),
        pipeline_run_id=str(job.get("pipeline_run_id") or "") or None,
        import_job_id=str(job.get("import_job_id") or "") or None,
        source_asset_id=str(asset_dict["id"]),
        parser_run_id=str(job["id"]),
        asset_type="parser_log",
        title=f"{filename}.parser.log.json",
        content=json.dumps(
            {
                "adapter": parsed.get("adapter"),
                "quality_signals": parsed.get("quality_signals") or [],
                "counts": {
                    "blocks": len(blocks),
                    "tables": len(parsed.get("tables") or []),
                    "ocr_spans": len(parsed.get("ocr_spans") or []),
                    "pages": len(parsed.get("pages") or []),
                },
            },
            ensure_ascii=False,
        ),
        content_type="application/json; charset=utf-8",
        store=_optional_object_store(),
    )
    quality_report_asset = repository.create_parser_artifact_asset(
        project_id=str(job["project_id"]),
        pipeline_run_id=str(job.get("pipeline_run_id") or "") or None,
        import_job_id=str(job.get("import_job_id") or "") or None,
        source_asset_id=str(asset_dict["id"]),
        parser_run_id=str(job["id"]),
        asset_type="quality_report",
        title=f"{filename}.quality.json",
        content=json.dumps({"findings": quality_findings}, ensure_ascii=False),
        content_type="application/json; charset=utf-8",
        store=_optional_object_store(),
    )
    ocr_debug_asset = None
    if parsed.get("ocr_spans"):
        ocr_debug_asset = repository.create_parser_artifact_asset(
            project_id=str(job["project_id"]),
            pipeline_run_id=str(job.get("pipeline_run_id") or "") or None,
            import_job_id=str(job.get("import_job_id") or "") or None,
            source_asset_id=str(asset_dict["id"]),
            parser_run_id=str(job["id"]),
            asset_type="ocr_debug_json",
            title=f"{filename}.ocr.json",
            content=json.dumps({"ocr_spans": parsed.get("ocr_spans") or []}, ensure_ascii=False),
            content_type="application/json; charset=utf-8",
            store=_optional_object_store(),
        )
    table_artifacts: dict[int, tuple[dict[str, Any] | None, dict[str, Any] | None]] = {}
    for table_index, table in enumerate(parsed.get("tables") or []):
        csv_text = _table_csv_text(table)
        html_text = _table_html_text(table)
        csv_asset = repository.create_parser_artifact_asset(
            project_id=str(job["project_id"]),
            pipeline_run_id=str(job.get("pipeline_run_id") or "") or None,
            import_job_id=str(job.get("import_job_id") or "") or None,
            source_asset_id=str(asset_dict["id"]),
            parser_run_id=str(job["id"]),
            asset_type="table_csv",
            title=f"{filename}.table-{table_index + 1}.csv",
            content=csv_text,
            content_type="text/csv; charset=utf-8",
            store=_optional_object_store(),
        ) if csv_text else None
        html_asset = repository.create_parser_artifact_asset(
            project_id=str(job["project_id"]),
            pipeline_run_id=str(job.get("pipeline_run_id") or "") or None,
            import_job_id=str(job.get("import_job_id") or "") or None,
            source_asset_id=str(asset_dict["id"]),
            parser_run_id=str(job["id"]),
            asset_type="table_html",
            title=f"{filename}.table-{table_index + 1}.html",
            content=html_text,
            content_type="text/html; charset=utf-8",
            store=_optional_object_store(),
        ) if html_text else None
        table_artifacts[table_index] = (csv_asset, html_asset)
    _defer_terminal_transaction(repository)
    with repository.connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO knowledge_trace_refs (
              project_id, pipeline_run_id, source_type, source_id, target_type, target_id,
              trace_role, confidence, created_by_job_type, created_by_job_id, metadata
            ) VALUES (%s::uuid, %s::uuid, 'source_asset', %s, 'parser_run', %s,
                      'derived_from', 1.0, 'knowledge_parser_runs', %s::uuid, '{}'::jsonb)
            ON CONFLICT DO NOTHING
            """,
            (job["project_id"], job.get("pipeline_run_id"), str(asset_dict["id"]), str(job["id"]), job["id"]),
        )
        for block in blocks:
            block_id = stable_pipeline_id(
                "block",
                job["id"],
                block.get("block_index"),
                content_hash(str(block.get("text") or ""))[:16],
            )
            block["id"] = block_id
            cursor.execute(
                """
                INSERT INTO knowledge_blocks (
                  id, project_id, pipeline_run_id, source_asset_id, parser_run_id, page_number,
                  block_index, block_type, text, bbox, section_path, html, markdown,
                  reading_order, confidence, content_hash, metadata
                ) VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s::uuid, %s,
                          %s, %s, %s, %s::jsonb, %s::text[], %s, %s,
                          %s, %s, %s, %s::jsonb)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    block_id,
                    job["project_id"],
                    job.get("pipeline_run_id"),
                    asset_dict["id"],
                    job["id"],
                    block["page_number"],
                    block["block_index"],
                    block["block_type"],
                    block["text"],
                    json.dumps(block.get("bbox")),
                    list(block.get("section_path") or []),
                    block.get("html"),
                    block.get("markdown"),
                    block.get("reading_order"),
                    block.get("confidence"),
                    str(block.get("content_hash") or content_hash(str(block.get("text") or ""))),
                    json.dumps(block.get("metadata") or {}),
                ),
            )
        for table_index, table in enumerate(parsed.get("tables") or []):
            table_id = str(table.get("id") or stable_pipeline_id("table", job["id"], table_index))
            csv_asset, html_asset = table_artifacts.get(table_index, (None, None))
            cursor.execute(
                """
                INSERT INTO knowledge_tables (
                  id, project_id, pipeline_run_id, source_asset_id, parser_run_id, page_number,
                  table_index, caption, table_json, csv_asset_id, html_asset_id, markdown,
                  row_count, column_count, confidence, quality_flags, metadata
                ) VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s::uuid, %s,
                          %s, %s, %s::jsonb, %s::uuid, %s::uuid, %s,
                          %s, %s, %s, %s::text[], %s::jsonb)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    table_id,
                    job["project_id"],
                    job.get("pipeline_run_id"),
                    asset_dict["id"],
                    job["id"],
                    table.get("page_number"),
                    table_index,
                    table.get("caption"),
                    json.dumps(table.get("table_json") or {}, ensure_ascii=False),
                    (csv_asset or {}).get("id"),
                    (html_asset or {}).get("id"),
                    str(table.get("markdown") or ""),
                    int(table.get("row_count") or 0),
                    int(table.get("column_count") or 0),
                    table.get("confidence"),
                    list(table.get("quality_flags") or []),
                    json.dumps({"confidence": table.get("confidence"), "quality_flags": table.get("quality_flags") or []}),
                ),
            )
            cursor.execute(
                """
                INSERT INTO knowledge_trace_refs (
                  project_id, pipeline_run_id, source_type, source_id, target_type, target_id,
                  trace_role, confidence, created_by_job_type, created_by_job_id, metadata
                ) VALUES (%s::uuid, %s::uuid, 'parser_run', %s, 'table', %s,
                          'derived_from', %s, 'knowledge_parser_runs', %s::uuid, '{}'::jsonb)
                ON CONFLICT DO NOTHING
                """,
                (job["project_id"], job.get("pipeline_run_id"), str(job["id"]), table_id, table.get("confidence"), job["id"]),
            )
        for span_index, span in enumerate(parsed.get("ocr_spans") or []):
            span_id = str(span.get("id") or stable_pipeline_id("ocr-span", job["id"], span_index, span.get("text")))
            cursor.execute(
                """
                INSERT INTO knowledge_ocr_spans (
                  id, project_id, pipeline_run_id, source_asset_id, parser_run_id,
                  page_number, text, confidence, bbox, language, source_image_ref,
                  content_hash, quality_flags, metadata
                ) VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s::uuid,
                          %s, %s, %s, %s::jsonb, %s, %s,
                          %s, %s::text[], %s::jsonb)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    span_id,
                    job["project_id"],
                    job.get("pipeline_run_id"),
                    asset_dict["id"],
                    job["id"],
                    span.get("page_number"),
                    str(span.get("text") or ""),
                    span.get("confidence"),
                    json.dumps(span.get("bbox")),
                    span.get("language"),
                    span.get("source_image_ref"),
                    str(span.get("content_hash") or content_hash(str(span.get("text") or ""))),
                    list(span.get("quality_flags") or []),
                    json.dumps(span.get("metadata") or {}),
                ),
            )
        for page_index, page in enumerate(parsed.get("pages") or []):
            page_number = int(page.get("page_number") or page_index + 1)
            page_id = stable_pipeline_id("page-snapshot", job["id"], page_number)
            cursor.execute(
                """
                INSERT INTO knowledge_page_snapshots (
                  id, project_id, pipeline_run_id, source_asset_id, parser_run_id,
                  page_number, text_preview, title, source_url, status_code, content_hash, metadata
                ) VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s::uuid,
                          %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    page_id,
                    job["project_id"],
                    job.get("pipeline_run_id"),
                    asset_dict["id"],
                    job["id"],
                    page_number,
                    str(page.get("text_preview") or "")[:2000],
                    str(page.get("title") or asset_dict.get("title") or ""),
                    str(page.get("source_url") or asset_dict.get("source_uri") or "") or None,
                    page.get("status_code"),
                    content_hash(str(page.get("text_preview") or "")),
                    json.dumps(page.get("metadata") or {}),
                ),
            )
        if _pipeline_run_type(repository, str(job.get("pipeline_run_id") or "") or None) != "reparse":
            cursor.execute(
                """
                INSERT INTO chunk_jobs (id, project_id, pipeline_run_id, import_job_id, parser_run_id)
                VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s::uuid)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    stable_pipeline_id("chunk-job", job["id"]),
                    job["project_id"],
                    job.get("pipeline_run_id"),
                    job.get("import_job_id"),
                    job["id"],
                ),
            )
        cursor.execute(
            """
            UPDATE knowledge_parser_runs
            SET block_count = %s,
                table_count = %s,
                ocr_span_count = %s,
                page_count = %s,
                engine_version = %s,
                parser_json_asset_id = %s::uuid,
                parser_markdown_asset_id = %s::uuid,
                output_asset_ids = %s::uuid[],
                quality_score = %s,
                fallback_from_engine = %s,
                fallback_reason = %s,
                quality_signals = %s::jsonb,
                metadata = metadata || %s::jsonb
            WHERE id = %s::uuid
            """,
            (
                len(blocks),
                len(parsed.get("tables") or []),
                len(parsed.get("ocr_spans") or []),
                len(parsed.get("pages") or []),
                str(_json(parsed.get("adapter")).get("engine_version") or "unknown"),
                (parser_json_asset or {}).get("id"),
                (parser_markdown_asset or {}).get("id"),
                [
                    str(asset["id"])
                    for asset in (
                        parser_json_asset,
                        parser_markdown_asset,
                        parser_log_asset,
                        quality_report_asset,
                        ocr_debug_asset,
                        *(asset for pair in table_artifacts.values() for asset in pair),
                    )
                    if asset
                ],
                round(max(0.0, 1.0 - min(1.0, len(quality_findings) * 0.08)), 4),
                (_json(parsed.get("adapter")).get("fallback_from_engines") or [None])[0],
                _json(parsed.get("adapter")).get("fallback_reason"),
                json.dumps(parsed["quality_signals"], ensure_ascii=False),
                json.dumps(
                    {
                        "adapter": parsed.get("adapter"),
                        "artifact_asset_ids": [
                            str(asset["id"])
                            for asset in (
                                parser_json_asset,
                                parser_markdown_asset,
                                parser_log_asset,
                                quality_report_asset,
                                ocr_debug_asset,
                                *(asset for pair in table_artifacts.values() for asset in pair),
                            )
                            if asset
                        ],
                    },
                    ensure_ascii=False,
                ),
                job["id"],
            ),
        )
        cursor.execute(
            """
            UPDATE knowledge_source_assets
            SET status = 'processed', parser_engine = %s, parser_version = %s, updated_at = now()
            WHERE id = %s::uuid
            """,
            (
                str(_json(parsed.get("adapter")).get("engine") or "unknown"),
                str(_json(parsed.get("adapter")).get("engine_version") or "unknown"),
                asset_dict["id"],
            ),
        )
        repository.connection.commit()
    _update_stage(
        repository,
        pipeline_run_id=str(job.get("pipeline_run_id") or "") or None,
        stage_key="parse",
        status="succeeded",
        summary={
            "block_count": len(blocks),
            "table_count": len(parsed.get("tables") or []),
            "ocr_span_count": len(parsed.get("ocr_spans") or []),
            "adapter": parsed.get("adapter"),
        },
    )
    _update_stage(
        repository,
        pipeline_run_id=str(job.get("pipeline_run_id") or "") or None,
        stage_key="ocr",
        status="succeeded" if parsed.get("ocr_spans") else "skipped",
        summary={"ocr_span_count": len(parsed.get("ocr_spans") or [])},
    )
    _update_stage(
        repository,
        pipeline_run_id=str(job.get("pipeline_run_id") or "") or None,
        stage_key="table_extract",
        status="succeeded" if parsed.get("tables") else "skipped",
        summary={"table_count": len(parsed.get("tables") or [])},
    )
    _record_quality_gate(
        repository,
        job=job,
        gate_key="parser_quality_gate",
        status=(
            "blocked"
            if not blocks
            else ("warning" if quality_findings else "passed")
        ),
        summary={"block_count": len(blocks), "quality_signals": parsed.get("quality_signals") or []},
        target_type="parser_run",
        target_id=str(job["id"]),
        additional_findings=quality_findings,
    )
    return {
        "block_count": len(blocks),
        "table_count": len(parsed.get("tables") or []),
        "ocr_span_count": len(parsed.get("ocr_spans") or []),
        "parser_json_asset_id": str((parser_json_asset or {}).get("id") or ""),
        "parser_markdown_asset_id": str((parser_markdown_asset or {}).get("id") or ""),
        "fallback_used": bool(_json(parsed.get("adapter")).get("fallback_from_engines")),
    }


def _optional_object_store():
    required = os.getenv("GENO_KNOWLEDGE_REQUIRE_OBJECT_STORE", "false").strip().lower() in {"1", "true", "yes"}
    if not os.environ.get("OBJECT_STORE_ENDPOINT", "").strip():
        if required:
            raise RuntimeError("knowledge object storage is required but OBJECT_STORE_ENDPOINT is missing")
        return None
    try:
        return build_object_store_from_env()
    except ObjectStoreError as exc:
        if required:
            raise RuntimeError(f"knowledge object storage is unavailable: {exc}") from exc
        return None


def _process_chunk_job(repository: KnowledgePipelineRepository, job: dict[str, Any]) -> dict[str, Any]:
    with _dict_cursor(repository) as cursor:
        cursor.execute(
            """
            SELECT b.*, a.market_code AS asset_market_code, a.locale AS asset_locale, a.city AS asset_city
            FROM knowledge_blocks b
            JOIN knowledge_source_assets a ON a.id = b.source_asset_id
            WHERE b.parser_run_id = %s::uuid
            ORDER BY b.block_index ASC
            """,
            (job["parser_run_id"],),
        )
        blocks = [dict(row) for row in cursor.fetchall()]
        cursor.execute(
            """
            SELECT *
            FROM knowledge_tables
            WHERE parser_run_id = %s::uuid
            ORDER BY table_index ASC
            """,
            (job["parser_run_id"],),
        )
        tables = [dict(row) for row in cursor.fetchall()]
        run_type = _pipeline_run_type(repository, str(job.get("pipeline_run_id") or "") or None)
    if not blocks:
        raise ValueError("no parser blocks to chunk")
    source_asset_id = str(blocks[0].get("source_asset_id") or "")
    with _dict_cursor(repository) as cursor:
        cursor.execute(
            """
            SELECT id, qdrant_point_id, chunk_version
            FROM knowledge_chunks
            WHERE project_id = %s::uuid AND source_asset_id = %s::uuid
              AND status = 'active' AND chunk_job_id <> %s::uuid
            ORDER BY created_at ASC
            """,
            (job["project_id"], source_asset_id, job["id"]),
        )
        prior_chunks = [dict(row) for row in cursor.fetchall()]
    chunk_version = max([int(chunk.get("chunk_version") or 1) for chunk in prior_chunks] or [0]) + 1
    chunk_ids: list[str] = []
    chunk_quality_findings: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for block in blocks:
        for segment_index, segment in enumerate(_split_chunk_text(str(block.get("text") or ""))):
            candidates.append(
                {
                    "text": segment,
                    "chunk_type": str(block.get("block_type") or "text") if block.get("block_type") in {"faq", "policy", "product", "review", "competitor"} else "text",
                    "source_block_ids": [block["id"]],
                    "source_table_ids": [],
                    "source_asset_id": block.get("source_asset_id"),
                    "section_path": list(block.get("section_path") or []),
                    "market_code": block.get("asset_market_code") or "GLOBAL",
                    "locale": block.get("asset_locale") or "en",
                    "city": block.get("asset_city"),
                    "source_order": [int(block.get("block_index") or 0), segment_index],
                }
            )
    for table in tables:
        table_text = str(table.get("markdown") or "").strip() or _table_html_text(table)
        if table_text:
            candidates.append(
                {
                    "text": table_text,
                    "chunk_type": "table",
                    "source_block_ids": [table["block_id"]] if table.get("block_id") else [],
                    "source_table_ids": [table["id"]],
                    "source_asset_id": table.get("source_asset_id") or source_asset_id,
                    "section_path": [],
                    "market_code": blocks[0].get("asset_market_code") or "GLOBAL",
                    "locale": blocks[0].get("asset_locale") or "en",
                    "city": blocks[0].get("asset_city"),
                    "source_order": [100000 + int(table.get("table_index") or 0), 0],
                }
            )
    candidates.sort(key=lambda candidate: tuple(candidate["source_order"]))
    seen_hashes: set[str] = set()
    with repository.connection.cursor() as cursor:
        for index, candidate in enumerate(candidates):
            text = str(candidate.get("text") or "").strip()
            if not text:
                continue
            digest = content_hash(text)
            duplicate = digest in seen_hashes
            seen_hashes.add(digest)
            quality_flags = _chunk_quality_flags(
                text,
                source_present=bool(candidate.get("source_asset_id")),
                chunk_type=str(candidate.get("chunk_type") or "text"),
                duplicate=duplicate,
                locale=str(candidate.get("locale") or "en"),
            )
            chunk_id = stable_pipeline_id("chunk", job["id"], index, content_hash(text)[:16])
            cursor.execute(
                """
                INSERT INTO knowledge_chunks (
                  id, project_id, pipeline_run_id, import_job_id, source_asset_id, parser_run_id, chunk_job_id,
                  status, embedding_status, chunk_type, chunk_index, text, token_count, market_code, locale,
                  city, content_hash, chunk_version, source_block_ids, source_table_ids, section_path, quality_flags
                ) VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s::uuid, %s::uuid, %s::uuid,
                          'active', 'pending', %s, %s, %s, %s, %s, %s,
                          %s, %s, %s, %s::uuid[], %s::uuid[], %s::text[], %s::text[])
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    chunk_id,
                    job["project_id"],
                    job.get("pipeline_run_id"),
                    job.get("import_job_id"),
                    candidate.get("source_asset_id"),
                    job.get("parser_run_id"),
                    job["id"],
                    str(candidate.get("chunk_type") or "text"),
                    index,
                    text,
                    max(1, len(text.split())),
                    str(candidate.get("market_code") or "GLOBAL"),
                    str(candidate.get("locale") or "en"),
                    str(candidate.get("city") or "") or None,
                    digest,
                    chunk_version,
                    list(candidate.get("source_block_ids") or []),
                    list(candidate.get("source_table_ids") or []),
                    list(candidate.get("section_path") or []),
                    quality_flags,
                ),
            )
            for source_type, source_ids in (
                ("block", candidate.get("source_block_ids") or []),
                ("table", candidate.get("source_table_ids") or []),
            ):
                for source_id in source_ids:
                    cursor.execute(
                        """
                        INSERT INTO knowledge_trace_refs (
                          project_id, pipeline_run_id, source_type, source_id, target_type, target_id,
                          trace_role, confidence, created_by_job_type, created_by_job_id, metadata
                        ) VALUES (%s::uuid, %s::uuid, %s, %s, 'chunk', %s,
                                  'derived_from', 1.0, 'chunk_jobs', %s::uuid, %s::jsonb)
                        ON CONFLICT DO NOTHING
                        """,
                        (
                            job["project_id"],
                            job.get("pipeline_run_id"),
                            source_type,
                            str(source_id),
                            chunk_id,
                            job["id"],
                            json.dumps({"content_hash": digest}, ensure_ascii=False),
                        ),
                    )
            if candidate.get("source_asset_id"):
                cursor.execute(
                    """
                    INSERT INTO knowledge_trace_refs (
                      project_id, pipeline_run_id, source_type, source_id, target_type, target_id,
                      trace_role, confidence, created_by_job_type, created_by_job_id, metadata
                    ) VALUES (%s::uuid, %s::uuid, 'source_asset', %s, 'chunk', %s,
                              'derived_from', 1.0, 'chunk_jobs', %s::uuid, %s::jsonb)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        job["project_id"],
                        job.get("pipeline_run_id"),
                        str(candidate["source_asset_id"]),
                        chunk_id,
                        job["id"],
                        json.dumps({"content_hash": digest}, ensure_ascii=False),
                    ),
                )
            for flag in quality_flags:
                chunk_quality_findings.append(
                    {
                        "finding_type": flag,
                        "severity": "warning",
                        "message": f"Chunk {chunk_id} has quality flag {flag}.",
                        "metadata": {"chunk_id": chunk_id, "content_hash": digest},
                    }
                )
            chunk_ids.append(chunk_id)
        if prior_chunks and chunk_ids and run_type in {"reparse", "rechunk", "full_rebuild"}:
            prior_chunk_ids = [str(chunk["id"]) for chunk in prior_chunks]
            cursor.execute(
                """
                UPDATE knowledge_chunks
                SET status = 'superseded', embedding_status = 'stale',
                    superseded_by_chunk_id = %s::uuid, updated_at = now()
                WHERE id = ANY(%s::uuid[])
                """,
                (chunk_ids[0], prior_chunk_ids),
            )
            cursor.execute(
                """
                UPDATE knowledge_fact_candidates
                SET status = 'needs_reextract',
                    metadata = metadata || %s::jsonb,
                    updated_at = now()
                WHERE project_id = %s::uuid
                  AND source_chunk_ids && %s::uuid[]
                  AND status IN ('pending_review', 'approved')
                """,
                (
                    json.dumps(
                        {
                            "reason": "source_chunks_superseded",
                            "replacement_pipeline_run_id": str(job.get("pipeline_run_id") or ""),
                        }
                    ),
                    job["project_id"],
                    prior_chunk_ids,
                ),
            )
            cursor.execute(
                """
                UPDATE localized_knowledge_facts
                SET status = 'superseded',
                    metadata = metadata || %s::jsonb
                WHERE project_id = %s::uuid
                  AND source_chunk_ids && %s::uuid[]
                  AND status = 'active'
                """,
                (
                    json.dumps(
                        {
                            "reason": "source_chunks_superseded",
                            "replacement_pipeline_run_id": str(job.get("pipeline_run_id") or ""),
                        }
                    ),
                    job["project_id"],
                    prior_chunk_ids,
                ),
            )
            cursor.execute(
                """
                UPDATE prompt_candidates
                SET review_status = 'superseded', updated_at = now()
                WHERE project_id = %s::uuid
                  AND source_chunk_ids && %s::uuid[]
                  AND review_status IN ('pending_review', 'approved', 'edited_approved', 'imported')
                """,
                (job["project_id"], prior_chunk_ids),
            )
            cursor.execute(
                """
                UPDATE content_drafts
                SET status = 'needs_revision', review_status = 'needs_revision', updated_at = now()
                WHERE project_id = %s::uuid
                  AND source_chunk_ids && %s::uuid[]
                  AND status IN ('pending_human_review', 'approved', 'published', 'exported')
                """,
                (job["project_id"], prior_chunk_ids),
            )
        cursor.execute(
            """
            UPDATE chunk_jobs
            SET chunk_count = %s, input_block_count = %s, output_chunk_count = %s,
                quality_finding_count = %s
            WHERE id = %s::uuid
            """,
            (len(chunk_ids), len(blocks), len(chunk_ids), len(chunk_quality_findings), job["id"]),
        )
        cursor.execute(
            """
            INSERT INTO embedding_jobs (id, project_id, pipeline_run_id, chunk_job_id)
            VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid)
            ON CONFLICT (id) DO NOTHING
            """,
            (
                stable_pipeline_id("embedding-job", job["id"]),
                job["project_id"],
                job.get("pipeline_run_id"),
                job["id"],
            ),
        )
        repository.connection.commit()
    stale_point_ids = [str(chunk.get("qdrant_point_id") or "") for chunk in prior_chunks if chunk.get("qdrant_point_id")]
    if stale_point_ids and run_type in {"reparse", "rechunk", "full_rebuild"}:
        QdrantKnowledgeStore(collection=os.getenv("QDRANT_COLLECTION") or DEFAULT_QDRANT_COLLECTION).update_payload(
            point_ids=stale_point_ids,
            payload={"status": "superseded", "embedding_status": "stale"},
        )
    _defer_terminal_transaction(repository)
    _update_stage(
        repository,
        pipeline_run_id=str(job.get("pipeline_run_id") or "") or None,
        stage_key="chunk",
        status="succeeded",
        summary={
            "chunk_count": len(chunk_ids),
            "chunk_version": chunk_version,
            "superseded_chunk_count": len(prior_chunks) if run_type in {"reparse", "rechunk", "full_rebuild"} else 0,
        },
    )
    _record_quality_gate(
        repository,
        job=job,
        gate_key="chunk_quality_gate",
        status="passed" if chunk_ids else "blocked",
        summary={"active_chunk_count": len(chunk_ids), "quality_finding_count": len(chunk_quality_findings)},
        target_type="chunk_job",
        target_id=str(job["id"]),
        finding_type="no_active_chunks" if not chunk_ids else None,
        message="Chunking produced no active chunks" if not chunk_ids else None,
        additional_findings=chunk_quality_findings,
    )
    return {
        "chunk_count": len(chunk_ids),
        "chunk_ids": chunk_ids[:20],
        "chunk_version": chunk_version,
        "superseded_chunk_count": len(prior_chunks) if run_type in {"reparse", "rechunk", "full_rebuild"} else 0,
    }


def _process_embedding_job(repository: KnowledgePipelineRepository, job: dict[str, Any]) -> dict[str, Any]:
    with _dict_cursor(repository) as cursor:
        cursor.execute(
            """
            SELECT * FROM knowledge_chunks
            WHERE chunk_job_id = %s::uuid AND status = 'active' AND embedding_status IN ('pending', 'failed', 'stale')
            ORDER BY chunk_index ASC
            """,
            (job["chunk_job_id"],),
        )
        chunks = [dict(row) for row in cursor.fetchall()]
    repository.connection.commit()
    if not chunks:
        return {"embedded_count": 0, "failed_count": 0}
    embedder = LocalBgeM3Embedder(str(job.get("embedding_model") or DEFAULT_EMBEDDING_MODEL))
    embedded: list[tuple[dict[str, Any], list[float]]] = []
    failed_chunks: list[tuple[dict[str, Any], str]] = []
    try:
        vectors = embedder.embed([str(chunk["text"]) for chunk in chunks])
        embedded = list(zip(chunks, vectors, strict=True))
    except Exception:  # noqa: BLE001 - retrying one-by-one isolates malformed chunks.
        for chunk in chunks:
            try:
                vector = embedder.embed([str(chunk["text"])])[0]
                embedded.append((chunk, vector))
            except Exception as exc:  # noqa: BLE001 - persisted below for operator retry.
                failed_chunks.append((chunk, str(exc)))
    qdrant = QdrantKnowledgeStore(
        collection=str(os.getenv("QDRANT_COLLECTION") or job.get("qdrant_collection") or DEFAULT_QDRANT_COLLECTION)
    )
    if not qdrant.enabled() and os.getenv("GENO_KNOWLEDGE_REQUIRE_QDRANT", "false").strip().lower() in {"1", "true", "yes"}:
        raise RuntimeError("Qdrant is required for knowledge embedding but QDRANT_URL is missing")
    embedding_model_version = str(job.get("embedding_model_version") or DEFAULT_EMBEDDING_MODEL_VERSION)
    points = []
    for chunk, vector in embedded:
        point_id = stable_pipeline_id("qdrant-point", chunk["id"], embedding_model_version)
        points.append(
            {
                "id": point_id,
                "vector": vector,
                "payload": {
                    "project_id": str(chunk["project_id"]),
                    "pipeline_run_id": str(job.get("pipeline_run_id") or chunk.get("pipeline_run_id") or ""),
                    "source_pipeline_run_id": str(chunk.get("pipeline_run_id") or ""),
                    "import_job_id": str(chunk.get("import_job_id") or ""),
                    "embedding_job_id": str(job["id"]),
                    "chunk_job_id": str(chunk.get("chunk_job_id") or ""),
                    "parser_run_id": str(chunk.get("parser_run_id") or ""),
                    "chunk_id": str(chunk["id"]),
                    "source_asset_id": str(chunk.get("source_asset_id") or ""),
                    "market_code": str(chunk.get("market_code") or "GLOBAL"),
                    "locale": str(chunk.get("locale") or "en"),
                    "city": str(chunk.get("city") or ""),
                    "chunk_type": str(chunk.get("chunk_type") or "text"),
                    "status": "active",
                    "embedding_status": "embedded",
                    "content_hash": str(chunk.get("content_hash") or ""),
                    "chunk_version": int(chunk.get("chunk_version") or 1),
                    "embedding_model": str(job.get("embedding_model") or DEFAULT_EMBEDDING_MODEL),
                    "embedding_model_version": embedding_model_version,
                    "embedding_backend": embedder.last_backend,
                    "created_at": str(chunk.get("created_at") or ""),
                },
            }
        )
    if points:
        qdrant.upsert(points=points, vector_size=len(embedded[0][1]))
    success_ratio = round(len(points) / max(1, len(chunks)), 4)
    threshold_passed = bool(points) and success_ratio >= EMBEDDING_MIN_SUCCESS_RATIO
    _defer_terminal_transaction(repository)
    with repository.connection.cursor() as cursor:
        for (chunk, _vector), point in zip(embedded, points, strict=True):
            cursor.execute(
                """
                UPDATE knowledge_chunks
                SET embedding_status = 'embedded', qdrant_point_id = %s, updated_at = now()
                WHERE id = %s::uuid
                """,
                (point["id"], chunk["id"]),
            )
        for chunk, error_message in failed_chunks:
            cursor.execute(
                """
                UPDATE knowledge_chunks
                SET embedding_status = 'failed', updated_at = now(),
                    metadata = metadata || %s::jsonb
                WHERE id = %s::uuid
                """,
                (json.dumps({"embedding_error": error_message[:1000]}, ensure_ascii=False), chunk["id"]),
            )
        cursor.execute(
            """
            UPDATE embedding_jobs SET embedded_count = %s, failed_count = %s WHERE id = %s::uuid
            """,
            (len(points), len(failed_chunks), job["id"]),
        )
        run_type = _pipeline_run_type(repository, str(job.get("pipeline_run_id") or "") or None)
        if threshold_passed and run_type not in {"rechunk", "reindex"}:
            cursor.execute(
                """
                INSERT INTO fact_extraction_jobs (
                  id, project_id, pipeline_run_id, import_job_id, fact_kinds, chunk_filter, max_facts, metadata
                )
                SELECT %s::uuid, %s::uuid, %s::uuid, cj.import_job_id, ARRAY['brand', 'competitor', 'market', 'source']::text[],
                       %s::jsonb, 20, %s::jsonb
                FROM chunk_jobs cj
                WHERE cj.id = %s::uuid
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    stable_pipeline_id("fact-extraction-job", job["id"]),
                    job["project_id"],
                    job.get("pipeline_run_id"),
                    json.dumps({"source_pipeline_run_id": str(chunks[0].get("pipeline_run_id") or "")}),
                    json.dumps({"trigger": "embedding_succeeded", "embedding_job_id": str(job["id"])}, ensure_ascii=False),
                    job["chunk_job_id"],
                ),
            )
        repository.connection.commit()
    _update_stage(
        repository,
        pipeline_run_id=str(job.get("pipeline_run_id") or "") or None,
        stage_key="embedding",
        status="succeeded" if threshold_passed else "blocked",
        summary={
            "embedded_count": len(points),
            "failed_count": len(failed_chunks),
            "success_ratio": success_ratio,
            "minimum_success_ratio": EMBEDDING_MIN_SUCCESS_RATIO,
            "qdrant_enabled": qdrant.enabled(),
            "embedding_backend": embedder.last_backend,
            "vector_dimension": len(embedded[0][1]) if embedded else 0,
        },
    )
    _record_quality_gate(
        repository,
        job=job,
        gate_key="embedding_gate",
        status="passed" if len(points) == len(chunks) else ("warning" if threshold_passed else "blocked"),
        summary={
            "active_chunk_count": len(chunks),
            "embedded_count": len(points),
            "success_ratio": success_ratio,
            "minimum_success_ratio": EMBEDDING_MIN_SUCCESS_RATIO,
            "embedding_backend": embedder.last_backend,
            "vector_dimension": len(embedded[0][1]) if embedded else 0,
        },
        target_type="embedding_job",
        target_id=str(job["id"]),
        finding_type="embedding_incomplete" if len(points) != len(chunks) else None,
        message="Not all active chunks were embedded" if len(points) != len(chunks) else None,
    )
    if not threshold_passed:
        raise RuntimeError(
            f"embedding success ratio {success_ratio:.4f} is below required {EMBEDDING_MIN_SUCCESS_RATIO:.4f}"
        )
    return {
        "embedded_count": len(points),
        "failed_count": len(failed_chunks),
        "success_ratio": success_ratio,
        "qdrant_enabled": qdrant.enabled(),
        "embedding_backend": embedder.last_backend,
        "vector_dimension": len(embedded[0][1]),
    }


def _process_fact_extraction_job(repository: KnowledgePipelineRepository, job: dict[str, Any]) -> dict[str, Any]:
    chunk_filter = _json(job.get("chunk_filter"))
    source_pipeline_run_id = str(chunk_filter.get("source_pipeline_run_id") or job.get("pipeline_run_id") or "") or None
    with _dict_cursor(repository) as cursor:
        cursor.execute(
            """
            SELECT id, target_brand, category, market_code
            FROM projects
            WHERE id = %s::uuid
            LIMIT 1
            """,
            (job["project_id"],),
        )
        project = dict(cursor.fetchone() or {})
        cursor.execute(
            """
            SELECT *
            FROM knowledge_chunks
            WHERE project_id = %s::uuid
              AND (%s::uuid IS NULL OR pipeline_run_id = %s::uuid)
              AND (%s::uuid IS NULL OR import_job_id = %s::uuid)
              AND (%s::uuid IS NULL OR source_asset_id = %s::uuid)
              AND (%s = '' OR chunk_type = %s)
              AND (%s = '' OR %s = ANY(quality_flags))
              AND status = 'active'
              AND embedding_status = 'embedded'
            ORDER BY chunk_index ASC
            LIMIT %s
            """,
            (
                job["project_id"],
                source_pipeline_run_id,
                source_pipeline_run_id,
                job.get("import_job_id"),
                job.get("import_job_id"),
                str(chunk_filter.get("source_asset_id") or "") or None,
                str(chunk_filter.get("source_asset_id") or "") or None,
                str(chunk_filter.get("chunk_type") or ""),
                str(chunk_filter.get("chunk_type") or ""),
                str(chunk_filter.get("quality_flag") or ""),
                str(chunk_filter.get("quality_flag") or ""),
                max(1, int(job.get("max_facts") or 20)),
            ),
        )
        chunks = [dict(row) for row in cursor.fetchall()]
    repository.connection.commit()
    if not chunks:
        _defer_terminal_transaction(repository)
        _update_stage(
            repository,
            pipeline_run_id=str(job.get("pipeline_run_id") or "") or None,
            stage_key="fact_extract",
            status="blocked",
            summary={"reason": "no embedded chunks available"},
        )
        return {"candidate_count": 0, "blocked": True}
    target_brand = str(project.get("target_brand") or "项目品牌")
    category = str(project.get("category") or "GEO knowledge")
    raw_text = "\n".join(_short_text(str(chunk.get("text") or ""), limit=1200) for chunk in chunks)
    allowed_fact_kinds = {
        str(value).strip().lower()
        for value in (job.get("fact_kinds") or ["brand", "competitor", "market", "source"])
        if str(value).strip()
    }
    model_facts: list[dict[str, Any]] = []
    model_status = "fallback"
    api_key = load_deepseek_api_key()
    if api_key:
        try:
            model_facts = list(
                deepseek_extract_knowledge_facts(
                    api_key=api_key,
                    raw_text=raw_text,
                    target_brand=target_brand,
                    category=category,
                    market_code=str(project.get("market_code") or "GLOBAL"),
                    max_facts=max(1, int(job.get("max_facts") or 20)),
                    requested_fact_kinds=tuple(sorted(allowed_fact_kinds)),
                    model=str(job.get("model") or "deepseek-v4-flash"),
                )
            )
            model_status = "deepseek_succeeded"
        except ValueError as exc:
            if _require_real_model():
                raise RuntimeError(f"DeepSeek fact extraction failed: {exc}") from exc
            model_status = f"deepseek_fallback:{exc}"
    elif _require_real_model():
        raise RuntimeError("DeepSeek API key is required for knowledge fact extraction")
    candidate_ids: list[str] = []
    fact_quality_findings: list[dict[str, Any]] = []
    _defer_terminal_transaction(repository)
    with _dict_cursor(repository) as cursor:
        cursor.execute(
            """
            SELECT subject, predicate, object_value, market_code, city
            FROM localized_knowledge_facts
            WHERE project_id = %s::uuid AND status = 'active'
            UNION ALL
            SELECT subject, predicate, object_value, market_code, city
            FROM knowledge_fact_candidates
            WHERE project_id = %s::uuid AND status IN ('pending_review', 'approved')
            """,
            (job["project_id"], job["project_id"]),
        )
        existing_facts = [dict(row) for row in cursor.fetchall()]
        seen_signatures = {
            (
                str(row.get("subject") or "").strip().lower(),
                str(row.get("predicate") or "").strip().lower(),
                str(row.get("object_value") or "").strip().lower(),
                str(row.get("market_code") or "GLOBAL").strip().upper(),
                str(row.get("city") or "").strip().lower(),
            )
            for row in existing_facts
        }
        existing_by_key: dict[tuple[str, str, str, str], set[str]] = {}
        for row in existing_facts:
            key = (
                str(row.get("subject") or "").strip().lower(),
                str(row.get("predicate") or "").strip().lower(),
                str(row.get("market_code") or "GLOBAL").strip().upper(),
                str(row.get("city") or "").strip().lower(),
            )
            existing_by_key.setdefault(key, set()).add(str(row.get("object_value") or "").strip().lower())
        source_items: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
        if model_facts:
            for index, model_fact in enumerate(model_facts):
                source_items.append((chunks[min(index, len(chunks) - 1)], model_fact))
        else:
            source_items = [(chunk, None) for chunk in chunks]
        for index, (chunk, model_fact) in enumerate(source_items):
            text = _short_text(str(chunk.get("text") or ""), limit=420)
            if not text:
                continue
            fact_id = stable_pipeline_id("fact-candidate", job["id"], chunk["id"], index, content_hash(text)[:16])
            fact_kind = str((model_fact or {}).get("fact_kind") or ("brand" if index == 0 else "source")).strip().lower()
            if fact_kind not in {"brand", "competitor", "market", "source"}:
                fact_kind = "source"
            if allowed_fact_kinds and fact_kind not in allowed_fact_kinds:
                continue
            object_value = str((model_fact or {}).get("object_value") or text).strip()
            subject = str((model_fact or {}).get("subject") or (target_brand if fact_kind == "brand" else category)).strip()
            predicate = str((model_fact or {}).get("predicate") or "states").strip()
            fact_type = str((model_fact or {}).get("fact_type") or ("brand_claim" if fact_kind == "brand" else "source_claim")).strip()
            city = (model_fact or {}).get("city") or chunk.get("city")
            confidence = float((model_fact or {}).get("confidence") or (0.72 if fact_kind == "brand" else 0.68))
            market_code = str((model_fact or {}).get("market_code") or chunk.get("market_code") or project.get("market_code") or "GLOBAL").upper()
            signature = (subject.lower(), predicate.lower(), object_value.lower(), market_code, str(city or "").lower())
            conflict_key = (subject.lower(), predicate.lower(), market_code, str(city or "").lower())
            quality_flags: list[str] = []
            if confidence < 0.6:
                quality_flags.append("fact_low_confidence")
            if signature in seen_signatures:
                quality_flags.append("fact_duplicate")
            elif existing_by_key.get(conflict_key) and object_value.lower() not in existing_by_key[conflict_key]:
                quality_flags.append("fact_conflict")
            source_market = str(chunk.get("market_code") or project.get("market_code") or "GLOBAL").upper()
            if market_code not in {"GLOBAL", source_market} and source_market != "GLOBAL":
                quality_flags.append("fact_market_mismatch")
            if fact_kind == "competitor" and subject.strip().lower() == target_brand.strip().lower():
                quality_flags.append("fact_competitor_alias_conflict")
            object_terms = {term for term in re.findall(r"[\w-]+", object_value.lower()) if len(term) >= 4}
            source_terms = {term for term in re.findall(r"[\w-]+", text.lower()) if len(term) >= 4}
            if model_fact and object_terms and len(object_terms & source_terms) / len(object_terms) < 0.2:
                quality_flags.append("fact_unsupported_claim")
            if re.search(r"\bsk-[A-Za-z0-9_-]{16,}\b", object_value):
                quality_flags.append("fact_forbidden_claim")
            cursor.execute(
                """
                INSERT INTO knowledge_fact_candidates (
                  id, project_id, pipeline_run_id, fact_extraction_job_id, fact_kind, fact_type,
                  subject, predicate, object_value, market_code, locale, city, confidence,
                  status, source_chunk_ids, source_block_ids, source_asset_ids,
                  extraction_model, extraction_prompt_version, metadata
                ) VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s, %s,
                          %s, %s, %s, %s, %s, %s, %s,
                          'pending_review', ARRAY[%s::uuid], %s::uuid[], ARRAY[%s::uuid],
                          %s, %s, %s::jsonb)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    fact_id,
                    job["project_id"],
                    job.get("pipeline_run_id"),
                    job["id"],
                    fact_kind,
                    fact_type,
                    subject,
                    predicate,
                    object_value,
                    market_code,
                    chunk.get("locale") or "en",
                    city,
                    confidence,
                    chunk["id"],
                    list(chunk.get("source_block_ids") or []),
                    chunk.get("source_asset_id"),
                    str(job.get("model") or "deepseek-v4-flash"),
                    str(job.get("prompt_version") or "knowledge_fact_extraction_v1"),
                    json.dumps({"extractor": "deepseek-v4-flash", "model_status": model_status, "requires_human_review": True, "quality_flags": quality_flags}, ensure_ascii=False),
                ),
            )
            cursor.execute(
                """
                INSERT INTO knowledge_trace_refs (
                  project_id, pipeline_run_id, source_type, source_id, target_type, target_id,
                  trace_role, confidence, created_by_job_type, created_by_job_id, metadata
                ) VALUES (%s::uuid, %s::uuid, 'chunk', %s, 'fact_candidate', %s,
                          'supporting_evidence', %s, 'fact_extraction_jobs', %s::uuid, %s::jsonb)
                ON CONFLICT DO NOTHING
                """,
                (
                    job["project_id"],
                    job.get("pipeline_run_id"),
                    str(chunk["id"]),
                    fact_id,
                    confidence,
                    job["id"],
                    json.dumps({"content_hash": str(chunk.get("content_hash") or "")}, ensure_ascii=False),
                ),
            )
            candidate_ids.append(fact_id)
            seen_signatures.add(signature)
            existing_by_key.setdefault(conflict_key, set()).add(object_value.lower())
            for flag in quality_flags:
                fact_quality_findings.append(
                    {
                        "finding_type": flag,
                        "severity": "high" if flag in {"fact_forbidden_claim"} else "warning",
                        "message": f"Fact candidate {fact_id} has quality flag {flag}.",
                        "metadata": {"fact_candidate_id": fact_id, "source_chunk_id": str(chunk["id"])},
                    }
                )
        fact_threshold_passed = len(candidate_ids) >= FACT_MIN_CANDIDATE_COUNT
        cursor.execute(
            """
            UPDATE fact_extraction_jobs
            SET output_candidate_count = %s,
                metadata = metadata || %s::jsonb
            WHERE id = %s::uuid
            """,
            (
                len(candidate_ids),
                json.dumps({"model_status": model_status, "model_fact_count": len(model_facts)}, ensure_ascii=False),
                job["id"],
            ),
        )
        if job.get("pipeline_run_id") and fact_threshold_passed:
            cursor.execute(
                """
                UPDATE knowledge_pipeline_runs
                SET status = 'waiting_human_review',
                    waiting_review_stage_key = 'fact_review',
                    waiting_review_count = %s,
                    summary = summary || %s::jsonb,
                    updated_at = now()
                WHERE id = %s::uuid
                """,
                (
                    len(candidate_ids),
                    json.dumps({"fact_candidate_count": len(candidate_ids)}, ensure_ascii=False),
                    job["pipeline_run_id"],
                ),
            )
        repository.connection.commit()
    _update_stage(
        repository,
        pipeline_run_id=str(job.get("pipeline_run_id") or "") or None,
        stage_key="fact_extract",
        status="succeeded" if fact_threshold_passed else "blocked",
        summary={
            "candidate_count": len(candidate_ids),
            "minimum_candidate_count": FACT_MIN_CANDIDATE_COUNT,
        },
    )
    _update_stage(
        repository,
        pipeline_run_id=str(job.get("pipeline_run_id") or "") or None,
        stage_key="fact_review",
        status="waiting_review" if fact_threshold_passed else "blocked",
        summary={"waiting_review_count": len(candidate_ids)},
    )
    _record_quality_gate(
        repository,
        job=job,
        gate_key="fact_quality_gate",
        status="blocked" if not fact_threshold_passed else ("warning" if fact_quality_findings else "passed"),
        summary={
            "candidate_count": len(candidate_ids),
            "minimum_candidate_count": FACT_MIN_CANDIDATE_COUNT,
            "model_status": model_status,
            "quality_finding_count": len(fact_quality_findings),
        },
        target_type="fact_extraction_job",
        target_id=str(job["id"]),
        finding_type="insufficient_fact_candidates" if not fact_threshold_passed else None,
        message="Fact extraction produced fewer traceable candidates than required" if not fact_threshold_passed else None,
        additional_findings=fact_quality_findings,
    )
    forbidden_findings = [
        finding for finding in fact_quality_findings if finding.get("finding_type") == "fact_forbidden_claim"
    ]
    _record_quality_gate(
        repository,
        job=job,
        gate_key="security_gate",
        status="blocked" if forbidden_findings else "passed",
        summary={"forbidden_fact_candidate_count": len(forbidden_findings)},
        target_type="fact_extraction_job",
        target_id=str(job["id"]),
        additional_findings=forbidden_findings,
    )
    return {
        "candidate_count": len(candidate_ids),
        "candidate_ids": candidate_ids[:20],
        "model_status": model_status,
        "blocked": not fact_threshold_passed,
    }


def _load_active_facts(repository: KnowledgePipelineRepository, job: dict[str, Any], *, limit: int = 50) -> list[dict[str, Any]]:
    fact_filter = _json(job.get("source_fact_filter"))
    chunk_filter = _json(job.get("source_chunk_filter"))
    clauses = [
        "f.project_id = %s::uuid",
        "f.status = 'active'",
        "cardinality(f.source_chunk_ids) > 0",
        "NOT EXISTS (SELECT 1 FROM knowledge_chunks c WHERE c.id = ANY(f.source_chunk_ids) AND (c.status <> 'active' OR c.embedding_status <> 'embedded'))",
    ]
    params: list[Any] = [job["project_id"]]
    for key in ("fact_kind", "fact_type", "market_code", "city"):
        value = str(fact_filter.get(key) or "").strip()
        if value:
            clauses.append(f"f.{key} = %s")
            params.append(value)
    competitor = str(fact_filter.get("competitor") or fact_filter.get("subject") or "").strip()
    if competitor:
        clauses.append("f.subject ILIKE %s")
        params.append(f"%{competitor}%")
    chunk_clauses = ["c.id = ANY(f.source_chunk_ids)", "c.status = 'active'", "c.embedding_status = 'embedded'"]
    source_asset_id = str(chunk_filter.get("source_asset_id") or "").strip()
    if source_asset_id:
        chunk_clauses.append("c.source_asset_id = %s::uuid")
        params.append(source_asset_id)
    chunk_type = str(chunk_filter.get("chunk_type") or "").strip()
    if chunk_type:
        chunk_clauses.append("c.chunk_type = %s")
        params.append(chunk_type)
    quality_flag = str(chunk_filter.get("quality_flag") or "").strip()
    if quality_flag:
        chunk_clauses.append("%s = ANY(c.quality_flags)")
        params.append(quality_flag)
    chunk_query = str(chunk_filter.get("query") or "").strip()
    if chunk_query:
        chunk_clauses.append("c.text ILIKE %s")
        params.append(f"%{chunk_query}%")
    if len(chunk_clauses) > 3:
        clauses.append("EXISTS (SELECT 1 FROM knowledge_chunks c WHERE " + " AND ".join(chunk_clauses) + ")")
    params.append(limit)
    with _dict_cursor(repository) as cursor:
        cursor.execute(
            f"""
            SELECT *
            FROM localized_knowledge_facts f
            WHERE {' AND '.join(clauses)}
            ORDER BY confidence DESC, valid_from DESC
            LIMIT %s
            """,
            tuple(params),
        )
        facts = [dict(row) for row in cursor.fetchall()]
    repository.connection.commit()
    return facts


def _process_prompt_generation_job(repository: KnowledgePipelineRepository, job: dict[str, Any]) -> dict[str, Any]:
    facts = _load_active_facts(repository, job, limit=max(1, int(job.get("requested_count") or 10)))
    if not facts:
        raise RuntimeError("Prompt generation requires active approved facts backed by active embedded chunks")
    with _dict_cursor(repository) as cursor:
        cursor.execute(
            """
            SELECT * FROM prompt_generation_templates
            WHERE id = %s::uuid AND status = 'published'
            LIMIT 1
            """,
            (job.get("template_id"),),
        )
        template = dict(cursor.fetchone() or {})
        cursor.execute(
            """
            SELECT text FROM prompt_questions WHERE project_id = %s::uuid
            UNION ALL
            SELECT text FROM prompt_candidates WHERE project_id = %s::uuid
            """,
            (job["project_id"], job["project_id"]),
        )
        existing_prompt_texts = [str(row[0] if not isinstance(row, dict) else row.get("text") or "") for row in cursor.fetchall()]
    repository.connection.commit()
    if not template:
        raise RuntimeError("Prompt generation requires a published template version")
    model_output: dict[str, Any] | None = None
    model_status = "fallback"
    api_key = load_deepseek_api_key()
    if api_key:
        try:
            model_output = deepseek_generate_knowledge_application(
                api_key=api_key,
                target_brand=str(facts[0]["subject"]),
                category="GEO knowledge",
                market_code=str(facts[0]["market_code"]),
                facts=tuple(facts),
                prompts=(),
                generation_type="prompt_candidates",
                content_type="prompt",
                target_platform=str(job.get("target_platform") or "chatgpt"),
                intent_type=str(job.get("intent_type") or "brand_visibility"),
                city=str(job.get("city") or "") or None,
                competitor=str(_json(job.get("source_fact_filter")).get("competitor") or "") or None,
                quantity=max(1, int(job.get("requested_count") or 10)),
                model=str(job.get("model") or "deepseek-v4-flash"),
                template_instruction=str(template.get("system_prompt") or template.get("template_body") or ""),
                output_schema=dict(template.get("output_schema") or {}) or None,
            )
            model_status = "deepseek_succeeded"
        except ValueError as exc:
            if _require_real_model():
                raise RuntimeError(f"DeepSeek Prompt generation failed: {exc}") from exc
            model_status = f"deepseek_fallback:{exc}"
    elif _require_real_model():
        raise RuntimeError("DeepSeek API key is required for Prompt generation")
    model_candidates = _model_items((model_output or {}).get("prompt_candidates"))
    fact_ids = [str(fact["id"]) for fact in facts]
    chunk_ids = sorted({str(chunk_id) for fact in facts for chunk_id in (fact.get("source_chunk_ids") or []) if chunk_id})
    candidate_ids: list[str] = []
    prompt_quality_findings: list[dict[str, Any]] = []
    selected_competitor = str(_json(job.get("source_fact_filter")).get("competitor") or "").strip()
    _defer_terminal_transaction(repository)
    with repository.connection.cursor() as cursor:
        for index, fact in enumerate(facts):
            model_candidate = model_candidates[index] if index < len(model_candidates) else {}
            prompt_text = str(
                model_candidate.get("text")
                or model_candidate.get("prompt")
                or f"What should I know about {fact['subject']} for {fact['market_code']} {fact.get('city') or 'customers'}?"
            ).strip()
            normalized_prompt = " ".join(prompt_text.lower().split())
            normalized_existing = [" ".join(value.lower().split()) for value in existing_prompt_texts if value.strip()]
            duplicate_state = "duplicate" if normalized_prompt in normalized_existing else "unique"
            if duplicate_state == "unique":
                prompt_terms = set(normalized_prompt.split())
                for existing in normalized_existing:
                    existing_terms = set(existing.split())
                    similarity = len(prompt_terms & existing_terms) / max(1, len(prompt_terms | existing_terms))
                    if similarity >= 0.8:
                        duplicate_state = "possible_duplicate"
                        break
            risk_flags = [duplicate_state] if duplicate_state != "unique" else []
            model_risk_flags = model_candidate.get("risk_flags")
            if isinstance(model_risk_flags, list):
                risk_flags.extend(str(flag) for flag in model_risk_flags if str(flag).strip())
            generated_city = str(model_candidate.get("city") or "").strip()
            requested_city = str(job.get("city") or "").strip()
            if generated_city and requested_city and generated_city.lower() != requested_city.lower():
                risk_flags.append("prompt_city_mismatch")
            if selected_competitor and selected_competitor.lower() not in prompt_text.lower():
                risk_flags.append("prompt_competitor_misreference")
            risk_flags = list(dict.fromkeys(risk_flags))
            candidate_id = stable_pipeline_id("prompt-candidate", job["id"], fact["id"], index)
            cursor.execute(
                """
                INSERT INTO prompt_candidates (
                  id, project_id, pipeline_run_id, generation_job_id, prompt_generation_job_id, text, intent_type,
                  market_code, city, language, target_brand, competitors, priority, intent_weight,
                  source_knowledge_fact_ids, source_chunk_ids, rationale, duplicate_state,
                  review_status, generation_model, generation_prompt_version, risk_flags,
                  target_platform, prompt_template_id, prompt_template_version
                ) VALUES (%s::uuid, %s::uuid, %s::uuid, null, %s::uuid, %s, %s,
                          %s, %s, %s, %s, '[]'::jsonb, %s, %s,
                          ARRAY[%s::uuid], %s::uuid[], %s, %s,
                          'pending_review', %s, %s, %s::jsonb,
                          %s, %s::uuid, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    candidate_id,
                    job["project_id"],
                    job.get("pipeline_run_id"),
                    job["id"],
                    prompt_text,
                    job.get("intent_type") or "brand_visibility",
                    fact["market_code"],
                    job.get("city") or fact.get("city") or "",
                    fact.get("locale") or "en",
                    fact["subject"],
                    index + 1,
                    1.0,
                    fact["id"],
                    list(fact.get("source_chunk_ids") or []),
                    f"Generated from approved fact: {_short_text(str(fact['object_value']), limit=160)}",
                    duplicate_state,
                    job.get("model") or "deepseek-v4-flash",
                    job.get("template_version") or "v1",
                    json.dumps(risk_flags, ensure_ascii=False),
                    job.get("target_platform") or "chatgpt",
                    job.get("template_id"),
                    job.get("template_version") or "v1",
                ),
            )
            cursor.execute(
                """
                INSERT INTO knowledge_trace_refs (
                  project_id, pipeline_run_id, source_type, source_id, target_type, target_id,
                  trace_role, confidence, created_by_job_type, created_by_job_id, metadata
                ) VALUES (%s::uuid, %s::uuid, 'approved_fact', %s, 'prompt_candidate', %s,
                          'prompt_input', %s, 'prompt_generation_jobs', %s::uuid, %s::jsonb)
                ON CONFLICT DO NOTHING
                """,
                (
                    job["project_id"],
                    job.get("pipeline_run_id"),
                    str(fact["id"]),
                    candidate_id,
                    fact.get("confidence"),
                    job["id"],
                    json.dumps({"prompt_text_hash": content_hash(prompt_text)}, ensure_ascii=False),
                ),
            )
            candidate_ids.append(candidate_id)
            existing_prompt_texts.append(prompt_text)
            for flag in risk_flags:
                prompt_quality_findings.append(
                    {
                        "finding_type": flag,
                        "severity": "warning",
                        "message": f"Prompt candidate {candidate_id} has quality flag {flag}.",
                        "metadata": {"prompt_candidate_id": candidate_id},
                    }
                )
        cursor.execute(
            "UPDATE prompt_generation_jobs SET generated_count = %s, metadata = metadata || %s::jsonb WHERE id = %s::uuid",
            (
                len(candidate_ids),
                json.dumps(
                    {
                        "model_status": model_status,
                        "model_response_hash": (model_output or {}).get("response_hash"),
                    },
                    ensure_ascii=False,
                ),
                job["id"],
            ),
        )
        if job.get("pipeline_run_id"):
            cursor.execute(
                """
                UPDATE knowledge_pipeline_runs
                SET status = 'waiting_human_review',
                    waiting_review_stage_key = 'prompt_review',
                    waiting_review_count = %s,
                    summary = summary || %s::jsonb,
                    updated_at = now()
                WHERE id = %s::uuid
                """,
                (
                    len(candidate_ids),
                    json.dumps({"prompt_candidate_count": len(candidate_ids)}, ensure_ascii=False),
                    job["pipeline_run_id"],
                ),
            )
        repository.connection.commit()
    _update_stage(
        repository,
        pipeline_run_id=str(job.get("pipeline_run_id") or "") or None,
        stage_key="prompt_generate",
        status="succeeded" if candidate_ids else "blocked",
        summary={"generated_count": len(candidate_ids)},
    )
    _update_stage(
        repository,
        pipeline_run_id=str(job.get("pipeline_run_id") or "") or None,
        stage_key="prompt_review",
        status="waiting_review" if candidate_ids else "blocked",
        summary={"waiting_review_count": len(candidate_ids)},
    )
    _record_quality_gate(
        repository,
        job=job,
        gate_key="generation_quality_gate",
        status=(
            "blocked" if not (candidate_ids and fact_ids and chunk_ids)
            else ("warning" if prompt_quality_findings else "passed")
        ),
        summary={
            "prompt_candidate_count": len(candidate_ids),
            "source_fact_count": len(fact_ids),
            "source_chunk_count": len(chunk_ids),
            "model_status": model_status,
            "quality_finding_count": len(prompt_quality_findings),
        },
        target_type="prompt_generation_job",
        target_id=str(job["id"]),
        finding_type="prompt_generation_untraceable" if not (candidate_ids and fact_ids and chunk_ids) else None,
        message="Prompt generation output is missing approved fact or chunk evidence" if not (candidate_ids and fact_ids and chunk_ids) else None,
        additional_findings=prompt_quality_findings,
    )
    return {"generated_count": len(candidate_ids), "prompt_candidate_ids": candidate_ids[:20], "model_status": model_status}


def _process_content_generation_job(repository: KnowledgePipelineRepository, job: dict[str, Any]) -> dict[str, Any]:
    facts = _load_active_facts(repository, job, limit=5)
    if not facts:
        raise RuntimeError("Content generation requires active approved facts backed by active embedded chunks")
    model_output: dict[str, Any] | None = None
    model_status = "fallback"
    api_key = load_deepseek_api_key()
    if api_key:
        try:
            model_output = deepseek_generate_knowledge_application(
                api_key=api_key,
                target_brand=str(facts[0]["subject"]),
                category="GEO knowledge",
                market_code=str(facts[0]["market_code"]),
                facts=tuple(facts),
                prompts=(),
                generation_type="content_draft",
                content_type=str(job.get("content_type") or "faq"),
                target_platform=str(job.get("target_platform") or "chatgpt"),
                intent_type=None,
                city=str(job.get("target_city") or "") or None,
                competitor=None,
                quantity=1,
                model=str(job.get("model") or "deepseek-v4-flash"),
                target_audience=str(job.get("target_audience") or "general customer"),
                forbidden_claims=tuple(str(value) for value in (job.get("forbidden_claims") or []) if str(value).strip()),
                target_action=_json(job.get("target_action")),
            )
            model_status = "deepseek_succeeded"
        except ValueError as exc:
            if _require_real_model():
                raise RuntimeError(f"DeepSeek content generation failed: {exc}") from exc
            model_status = f"deepseek_fallback:{exc}"
    elif _require_real_model():
        raise RuntimeError("DeepSeek API key is required for content generation")
    fact_ids = [str(fact["id"]) for fact in facts]
    chunk_ids = sorted({str(chunk_id) for fact in facts for chunk_id in (fact.get("source_chunk_ids") or []) if chunk_id})
    title = f"{facts[0]['subject']} GEO {job.get('content_type') or 'FAQ'} draft"
    model_markdown = str((model_output or {}).get("content_markdown") or "").strip()
    if model_markdown:
        draft_markdown = _ensure_target_brand_in_markdown(
            model_markdown,
            target_brand=str(facts[0]["subject"]),
            title=title,
        )
    else:
        body_lines = [
            f"# {title}",
            "",
            "## Approved knowledge summary",
            *[f"- {fact['subject']} {fact['predicate']} {_short_text(str(fact['object_value']), limit=220)}" for fact in facts],
            "",
            "## GEO-ready answer",
            f"{facts[0]['subject']} should be described with concrete, source-backed claims for {facts[0]['market_code']} customers.",
        ]
        draft_markdown = "\n".join(body_lines)
    forbidden_matches = [
        claim
        for claim in (str(value).strip() for value in (job.get("forbidden_claims") or []))
        if claim and claim.lower() in draft_markdown.lower()
    ]
    required_citations = max(1, int(job.get("required_citations") or 1))
    model_risk_flags = [str(value) for value in ((model_output or {}).get("risk_flags") or []) if str(value).strip()]
    risk_flags = list(dict.fromkeys([
        *model_risk_flags,
        *(f"forbidden_claim:{claim}" for claim in forbidden_matches),
        *(["insufficient_citation_evidence"] if len(chunk_ids) < required_citations else []),
    ]))
    draft_summary = str((model_output or {}).get("summary") or _short_text(draft_markdown, limit=300))
    target_action = _json(job.get("target_action"))
    source_action_id = str(target_action.get("source_action_id") or "") or None
    source_gap_type = str(target_action.get("source_gap_type") or "") or None
    draft_id = stable_pipeline_id("content-draft", job["id"], content_hash(draft_markdown)[:16])
    _defer_terminal_transaction(repository)
    with repository.connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO content_drafts (
              id, project_id, title, content_type, content_template_id, target_question_ids,
              target_city, target_platform, target_source_type, used_knowledge_fact_ids,
              source_gap_types, source_action_id, evidence_answer_run_ids, draft_markdown,
              review_status, created_by, generation_job_id, source_fact_ids,
              generation_model, generation_prompt_version, raw_output_hash,
              pipeline_run_id, content_generation_job_id, source_chunk_ids, citation_refs, status,
              summary, risk_flags
            ) VALUES (%s::uuid, %s::uuid, %s, %s, 'geo_content_draft_v1', '{}',
                      %s, %s, 'approved_knowledge_fact', %s::uuid[],
                      %s::text[], %s::uuid, '{}', %s,
                      'pending_human_review', 'knowledge-worker', null, %s::uuid[],
                      %s, %s, %s,
                      %s::uuid, %s::uuid, %s::uuid[], %s::jsonb, 'pending_human_review',
                      %s, %s::jsonb)
            ON CONFLICT (id) DO NOTHING
            """,
            (
                draft_id,
                job["project_id"],
                title,
                job.get("content_type") or "faq",
                job.get("target_city") or facts[0].get("city") or "GLOBAL",
                job.get("target_platform") or "chatgpt",
                fact_ids,
                [source_gap_type] if source_gap_type else [],
                source_action_id,
                draft_markdown,
                fact_ids,
                job.get("model") or "deepseek-v4-flash",
                job.get("template_version") or "geo_content_draft_v1",
                content_hash(draft_markdown),
                job.get("pipeline_run_id"),
                job["id"],
                chunk_ids,
                json.dumps([{"type": "approved_fact", "id": fact_id} for fact_id in fact_ids], ensure_ascii=False),
                draft_summary,
                json.dumps(risk_flags, ensure_ascii=False),
            ),
        )
        for fact in facts:
            cursor.execute(
                """
                INSERT INTO knowledge_trace_refs (
                  project_id, pipeline_run_id, source_type, source_id, target_type, target_id,
                  trace_role, confidence, created_by_job_type, created_by_job_id, metadata
                ) VALUES (%s::uuid, %s::uuid, 'approved_fact', %s, 'content_draft', %s,
                          'content_input', %s, 'content_generation_jobs', %s::uuid, %s::jsonb)
                ON CONFLICT DO NOTHING
                """,
                (
                    job["project_id"],
                    job.get("pipeline_run_id"),
                    str(fact["id"]),
                    draft_id,
                    fact.get("confidence"),
                    job["id"],
                    json.dumps({"content_hash": content_hash(draft_markdown)}, ensure_ascii=False),
                ),
            )
        if source_action_id:
            cursor.execute(
                """
                INSERT INTO knowledge_trace_refs (
                  project_id, pipeline_run_id, source_type, source_id, target_type, target_id,
                  trace_role, confidence, created_by_job_type, created_by_job_id, metadata
                ) VALUES (%s::uuid, %s::uuid, 'action_plan', %s, 'content_draft', %s,
                          'content_input', 1.0, 'content_generation_jobs', %s::uuid, '{}'::jsonb)
                ON CONFLICT DO NOTHING
                """,
                (job["project_id"], job.get("pipeline_run_id"), source_action_id, draft_id, job["id"]),
            )
        for source_type, source_key in (("report", "source_report_id"), ("retest", "source_retest_id")):
            source_id = str(target_action.get(source_key) or "").strip()
            if not source_id:
                continue
            cursor.execute(
                """
                INSERT INTO knowledge_trace_refs (
                  project_id, pipeline_run_id, source_type, source_id, target_type, target_id,
                  trace_role, confidence, created_by_job_type, created_by_job_id, metadata
                ) VALUES (%s::uuid, %s::uuid, %s, %s, 'content_draft', %s,
                          'content_input', 1.0, 'content_generation_jobs', %s::uuid, %s::jsonb)
                ON CONFLICT DO NOTHING
                """,
                (
                    job["project_id"],
                    job.get("pipeline_run_id"),
                    source_type,
                    source_id,
                    draft_id,
                    job["id"],
                    json.dumps({"source_gap_type": source_gap_type}, ensure_ascii=False),
                ),
            )
        cursor.execute(
            "UPDATE content_generation_jobs SET generated_count = 1, metadata = metadata || %s::jsonb WHERE id = %s::uuid",
            (
                json.dumps(
                    {
                        "model_status": model_status,
                        "model_response_hash": (model_output or {}).get("response_hash"),
                    },
                    ensure_ascii=False,
                ),
                job["id"],
            ),
        )
        if job.get("pipeline_run_id"):
            cursor.execute(
                """
                UPDATE knowledge_pipeline_runs
                SET status = 'waiting_human_review',
                    waiting_review_stage_key = 'content_review',
                    waiting_review_count = GREATEST(waiting_review_count, 1),
                    summary = summary || %s::jsonb,
                    updated_at = now()
                WHERE id = %s::uuid
                """,
                (
                    json.dumps({"content_draft_count": 1}, ensure_ascii=False),
                    job["pipeline_run_id"],
                ),
            )
        repository.connection.commit()
    _update_stage(
        repository,
        pipeline_run_id=str(job.get("pipeline_run_id") or "") or None,
        stage_key="content_generate",
        status="succeeded",
        summary={"generated_count": 1},
    )
    _update_stage(
        repository,
        pipeline_run_id=str(job.get("pipeline_run_id") or "") or None,
        stage_key="content_review",
        status="waiting_review",
        summary={"waiting_review_count": 1},
    )
    traceable = bool(fact_ids and chunk_ids)
    generation_safe = traceable and not risk_flags
    _record_quality_gate(
        repository,
        job=job,
        gate_key="generation_quality_gate",
        status="passed" if generation_safe else "blocked",
        summary={
            "content_draft_count": 1,
            "source_fact_count": len(fact_ids),
            "source_chunk_count": len(chunk_ids),
            "model_status": model_status,
            "required_citations": required_citations,
            "risk_flags": risk_flags,
        },
        target_type="content_generation_job",
        target_id=str(job["id"]),
        finding_type="content_generation_unsafe" if not generation_safe else None,
        message="Content draft is untraceable or violates generation constraints" if not generation_safe else None,
    )
    contains_secret_marker = any(marker in draft_markdown.lower() for marker in ("api_key", "api key", "sk-"))
    _record_quality_gate(
        repository,
        job=job,
        gate_key="security_gate",
        status="blocked" if contains_secret_marker else "passed",
        summary={"secret_marker_detected": contains_secret_marker},
        target_type="content_draft",
        target_id=draft_id,
        finding_type="generated_secret_marker" if contains_secret_marker else None,
        message="Generated content contains a provider secret marker" if contains_secret_marker else None,
    )
    _record_quality_gate(
        repository,
        job=job,
        gate_key="traceability_gate",
        status="passed" if traceable else "blocked",
        summary={"source_fact_count": len(fact_ids), "source_chunk_count": len(chunk_ids)},
        target_type="content_draft",
        target_id=draft_id,
        finding_type="traceability_missing" if not traceable else None,
        message="Content draft cannot be traced to approved facts and chunks" if not traceable else None,
    )
    return {
        "generated_count": 1,
        "content_draft_ids": [draft_id],
        "model_status": model_status,
        "risk_flags": risk_flags,
    }


def _process_job(repository: KnowledgePipelineRepository, table: str, job: dict[str, Any]) -> dict[str, Any]:
    if table == "knowledge_import_jobs":
        return _process_import_job(repository, job)
    if table == "crawl_jobs":
        return _process_crawl_job(repository, job)
    if table == "knowledge_parser_runs":
        return _process_parser_run(repository, job)
    if table == "chunk_jobs":
        return _process_chunk_job(repository, job)
    if table == "embedding_jobs":
        return _process_embedding_job(repository, job)
    if table == "fact_extraction_jobs":
        return _process_fact_extraction_job(repository, job)
    if table == "prompt_generation_jobs":
        return _process_prompt_generation_job(repository, job)
    if table == "content_generation_jobs":
        return _process_content_generation_job(repository, job)
    return {"skipped": table}


def _knowledge_terminal_status(table: str, result: dict[str, Any]) -> str:
    if table == "knowledge_parser_runs" and result.get("fallback_used"):
        return "fallback_succeeded"
    # A Content Job records a successful model result as succeeded. QA blocking
    # belongs to the resulting Asset state, not a partial Job state.
    if table == "content_generation_jobs":
        return "succeeded"
    if result.get("failed_count") or result.get("blocked"):
        return "partial_succeeded"
    return "succeeded"


def _test_after_claim_failpoint(claim: LeaseClaim) -> None:
    failpoint = os.getenv("GENO_DURABLE_JOB_AFTER_CLAIM_FAILPOINT", "").strip()
    if not failpoint:
        return
    if os.getenv("GENO_DEPLOYMENT_ENVIRONMENT", "").strip().lower() != "test":
        raise RuntimeError("durable job failpoints are restricted to the test environment")
    if failpoint not in {"all", claim.spec.table}:
        return
    target_attempt = max(
        1, int(os.getenv("GENO_DURABLE_JOB_AFTER_CLAIM_FAILPOINT_ATTEMPT", "1"))
    )
    if claim.attempt_count != target_attempt:
        return
    pause_seconds = max(
        0.0, float(os.getenv("GENO_DURABLE_JOB_AFTER_CLAIM_PAUSE_SECONDS", "0"))
    )
    if pause_seconds:
        time.sleep(pause_seconds)
    else:
        raise RuntimeError("test failpoint after durable job claim")


def _test_after_business_failpoint(claim: LeaseClaim) -> None:
    failpoint = os.getenv("GENO_DURABLE_JOB_AFTER_BUSINESS_FAILPOINT", "").strip()
    if not failpoint:
        return
    if os.getenv("GENO_DEPLOYMENT_ENVIRONMENT", "").strip().lower() != "test":
        raise RuntimeError("durable job failpoints are restricted to the test environment")
    if failpoint not in {"all", claim.spec.table}:
        return
    target_attempt = max(
        1, int(os.getenv("GENO_DURABLE_JOB_AFTER_BUSINESS_FAILPOINT_ATTEMPT", "1"))
    )
    if claim.attempt_count != target_attempt:
        return
    pause_seconds = max(
        0.0, float(os.getenv("GENO_DURABLE_JOB_AFTER_BUSINESS_PAUSE_SECONDS", "0"))
    )
    if pause_seconds:
        time.sleep(pause_seconds)
    else:
        raise RuntimeError("test failpoint after durable business result")


def _test_after_finalizing_failpoint(claim: LeaseClaim) -> None:
    failpoint = os.getenv("GENO_DURABLE_JOB_AFTER_FINALIZING_FAILPOINT", "").strip()
    if not failpoint:
        return
    if os.getenv("GENO_DEPLOYMENT_ENVIRONMENT", "").strip().lower() != "test":
        raise RuntimeError("durable job failpoints are restricted to the test environment")
    if failpoint not in {"all", claim.spec.table}:
        return
    target_attempt = max(
        1, int(os.getenv("GENO_DURABLE_JOB_AFTER_FINALIZING_FAILPOINT_ATTEMPT", "1"))
    )
    if claim.attempt_count != target_attempt:
        return
    pause_seconds = max(
        0.0, float(os.getenv("GENO_DURABLE_JOB_AFTER_FINALIZING_PAUSE_SECONDS", "0"))
    )
    if pause_seconds:
        time.sleep(pause_seconds)
    else:
        raise RuntimeError("test failpoint after durable finalizing descriptor")


def _process_claim(
    repository: KnowledgePipelineRepository,
    claim: LeaseClaim,
    *,
    lease_seconds: int,
    guard: LeaseGuard | None = None,
) -> dict[str, Any]:
    table = claim.spec.table
    job = claim.worker_payload()
    active_guard = guard or repository.lease_guard(claim, lease_seconds=lease_seconds)
    active_guard.start()
    try:
        descriptor_persisted = False
        with repository.fence_job_commits(claim, lease_seconds=lease_seconds) as fenced:
            _test_after_claim_failpoint(claim)
            if claim.claimed_from == "finalizing":
                descriptor = _json(job.get("finalize_descriptor"))
                result = _json(descriptor.get("result"))
                status = str(descriptor.get("terminal_status") or "")
                if not result or status not in claim.spec.success_statuses:
                    raise FinalizingDescriptorError(
                        f"reclaimed finalizing {table} has no valid persisted descriptor"
                    )
            else:
                result = _process_job(repository, table, job)
                status = _knowledge_terminal_status(table, result)
            if not fenced.commits_deferred:
                fenced.defer_commits_until_terminal()
            _test_after_business_failpoint(claim)
            active_guard.raise_if_stopped()
            if claim.claimed_from != "finalizing" and claim.spec.supports_finalizing:
                fenced.begin_finalizing(
                    descriptor={
                        "descriptor_version": "durable_artifact_finalize_v1",
                        "terminal_status": status,
                        "result": result,
                    }
                )
                descriptor_persisted = True
            else:
                # Stop the independent heartbeat before the atomic terminal
                # commit so it cannot observe the cleared token as a loss.
                active_guard.stop()
                fenced.complete(status=status, result=result)
        if descriptor_persisted:
            _test_after_finalizing_failpoint(claim)
            active_guard.raise_if_stopped()
            active_guard.stop()
            repository.complete_job(claim, status=status, summary=result)
        if job.get("project_id"):
            repository.refresh_project_pipeline_states(project_id=str(job["project_id"]))
        return {
            "table": table,
            "id": str(claim.job_id),
            "status": status,
            "reclaimed": claim.reclaimed,
            "result": result,
        }
    except LostLeaseError as exc:
        active_guard.stop()
        repository.connection.rollback()
        final_status = "lease_lost"
        if exc.cancel_requested or active_guard.cancel_requested:
            try:
                repository.acknowledge_job_cancel(claim)
                final_status = "cancelled"
            except LostLeaseError:
                repository.connection.rollback()
        return {
            "table": table,
            "id": str(claim.job_id),
            "status": final_status,
            "reclaimed": claim.reclaimed,
        }
    except Exception as exc:  # noqa: BLE001 - the durable state must record handler failure.
        try:
            active_guard.raise_if_stopped()
        except LostLeaseError as lease_error:
            active_guard.stop()
            repository.connection.rollback()
            if lease_error.cancel_requested or active_guard.cancel_requested:
                try:
                    repository.acknowledge_job_cancel(claim)
                    status = "cancelled"
                except LostLeaseError:
                    repository.connection.rollback()
                    status = "lease_lost"
            else:
                status = "lease_lost"
            return {
                "table": table,
                "id": str(claim.job_id),
                "status": status,
                "reclaimed": claim.reclaimed,
            }
        active_guard.stop()
        try:
            failed = repository.fail_job(
                claim,
                error_code=exc.__class__.__name__,
                error_message=str(exc),
                retryable=not isinstance(exc, FinalizingDescriptorError),
            )
            status = str(failed["status"])
        except LostLeaseError:
            repository.connection.rollback()
            status = "lease_lost"
        if job.get("project_id") and status != "lease_lost":
            repository.refresh_project_pipeline_states(project_id=str(job["project_id"]))
        return {
            "table": table,
            "id": str(claim.job_id),
            "status": status,
            "reclaimed": claim.reclaimed,
            "error": str(exc),
        }


def run_once(repository: KnowledgePipelineRepository, *, worker_id: str, lease_seconds: int, max_jobs: int) -> dict[str, Any]:
    processed: list[dict[str, Any]] = []
    pipeline = repository.run_ready_pipeline_once(worker_id=worker_id)
    if pipeline:
        processed.append({"table": "knowledge_pipeline_runs", "id": str(pipeline["id"]), "status": "running"})

    # Owner transfer for every table happens before any recovered handler runs.
    # Guards start immediately so later tables cannot expire while an earlier
    # recovered handler is executing.
    recovery_claims: list[tuple[LeaseClaim, LeaseGuard]] = []
    recovery_order = repository.next_job_table_order(
        queue_name="knowledge_recovery", worker_id=worker_id
    )
    for table in recovery_order:
        outcome = repository.claim_job_outcome(
            table,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            mode="recovery",
        )
        if outcome.claim is not None:
            guard = repository.lease_guard(outcome.claim, lease_seconds=lease_seconds).start()
            recovery_claims.append((outcome.claim, guard))
        elif outcome.kind != "empty":
            processed.append(
                {
                    "table": table,
                    "id": str(outcome.job_id),
                    "status": outcome.kind,
                    "reclaimed": False,
                }
            )
    repository.record_recovery_pass(worker_id=worker_id, slots_used=len(recovery_order))
    for claim, guard in recovery_claims:
        processed.append(
            _process_claim(
                repository,
                claim,
                lease_seconds=lease_seconds,
                guard=guard,
            )
        )

    # Fresh work has a separate budget and a DB-persisted round-robin cursor.
    for _ in range(max(0, max_jobs)):
        claim: LeaseClaim | None = None
        for table in repository.next_job_table_order(
            queue_name="knowledge_fresh", worker_id=worker_id
        ):
            outcome = repository.claim_job_outcome(
                table,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                mode="fresh",
            )
            if outcome.claim is not None:
                claim = outcome.claim
                break
            if outcome.kind != "empty":
                processed.append(
                    {
                        "table": table,
                        "id": str(outcome.job_id),
                        "status": outcome.kind,
                        "reclaimed": False,
                    }
                )
        if claim is None:
            break
        processed.append(_process_claim(repository, claim, lease_seconds=lease_seconds))
    return {"worker": worker_id, "processed": processed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run GEO knowledge pipeline DB-polling worker.")
    parser.add_argument("--worker-id", default=os.getenv("GENO_KNOWLEDGE_WORKER_ID", "knowledge-worker"))
    parser.add_argument("--lease-seconds", type=int, default=600)
    parser.add_argument("--max-jobs", type=int, default=1)
    parser.add_argument("--loop-once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=float(os.getenv("GENO_KNOWLEDGE_WORKER_POLL_SECONDS", "2.0")))
    args = parser.parse_args(argv)
    repository = connect_knowledge_pipeline_repository()
    repository.set_maintenance_scope(worker_id=args.worker_id)
    try:
        while True:
            result = run_once(repository, worker_id=args.worker_id, lease_seconds=args.lease_seconds, max_jobs=args.max_jobs)
            print(json.dumps(result, ensure_ascii=False, default=str))
            if args.loop_once:
                return 0
            time.sleep(args.poll_seconds)
    finally:
        close_knowledge_repository(repository)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
