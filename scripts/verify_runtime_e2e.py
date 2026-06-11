from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import psycopg

from geno_core.bootstrap import build_au_project_bootstrap
from geno_core.collection import collect_prompt_once
from geno_core.collectors import JsonHttpResponse, PerplexitySonarCollector
from geno_core.models import RuntimeHumanReviewInput, RuntimeProjectBrandLogoUpload, RuntimePromptImportInput
from geno_core.object_store import archive_project_brand_logo
from geno_core.prompt_import import prompt_import_file_to_csv
from geno_core.runtime import build_object_store_from_env, build_repository_from_env, close_repository_connection
from workers.collector_worker import run_collection_slice as worker_module


ROOT = Path(__file__).resolve().parents[1]


class FakePerplexityHttpClient:
    def post_json(self, **kwargs: object) -> JsonHttpResponse:
        return JsonHttpResponse(
            status_code=200,
            payload={
                "choices": [
                    {
                        "message": {
                            "content": (
                                "Perplexity E2E answer for an Australian design partner. "
                                "It cites official and review sources for audit replay."
                            )
                        }
                    }
                ],
                "citations": [
                    "https://examplebrand.example/au/e2e-api-snapshot",
                    "https://reviews.example/e2e-api-snapshot",
                ],
            },
        )


def _xlsx_prompt_import_bytes() -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as workbook:
        workbook.writestr(
            "xl/workbook.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Prompts" sheetId="1" r:id="rId1"/></sheets>
</workbook>""",
        )
        workbook.writestr(
            "xl/_rels/workbook.xml.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>""",
        )
        workbook.writestr(
            "xl/worksheets/sheet1.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="A1" t="inlineStr"><is><t>text</t></is></c>
      <c r="B1" t="inlineStr"><is><t>intent_type</t></is></c>
      <c r="C1" t="inlineStr"><is><t>city</t></is></c>
      <c r="D1" t="inlineStr"><is><t>priority</t></is></c>
      <c r="E1" t="inlineStr"><is><t>intent_weight</t></is></c>
    </row>
    <row r="2">
      <c r="A2" t="inlineStr"><is><t>Runtime E2E XLSX prompt for Sydney AI recommendations</t></is></c>
      <c r="B2" t="inlineStr"><is><t>brand_awareness</t></is></c>
      <c r="C2" t="inlineStr"><is><t>Sydney</t></is></c>
      <c r="D2" t="inlineStr"><is><t>1</t></is></c>
      <c r="E2" t="inlineStr"><is><t>0.8</t></is></c>
    </row>
  </sheetData>
</worksheet>""",
        )
    return buffer.getvalue()


def _database_url() -> str:
    value = os.environ.get("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is required for runtime E2E verification")
    return value


def _query_one(sql: str, params: tuple[object, ...] = ()) -> dict[str, Any]:
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
            cursor.execute(sql, params)
            row = cursor.fetchone()
    if row is None:
        raise AssertionError(f"Expected one row for query: {sql}")
    return dict(row)


def _query_all(sql: str, params: tuple[object, ...] = ()) -> list[dict[str, Any]]:
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
    return [dict(row) for row in rows]


def _run_worker_fixture() -> dict[str, Any]:
    command = [
        sys.executable,
        str(ROOT / "workers/collector_worker/run_collection_slice.py"),
        "--mode",
        "fixture",
        "--prompt-limit",
        "1",
        "--cities",
        "Sydney",
        "--sample-size",
        "3",
        "--persist",
        "--persist-analysis",
    ]
    result = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def _assert_counts(project_id: str) -> dict[str, int]:
    rows = _query_all(
        """
        SELECT 'answer_runs' AS name, count(*)::int AS count FROM answer_runs WHERE project_id = %s
        UNION ALL
        SELECT 'raw_answers', count(*)::int FROM raw_answers ra
          JOIN answer_runs ar ON ar.id = ra.answer_run_id WHERE ar.project_id = %s
        UNION ALL
        SELECT 'evidence_assets', count(*)::int FROM evidence_assets ea
          JOIN answer_runs ar ON ar.id = ea.answer_run_id WHERE ar.project_id = %s
        UNION ALL
        SELECT 'collection_run_summaries', count(*)::int FROM collection_run_summaries WHERE project_id = %s
        UNION ALL
        SELECT 'visibility_score_snapshots', count(*)::int FROM visibility_score_snapshots WHERE project_id = %s
        UNION ALL
        SELECT 'score_contributions', count(*)::int FROM score_contributions sc
          JOIN visibility_score_snapshots vs ON vs.id = sc.score_snapshot_id WHERE vs.project_id = %s
        UNION ALL
        SELECT 'report_exports', count(*)::int FROM report_exports WHERE project_id = %s
        UNION ALL
        SELECT 'traceability_bundles', count(*)::int FROM traceability_bundles WHERE project_id = %s
        UNION ALL
        SELECT 'audit_events', count(*)::int FROM audit_events WHERE project_id = %s
        """,
        (project_id,) * 9,
    )
    counts = {row["name"]: int(row["count"]) for row in rows}
    expected_minimums = {
        "answer_runs": 6,
        "raw_answers": 6,
        "evidence_assets": 12,
        "collection_run_summaries": 1,
        "visibility_score_snapshots": 1,
        "score_contributions": 8,
        "report_exports": 1,
        "traceability_bundles": 1,
        "audit_events": 8,
    }
    for name, minimum in expected_minimums.items():
        actual = counts.get(name, 0)
        if actual < minimum:
            raise AssertionError(f"{name} count {actual} is below expected minimum {minimum}")
    return counts


def _assert_report_artifacts(project_id: str) -> list[str]:
    report = _query_one(
        """
        SELECT markdown_url, pdf_url, csv_url
        FROM report_exports
        WHERE project_id = %s
        ORDER BY exported_at DESC
        LIMIT 1
        """,
        (project_id,),
    )
    store = build_object_store_from_env()
    uris = [report["markdown_url"], report["pdf_url"], report["csv_url"]]
    missing: list[str] = []
    for uri in uris:
        key = str(uri).split("/", 3)[-1]
        if not store.head_object(key=key):
            missing.append(str(uri))
    if missing:
        raise AssertionError(f"Missing archived report artifacts: {missing}")
    return [str(uri) for uri in uris]


def _assert_human_review_queue(project_id: str) -> dict[str, Any]:
    repository = build_repository_from_env()
    try:
        score_queue = repository.list_runtime_human_review_queue(
            project_id=project_id,
            target_type="visibility_score_snapshot",
            limit=1,
        )
        draft_queue = repository.list_runtime_human_review_queue(
            project_id=project_id,
            target_type="content_draft",
            queue_status="pending_review",
            limit=1,
        )
    finally:
        close_repository_connection(repository)
    if score_queue.total_count < 1:
        raise AssertionError("Expected at least one visibility score item in the human review queue")
    if draft_queue.total_count < 1:
        raise AssertionError("Expected at least one pending content draft item in the human review queue")
    score_item = score_queue.records[0]
    draft_item = draft_queue.records[0]
    if not score_item.evidence_refs or not draft_item.evidence_refs:
        raise AssertionError("Human review queue items must include evidence refs")
    repository = build_repository_from_env()
    try:
        approved_review = repository.save_human_review(
            RuntimeHumanReviewInput(
                project_id=project_id,
                target_type="content_draft",
                target_id=draft_item.target_id,
                review_status="approved",
                decision="approved_for_publish",
                reviewer_id="runtime-e2e",
                notes="Runtime E2E approved the content draft review projection.",
                payload={"source": "runtime-e2e"},
            )
        )
        reviewed_queue = repository.list_runtime_human_review_queue(
            project_id=project_id,
            target_type="content_draft",
            queue_status="reviewed",
            limit=10,
        )
    finally:
        close_repository_connection(repository)
    approved_draft = _query_one(
        "SELECT review_status FROM content_drafts WHERE id = %s AND project_id = %s",
        (draft_item.target_id, project_id),
    )
    reviewed_ids = {item.target_id for item in reviewed_queue.records}
    projection_audit = _query_one(
        """
        SELECT event_type, method_version
        FROM audit_events
        WHERE project_id = %s
          AND target_type = 'content_draft'
          AND target_id = %s
          AND event_type = 'content_draft_review_status_updated'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (project_id, draft_item.target_id),
    )
    if approved_draft["review_status"] != "approved":
        raise AssertionError(f"Expected content draft review_status=approved, got {approved_draft['review_status']}")
    if draft_item.target_id not in reviewed_ids:
        raise AssertionError("Approved content draft did not move into the reviewed queue")
    return {
        "score_queue_count": score_queue.total_count,
        "draft_queue_count": draft_queue.total_count,
        "score_target_type": score_item.target_type,
        "draft_target_type": draft_item.target_type,
        "draft_queue_status": draft_item.queue_status,
        "score_reason": score_item.reason,
        "draft_reason": draft_item.reason,
        "approved_review_id": approved_review.human_review["id"],
        "approved_draft_id": draft_item.target_id,
        "approved_draft_status": approved_draft["review_status"],
        "reviewed_queue_count": reviewed_queue.total_count,
        "projection_audit_event_type": projection_audit["event_type"],
        "projection_audit_method_version": projection_audit["method_version"],
    }


def _assert_prompt_file_import(project_id: str) -> dict[str, Any]:
    csv_content, source_format = prompt_import_file_to_csv(
        file_bytes=_xlsx_prompt_import_bytes(),
        filename="runtime-e2e-prompts.xlsx",
    )
    repository = build_repository_from_env()
    try:
        result = repository.import_runtime_prompts_csv(
            RuntimePromptImportInput(
                project_id=project_id,
                csv_content=csv_content,
                imported_by="runtime-e2e",
                source_filename="runtime-e2e-prompts.xlsx",
                source_format=source_format,
                source_content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        )
    finally:
        close_repository_connection(repository)
    if source_format != "xlsx":
        raise AssertionError(f"Expected source_format=xlsx, got {source_format}")
    prompt_count = int(result.prompt_import.get("prompt_count", 0))
    if prompt_count != 1:
        raise AssertionError(f"Expected one imported prompt, got {prompt_count}")
    audit = result.audit_events[0] if result.audit_events else {}
    if audit.get("method_version") != "runtime_prompt_import_xlsx_v1":
        raise AssertionError(f"Expected xlsx prompt import audit method, got {audit}")
    input_refs = audit.get("input_refs") or {}
    if input_refs.get("source_format") != "xlsx":
        raise AssertionError(f"Expected xlsx source format in audit input refs, got {input_refs}")
    repository = build_repository_from_env()
    try:
        history = repository.list_runtime_prompt_imports(
            project_id=project_id,
            source_format="xlsx",
            limit=5,
        )
    finally:
        close_repository_connection(repository)
    if history.total_count < 1:
        raise AssertionError("Expected at least one xlsx prompt import history item")
    history_item = history.records[0].prompt_import
    if history_item.get("source_filename") != "runtime-e2e-prompts.xlsx":
        raise AssertionError(f"Expected prompt import history to include source filename, got {history_item}")
    return {
        "source_format": source_format,
        "source_filename": result.prompt_import["source_filename"],
        "import_count": prompt_count,
        "prompt_question_id": result.prompts[0]["id"],
        "audit_event_type": audit.get("event_type"),
        "audit_method_version": audit.get("method_version"),
        "audit_source_format": input_refs.get("source_format"),
        "history_count": history.total_count,
        "history_source_filename": history_item.get("source_filename"),
    }


def _assert_project_brand_logo_upload(project_id: str) -> dict[str, Any]:
    store = build_object_store_from_env()
    stored = archive_project_brand_logo(
        project_id=project_id,
        filename="runtime-e2e-logo.png",
        content=b"runtime-e2e-logo-bytes",
        content_type="image/png",
        store=store,
    )
    repository = build_repository_from_env()
    try:
        brand_kit = repository.upload_project_brand_logo(
            RuntimeProjectBrandLogoUpload(
                project_id=project_id,
                logo_url=stored.uri,
                filename="runtime-e2e-logo.png",
                content_type=stored.content_type,
                content_hash=stored.content_hash,
                uploaded_by="runtime-e2e",
            )
        )
    finally:
        close_repository_connection(repository)
    key = stored.uri.split("/", 3)[-1]
    if not store.head_object(key=key):
        raise AssertionError(f"Archived project brand logo is missing from object store: {stored.uri}")
    if brand_kit.brand_kit.get("logo_url") != stored.uri:
        raise AssertionError(f"Expected Brand Kit logo_url to be {stored.uri}, got {brand_kit.brand_kit}")
    audit = brand_kit.audit_events[0] if brand_kit.audit_events else {}
    input_refs = audit.get("input_refs") or {}
    output_refs = audit.get("output_refs") or {}
    if audit.get("event_type") != "project_brand_logo_uploaded":
        raise AssertionError(f"Expected project_brand_logo_uploaded audit event, got {audit}")
    if input_refs.get("content_hash", [None])[0] != stored.content_hash:
        raise AssertionError(f"Expected logo content hash in audit input refs, got {input_refs}")
    if output_refs.get("logo_url", [None])[0] != stored.uri:
        raise AssertionError(f"Expected logo URI in audit output refs, got {output_refs}")
    return {
        "logo_url": stored.uri,
        "content_hash": stored.content_hash,
        "content_type": stored.content_type,
        "audit_event_type": audit.get("event_type"),
        "audit_method_version": audit.get("method_version"),
        "audit_source_filename": input_refs.get("source_filename", [None])[0],
    }


def _run_api_snapshot_archive_slice() -> dict[str, Any]:
    bootstrap = build_au_project_bootstrap(
        tenant_name="Runtime E2E API Snapshot Tenant",
        project_name="Runtime E2E API Snapshot Project",
        target_brand="E2EBrand",
        brand_official_domains=("examplebrand.example",),
    )
    record = collect_prompt_once(
        project_id=bootstrap.project.id,
        prompt=bootstrap.prompt_questions[0],
        market_profile=bootstrap.market_profile,
        collector=PerplexitySonarCollector(api_key="test-key", http_client=FakePerplexityHttpClient()),
        city="Sydney",
        sample_index=1,
        sample_size=3,
    )
    persistence = worker_module._persist_records(
        bootstrap=bootstrap,
        mode="api",
        run_type="p0a_api_snapshot_e2e",
        planned_runs=1,
        records=(record,),
        successes=(record,),
        failures=(),
        persist_analysis=False,
        score_formula_version="au_visibility_v1",
        judge_gateway="fixture",
        judge_model="local-fixture-judge",
    )
    asset = _query_one(
        """
        SELECT ea.url, ea.content_hash
        FROM evidence_assets ea
        JOIN answer_runs ar ON ar.id = ea.answer_run_id
        WHERE ar.project_id = %s AND ea.asset_type = 'html_snapshot'
        ORDER BY ea.created_at DESC
        LIMIT 1
        """,
        (bootstrap.project.id,),
    )
    audit = _query_one(
        """
        SELECT event_type, output_refs
        FROM audit_events
        WHERE project_id = %s AND event_type = 'api_snapshot_assets_archived'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (bootstrap.project.id,),
    )
    store = build_object_store_from_env()
    uri = str(asset["url"])
    if not uri.startswith("s3://"):
        raise AssertionError(f"Expected archived s3:// EvidenceAsset URL, got {uri}")
    key = uri.split("/", 3)[-1]
    if not store.head_object(key=key):
        raise AssertionError(f"Archived API snapshot object is missing from object store: {uri}")
    if len(str(asset["content_hash"])) != 64:
        raise AssertionError("Archived API snapshot content_hash must be a 64-character SHA-256 hex string")
    return {
        "project_id": bootstrap.project.id,
        "answer_run_id": record.answer_run.id,
        "evidence_asset_url": uri,
        "evidence_asset_hash": asset["content_hash"],
        "audit_event_type": audit["event_type"],
        "audit_output_refs": audit["output_refs"],
        "persistence": persistence,
    }


def main() -> None:
    fixture_payload = _run_worker_fixture()
    project_id = fixture_payload["persistence"]["project_id"]
    readiness_gate = fixture_payload["p0a_readiness_gate"]
    if readiness_gate["gate_status"] != "pass":
        raise AssertionError(f"Expected fixture P0a readiness gate to pass: {readiness_gate}")
    counts = _assert_counts(project_id)
    report_artifacts = _assert_report_artifacts(project_id)
    human_review_queue = _assert_human_review_queue(project_id)
    prompt_file_import = _assert_prompt_file_import(project_id)
    project_brand_logo_upload = _assert_project_brand_logo_upload(project_id)
    api_snapshot = _run_api_snapshot_archive_slice()
    summary = {
        "status": "passed",
        "fixture_project_id": project_id,
        "fixture_worker": {
            "record_count": fixture_payload["record_count"],
            "success_count": fixture_payload["success_count"],
            "readiness_gate_status": readiness_gate["gate_status"],
            "analysis": fixture_payload["persistence"]["analysis"],
            "api_snapshot_artifacts": fixture_payload["persistence"]["api_snapshot_artifacts"],
        },
        "postgres_counts": counts,
        "report_artifacts": report_artifacts,
        "human_review_queue": human_review_queue,
        "prompt_file_import": prompt_file_import,
        "project_brand_logo_upload": project_brand_logo_upload,
        "api_snapshot_archive": api_snapshot,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
