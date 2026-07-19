from __future__ import annotations

from pathlib import Path
import subprocess
import time
from uuid import uuid4

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
BUSYBOX_IMAGE = (
    "busybox@sha256:fd8d9aa63ba2f0982b5304e1ee8d3b90a210bc1ffb5314d980eb6962f1a9715d"
)


def _compose(
    project: str,
    compose_file: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "docker",
            "compose",
            "--project-name",
            project,
            "--file",
            str(compose_file),
            *arguments,
        ],
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
        timeout=90,
    )


def _health(container_id: str) -> str:
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Health.Status}}", container_id],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return result.stdout.strip()


def _wait_health(container_id: str, expected: str) -> None:
    deadline = time.monotonic() + 20
    observed = "unknown"
    while time.monotonic() < deadline:
        observed = _health(container_id)
        if observed == expected:
            return
        time.sleep(0.25)
    raise AssertionError(f"container health stayed {observed}, expected {expected}")


@pytest.mark.integration
def test_f018_infra_01_running_compose_changes_healthy_unhealthy_and_recovers(
    tmp_path: Path,
) -> None:
    compose_file = tmp_path / "compose.health-runtime.yml"
    compose_file.write_text(
        yaml.safe_dump(
            {
                "name": "geo-f018-health-runtime",
                "services": {
                    "health-fixture": {
                        "image": BUSYBOX_IMAGE,
                        "pull_policy": "if_not_present",
                        "command": ["sh", "-c", "while :; do sleep 60; done"],
                        "healthcheck": {
                            "test": ["CMD-SHELL", "test ! -f /tmp/force-unhealthy"],
                            "interval": "1s",
                            "timeout": "1s",
                            "retries": 2,
                            "start_period": "1s",
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    project = f"geo-f018-health-{uuid4().hex[:12]}"
    subprocess.run(
        ["docker", "info", "--format", "{{.ServerVersion}}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    try:
        _compose(project, compose_file, "up", "--detach", "--wait")
        container_id = _compose(
            project, compose_file, "ps", "--quiet", "health-fixture"
        ).stdout.strip()
        assert container_id
        _wait_health(container_id, "healthy")

        subprocess.run(
            ["docker", "exec", container_id, "touch", "/tmp/force-unhealthy"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        _wait_health(container_id, "unhealthy")

        subprocess.run(
            ["docker", "exec", container_id, "sh", "-c", "rm /tmp/force-unhealthy"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        _wait_health(container_id, "healthy")
    finally:
        _compose(
            project,
            compose_file,
            "down",
            "--volumes",
            "--remove-orphans",
            check=False,
        )
