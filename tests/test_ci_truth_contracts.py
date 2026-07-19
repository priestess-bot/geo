from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_INTEGRATION_ENV = (
    "GEO_DATABASE_URL",
    "GEO_ACCESS_TEST_ADMIN_DATABASE_URL",
    "GEO_ACCESS_TEST_DATABASE_URL",
    "GEO_ACCEPTANCE_TEST_ADMIN_DATABASE_URL",
    "GEO_ACCEPTANCE_TEST_APP_DATABASE_URL",
    "GEO_ACCEPTANCE_TEST_ISOLATION_MARKER",
    "GEO_ACCEPTANCE_TEST_WORKER_DATABASE_URL",
    "GEO_PLACEMENT_TEST_ADMIN_URL",
    "GEO_F019_TEST_MINIO_ENDPOINT",
    "GEO_TEST_DATABASE_URL",
)


def test_required_integration_gate_rejects_missing_environment() -> None:
    environment = os.environ.copy()
    for name in REQUIRED_INTEGRATION_ENV:
        environment.pop(name, None)
    result = subprocess.run(
        ["make", "--silent", "test-integration-required"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert all(f"{name} is required" in output for name in REQUIRED_INTEGRATION_ENV)


def test_selected_skip_fails_and_reports_truthful_counts() -> None:
    environment = os.environ.copy()
    environment.pop("GEO_ACCESS_TEST_DATABASE_URL", None)
    environment.pop("GEO_ACCESS_TEST_ADMIN_DATABASE_URL", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--fail-on-skipped",
            "--ci-summary-label=F015 contract",
            "tests/integration/test_access_postgres.py",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "CI test summary [F015 contract]" in output
    assert "collected=1 passed=0 failed=0 skipped=1" in output


def test_zero_collection_is_nonzero_and_reported_truthfully() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--fail-on-skipped",
            "--ci-summary-label=F015 zero collection",
            "-k",
            "this_test_name_does_not_exist",
            "tests/test_ci_truth_contracts.py",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "CI test summary [F015 zero collection]" in output
    assert "collected=0 passed=0 failed=0 skipped=0" in output


def test_live_marker_collects_one_test_without_requesting_a_paid_call() -> None:
    environment = os.environ.copy()
    environment.pop("GEO_RUN_LIVE_DEEPSEEK_TEST", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-m",
            "live",
            "tests/test_geo_deepseek_live_generation.py",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.count("test_stable_job_worker_package_and_claim_lineage") == 1

    refused = subprocess.run(
        ["make", "--silent", "deepseek-live"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert refused.returncode != 0
    assert "Paid DeepSeek call was not requested" in refused.stderr
