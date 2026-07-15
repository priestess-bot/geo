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
from scripts.build_au_p0b_manual_backfill_template import (  # noqa: E402
    DEFAULT_MANIFEST_PATH as DEFAULT_MANUAL_BACKFILL_TEMPLATE_MANIFEST_PATH,
    DEFAULT_OUTPUT_PATH as DEFAULT_MANUAL_BACKFILL_TEMPLATE_PATH,
    build_manual_backfill_template,
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
DEFAULT_ENV_BOOTSTRAP_PATH = "docs/runtime_preflight/au-p0b-google-env-bootstrap-latest.json"
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


def _as_sequence(value: object) -> list[object]:
    return list(value) if isinstance(value, (list, tuple)) else []


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


def _env_file_hygiene_summary(playwright_env: dict[str, Any], env_verifier: dict[str, Any]) -> dict[str, Any]:
    env_file = _as_dict(playwright_env.get("env_file"))
    hygiene = _as_dict(env_file.get("hygiene"))
    errors = [str(item) for item in _as_list(hygiene.get("errors"))]
    warnings = [str(item) for item in _as_list(hygiene.get("warnings"))]
    return {
        "path": str(env_file.get("path") or ""),
        "exists": env_file.get("exists") is True,
        "loaded": env_file.get("loaded") is True,
        "entry_count": int(env_file.get("entry_count") or 0),
        "template_file": hygiene.get("template_file") is True,
        "inside_workspace": hygiene.get("inside_workspace") is True,
        "relative_path": str(hygiene.get("relative_path") or ""),
        "git_ignored": hygiene.get("git_ignored") if hygiene.get("git_ignored") in {True, False, None} else None,
        "git_tracked": hygiene.get("git_tracked") if hygiene.get("git_tracked") in {True, False, None} else None,
        "git_safe": hygiene.get("git_safe") is True,
        "file_mode": str(hygiene.get("file_mode") or ""),
        "permission_safe": hygiene.get("permission_safe") is True,
        "hygiene_required": hygiene.get("hygiene_required") is True,
        "hygiene_ready": hygiene.get("hygiene_ready") is True,
        "errors": errors,
        "warnings": warnings,
        "verifier_ready": env_verifier.get("env_file_hygiene_ready") is True,
        "verifier_errors": [str(item) for item in _as_list(env_verifier.get("env_file_hygiene_errors"))],
        "secret_redacted": hygiene.get("secret_redacted") is True,
    }


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


def _environment_handoff_missing(
    *,
    missing_required: list[str],
    missing_full_required: list[str],
    missing_selector_groups: list[str],
    missing_dependencies: list[str],
    file_gate_issues: list[str],
    env_file_hygiene: dict[str, Any],
) -> list[str]:
    missing = [
        *[f"smoke_env:{name}" for name in missing_required],
        *[f"full_run_env:{name}" for name in missing_full_required],
        *[f"selector_group:{name}" for name in missing_selector_groups],
        *[f"dependency:{name}" for name in missing_dependencies],
    ]
    for issue in file_gate_issues:
        if issue == "MANUAL_BACKFILL_PATH:file_missing" and "MANUAL_BACKFILL_PATH" in missing_full_required:
            continue
        missing.append(f"file_gate:{issue}")
    if env_file_hygiene.get("hygiene_ready") is not True:
        errors = [str(item) for item in _as_list(env_file_hygiene.get("errors"))]
        missing.extend([f"env_file_hygiene:{error}" for error in errors] or ["env_file_hygiene:not_ready"])
    return missing


def _environment_handoff(
    *,
    required_environment: list[dict[str, Any]],
    full_run_required_environment: list[dict[str, Any]],
    selector_groups: list[dict[str, Any]],
    file_checks: list[dict[str, Any]],
    dependency_checks: list[dict[str, Any]],
    env_file_hygiene: dict[str, Any],
    missing_required: list[str],
    missing_full_required: list[str],
    missing_selector_groups: list[str],
    missing_dependencies: list[str],
    file_gate_issues: list[str],
    env_file_path: Path | None,
) -> dict[str, Any]:
    missing_inputs = _environment_handoff_missing(
        missing_required=missing_required,
        missing_full_required=missing_full_required,
        missing_selector_groups=missing_selector_groups,
        missing_dependencies=missing_dependencies,
        file_gate_issues=file_gate_issues,
        env_file_hygiene=env_file_hygiene,
    )
    owner_hints = {
        "GOOGLE_PLAYWRIGHT_ENABLED": "browser_automation_operator",
        "MANUAL_BACKFILL_PATH": "google_manual_backfill_operator",
        "DATABASE_URL": "runtime_database_admin",
        "GOOGLE_PLAYWRIGHT_STORAGE_STATE": "browser_automation_operator",
        "GEO_BROWSER_ARTIFACT_DIR": "artifact_store_operator",
    }
    environment_items: list[dict[str, Any]] = []
    for task in [*required_environment, *full_run_required_environment]:
        name = str(task.get("name", ""))
        environment_items.append(
            {
                "name": name,
                "gate": task.get("gate", ""),
                "required": task.get("required") is True,
                "present": task.get("present") is True,
                "truthy": task.get("truthy") if isinstance(task.get("truthy"), bool) else None,
                "source": task.get("source", "missing"),
                "owner_hint": owner_hints.get(name, "platform_operator"),
                "accepted_injection_methods": ["process_environment", "GEO_AU_P0B_GOOGLE_ENV_FILE", ".env.au-p0b-google"],
                "env_file_key": name,
                "value_length": task.get("value_length", 0),
                "sha256_prefix": task.get("sha256_prefix", ""),
                "secret_redacted": task.get("secret_redacted") is True,
                "post_update_checks": [
                    "make au-p0b-google-playwright-env",
                    "make verify-au-p0b-google-playwright-env",
                    "make au-p0b-google-execution-checklist",
                    "make verify-au-p0b-google-execution-checklist",
                ],
            }
        )
    selector_items: list[dict[str, Any]] = []
    for task in selector_groups:
        group = str(task.get("group", ""))
        selector_items.append(
            {
                "group": group,
                "candidate_names": [str(name) for name in _as_list(task.get("candidate_names"))],
                "present": task.get("present") is True,
                "selected_name": str(task.get("selected_name", "")),
                "source": task.get("source", "missing"),
                "owner_hint": "browser_automation_operator",
                "accepted_injection_methods": ["process_environment", "GEO_AU_P0B_GOOGLE_ENV_FILE", ".env.au-p0b-google"],
                "value_length": task.get("value_length", 0),
                "sha256_prefix": task.get("sha256_prefix", ""),
                "secret_redacted": task.get("secret_redacted") is True,
                "post_update_checks": [
                    "make au-p0b-google-playwright-env",
                    "PYTHONPATH=packages/geo_core:apps/api python3 scripts/verify_au_p0b_google_playwright_env_report.py ${GEO_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-playwright-env-latest.json} --require-ready-smoke",
                ],
            }
        )
    file_items: list[dict[str, Any]] = []
    for task in file_checks:
        name = str(task.get("name", ""))
        file_items.append(
            {
                "name": name,
                "expected_type": str(task.get("expected_type", "")),
                "present": task.get("present") is True,
                "exists": task.get("exists") is True,
                "is_file": task.get("is_file") is True,
                "is_dir": task.get("is_dir") is True,
                "source": task.get("source", "missing"),
                "owner_hint": owner_hints.get(name, "platform_operator"),
                "accepted_injection_methods": ["process_environment", "GEO_AU_P0B_GOOGLE_ENV_FILE", ".env.au-p0b-google"],
                "value_length": task.get("value_length", 0),
                "sha256_prefix": task.get("sha256_prefix", ""),
                "secret_redacted": task.get("secret_redacted") is True,
                "post_update_checks": [
                    "make au-p0b-google-playwright-env",
                    "make verify-au-p0b-google-playwright-env",
                ],
            }
        )
    dependency_items = [
        {
            "name": str(task.get("name", "")),
            "present": task.get("present") is True,
            "source": task.get("source", "unknown"),
            "owner_hint": "runtime_operator",
            "secret_redacted": task.get("secret_redacted") is True,
            "post_update_checks": [
                "make au-p0b-google-playwright-env",
                "make verify-au-p0b-google-playwright-env",
            ],
        }
        for task in dependency_checks
    ]
    return {
        "version": "au_p0b_google_environment_handoff_v1",
        "ready": not missing_inputs,
        "missing_required_count": len(missing_inputs),
        "missing_required": missing_inputs,
        "target_env_file": str(env_file_path) if env_file_path else "",
        "setup_commands": [
            "make verify-au-p0b-google-env-template",
            "make au-p0b-google-env-bootstrap",
            "make verify-au-p0b-google-env-bootstrap",
        ],
        "environment_items": environment_items,
        "selector_items": selector_items,
        "file_items": file_items,
        "dependency_items": dependency_items,
        "verification_commands": [
            "make au-p0b-google-playwright-env",
            "make verify-au-p0b-google-playwright-env",
            "PYTHONPATH=packages/geo_core:apps/api python3 scripts/verify_au_p0b_google_playwright_env_report.py ${GEO_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-playwright-env-latest.json} --require-ready-smoke",
            "make au-p0b-google-manual-template",
            "make verify-au-p0b-google-manual-backfill",
            "make au-p0b-google-execution-checklist",
            "make verify-au-p0b-google-execution-checklist",
        ],
        "evidence_outputs": [
            DEFAULT_ENV_BOOTSTRAP_PATH,
            "docs/runtime_preflight/au-p0b-google-playwright-env-latest.json",
            "docs/runtime_preflight/au-p0b-google-manual-backfill-verification-latest.json",
            "docs/runtime_preflight/au-p0b-google-execution-checklist-latest.json",
        ],
        "redaction_policy": {
            "raw_secret_values_allowed": False,
            "recorded_fields": [
                "present",
                "source",
                "truthy",
                "value_length",
                "sha256_prefix",
                "exists",
                "is_file",
                "is_dir",
                "secret_redacted",
            ],
            "forbidden_exact_secret_field_count": 2,
            "forbidden_exact_secret_fields_redacted": True,
        },
    }


def _manual_backfill_artifact(package: dict[str, Any], status_report: dict[str, Any]) -> dict[str, Any]:
    package_artifact = _as_dict(_as_dict(package.get("artifacts")).get("manual_backfill"))
    if package_artifact:
        return package_artifact
    return _as_dict(_as_dict(status_report.get("artifacts")).get("manual_backfill"))


def _manual_backfill_missing_reasons(manual_artifact: dict[str, Any]) -> list[str]:
    if (
        manual_artifact.get("manual_backfill_ready") is True
        and manual_artifact.get("status") == "pass"
        and manual_artifact.get("hash_valid") is True
    ):
        return []
    errors = [str(error) for error in _as_list(manual_artifact.get("errors"))]
    if not errors:
        errors = ["file_missing" if manual_artifact.get("exists") is False else "manual_backfill_not_ready"]
    return sorted(f"manual_backfill:{error}" for error in errors)


def _manual_backfill_handoff(
    *,
    package: dict[str, Any],
    status_report: dict[str, Any],
    generated_at: str | None,
) -> dict[str, Any]:
    _lines, template_manifest = build_manual_backfill_template(generated_at=generated_at)
    expected_record_count = int(template_manifest.get("expected_record_count") or 0)
    prompt_count = int(template_manifest.get("prompt_count") or 0)
    geo_cities = [str(value) for value in _as_sequence(template_manifest.get("geo_cities"))]
    expected_prompt_city_count = prompt_count * len(geo_cities)
    sample_size = int(template_manifest.get("sample_size") or 0)
    manual_artifact = _manual_backfill_artifact(package, status_report)
    status = str(manual_artifact.get("status") or "fail")
    hash_valid = manual_artifact.get("hash_valid") is True
    ready = manual_artifact.get("manual_backfill_ready") is True and status == "pass" and hash_valid
    missing_reasons = _manual_backfill_missing_reasons(manual_artifact)
    artifact_expected_record_count = int(manual_artifact.get("expected_record_count") or 0)
    artifact_record_count = int(manual_artifact.get("record_count") or 0)
    artifact_covered_prompt_city_count = int(manual_artifact.get("covered_prompt_city_count") or 0)
    return {
        "version": "au_p0b_google_manual_backfill_handoff_v1",
        "ready": ready,
        "status": status,
        "hash_valid": hash_valid,
        "manual_backfill_ready": manual_artifact.get("manual_backfill_ready") is True,
        "missing_reason_count": len(missing_reasons),
        "missing_reasons": missing_reasons,
        "manual_jsonl_env_var": "MANUAL_BACKFILL_PATH",
        "target_jsonl_path": DEFAULT_MANUAL_BACKFILL_TEMPLATE_PATH,
        "target_jsonl_path_source": "default_template_path_or_MANUAL_BACKFILL_PATH_env_when_configured",
        "manual_jsonl_path_redacted": True,
        "template_path": DEFAULT_MANUAL_BACKFILL_TEMPLATE_PATH,
        "template_manifest_path": DEFAULT_MANUAL_BACKFILL_TEMPLATE_MANIFEST_PATH,
        "verification_path": str(manual_artifact.get("path") or DEFAULT_MANUAL_BACKFILL_VERIFICATION_PATH),
        "expected_record_count": artifact_expected_record_count or expected_record_count,
        "record_count": artifact_record_count,
        "expected_prompt_city_count": expected_prompt_city_count,
        "covered_prompt_city_count": artifact_covered_prompt_city_count,
        "expected_sample_size": sample_size,
        "prompt_count": prompt_count,
        "geo_cities": geo_cities,
        "file_sha256": str(manual_artifact.get("file_sha256") or ""),
        "verification_hash": str(manual_artifact.get("verification_hash") or ""),
        "required_fields": [str(value) for value in _as_sequence(template_manifest.get("required_fields"))],
        "operator_requirements": [
            "fill_answer_text_for_each_record",
            "include_at_least_one_citation_url_for_each_record",
            "include_screenshot_url_or_html_snapshot_url_for_each_record",
            "preserve_prompt_city_sample_index_and_sample_size",
        ],
        "setup_commands": [
            "make au-p0b-google-manual-template",
        ],
        "verification_commands": [
            "make verify-au-p0b-google-manual-backfill",
            "make au-p0b-google-status",
            "make verify-au-p0b-google-status",
            "make au-p0b-google-package",
            "make verify-au-p0b-google-package",
            "make au-p0b-google-execution-checklist",
            "make verify-au-p0b-google-execution-checklist",
        ],
        "evidence_outputs": [
            DEFAULT_MANUAL_BACKFILL_TEMPLATE_PATH,
            DEFAULT_MANUAL_BACKFILL_TEMPLATE_MANIFEST_PATH,
            str(manual_artifact.get("path") or DEFAULT_MANUAL_BACKFILL_VERIFICATION_PATH),
        ],
        "redaction_policy": {
            "raw_answer_values_allowed": False,
            "raw_citation_values_allowed": False,
            "raw_asset_urls_allowed": False,
            "manual_jsonl_path_redacted": True,
            "recorded_fields": [
                "status",
                "exists",
                "hash_valid",
                "record_count",
                "expected_record_count",
                "covered_prompt_city_count",
                "file_sha256",
                "verification_hash",
                "missing_reasons",
                "template_path",
                "verification_path",
            ],
        },
    }


def _execution_commands_by_id() -> dict[str, dict[str, str]]:
    return {command["id"]: command for command in _execution_commands()}


def _phase_commands(commands_by_id: dict[str, dict[str, str]], command_ids: tuple[str, ...]) -> list[dict[str, str]]:
    return [commands_by_id[command_id] for command_id in command_ids if command_id in commands_by_id]


def _google_phase_artifact_entry(
    *,
    package: dict[str, Any],
    artifact_key: str,
    manual_backfill_handoff: dict[str, Any],
    google_allowed: bool,
    remaining_blockers: list[str],
) -> dict[str, Any]:
    if artifact_key == "evidence_package":
        status = str(package.get("status") or "fail")
        errors = [str(value) for value in _as_list(_as_dict(package.get("summary")).get("blocking_reasons"))]
        ready = status == "pass" and google_allowed and not remaining_blockers
        return {
            "key": artifact_key,
            "path": str(package.get("output_path") or ""),
            "exists": True,
            "status": status,
            "ready": ready,
            "hash_valid": bool(package.get("package_payload_hash")),
            "google_main_scoring_allowed": google_allowed,
            "errors": errors,
        }

    artifact = _as_dict(_as_dict(package.get("artifacts")).get(artifact_key))
    status = str(artifact.get("status") or "missing")
    errors = [str(value) for value in _as_list(artifact.get("errors"))]
    ready = status == "pass"
    if artifact_key == "playwright_env":
        ready = (
            ready
            and artifact.get("ready_for_playwright_smoke") is True
            and artifact.get("ready_for_full_google_run") is True
        )
    elif artifact_key == "playwright_smoke":
        ready = ready and artifact.get("smoke_success") is True
    elif artifact_key == "manual_backfill":
        ready = manual_backfill_handoff.get("ready") is True
    elif artifact_key == "health":
        ready = ready and artifact.get("collector_health_ready") is True
    elif artifact_key == "spike":
        ready = ready and artifact.get("google_gates_ready") is True
    elif artifact_key == "status_report":
        ready = ready and artifact.get("google_main_scoring_allowed") is True
    return {
        "key": artifact_key,
        "path": str(artifact.get("path") or ""),
        "exists": artifact.get("exists") is True,
        "status": status,
        "ready": ready,
        "hash_valid": artifact.get("hash_valid") if "hash_valid" in artifact else None,
        "errors": errors,
        "ready_for_playwright_smoke": artifact.get("ready_for_playwright_smoke")
        if "ready_for_playwright_smoke" in artifact
        else None,
        "ready_for_full_google_run": artifact.get("ready_for_full_google_run")
        if "ready_for_full_google_run" in artifact
        else None,
        "smoke_success": artifact.get("smoke_success") if "smoke_success" in artifact else None,
        "manual_backfill_ready": artifact.get("manual_backfill_ready") if "manual_backfill_ready" in artifact else None,
        "collector_health_ready": artifact.get("collector_health_ready") if "collector_health_ready" in artifact else None,
        "google_gates_ready": artifact.get("google_gates_ready") if "google_gates_ready" in artifact else None,
        "google_main_scoring_allowed": artifact.get("google_main_scoring_allowed")
        if "google_main_scoring_allowed" in artifact
        else None,
    }


def _google_phase_blocking_reasons(
    *,
    phase_id: str,
    artifact_entries: list[dict[str, Any]],
    environment_handoff: dict[str, Any],
    manual_backfill_handoff: dict[str, Any],
    remaining_blockers: list[str],
    google_allowed: bool,
    prerequisite_phase_id: str,
    prerequisite_ready: bool,
) -> list[str]:
    reasons: list[str] = []
    if prerequisite_phase_id and not prerequisite_ready:
        reasons.append(f"prerequisite_phase_not_ready:{prerequisite_phase_id}")
    if phase_id == "environment":
        reasons.extend(f"environment_handoff:{value}" for value in _as_list(environment_handoff.get("missing_required")))
    if phase_id == "manual_backfill":
        reasons.extend(str(value) for value in _as_list(manual_backfill_handoff.get("missing_reasons")))
    if phase_id == "main_scoring" and not google_allowed:
        reasons.extend(f"google_main_scoring_blocker:{blocker}" for blocker in remaining_blockers)
    for artifact in artifact_entries:
        key = str(artifact.get("key") or "")
        if artifact.get("ready") is True:
            continue
        for error in _as_list(artifact.get("errors")):
            reasons.append(f"{key}:{error}")
        if artifact.get("exists") is False:
            reasons.append(f"{key}:file_missing")
        if artifact.get("status") != "pass":
            reasons.append(f"{key}:status_not_pass")
        if artifact.get("ready") is not True:
            reasons.append(f"{key}:not_ready")
    return sorted(dict.fromkeys(reasons))


def _google_phase_handoff_phase(
    *,
    phase_id: str,
    title: str,
    planned_runs: int,
    command_ids: tuple[str, ...],
    artifact_keys: tuple[str, ...],
    prerequisite_gate_ids: tuple[str, ...],
    prerequisite_phase_id: str,
    prerequisite_ready: bool,
    can_start: bool,
    commands_by_id: dict[str, dict[str, str]],
    package: dict[str, Any],
    environment_handoff: dict[str, Any],
    manual_backfill_handoff: dict[str, Any],
    google_allowed: bool,
    remaining_blockers: list[str],
) -> dict[str, Any]:
    artifact_entries = [
        _google_phase_artifact_entry(
            package=package,
            artifact_key=key,
            manual_backfill_handoff=manual_backfill_handoff,
            google_allowed=google_allowed,
            remaining_blockers=remaining_blockers,
        )
        for key in artifact_keys
    ]
    ready = all(entry.get("ready") is True for entry in artifact_entries)
    blocking_reasons = _google_phase_blocking_reasons(
        phase_id=phase_id,
        artifact_entries=artifact_entries,
        environment_handoff=environment_handoff,
        manual_backfill_handoff=manual_backfill_handoff,
        remaining_blockers=remaining_blockers,
        google_allowed=google_allowed,
        prerequisite_phase_id=prerequisite_phase_id,
        prerequisite_ready=prerequisite_ready,
    )
    return {
        "id": phase_id,
        "title": title,
        "planned_runs": planned_runs,
        "ready": ready,
        "can_start": can_start,
        "command_ids": list(command_ids),
        "commands": _phase_commands(commands_by_id, command_ids),
        "artifact_keys": list(artifact_keys),
        "artifacts": artifact_entries,
        "evidence_outputs": [str(entry.get("path") or "") for entry in artifact_entries],
        "prerequisite_gate_ids": list(prerequisite_gate_ids),
        "prerequisite_phase_id": prerequisite_phase_id,
        "blocking_reasons": blocking_reasons,
    }


def _google_spike_phase_handoff(
    *,
    package: dict[str, Any],
    runbook_ok: bool,
    environment_handoff: dict[str, Any],
    manual_backfill_handoff: dict[str, Any],
    remaining_blockers: list[str],
    google_allowed: bool,
    full_spike_planned_runs: int,
) -> dict[str, Any]:
    commands_by_id = _execution_commands_by_id()
    manual_expected_record_count = int(manual_backfill_handoff.get("expected_record_count") or 0)
    environment = _google_phase_handoff_phase(
        phase_id="environment",
        title="Google Playwright and full-run input readiness",
        planned_runs=0,
        command_ids=("verify_playwright_env",),
        artifact_keys=("playwright_env",),
        prerequisite_gate_ids=("verify_env_template", "hard_playwright_env_gate"),
        prerequisite_phase_id="",
        prerequisite_ready=runbook_ok,
        can_start=runbook_ok,
        commands_by_id=commands_by_id,
        package=package,
        environment_handoff=environment_handoff,
        manual_backfill_handoff=manual_backfill_handoff,
        google_allowed=google_allowed,
        remaining_blockers=remaining_blockers,
    )
    browser_smoke = _google_phase_handoff_phase(
        phase_id="browser_smoke",
        title="Single Google browser smoke capture",
        planned_runs=1,
        command_ids=("run_smoke", "verify_smoke_strict"),
        artifact_keys=("playwright_smoke",),
        prerequisite_gate_ids=("hard_playwright_env_gate",),
        prerequisite_phase_id="environment",
        prerequisite_ready=environment.get("ready") is True,
        can_start=environment.get("ready") is True,
        commands_by_id=commands_by_id,
        package=package,
        environment_handoff=environment_handoff,
        manual_backfill_handoff=manual_backfill_handoff,
        google_allowed=google_allowed,
        remaining_blockers=remaining_blockers,
    )
    manual_backfill = _google_phase_handoff_phase(
        phase_id="manual_backfill",
        title="Strict 120-row Google AI Mode manual verification",
        planned_runs=manual_expected_record_count,
        command_ids=("build_manual_template", "verify_manual_backfill"),
        artifact_keys=("manual_backfill",),
        prerequisite_gate_ids=("verify_manual_backfill",),
        prerequisite_phase_id="browser_smoke",
        prerequisite_ready=browser_smoke.get("ready") is True,
        can_start=browser_smoke.get("ready") is True,
        commands_by_id=commands_by_id,
        package=package,
        environment_handoff=environment_handoff,
        manual_backfill_handoff=manual_backfill_handoff,
        google_allowed=google_allowed,
        remaining_blockers=remaining_blockers,
    )
    health_check = _google_phase_handoff_phase(
        phase_id="health_check",
        title="Collector health-only matrix preflight",
        planned_runs=full_spike_planned_runs,
        command_ids=("run_health", "manifest_health"),
        artifact_keys=("health", "health_manifest"),
        prerequisite_gate_ids=("verify_smoke_strict", "verify_manual_backfill"),
        prerequisite_phase_id="manual_backfill",
        prerequisite_ready=manual_backfill.get("ready") is True,
        can_start=manual_backfill.get("ready") is True,
        commands_by_id=commands_by_id,
        package=package,
        environment_handoff=environment_handoff,
        manual_backfill_handoff=manual_backfill_handoff,
        google_allowed=google_allowed,
        remaining_blockers=remaining_blockers,
    )
    full_spike = _google_phase_handoff_phase(
        phase_id="full_spike",
        title="Full 240-run browser plus manual Google spike",
        planned_runs=full_spike_planned_runs,
        command_ids=("run_full_spike", "manifest_full_spike"),
        artifact_keys=("spike", "spike_manifest"),
        prerequisite_gate_ids=("make verify-au-p0b-google-status",),
        prerequisite_phase_id="health_check",
        prerequisite_ready=health_check.get("ready") is True,
        can_start=health_check.get("ready") is True,
        commands_by_id=commands_by_id,
        package=package,
        environment_handoff=environment_handoff,
        manual_backfill_handoff=manual_backfill_handoff,
        google_allowed=google_allowed,
        remaining_blockers=remaining_blockers,
    )
    main_scoring = _google_phase_handoff_phase(
        phase_id="main_scoring",
        title="Google main scoring denominator promotion",
        planned_runs=0,
        command_ids=("refresh_status", "refresh_package"),
        artifact_keys=("status_report", "evidence_package"),
        prerequisite_gate_ids=("hard_status_gate", "hard_package_gate"),
        prerequisite_phase_id="full_spike",
        prerequisite_ready=full_spike.get("ready") is True,
        can_start=full_spike.get("ready") is True,
        commands_by_id=commands_by_id,
        package=package,
        environment_handoff=environment_handoff,
        manual_backfill_handoff=manual_backfill_handoff,
        google_allowed=google_allowed,
        remaining_blockers=remaining_blockers,
    )
    phases = [environment, browser_smoke, manual_backfill, health_check, full_spike, main_scoring]
    ready_phase_count = sum(1 for phase in phases if phase.get("ready") is True)
    next_phase = next((str(phase.get("id")) for phase in phases if phase.get("ready") is not True), "complete")
    return {
        "version": "au_p0b_google_spike_phase_handoff_v1",
        "ready": ready_phase_count == len(phases),
        "phase_count": len(phases),
        "ready_phase_count": ready_phase_count,
        "blocked_phase_count": len(phases) - ready_phase_count,
        "next_phase": next_phase,
        "full_spike_planned_runs": full_spike_planned_runs,
        "manual_expected_record_count": manual_expected_record_count,
        "phase_order": [str(phase.get("id")) for phase in phases],
        "phases": phases,
        "redaction_policy": {
            "raw_secret_values_allowed": False,
            "raw_answer_values_allowed": False,
            "raw_citation_values_allowed": False,
            "raw_asset_urls_allowed": False,
            "phase_entries_reference_command_ids_and_artifact_paths_only": True,
        },
    }


def _setup_commands() -> list[dict[str, str]]:
    return [
        {
            "id": "verify_env_template",
            "shell": "make verify-au-p0b-google-env-template",
            "purpose": "Verify the committed Google env template is complete, disabled by default, and free of selectors/secrets.",
        },
        {
            "id": "bootstrap_env_file",
            "shell": "make au-p0b-google-env-bootstrap",
            "purpose": "Create or confirm the local Google spike env file with 0600 permissions and git hygiene audit.",
        },
        {
            "id": "verify_env_bootstrap",
            "shell": "make verify-au-p0b-google-env-bootstrap",
            "purpose": "Verify the bootstrap hash, env-file permissions, gitignored/not tracked state and redaction policy.",
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
                "PYTHONPATH=packages/geo_core:apps/api "
                "python3 scripts/verify_au_p0b_google_playwright_smoke.py "
                "${GEO_AU_P0B_GOOGLE_PLAYWRIGHT_SMOKE_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-playwright-smoke-latest.json} "
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
                "PYTHONPATH=packages/geo_core:apps/api "
                "python3 scripts/verify_au_p0b_google_playwright_env_report.py "
                "${GEO_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-playwright-env-latest.json} "
                "--require-ready-smoke"
            ),
            "purpose": "Fail until Google Playwright is enabled, selectors and Playwright dependency are ready.",
        },
        {
            "id": "hard_status_gate",
            "shell": (
                "PYTHONPATH=packages/geo_core:apps/api "
                "python3 scripts/verify_au_p0b_google_spike_status_report.py "
                "${GEO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-spike-status-latest.json} "
                "--require-google-main-scoring-allowed"
            ),
            "purpose": "Fail until Google can enter the main scoring denominator.",
        },
        {
            "id": "hard_package_gate",
            "shell": (
                "PYTHONPATH=packages/geo_core:apps/api "
                "python3 scripts/verify_au_p0b_google_evidence_package.py "
                "${GEO_AU_P0B_GOOGLE_PACKAGE_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-evidence-package-latest.json} "
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
            "commands": [
                "make verify-au-p0b-google-env-template",
                "make au-p0b-google-env-bootstrap",
                "make verify-au-p0b-google-env-bootstrap",
                "make au-p0b-google-playwright-env",
            ],
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
    env_file_hygiene = _env_file_hygiene_summary(playwright_env, env_verifier)

    missing_required = _missing_env_names(required_environment)
    missing_full_required = _missing_env_names(full_run_required_environment)
    missing_selector_groups = sorted(task["group"] for task in selector_groups if task.get("present") is not True)
    missing_dependencies = sorted(task["name"] for task in dependency_checks if task.get("present") is not True)
    file_gate_issues = _file_gate_issues(file_checks)
    environment_handoff = _environment_handoff(
        required_environment=required_environment,
        full_run_required_environment=full_run_required_environment,
        selector_groups=selector_groups,
        file_checks=file_checks,
        dependency_checks=dependency_checks,
        env_file_hygiene=env_file_hygiene,
        missing_required=missing_required,
        missing_full_required=missing_full_required,
        missing_selector_groups=missing_selector_groups,
        missing_dependencies=missing_dependencies,
        file_gate_issues=file_gate_issues,
        env_file_path=env_file_path,
    )
    manual_backfill_handoff = _manual_backfill_handoff(
        package=package,
        status_report=status_report,
        generated_at=generated_at,
    )
    remaining_blockers = [str(item) for item in _as_list(package.get("remaining_blockers"))]
    runbook_ok = runbook_verifier.get("status") == "pass" and runbook_verifier.get("hash_valid") is True
    env_ok = env_verifier.get("status") == "pass" and env_verifier.get("hash_valid") is True
    status_ok = status_verifier.get("status") == "pass" and status_verifier.get("hash_valid") is True
    package_ok = package_verifier.get("status") == "pass" and package_verifier.get("hash_valid") is True
    google_allowed = package.get("google_main_scoring_allowed") is True
    full_spike_planned_runs = int(runbook_verifier.get("planned_runs") or 0)
    google_spike_phase_handoff = _google_spike_phase_handoff(
        package=package,
        runbook_ok=runbook_ok,
        environment_handoff=environment_handoff,
        manual_backfill_handoff=manual_backfill_handoff,
        remaining_blockers=remaining_blockers,
        google_allowed=google_allowed,
        full_spike_planned_runs=full_spike_planned_runs,
    )
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
            "env_file_hygiene_ready": env_file_hygiene["hygiene_ready"],
            "env_file_hygiene_error_count": len(env_file_hygiene["errors"]),
            "env_file_hygiene_warning_count": len(env_file_hygiene["warnings"]),
            "environment_handoff_ready": environment_handoff["ready"],
            "environment_handoff_missing_required_count": environment_handoff["missing_required_count"],
            "environment_handoff_missing_required": environment_handoff["missing_required"],
            "environment_handoff_target_env_file": environment_handoff["target_env_file"],
            "environment_handoff_setup_command_count": len(environment_handoff["setup_commands"]),
            "environment_handoff_verification_command_count": len(environment_handoff["verification_commands"]),
            "environment_handoff_secret_redacted": (
                _as_dict(environment_handoff.get("redaction_policy")).get("raw_secret_values_allowed") is False
                and _as_dict(environment_handoff.get("redaction_policy")).get(
                    "forbidden_exact_secret_fields_redacted"
                )
                is True
            ),
            "manual_backfill_handoff_ready": manual_backfill_handoff["ready"],
            "manual_backfill_handoff_status": manual_backfill_handoff["status"],
            "manual_backfill_handoff_expected_record_count": manual_backfill_handoff["expected_record_count"],
            "manual_backfill_handoff_record_count": manual_backfill_handoff["record_count"],
            "manual_backfill_handoff_expected_prompt_city_count": manual_backfill_handoff[
                "expected_prompt_city_count"
            ],
            "manual_backfill_handoff_covered_prompt_city_count": manual_backfill_handoff[
                "covered_prompt_city_count"
            ],
            "manual_backfill_handoff_missing_reason_count": manual_backfill_handoff["missing_reason_count"],
            "manual_backfill_handoff_missing_reasons": manual_backfill_handoff["missing_reasons"],
            "manual_backfill_handoff_template_path": manual_backfill_handoff["template_path"],
            "manual_backfill_handoff_verification_path": manual_backfill_handoff["verification_path"],
            "manual_backfill_handoff_content_redacted": (
                _as_dict(manual_backfill_handoff.get("redaction_policy")).get("raw_answer_values_allowed") is False
                and _as_dict(manual_backfill_handoff.get("redaction_policy")).get(
                    "raw_citation_values_allowed"
                )
                is False
                and _as_dict(manual_backfill_handoff.get("redaction_policy")).get("raw_asset_urls_allowed") is False
            ),
            "google_spike_phase_handoff_ready": google_spike_phase_handoff["ready"],
            "google_spike_phase_handoff_next_phase": google_spike_phase_handoff["next_phase"],
            "google_spike_phase_handoff_ready_phase_count": google_spike_phase_handoff["ready_phase_count"],
            "google_spike_phase_handoff_blocked_phase_count": google_spike_phase_handoff["blocked_phase_count"],
            "google_spike_phase_handoff_full_spike_planned_runs": google_spike_phase_handoff[
                "full_spike_planned_runs"
            ],
            "google_spike_phase_order": google_spike_phase_handoff["phase_order"],
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
        "env_file_hygiene": env_file_hygiene,
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
        "environment_handoff": environment_handoff,
        "manual_backfill_handoff": manual_backfill_handoff,
        "google_spike_phase_handoff": google_spike_phase_handoff,
        "setup_commands": _setup_commands(),
        "execution_commands": _execution_commands(),
        "verification_commands": _verification_commands(),
        "work_items": _work_items(),
        "evidence_outputs": [
            str(runbook_path),
            str(execution_path),
            DEFAULT_ENV_BOOTSTRAP_PATH,
            str(playwright_env_path),
            str(artifact_paths.get("playwright_smoke_json") or DEFAULT_SMOKE_PATH),
            DEFAULT_MANUAL_BACKFILL_TEMPLATE_PATH,
            DEFAULT_MANUAL_BACKFILL_TEMPLATE_MANIFEST_PATH,
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
            "The manual backfill handoff records only template paths, counts, hashes and missing reasons; raw answers, citations and asset URLs stay outside this checklist.",
            "Google can enter the main scoring denominator only when the status/package hard gates pass.",
        ],
    }
    checklist["google_execution_checklist_hash"] = compute_google_execution_checklist_hash(checklist)
    return checklist


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU P0b Google execution checklist JSON")
    parser.add_argument(
        "--runbook-path",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH", DEFAULT_RUNBOOK_PATH),
        help="Path to the generated AU P0b Google runbook JSON.",
    )
    parser.add_argument(
        "--execution-path",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_RUNBOOK_EXECUTION_OUTPUT_PATH", DEFAULT_EXECUTION_PATH),
        help="Path to the generated AU P0b Google runbook execution JSON.",
    )
    parser.add_argument(
        "--playwright-env-path",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH", DEFAULT_PLAYWRIGHT_ENV_PATH),
        help="Path to the redacted Google Playwright environment report JSON.",
    )
    parser.add_argument(
        "--status-report-path",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH", DEFAULT_STATUS_REPORT_PATH),
        help="Path to the AU P0b Google status report JSON.",
    )
    parser.add_argument(
        "--package-path",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_PACKAGE_OUTPUT_PATH", DEFAULT_PACKAGE_PATH),
        help="Path to the AU P0b Google evidence package JSON.",
    )
    parser.add_argument(
        "--env-file",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_ENV_FILE", DEFAULT_ENV_FILE),
        help="Optional env file to parse if the Playwright env report is missing.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
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
