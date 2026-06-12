from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_au_p0b_google_evidence_package import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_PACKAGE_PATH,
    build_au_p0b_google_evidence_package,
)
from scripts.build_au_p0b_google_playwright_env_report import (  # noqa: E402
    DEFAULT_ENV_FILE,
    DEFAULT_OUTPUT_PATH as DEFAULT_PLAYWRIGHT_ENV_PATH,
    build_google_playwright_env_report,
)
from scripts.build_au_p0b_google_spike_runbook import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_RUNBOOK_PATH,
    build_au_p0b_google_spike_runbook,
)
from scripts.build_au_p0b_google_spike_status_report import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_STATUS_REPORT_PATH,
    build_au_p0b_google_spike_status_report,
)
from scripts.run_au_p0b_google_playwright_smoke import DEFAULT_OUTPUT_PATH as DEFAULT_SMOKE_PATH  # noqa: E402
from scripts.run_au_p0b_google_spike_runbook import DEFAULT_OUTPUT_PATH as DEFAULT_EXECUTION_PATH  # noqa: E402
from scripts.verify_au_p0b_google_evidence_package import verify_au_p0b_google_evidence_package  # noqa: E402
from scripts.verify_au_p0b_google_playwright_env_report import verify_google_playwright_env_report  # noqa: E402
from scripts.verify_au_p0b_google_spike_runbook import verify_au_p0b_google_spike_runbook  # noqa: E402
from scripts.verify_au_p0b_google_spike_status_report import (  # noqa: E402
    verify_au_p0b_google_spike_status_report,
)


CHECKLIST_VERSION = "au_p0b_google_execution_checklist_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0b-google-execution-checklist-latest.json"
DEFAULT_MANUAL_BACKFILL_VERIFICATION_PATH = (
    "docs/runtime_preflight/au-p0b-google-manual-backfill-verification-latest.json"
)
DEFAULT_HEALTH_PATH = "docs/runtime_preflight/au-p0b-google-spike-health-latest.json"
DEFAULT_HEALTH_MANIFEST_PATH = "docs/runtime_preflight/au-p0b-google-spike-health-manifest-latest.json"
DEFAULT_SPIKE_PATH = "docs/runtime_preflight/au-p0b-google-spike-latest.json"
DEFAULT_SPIKE_MANIFEST_PATH = "docs/runtime_preflight/au-p0b-google-spike-manifest-latest.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_google_execution_checklist_hash(checklist: dict[str, Any]) -> str:
    payload = dict(checklist)
    payload.pop("google_execution_checklist_hash", None)
    return hashlib.sha256(_stable_bytes(payload)).hexdigest()


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _load_json(path: Path) -> tuple[Any | None, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, {"path": str(path), "exists": False, "source": "missing_file", "errors": ["file_missing"]}
    except json.JSONDecodeError as exc:
        return None, {
            "path": str(path),
            "exists": True,
            "source": "invalid_file",
            "errors": [f"json_invalid:{exc.msg}"],
        }
    return payload, {"path": str(path), "exists": True, "source": "existing_file", "errors": []}


def _load_or_build_runbook(path: Path, *, generated_at: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if isinstance(payload, dict):
        return payload, source
    return build_au_p0b_google_spike_runbook(generated_at=generated_at), {**source, "source": "generated_in_memory"}


def _load_or_build_playwright_env(
    path: Path,
    *,
    runbook_path: Path,
    env_file_path: Path | None,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if isinstance(payload, dict):
        return payload, source
    report = build_google_playwright_env_report(
        runbook_path=runbook_path,
        env_file_path=env_file_path,
        output_path=path,
        generated_at=generated_at,
    )
    return report, {**source, "source": "generated_in_memory"}


def _load_or_build_status_report(
    path: Path,
    *,
    runbook_path: Path,
    execution_path: Path,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if isinstance(payload, dict):
        return payload, source
    report = build_au_p0b_google_spike_status_report(
        runbook_path=runbook_path,
        execution_path=execution_path,
        output_path=path,
        generated_at=generated_at,
    )
    return report, {**source, "source": "generated_in_memory"}


def _load_or_build_package(
    path: Path,
    *,
    runbook_path: Path,
    execution_path: Path,
    status_report_path: Path,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if isinstance(payload, dict):
        return payload, source
    package = build_au_p0b_google_evidence_package(
        runbook_path=runbook_path,
        execution_path=execution_path,
        status_report_path=status_report_path,
        output_path=path,
        generated_at=generated_at,
    )
    return package, {**source, "source": "generated_in_memory"}


def _env_tasks(checks: list[object], *, gate: str) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for item in checks:
        check = _as_dict(item)
        present = check.get("present") is True
        truthy = check.get("truthy")
        missing_for_gate = not present or truthy is False
        tasks.append(
            {
                "name": str(check.get("name", "")),
                "gate": gate,
                "required": True,
                "present": present,
                "truthy": truthy if isinstance(truthy, bool) else None,
                "source": check.get("source", "missing"),
                "value_length": check.get("value_length", 0),
                "sha256_prefix": check.get("sha256_prefix", ""),
                "secret_redacted": check.get("secret_redacted") is True,
                "action": "keep_current_redacted_value"
                if not missing_for_gate
                else ("set_truthy_environment" if present and truthy is False else "set_required_environment"),
                "accepted_sources": ["process", "env_file"],
            }
        )
    return tasks


def _selector_tasks(groups: list[object]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for item in groups:
        group = _as_dict(item)
        present = group.get("present") is True
        tasks.append(
            {
                "group": str(group.get("group", "")),
                "candidate_names": [str(name) for name in _as_list(group.get("candidate_names"))],
                "present": present,
                "selected_name": str(group.get("selected_name", "")),
                "source": group.get("source", "missing"),
                "value_length": group.get("value_length", 0),
                "sha256_prefix": group.get("sha256_prefix", ""),
                "secret_redacted": group.get("secret_redacted") is True,
                "action": "keep_current_redacted_selector" if present else "set_google_playwright_selector",
            }
        )
    return tasks


def _file_tasks(checks: list[object]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for item in checks:
        check = _as_dict(item)
        expected_type = str(check.get("expected_type", ""))
        present = check.get("present") is True
        exists = check.get("exists") is True
        is_file = check.get("is_file") is True
        is_dir = check.get("is_dir") is True
        if expected_type == "file":
            ok = not present or (exists and is_file)
        elif expected_type == "directory":
            ok = not present or (exists and is_dir)
        else:
            ok = True
        tasks.append(
            {
                "name": str(check.get("name", "")),
                "present": present,
                "source": check.get("source", "missing"),
                "value_length": check.get("value_length", 0),
                "sha256_prefix": check.get("sha256_prefix", ""),
                "expected_type": expected_type,
                "exists": exists,
                "is_file": is_file,
                "is_dir": is_dir,
                "secret_redacted": check.get("secret_redacted") is True,
                "action": "keep_current_redacted_path" if ok else "fix_redacted_path_target",
            }
        )
    return tasks


def _dependency_tasks(checks: list[object]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for item in checks:
        check = _as_dict(item)
        present = check.get("present") is True
        tasks.append(
            {
                "name": str(check.get("name", "")),
                "present": present,
                "source": check.get("source", "unknown"),
                "secret_redacted": check.get("secret_redacted") is True,
                "action": "keep_current_dependency" if present else "install_dependency",
            }
        )
    return tasks


def _missing_env_names(tasks: list[dict[str, Any]]) -> list[str]:
    return sorted(
        task["name"]
        for task in tasks
        if task.get("present") is not True or task.get("truthy") is False
    )


def _file_gate_issues(tasks: list[dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    for task in tasks:
        name = str(task.get("name", ""))
        expected_type = str(task.get("expected_type", ""))
        present = task.get("present") is True
        if name == "MANUAL_BACKFILL_PATH" and (not present or task.get("is_file") is not True):
            issues.append(f"{name}:file_missing")
        elif present and expected_type == "file" and task.get("is_file") is not True:
            issues.append(f"{name}:file_missing")
        elif present and expected_type == "directory" and task.get("is_dir") is not True:
            issues.append(f"{name}:directory_missing")
    return sorted(issues)


def _setup_commands() -> list[dict[str, str]]:
    return [
        {
            "id": "copy_env_template",
            "shell": "cp .env.au-p0b-google.example .env.au-p0b-google",
            "purpose": "Create a local Google spike env file without committing selectors or secrets.",
        },
        {"id": "build_runbook", "shell": "make au-p0b-google-runbook", "purpose": "Freeze the Google spike command plan."},
        {
            "id": "dry_run_runbook",
            "shell": "make au-p0b-google-runbook-dry-run && make verify-au-p0b-google-runbook-execution",
            "purpose": "Confirm the Google spike sequence is auditable before external browser/API calls.",
        },
        {
            "id": "build_playwright_env",
            "shell": "make au-p0b-google-playwright-env",
            "purpose": "Generate the redacted Google Playwright environment report.",
        },
        {
            "id": "build_execution_checklist",
            "shell": "make au-p0b-google-execution-checklist",
            "purpose": "Refresh this execution checklist after env/report/status changes.",
        },
    ]


def _execution_commands() -> list[dict[str, str]]:
    return [
        {"id": "verify_playwright_env", "shell": "make verify-au-p0b-google-playwright-env", "purpose": "Verify env report hash and redaction."},
        {"id": "run_smoke", "shell": "make au-p0b-google-playwright-smoke", "purpose": "Run one real Google browser smoke capture."},
        {
            "id": "verify_smoke_strict",
            "shell": (
                "PYTHONPATH=packages/geno_core:apps/api "
                "python3 scripts/verify_au_p0b_google_playwright_smoke.py "
                "${GENO_AU_P0B_GOOGLE_PLAYWRIGHT_SMOKE_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-playwright-smoke-latest.json} "
                "--require-success"
            ),
            "purpose": "Fail until the smoke capture has screenshot/html hashes and browser capture metadata.",
        },
        {"id": "build_manual_template", "shell": "make au-p0b-google-manual-template", "purpose": "Generate the 120-row manual backfill template."},
        {
            "id": "verify_manual_backfill",
            "shell": "make verify-au-p0b-google-manual-backfill",
            "purpose": "Strict-verify the filled manual backfill JSONL before health/full spike.",
        },
        {"id": "run_health", "shell": "make au-p0b-google-spike-health", "purpose": "Run Google spike health-only check."},
        {"id": "manifest_health", "shell": "make au-p0b-google-spike-health-manifest", "purpose": "Hash and manifest the health check payload."},
        {"id": "run_full_spike", "shell": "make au-p0b-google-spike", "purpose": "Run the 240-run browser+manual Google spike matrix."},
        {"id": "manifest_full_spike", "shell": "make au-p0b-google-spike-manifest", "purpose": "Hash and manifest the full spike payload."},
        {"id": "refresh_status", "shell": "make au-p0b-google-status && make verify-au-p0b-google-status", "purpose": "Refresh Google gate status."},
        {"id": "refresh_package", "shell": "make au-p0b-google-package && make verify-au-p0b-google-package", "purpose": "Refresh the Google evidence package."},
    ]


def _verification_commands() -> list[dict[str, str]]:
    return [
        {
            "id": "hard_playwright_env_gate",
            "shell": (
                "PYTHONPATH=packages/geno_core:apps/api "
                "python3 scripts/verify_au_p0b_google_playwright_env_report.py "
                "${GENO_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-playwright-env-latest.json} "
                "--require-ready-smoke"
            ),
            "purpose": "Fail until Google Playwright is enabled, selectors and Playwright dependency are ready.",
        },
        {
            "id": "hard_status_gate",
            "shell": (
                "PYTHONPATH=packages/geno_core:apps/api "
                "python3 scripts/verify_au_p0b_google_spike_status_report.py "
                "${GENO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-status-latest.json} "
                "--require-google-main-scoring-allowed"
            ),
            "purpose": "Fail until Google can enter the main scoring denominator.",
        },
        {
            "id": "hard_package_gate",
            "shell": (
                "PYTHONPATH=packages/geno_core:apps/api "
                "python3 scripts/verify_au_p0b_google_evidence_package.py "
                "${GENO_AU_P0B_GOOGLE_PACKAGE_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-evidence-package-latest.json} "
                "--require-google-main-scoring-allowed"
            ),
            "purpose": "Fail until the package proves Google main scoring is allowed.",
        },
    ]


def _work_items() -> list[dict[str, Any]]:
    return [
        {
            "id": "google_playwright_environment",
            "stage": "P0b",
            "commands": ["cp .env.au-p0b-google.example .env.au-p0b-google", "make au-p0b-google-playwright-env"],
            "hard_gate": "hard_playwright_env_gate",
        },
        {
            "id": "google_playwright_smoke",
            "stage": "P0b",
            "commands": ["make au-p0b-google-playwright-smoke"],
            "hard_gate": "verify_smoke_strict",
        },
        {
            "id": "google_manual_backfill",
            "stage": "P0b",
            "commands": ["make au-p0b-google-manual-template", "make verify-au-p0b-google-manual-backfill"],
            "hard_gate": "verify_manual_backfill",
        },
        {
            "id": "google_spike_health",
            "stage": "P0b",
            "commands": ["make au-p0b-google-spike-health", "make au-p0b-google-spike-health-manifest"],
            "hard_gate": "make verify-au-p0b-google-status",
        },
        {
            "id": "google_full_spike",
            "stage": "P0b",
            "commands": ["make au-p0b-google-spike", "make au-p0b-google-spike-manifest"],
            "hard_gate": "hard_package_gate",
        },
    ]


def _expected_next_action(
    *,
    runbook_ok: bool,
    env_ok: bool,
    ready_for_smoke: bool,
    env_next_action: str,
    remaining_blockers: list[str],
    google_allowed: bool,
) -> str:
    if not runbook_ok:
        return "run_make_au_p0b_google_runbook"
    if not env_ok or not ready_for_smoke:
        return env_next_action or "populate_google_playwright_smoke_environment"
    if any(blocker.startswith("playwright_smoke:") for blocker in remaining_blockers):
        return "run_google_playwright_smoke"
    if any(blocker.startswith("manual_backfill:") for blocker in remaining_blockers):
        return "run_verify_google_manual_backfill"
    if any(blocker.startswith("health:") or blocker.startswith("health_manifest:") for blocker in remaining_blockers):
        return "run_au_p0b_google_spike_health"
    if any(blocker.startswith("spike:") or blocker.startswith("spike_manifest:") for blocker in remaining_blockers):
        return "run_au_p0b_google_spike"
    if not google_allowed:
        return "run_au_p0b_google_status"
    return "allow_google_into_main_scoring_denominator"


def build_au_p0b_google_execution_checklist(
    *,
    runbook_path: Path = Path(DEFAULT_RUNBOOK_PATH),
    execution_path: Path = Path(DEFAULT_EXECUTION_PATH),
    playwright_env_path: Path = Path(DEFAULT_PLAYWRIGHT_ENV_PATH),
    status_report_path: Path = Path(DEFAULT_STATUS_REPORT_PATH),
    package_path: Path = Path(DEFAULT_PACKAGE_PATH),
    env_file_path: Path | None = Path(DEFAULT_ENV_FILE),
    output_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    runbook, runbook_source = _load_or_build_runbook(runbook_path, generated_at=generated_at)
    playwright_env, playwright_env_source = _load_or_build_playwright_env(
        playwright_env_path,
        runbook_path=runbook_path,
        env_file_path=env_file_path,
        generated_at=generated_at,
    )
    status_report, status_source = _load_or_build_status_report(
        status_report_path,
        runbook_path=runbook_path,
        execution_path=execution_path,
        generated_at=generated_at,
    )
    package, package_source = _load_or_build_package(
        package_path,
        runbook_path=runbook_path,
        execution_path=execution_path,
        status_report_path=status_report_path,
        generated_at=generated_at,
    )

    runbook_verifier = verify_au_p0b_google_spike_runbook(runbook, path=runbook_path)
    env_verifier = verify_google_playwright_env_report(playwright_env, path=playwright_env_path)
    status_verifier = verify_au_p0b_google_spike_status_report(status_report, path=status_report_path)
    package_verifier = verify_au_p0b_google_evidence_package(package, path=package_path)
    required_environment = _env_tasks(_as_list(playwright_env.get("required")), gate="playwright_smoke")
    full_run_required_environment = _env_tasks(_as_list(playwright_env.get("full_run_required")), gate="full_google_run")
    selector_groups = _selector_tasks(_as_list(playwright_env.get("selector_groups")))
    file_checks = _file_tasks(_as_list(playwright_env.get("file_checks")))
    dependency_checks = _dependency_tasks(_as_list(playwright_env.get("dependency_checks")))

    missing_required = _missing_env_names(required_environment)
    missing_full_required = _missing_env_names(full_run_required_environment)
    missing_selector_groups = sorted(task["group"] for task in selector_groups if task.get("present") is not True)
    missing_dependencies = sorted(task["name"] for task in dependency_checks if task.get("present") is not True)
    file_gate_issues = _file_gate_issues(file_checks)
    remaining_blockers = [str(item) for item in _as_list(package.get("remaining_blockers"))]
    runbook_ok = runbook_verifier.get("status") == "pass" and runbook_verifier.get("hash_valid") is True
    env_ok = env_verifier.get("status") == "pass" and env_verifier.get("hash_valid") is True
    status_ok = status_verifier.get("status") == "pass" and status_verifier.get("hash_valid") is True
    package_ok = package_verifier.get("status") == "pass" and package_verifier.get("hash_valid") is True
    google_allowed = package.get("google_main_scoring_allowed") is True
    ready = runbook_ok and env_ok and status_ok and package_ok and google_allowed and not remaining_blockers
    next_action = _expected_next_action(
        runbook_ok=runbook_ok,
        env_ok=env_ok,
        ready_for_smoke=playwright_env.get("ready_for_playwright_smoke") is True,
        env_next_action=str(playwright_env.get("next_action") or ""),
        remaining_blockers=remaining_blockers,
        google_allowed=google_allowed,
    )
    artifact_paths = _as_dict(runbook.get("artifact_paths"))
    checklist: dict[str, Any] = {
        "execution_checklist_version": CHECKLIST_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if ready else "fail",
        "google_execution_checklist_ready": ready,
        "google_main_scoring_allowed": google_allowed,
        "limited_coverage": not google_allowed,
        "next_action": next_action,
        "paths": {
            "runbook": str(runbook_path),
            "execution": str(execution_path),
            "playwright_env": str(playwright_env_path),
            "playwright_smoke": str(artifact_paths.get("playwright_smoke_json") or DEFAULT_SMOKE_PATH),
            "manual_backfill_verification": str(
                artifact_paths.get("manual_backfill_verification_json") or DEFAULT_MANUAL_BACKFILL_VERIFICATION_PATH
            ),
            "health": str(artifact_paths.get("health_json") or DEFAULT_HEALTH_PATH),
            "health_manifest": str(artifact_paths.get("health_manifest") or DEFAULT_HEALTH_MANIFEST_PATH),
            "spike": str(artifact_paths.get("spike_json") or DEFAULT_SPIKE_PATH),
            "spike_manifest": str(artifact_paths.get("spike_manifest") or DEFAULT_SPIKE_MANIFEST_PATH),
            "status_report": str(status_report_path),
            "package": str(package_path),
            "output": str(output_path) if output_path else "",
            "env_file": str(env_file_path) if env_file_path else "",
        },
        "summary": {
            "planned_runs": runbook_verifier.get("planned_runs"),
            "step_count": runbook_verifier.get("step_count"),
            "required_environment_count": len(required_environment),
            "missing_required_environment_count": len(missing_required),
            "missing_required_environment": missing_required,
            "full_run_required_environment_count": len(full_run_required_environment),
            "missing_full_run_required_environment_count": len(missing_full_required),
            "missing_full_run_required_environment": missing_full_required,
            "selector_group_count": len(selector_groups),
            "missing_selector_group_count": len(missing_selector_groups),
            "missing_selector_groups": missing_selector_groups,
            "missing_dependency_count": len(missing_dependencies),
            "missing_dependencies": missing_dependencies,
            "file_gate_issue_count": len(file_gate_issues),
            "file_gate_issues": file_gate_issues,
            "remaining_blocker_count": len(remaining_blockers),
            "remaining_blockers": remaining_blockers,
            "runbook_verifier_status": runbook_verifier.get("status", ""),
            "playwright_env_verifier_status": env_verifier.get("status", ""),
            "status_verifier_status": status_verifier.get("status", ""),
            "package_verifier_status": package_verifier.get("status", ""),
        },
        "runbook_source": runbook_source,
        "runbook_verifier": runbook_verifier,
        "playwright_environment_source": playwright_env_source,
        "playwright_environment": {
            "environment_report_version": playwright_env.get("environment_report_version", ""),
            "status": playwright_env.get("status", ""),
            "ready_for_playwright_smoke": playwright_env.get("ready_for_playwright_smoke") is True,
            "ready_for_full_google_run": playwright_env.get("ready_for_full_google_run") is True,
            "collector_health": playwright_env.get("collector_health", ""),
            "next_action": playwright_env.get("next_action", ""),
            "environment_report_hash": playwright_env.get("environment_report_hash", ""),
            "secrets_redacted": playwright_env.get("secrets_redacted") is True,
        },
        "playwright_environment_verifier": env_verifier,
        "status_report_source": status_source,
        "status_report": {
            "status_report_version": status_report.get("status_report_version", ""),
            "status": status_report.get("status", ""),
            "google_main_scoring_allowed": status_report.get("google_main_scoring_allowed") is True,
            "limited_coverage": status_report.get("limited_coverage") is True,
            "next_action": status_report.get("next_action", ""),
            "status_report_hash": status_report.get("status_report_hash", ""),
        },
        "status_report_verifier": status_verifier,
        "package_source": package_source,
        "evidence_package": {
            "package_version": package.get("package_version", ""),
            "status": package.get("status", ""),
            "google_main_scoring_allowed": google_allowed,
            "limited_coverage": package.get("limited_coverage") is True,
            "next_action": package.get("next_action", ""),
            "package_payload_hash": package.get("package_payload_hash", ""),
            "summary": package.get("summary", {}),
        },
        "evidence_package_verifier": package_verifier,
        "required_environment": required_environment,
        "full_run_required_environment": full_run_required_environment,
        "selector_groups": selector_groups,
        "file_checks": file_checks,
        "dependency_checks": dependency_checks,
        "setup_commands": _setup_commands(),
        "execution_commands": _execution_commands(),
        "verification_commands": _verification_commands(),
        "work_items": _work_items(),
        "evidence_outputs": [
            str(runbook_path),
            str(execution_path),
            str(playwright_env_path),
            str(artifact_paths.get("playwright_smoke_json") or DEFAULT_SMOKE_PATH),
            str(artifact_paths.get("manual_backfill_verification_json") or DEFAULT_MANUAL_BACKFILL_VERIFICATION_PATH),
            str(artifact_paths.get("health_json") or DEFAULT_HEALTH_PATH),
            str(artifact_paths.get("health_manifest") or DEFAULT_HEALTH_MANIFEST_PATH),
            str(artifact_paths.get("spike_json") or DEFAULT_SPIKE_PATH),
            str(artifact_paths.get("spike_manifest") or DEFAULT_SPIKE_MANIFEST_PATH),
            str(status_report_path),
            str(package_path),
        ],
        "current_boundary": [
            "This checklist proves the P0b Google execution path is auditable, ordered and redacted.",
            "It does not prove real Google selector/session readiness, smoke success, manual 120-row completion or 240-run completion.",
            "Google can enter the main scoring denominator only when the status/package hard gates pass.",
        ],
    }
    checklist["google_execution_checklist_hash"] = compute_google_execution_checklist_hash(checklist)
    return checklist


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU P0b Google execution checklist JSON")
    parser.add_argument(
        "--runbook-path",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH", DEFAULT_RUNBOOK_PATH),
        help="Path to the generated AU P0b Google runbook JSON.",
    )
    parser.add_argument(
        "--execution-path",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_RUNBOOK_EXECUTION_OUTPUT_PATH", DEFAULT_EXECUTION_PATH),
        help="Path to the generated AU P0b Google runbook execution JSON.",
    )
    parser.add_argument(
        "--playwright-env-path",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH", DEFAULT_PLAYWRIGHT_ENV_PATH),
        help="Path to the redacted Google Playwright environment report JSON.",
    )
    parser.add_argument(
        "--status-report-path",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH", DEFAULT_STATUS_REPORT_PATH),
        help="Path to the AU P0b Google status report JSON.",
    )
    parser.add_argument(
        "--package-path",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_PACKAGE_OUTPUT_PATH", DEFAULT_PACKAGE_PATH),
        help="Path to the AU P0b Google evidence package JSON.",
    )
    parser.add_argument(
        "--env-file",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_ENV_FILE", DEFAULT_ENV_FILE),
        help="Optional env file to parse if the Playwright env report is missing.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU P0b Google execution checklist JSON.",
    )
    parser.add_argument(
        "--require-google-main-scoring-ready",
        action="store_true",
        help="Exit non-zero unless the checklist proves Google can enter the main scoring denominator.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    checklist = build_au_p0b_google_execution_checklist(
        runbook_path=Path(args.runbook_path),
        execution_path=Path(args.execution_path),
        playwright_env_path=Path(args.playwright_env_path),
        status_report_path=Path(args.status_report_path),
        package_path=Path(args.package_path),
        env_file_path=Path(args.env_file) if args.env_file else None,
        output_path=output_path,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(checklist, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(checklist, ensure_ascii=False, indent=2, default=str))
    if args.require_google_main_scoring_ready and checklist["google_execution_checklist_ready"] is not True:
        raise SystemExit(2)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
