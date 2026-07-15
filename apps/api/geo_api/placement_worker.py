"""CLI entry point for project-scoped placement generation jobs."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import socket
import time
from uuid import UUID

import psycopg

from geo_core.model_gateway.deepseek import (
    DeepSeekGateway,
    default_deepseek_capability_registry,
)
from geo_core.placements.generation_worker import PlacementGenerationWorker
from geo_core.placements.postgres_generation import PsycopgGenerationWorkerPort


def _required_file(name: str) -> Path:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    path = Path(value)
    if not path.is_file():
        raise RuntimeError(f"{name} does not reference a readable file")
    return path


def build_worker() -> PlacementGenerationWorker:
    database_url_file = _required_file("GEO_DATABASE_URL_FILE")
    api_key_file = _required_file("GEO_DEEPSEEK_API_KEY_FILE")
    project_value = os.getenv("GEO_PROJECT_ID", "").strip()
    if not project_value:
        raise RuntimeError("GEO_PROJECT_ID is required for the RLS-scoped worker")
    database_url = database_url_file.read_text(encoding="utf-8").strip()
    if not database_url:
        raise RuntimeError("GEO_DATABASE_URL_FILE is empty")
    project_id = UUID(project_value)
    port = PsycopgGenerationWorkerPort(
        connection_factory=lambda: psycopg.connect(database_url), project_id=project_id
    )
    gateway = DeepSeekGateway(
        api_key_file=api_key_file,
        capability_registry=default_deepseek_capability_registry(),
    )
    worker_id = os.getenv("GEO_WORKER_ID", f"placement:{socket.gethostname()}")
    return PlacementGenerationWorker(port=port, gateway=gateway, worker_id=worker_id)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the GEO placement generation worker")
    parser.add_argument("--once", action="store_true", help="process at most one job")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()
    worker = build_worker()
    if args.once:
        worker.run_once()
        return 0
    while True:
        result = worker.run_once()
        if result is None:
            time.sleep(max(args.poll_seconds, 0.1))


if __name__ == "__main__":
    raise SystemExit(main())
