from __future__ import annotations

import json
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


def test_frontend_contract_gate_executes_auth_bff_behavior() -> None:
    root_package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    auth_package = json.loads(
        (ROOT / "packages/web/auth/package.json").read_text(encoding="utf-8")
    )
    root_scripts = root_package["scripts"]
    auth_contract = auth_package["scripts"]["test:contracts"]

    assert "test:auth-bff" in root_scripts["test:contracts"]
    assert "--filter @geo/auth test:contracts" in root_scripts["test:auth-bff"]
    assert "node --test" in auth_contract
    assert "auth_bff_contract.test.mjs" in auth_contract

    python_contract = (ROOT / "tests/test_auth_web_contracts.py").read_text(encoding="utf-8")
    assert "register_typescript_resolver.mjs" in python_contract
    assert '"corepack"' not in python_contract

    make_dry_run = subprocess.run(
        ["make", "--dry-run", "web-contracts"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "pnpm test:contracts" in make_dry_run.stdout
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "run: make web-contracts" in workflow


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


def test_production_upgrade_defaults_to_atomic_and_gates_compatible_online_cutover() -> None:
    runbook = (ROOT / "docs/operations/production-runbook.md").read_text(encoding="utf-8")
    non_b_runbook = (ROOT / "docs/operations/non-b-roadmap-operations.md").read_text(
        encoding="utf-8"
    )

    assert "单版本原子升级" in runbook
    assert "不支持未列入 writer inventory 的旧 API、Web、Worker 或 Relay" in runbook
    assert "停止 API、Web、Worker 和 Relay" in runbook
    assert "恢复到升级前" in runbook
    assert "一致性备份" in runbook
    assert "仓库外 `/v1` 调用方" in runbook
    assert "滚动 API、Worker、Web" not in runbook
    for requirement in (
        "trigger 或应用双写",
        "同一事务",
        "单调 watermark",
        "difference_count=0",
        "lag=0",
        "rollback window",
        "旧 writer 退役",
        "dual-read 只用于对账而不承担同步",
    ):
        assert requirement in non_b_runbook


def test_non_b_operations_runbook_preserves_truth_and_manual_release_boundaries() -> None:
    runbook = (ROOT / "docs/operations/non-b-roadmap-operations.md").read_text(
        encoding="utf-8"
    )

    for requirement in (
        "本地测试不能替代",
        "禁止静默 fallback",
        "不能进入 Task identity",
        "insufficient_evidence",
        "inconclusive",
        "不做代理轮换、stealth 或绕过",
        "DEK\ncrypto-erasure",
        "审批只允许创建未开始",
        "Attribution 必须明确为 `unavailable`",
        "Owner 不能验证自己的证据",
        "`BLOCKED_EXTERNAL`",
    ):
        assert requirement in runbook


def test_admin_next_types_do_not_depend_on_the_playwright_build_directory() -> None:
    next_environment = (ROOT / "apps/admin-web/next-env.d.ts").read_text(encoding="utf-8")
    browser_runner = (ROOT / "scripts/run-required-browser-tests.mjs").read_text(
        encoding="utf-8"
    )

    assert './.next/types/routes.d.ts' in next_environment
    assert ".next-playwright" not in next_environment
    assert "originalAdminNextEnvironment" in browser_runner
    assert "writeFileSync(adminNextEnvironment" in browser_runner


def test_browser_configs_allow_isolated_local_server_ports() -> None:
    expected = {
        "playwright.config.ts": "PLAYWRIGHT_ADMIN_SERVER_PORT",
        "playwright.customer.config.ts": "PLAYWRIGHT_CUSTOMER_SERVER_PORT",
        "playwright.workflow-c.config.ts": "PLAYWRIGHT_WORKFLOW_C_SERVER_PORT",
    }

    for filename, variable in expected.items():
        source = (ROOT / filename).read_text(encoding="utf-8")
        assert variable in source
        assert "must be a TCP port" in source
        assert "-p ${" in source
