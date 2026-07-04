from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import psycopg


ROOT = Path(__file__).resolve().parents[1]


def _database_url() -> str:
    value = os.environ.get("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is required")
    return value


def _query_one(sql: str, params: tuple[object, ...] = ()) -> dict[str, Any]:
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
            cursor.execute(sql, params)
            row = cursor.fetchone()
    if row is None:
        raise AssertionError(f"Expected one row for query: {sql}")
    return dict(row)


def _query_counts(project_id: str) -> dict[str, int]:
    rows = []
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
            cursor.execute(
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
                SELECT 'action_recommendations', count(*)::int FROM action_recommendations WHERE project_id = %s
                UNION ALL
                SELECT 'content_drafts', count(*)::int FROM content_drafts WHERE project_id = %s
                UNION ALL
                SELECT 'audit_events', count(*)::int FROM audit_events WHERE project_id = %s
                """,
                (project_id,) * 11,
            )
            rows = cursor.fetchall()
    return {str(row["name"]): int(row["count"]) for row in rows}


def _assert_project_ready(project_id: str) -> dict[str, Any]:
    project = _query_one(
        """
        SELECT id, name, target_brand, category, status
        FROM projects
        WHERE id = %s
        """,
        (project_id,),
    )
    competitor_count = _query_one(
        """
        SELECT count(*)::int AS count
        FROM competitor_entities
        WHERE project_id = %s AND status = ANY(%s)
        """,
        (project_id, ["active", "paused"]),
    )
    prompt_count = _query_one(
        """
        SELECT count(*)::int AS count
        FROM prompt_questions
        WHERE project_id = %s AND status = %s
        """,
        (project_id, "active"),
    )
    active_competitors = int(competitor_count["count"])
    active_prompts = int(prompt_count["count"])
    if active_competitors < 3 or active_competitors > 5:
        raise AssertionError(f"Expected 3-5 active/paused competitors, got {active_competitors}")
    if active_prompts < 1:
        raise AssertionError("Expected at least one active prompt")
    return {
        "project": project,
        "active_competitors": active_competitors,
        "active_prompts": active_prompts,
    }


def _run_worker(project_id: str, *, prompt_limit: int, cities: str, sample_size: int) -> dict[str, Any]:
    command = [
        sys.executable,
        str(ROOT / "workers/collector_worker/run_collection_slice.py"),
        "--mode",
        "fixture",
        "--project-id",
        project_id,
        "--prompt-limit",
        str(prompt_limit),
        "--cities",
        cities,
        "--sample-size",
        str(sample_size),
        "--persist",
        "--persist-analysis",
    ]
    result = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def _assert_minimum_counts(counts: dict[str, int], *, prompt_limit: int, city_count: int, sample_size: int) -> None:
    expected_answer_runs = prompt_limit * city_count * sample_size * 2
    expected = {
        "answer_runs": expected_answer_runs,
        "raw_answers": expected_answer_runs,
        "evidence_assets": expected_answer_runs * 2,
        "collection_run_summaries": 1,
        "visibility_score_snapshots": 1,
        "score_contributions": 1,
        "report_exports": 1,
        "traceability_bundles": 1,
        "action_recommendations": 1,
        "content_drafts": 1,
        "audit_events": 5,
    }
    failures = {
        name: {"actual": counts.get(name, 0), "minimum": minimum}
        for name, minimum in expected.items()
        if counts.get(name, 0) < minimum
    }
    if failures:
        raise AssertionError(f"Runtime project E2E count checks failed: {failures}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run and verify a fixture E2E flow against an existing runtime project.")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--prompt-limit", type=int, default=1)
    parser.add_argument("--cities", default="Sydney")
    parser.add_argument("--sample-size", type=int, default=3)
    args = parser.parse_args()

    before_counts = _query_counts(args.project_id)
    readiness = _assert_project_ready(args.project_id)
    worker_payload = _run_worker(
        args.project_id,
        prompt_limit=args.prompt_limit,
        cities=args.cities,
        sample_size=args.sample_size,
    )
    after_counts = _query_counts(args.project_id)
    city_count = len([city for city in args.cities.split(",") if city.strip()])
    _assert_minimum_counts(
        after_counts,
        prompt_limit=args.prompt_limit,
        city_count=city_count,
        sample_size=args.sample_size,
    )
    latest_report = _query_one(
        """
        SELECT id, report_version, markdown_url, pdf_url, csv_url, exported_at
        FROM report_exports
        WHERE project_id = %s
        ORDER BY exported_at DESC
        LIMIT 1
        """,
        (args.project_id,),
    )
    latest_score = _query_one(
        """
        SELECT id, final_score, formula_version, created_at
        FROM visibility_score_snapshots
        WHERE project_id = %s
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (args.project_id,),
    )
    summary = {
        "status": "passed",
        "project_id": args.project_id,
        "readiness": readiness,
        "worker": {
            "record_count": worker_payload["record_count"],
            "success_count": worker_payload["success_count"],
            "failure_count": worker_payload["failure_count"],
            "persistence": worker_payload["persistence"],
        },
        "counts_before": before_counts,
        "counts_after": after_counts,
        "latest_score": latest_score,
        "latest_report": latest_report,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
