#!/usr/bin/env python3
"""Run the governed GEO lifecycle against stable application services."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import os
from pathlib import Path
import sys
from typing import Mapping

import psycopg

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.geo_acceptance import AcceptanceConfig, run_acceptance  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run real PostgreSQL and durable GEO workflow state with controlled model "
            "and URL adapters. DeepSeek is paid and opt-in only."
        )
    )
    parser.add_argument(
        "--app-database-url",
        default=os.getenv("GEO_ACCEPTANCE_APP_DATABASE_URL", ""),
        help="geo_app PostgreSQL URL (or GEO_ACCEPTANCE_APP_DATABASE_URL)",
    )
    parser.add_argument(
        "--worker-database-url",
        default=os.getenv("GEO_ACCEPTANCE_WORKER_DATABASE_URL", ""),
        help="geo_worker PostgreSQL URL (or GEO_ACCEPTANCE_WORKER_DATABASE_URL)",
    )
    parser.add_argument("--run-id", default=f"geo-acceptance-{datetime.now(UTC):%Y%m%d%H%M%S}")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/geo-acceptance/result.json"),
    )
    parser.add_argument(
        "--live-deepseek",
        action="store_true",
        help="explicitly allow one paid DeepSeek generation call",
    )
    parser.add_argument(
        "--deepseek-key-file",
        type=Path,
        default=(
            Path(os.environ["GEO_DEEPSEEK_API_KEY_FILE"])
            if os.getenv("GEO_DEEPSEEK_API_KEY_FILE")
            else None
        ),
    )
    parser.add_argument(
        "--runtime-object-store",
        action="store_true",
        help="write artifacts to configured S3-compatible storage instead of memory",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        config = AcceptanceConfig(
            app_database_url=args.app_database_url,
            worker_database_url=args.worker_database_url,
            run_id=args.run_id,
            output_path=args.output,
            live_deepseek=args.live_deepseek,
            deepseek_key_file=args.deepseek_key_file,
            runtime_object_store=args.runtime_object_store,
        )
        result = run_acceptance(config)
    except (AssertionError, RuntimeError, ValueError, psycopg.Error) as error:
        print(f"GEO acceptance failed: {error}")
        return 1
    project = result.get("project")
    project_id = project.get("project_id") if isinstance(project, Mapping) else "unknown"
    print(f"GEO acceptance passed: project={project_id} result={config.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
