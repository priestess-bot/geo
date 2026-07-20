from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any
from uuid import uuid4

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_COMPOSE = ROOT / "infra" / "compose.prod.yml"
BUSYBOX_IMAGE = (
    "busybox@sha256:fd8d9aa63ba2f0982b5304e1ee8d3b90a210bc1ffb5314d980eb6962f1a9715d"
)


def _run_compose(
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
        check=check,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _runtime_fixture() -> dict[str, Any]:
    production = yaml.safe_load(PRODUCTION_COMPOSE.read_text(encoding="utf-8"))
    return {
        "name": "geo-infra-egress-contract",
        "services": {
            "external-fixture": {
                "image": BUSYBOX_IMAGE,
                "pull_policy": "if_not_present",
                "command": [
                    "sh",
                    "-ec",
                    "mkdir -p /www; printf fixture-ok > /www/health; "
                    "exec httpd -f -p 8080 -h /www",
                ],
                "networks": ["egress"],
                "healthcheck": {
                    "test": [
                        "CMD",
                        "wget",
                        "-q",
                        "-O",
                        "-",
                        "http://127.0.0.1:8080/health",
                    ],
                    "interval": "1s",
                    "timeout": "1s",
                    "retries": 10,
                },
            },
            "backend-only-probe": {
                "image": BUSYBOX_IMAGE,
                "pull_policy": "if_not_present",
                "command": [
                    "sh",
                    "-ec",
                    "if wget -q -T 2 -O /dev/null "
                    "http://external-fixture:8080/health; then exit 41; fi",
                ],
                "networks": ["backend"],
            },
            "egress-probe": {
                "image": BUSYBOX_IMAGE,
                "pull_policy": "if_not_present",
                "command": [
                    "sh",
                    "-ec",
                    'test "$(wget -q -T 5 -O - '
                    'http://external-fixture:8080/health)" = "fixture-ok"',
                ],
                "networks": ["backend", "egress"],
            },
        },
        "networks": {
            "backend": production["networks"]["backend"],
            "egress": production["networks"]["egress"],
        },
    }


@pytest.mark.integration
def test_backend_only_probe_is_blocked_while_egress_probe_reaches_fixture(
    tmp_path: Path,
) -> None:
    compose_file = tmp_path / "compose.network-contract.yml"
    compose_file.write_text(yaml.safe_dump(_runtime_fixture()), encoding="utf-8")
    project = f"geo-infra-egress-{uuid4().hex[:12]}"

    subprocess.run(
        ["docker", "info", "--format", "{{.ServerVersion}}"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    try:
        _run_compose(project, compose_file, "up", "--detach", "--wait", "external-fixture")
        blocked = _run_compose(
            project,
            compose_file,
            "run",
            "--rm",
            "backend-only-probe",
            check=False,
        )
        allowed = _run_compose(
            project,
            compose_file,
            "run",
            "--rm",
            "egress-probe",
            check=False,
        )

        assert blocked.returncode == 0, blocked.stderr
        assert allowed.returncode == 0, allowed.stderr
    finally:
        _run_compose(
            project,
            compose_file,
            "down",
            "--volumes",
            "--remove-orphans",
            check=False,
        )
