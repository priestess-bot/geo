#!/usr/bin/env python3
"""Run F018 runtime tests against disposable Docker resources."""

from __future__ import annotations

import os
from pathlib import Path
import secrets
import socket
import subprocess
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "infra" / "docker-compose.yml"


def _unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _run(
    command: list[str],
    *,
    environment: dict[str, str],
    capture: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        check=check,
        text=True,
        capture_output=capture,
    )


def main() -> int:
    project = f"geo-f018-runtime-{uuid4().hex[:12]}"
    postgres_port = _unused_port()
    app_password = secrets.token_urlsafe(24)
    worker_password = secrets.token_urlsafe(24)
    environment = os.environ.copy()
    environment["GEO_POSTGRES_HOST_PORT"] = str(postgres_port)
    compose = [
        "docker",
        "compose",
        "--project-name",
        project,
        "--file",
        str(COMPOSE),
    ]
    admin_url = (
        f"postgresql://geo_installer:geo_installer_dev@127.0.0.1:{postgres_port}/geo"
    )
    app_url = f"postgresql://geo_app_dev:{app_password}@127.0.0.1:{postgres_port}/geo"
    worker_url = (
        f"postgresql://geo_worker_dev:{worker_password}@127.0.0.1:{postgres_port}/geo"
    )
    exit_code = 0
    try:
        _run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            environment=environment,
            capture=True,
        )
        _run(
            [*compose, "up", "--detach", "--wait", "postgres"],
            environment=environment,
            capture=True,
        )
        test_environment = environment | {
            "GEO_DATABASE_URL": admin_url,
            "GEO_DEV_APP_PASSWORD": app_password,
            "GEO_DEV_WORKER_PASSWORD": worker_password,
            "GEO_ACCESS_TEST_ADMIN_DATABASE_URL": admin_url,
            "GEO_ACCEPTANCE_TEST_APP_DATABASE_URL": app_url,
            "GEO_ACCEPTANCE_TEST_WORKER_DATABASE_URL": worker_url,
        }
        test_environment.pop("DATABASE_URL", None)
        _run(["uv", "run", "alembic", "upgrade", "head"], environment=test_environment)
        _run(
            ["uv", "run", "python", "scripts/provision_dev_database.py"],
            environment=test_environment,
        )
        result = _run(
            [
                "uv",
                "run",
                "pytest",
                "-q",
                "--strict-markers",
                "--fail-on-skipped",
                "--ci-summary-label=F018 isolated Docker runtime",
                "tests/infra/test_production_network_runtime.py",
                "tests/infra/test_compose_health_runtime.py",
                "tests/integration/test_runtime_readiness_dependencies.py",
                "tests/integration/test_runtime_health_postgres.py",
            ],
            environment=test_environment,
            check=False,
        )
        exit_code = result.returncode
    except (OSError, subprocess.CalledProcessError):
        print("F018 isolated Docker runtime gate failed before test execution")
        exit_code = 2
    finally:
        cleanup = _run(
            [*compose, "down", "--volumes", "--remove-orphans"],
            environment=environment,
            capture=True,
            check=False,
        )
        if cleanup.returncode != 0:
            print("F018 isolated Docker runtime gate failed to clean disposable Docker resources")
            if cleanup.stdout:
                print(cleanup.stdout.strip())
            if cleanup.stderr:
                print(cleanup.stderr.strip())
            exit_code = 2
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
