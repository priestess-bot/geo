from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import psycopg

from geno_core.bootstrap import build_au_project_bootstrap
from geno_core.collection import collect_prompt_once
from geno_core.collectors import JsonHttpResponse, PerplexitySonarCollector
from geno_core.runtime import build_object_store_from_env, close_repository_connection
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
        "api_snapshot_archive": api_snapshot,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
