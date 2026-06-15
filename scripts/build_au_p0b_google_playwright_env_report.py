from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_au_p0b_google_spike_runbook import DEFAULT_OUTPUT_PATH as DEFAULT_RUNBOOK_PATH  # noqa: E402
from scripts.verify_au_p0b_google_spike_runbook import verify_au_p0b_google_spike_runbook  # noqa: E402
from scripts.build_au_p0a_env_report import _env_file_hygiene  # noqa: E402


ENV_REPORT_VERSION = "au_p0b_google_playwright_environment_report_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0b-google-playwright-env-latest.json"
DEFAULT_ENV_FILE = ".env.au-p0b-google"
REQUIRED_ENV = ("GOOGLE_PLAYWRIGHT_ENABLED",)
TRUTHY_REQUIRED_ENV = {"GOOGLE_PLAYWRIGHT_ENABLED"}
FULL_RUN_REQUIRED_ENV = ("MANUAL_BACKFILL_PATH", "DATABASE_URL")
RECOMMENDED_ENV = (
    "GOOGLE_PLAYWRIGHT_SUBMIT_SELECTOR",
    "GOOGLE_PLAYWRIGHT_CITATION_SELECTOR",
    "GOOGLE_PLAYWRIGHT_STORAGE_STATE",
    "GOOGLE_AIO_PLAYWRIGHT_START_URL",
    "GOOGLE_AI_MODE_PLAYWRIGHT_START_URL",
    "GOOGLE_PLAYWRIGHT_BROWSER_NAME",
    "GOOGLE_PLAYWRIGHT_TIMEOUT_SECONDS",
    "GOOGLE_PLAYWRIGHT_VENDOR_COST",
    "GENO_BROWSER_ARTIFACT_DIR",
    "OBJECT_STORE_ENDPOINT",
    "OBJECT_STORE_BUCKET",
)
REQUIRED_SELECTOR_GROUPS = (
    ("google_aio_prompt_selector", ("GOOGLE_AIO_PLAYWRIGHT_PROMPT_SELECTOR", "GOOGLE_PLAYWRIGHT_PROMPT_SELECTOR")),
    ("google_aio_answer_selector", ("GOOGLE_AIO_PLAYWRIGHT_ANSWER_SELECTOR", "GOOGLE_PLAYWRIGHT_ANSWER_SELECTOR")),
)
OPTIONAL_FILE_ENVS = ("GOOGLE_PLAYWRIGHT_STORAGE_STATE",)
OPTIONAL_DIRECTORY_ENVS = ("GENO_BROWSER_ARTIFACT_DIR",)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_report_bytes(report: dict[str, Any]) -> bytes:
    return json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_google_playwright_env_report_hash(report: dict[str, Any]) -> str:
    payload = dict(report)
    payload.pop("environment_report_hash", None)
    return hashlib.sha256(_stable_report_bytes(payload)).hexdigest()


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _strip_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _env_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _load_env_file(path: Path | None) -> tuple[dict[str, str], dict[str, Any]]:
    if path is None:
        return {}, {
            "path": "",
            "exists": False,
            "loaded": False,
            "entry_count": 0,
            "errors": [],
            "hygiene": _env_file_hygiene(None, exists=False, entry_count=0),
        }
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, {
            "path": str(path),
            "exists": False,
            "loaded": False,
            "entry_count": 0,
            "errors": [],
            "hygiene": _env_file_hygiene(path, exists=False, entry_count=0),
        }
    values: dict[str, str] = {}
    errors: list[str] = []
    for line_number, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].strip()
        if "=" not in stripped:
            errors.append(f"env_file_line_invalid:{line_number}")
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key or not key.replace("_", "").isalnum() or key[0].isdigit():
            errors.append(f"env_file_key_invalid:{line_number}")
            continue
        values[key] = _strip_env_value(value)
    return values, {
        "path": str(path),
        "exists": True,
        "loaded": True,
        "entry_count": len(values),
        "errors": errors,
        "hygiene": _env_file_hygiene(path, exists=True, entry_count=len(values)),
        "secrets_redacted": True,
    }


def _load_runbook(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"path": str(path), "exists": False, "status": "fail", "errors": ["runbook_file_missing"], "hash_valid": False}
    except json.JSONDecodeError as exc:
        return {
            "path": str(path),
            "exists": True,
            "status": "fail",
            "errors": [f"runbook_json_invalid:{exc.msg}"],
            "hash_valid": False,
        }
    if not isinstance(payload, dict):
        return {"path": str(path), "exists": True, "status": "fail", "errors": ["runbook_not_json_object"], "hash_valid": False}
    verification = verify_au_p0b_google_spike_runbook(payload, path=path)
    return {
        "path": str(path),
        "exists": True,
        "status": verification["status"],
        "errors": verification["errors"],
        "hash_valid": verification["hash_valid"],
        "runbook_version": verification.get("runbook_version", ""),
        "planned_runs": verification.get("planned_runs"),
        "step_count": verification.get("step_count"),
    }


def _value_for(name: str, *, env_file_values: Mapping[str, str], process_env: Mapping[str, str]) -> tuple[str, str]:
    if process_env.get(name):
        return str(process_env[name]), "process"
    if env_file_values.get(name):
        return str(env_file_values[name]), "env_file"
    return "", "missing"


def _check_env_names(
    names: tuple[str, ...],
    *,
    env_file_values: Mapping[str, str],
    process_env: Mapping[str, str],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for name in names:
        value, source = _value_for(name, env_file_values=env_file_values, process_env=process_env)
        check: dict[str, Any] = {
            "name": name,
            "present": bool(value),
            "source": source,
            "value_length": len(value),
            "sha256_prefix": _fingerprint(value) if value else "",
            "secret_redacted": True,
        }
        if name in TRUTHY_REQUIRED_ENV:
            check["truthy"] = _env_truthy(value)
        checks.append(check)
    return checks


def _selector_group_checks(
    *,
    env_file_values: Mapping[str, str],
    process_env: Mapping[str, str],
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for group_name, names in REQUIRED_SELECTOR_GROUPS:
        selected_name = ""
        selected_source = "missing"
        selected_value = ""
        for name in names:
            value, source = _value_for(name, env_file_values=env_file_values, process_env=process_env)
            if value:
                selected_name = name
                selected_source = source
                selected_value = value
                break
        groups.append(
            {
                "group": group_name,
                "candidate_names": list(names),
                "present": bool(selected_value),
                "selected_name": selected_name,
                "source": selected_source,
                "value_length": len(selected_value),
                "sha256_prefix": _fingerprint(selected_value) if selected_value else "",
                "secret_redacted": True,
            }
        )
    return groups


def _file_checks(
    names: tuple[str, ...],
    *,
    env_file_values: Mapping[str, str],
    process_env: Mapping[str, str],
    expected_type: str,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for name in names:
        value, source = _value_for(name, env_file_values=env_file_values, process_env=process_env)
        exists = Path(value).exists() if value else False
        is_file = Path(value).is_file() if value else False
        is_dir = Path(value).is_dir() if value else False
        checks.append(
            {
                "name": name,
                "present": bool(value),
                "source": source,
                "value_length": len(value),
                "sha256_prefix": _fingerprint(value) if value else "",
                "expected_type": expected_type,
                "exists": exists,
                "is_file": is_file,
                "is_dir": is_dir,
                "secret_redacted": True,
            }
        )
    return checks


def _playwright_available(override: bool | None = None) -> bool:
    if override is not None:
        return override
    try:
        import playwright.sync_api  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True


def _collector_health(
    *,
    required: list[dict[str, Any]],
    selector_groups: list[dict[str, Any]],
    file_checks: list[dict[str, Any]],
    playwright_available: bool,
) -> str:
    enabled = next((item for item in required if item.get("name") == "GOOGLE_PLAYWRIGHT_ENABLED"), {})
    if enabled.get("truthy") is not True:
        return "not_configured"
    if any(item.get("present") is not True for item in selector_groups):
        return "selector_missing"
    for item in file_checks:
        if item.get("name") == "GOOGLE_PLAYWRIGHT_STORAGE_STATE" and item.get("present") and not item.get("is_file"):
            return "session_state_missing"
    if not playwright_available:
        return "playwright_missing"
    return "ready"


def _next_action(
    *,
    runbook: dict[str, Any],
    env_file: dict[str, Any],
    missing_required: list[str],
    missing_selector_groups: list[str],
    storage_state_ok: bool,
    playwright_available: bool,
    collector_health: str,
) -> str:
    if runbook.get("status") != "pass":
        return "run_or_fix_au_p0b_google_runbook"
    hygiene = env_file.get("hygiene") if isinstance(env_file.get("hygiene"), dict) else {}
    if env_file.get("errors") or hygiene.get("errors"):
        return "fix_google_playwright_env_file"
    if missing_required or missing_selector_groups:
        return "populate_google_playwright_smoke_environment"
    if not storage_state_ok:
        return "fix_google_playwright_storage_state"
    if not playwright_available:
        return "install_python_playwright"
    if collector_health != "ready":
        return "fix_google_playwright_collector_health"
    return "run_au_p0b_google_playwright_smoke"


def _summary(
    *,
    required: list[dict[str, Any]],
    full_run_required: list[dict[str, Any]],
    recommended: list[dict[str, Any]],
    selector_groups: list[dict[str, Any]],
    dependency_checks: list[dict[str, Any]],
    missing_required: list[str],
    missing_full_run_required: list[str],
    missing_selector_groups: list[str],
    runbook: dict[str, Any],
    env_file: dict[str, Any],
    storage_state_ok: bool,
    manual_backfill_ok: bool,
    playwright_ok: bool,
    collector_health: str,
    ready_for_smoke: bool,
    ready_for_full_run: bool,
    next_action: str,
) -> dict[str, Any]:
    missing_recommended = [str(item.get("name") or "") for item in recommended if item.get("present") is not True]
    missing_dependencies = [
        str(item.get("name") or "") for item in dependency_checks if item.get("present") is not True
    ]
    env_file_hygiene = env_file.get("hygiene") if isinstance(env_file.get("hygiene"), dict) else {}
    hygiene_errors = [str(item) for item in env_file_hygiene.get("errors", [])] if isinstance(env_file_hygiene, dict) else []
    hygiene_warnings = (
        [str(item) for item in env_file_hygiene.get("warnings", [])] if isinstance(env_file_hygiene, dict) else []
    )
    return {
        "required_count": len(required),
        "present_required_count": len(required) - len(missing_required),
        "missing_required_count": len(missing_required),
        "missing_required": missing_required,
        "full_run_required_count": len(full_run_required),
        "present_full_run_required_count": len(full_run_required) - len(missing_full_run_required),
        "missing_full_run_required_count": len(missing_full_run_required),
        "missing_full_run_required": missing_full_run_required,
        "recommended_count": len(recommended),
        "present_recommended_count": len(recommended) - len(missing_recommended),
        "missing_recommended_count": len(missing_recommended),
        "missing_recommended": missing_recommended,
        "selector_group_count": len(selector_groups),
        "present_selector_group_count": len(selector_groups) - len(missing_selector_groups),
        "missing_selector_group_count": len(missing_selector_groups),
        "missing_selector_groups": missing_selector_groups,
        "dependency_count": len(dependency_checks),
        "present_dependency_count": len(dependency_checks) - len(missing_dependencies),
        "missing_dependency_count": len(missing_dependencies),
        "missing_dependencies": missing_dependencies,
        "runbook_status": runbook.get("status", ""),
        "runbook_hash_valid": runbook.get("hash_valid") is True,
        "env_file_exists": env_file.get("exists") is True,
        "env_file_loaded": env_file.get("loaded") is True,
        "env_file_entry_count": env_file.get("entry_count", 0),
        "env_file_hygiene_ready": env_file_hygiene.get("hygiene_ready") is True,
        "env_file_hygiene_error_count": len(hygiene_errors),
        "env_file_hygiene_warning_count": len(hygiene_warnings),
        "storage_state_file_ready": storage_state_ok,
        "manual_backfill_file_ready": manual_backfill_ok,
        "playwright_available": playwright_ok,
        "collector_health": collector_health,
        "ready_for_playwright_smoke": ready_for_smoke,
        "ready_for_full_google_run": ready_for_full_run,
        "next_action": next_action,
        "raw_secret_values_allowed": False,
        "selector_values_allowed": False,
        "database_urls_allowed": False,
        "provider_response_values_allowed": False,
    }


def build_google_playwright_env_report(
    *,
    runbook_path: Path = Path(DEFAULT_RUNBOOK_PATH),
    env_file_path: Path | None = None,
    output_path: Path | None = None,
    env: Mapping[str, str] | None = None,
    playwright_available: bool | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    process_env = os.environ if env is None else env
    runbook = _load_runbook(runbook_path)
    env_file_values, env_file = _load_env_file(env_file_path)
    required = _check_env_names(REQUIRED_ENV, env_file_values=env_file_values, process_env=process_env)
    full_run_required = _check_env_names(
        FULL_RUN_REQUIRED_ENV,
        env_file_values=env_file_values,
        process_env=process_env,
    )
    recommended = _check_env_names(RECOMMENDED_ENV, env_file_values=env_file_values, process_env=process_env)
    selector_groups = _selector_group_checks(env_file_values=env_file_values, process_env=process_env)
    file_checks = [
        *_file_checks(OPTIONAL_FILE_ENVS, env_file_values=env_file_values, process_env=process_env, expected_type="file"),
        *_file_checks(
            OPTIONAL_DIRECTORY_ENVS,
            env_file_values=env_file_values,
            process_env=process_env,
            expected_type="directory",
        ),
        *_file_checks(("MANUAL_BACKFILL_PATH",), env_file_values=env_file_values, process_env=process_env, expected_type="file"),
    ]
    dependency_checks = [
        {
            "name": "python_playwright_package",
            "present": _playwright_available(playwright_available),
            "source": "python_import",
            "secret_redacted": True,
        }
    ]
    missing_required = [
        item["name"]
        for item in required
        if not item["present"] or (item["name"] in TRUTHY_REQUIRED_ENV and item.get("truthy") is not True)
    ]
    missing_full_run_required = [item["name"] for item in full_run_required if not item["present"]]
    missing_selector_groups = [item["group"] for item in selector_groups if not item["present"]]
    storage_state_ok = all(
        not item["present"] or item["is_file"]
        for item in file_checks
        if item["name"] == "GOOGLE_PLAYWRIGHT_STORAGE_STATE"
    )
    manual_backfill_ok = all(
        item["present"] and item["is_file"] for item in file_checks if item["name"] == "MANUAL_BACKFILL_PATH"
    )
    playwright_ok = dependency_checks[0]["present"] is True
    collector_health = _collector_health(
        required=required,
        selector_groups=selector_groups,
        file_checks=file_checks,
        playwright_available=playwright_ok,
    )
    env_file_hygiene = env_file.get("hygiene") if isinstance(env_file.get("hygiene"), dict) else {}
    env_file_errors = [*list(env_file.get("errors", [])), *list(env_file_hygiene.get("errors", []))]
    env_file_hygiene_ready = env_file_hygiene.get("hygiene_ready") is True
    ready_for_smoke = (
        runbook.get("status") == "pass"
        and not env_file_errors
        and env_file_hygiene_ready
        and not missing_required
        and not missing_selector_groups
        and storage_state_ok
        and playwright_ok
        and collector_health == "ready"
    )
    ready_for_full_run = (
        ready_for_smoke
        and not missing_full_run_required
        and manual_backfill_ok
    )
    warnings = [
        *[f"recommended_env_missing:{item['name']}" for item in recommended if not item["present"]],
        *[f"full_run_required_env_missing:{name}" for name in missing_full_run_required],
    ]
    if any(item["name"] == "MANUAL_BACKFILL_PATH" and item["present"] and not item["is_file"] for item in file_checks):
        warnings.append("manual_backfill_path_file_missing")
    required_errors = [
        (
            f"required_env_missing:{item['name']}"
            if not item["present"]
            else f"required_env_not_truthy:{item['name']}"
        )
        for item in required
        if not item["present"] or (item["name"] in TRUTHY_REQUIRED_ENV and item.get("truthy") is not True)
    ]
    errors = [
        *[f"runbook:{error}" for error in runbook.get("errors", [])],
        *[f"env_file:{error}" for error in env_file_errors],
        *required_errors,
        *[f"selector_group_missing:{name}" for name in missing_selector_groups],
    ]
    if not storage_state_ok:
        errors.append("storage_state_file_missing")
    if not playwright_ok:
        errors.append("python_playwright_package_missing")
    if collector_health != "ready":
        errors.append(f"collector_health:{collector_health}")
    next_action = _next_action(
        runbook=runbook,
        env_file=env_file,
        missing_required=missing_required,
        missing_selector_groups=missing_selector_groups,
        storage_state_ok=storage_state_ok,
        playwright_available=playwright_ok,
        collector_health=collector_health,
    )

    report: dict[str, Any] = {
        "environment_report_version": ENV_REPORT_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if ready_for_smoke else "fail",
        "ready_for_playwright_smoke": ready_for_smoke,
        "ready_for_full_google_run": ready_for_full_run,
        "next_action": next_action,
        "runbook_path": str(runbook_path),
        "output_path": str(output_path) if output_path else "",
        "runbook": runbook,
        "env_file": env_file,
        "required": required,
        "full_run_required": full_run_required,
        "recommended": recommended,
        "selector_groups": selector_groups,
        "file_checks": file_checks,
        "dependency_checks": dependency_checks,
        "collector_health": collector_health,
        "missing_required": missing_required,
        "missing_full_run_required": missing_full_run_required,
        "missing_selector_groups": missing_selector_groups,
        "summary": _summary(
            required=required,
            full_run_required=full_run_required,
            recommended=recommended,
            selector_groups=selector_groups,
            dependency_checks=dependency_checks,
            missing_required=missing_required,
            missing_full_run_required=missing_full_run_required,
            missing_selector_groups=missing_selector_groups,
            runbook=runbook,
            env_file=env_file,
            storage_state_ok=storage_state_ok,
            manual_backfill_ok=manual_backfill_ok,
            playwright_ok=playwright_ok,
            collector_health=collector_health,
            ready_for_smoke=ready_for_smoke,
            ready_for_full_run=ready_for_full_run,
            next_action=next_action,
        ),
        "warnings": warnings,
        "errors": errors,
        "secrets_redacted": True,
    }
    report["environment_report_hash"] = compute_google_playwright_env_report_hash(report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a redacted AU P0b Google Playwright environment report")
    parser.add_argument(
        "--runbook-path",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH", DEFAULT_RUNBOOK_PATH),
        help="Path to the generated AU P0b Google runbook JSON.",
    )
    parser.add_argument(
        "--env-file",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_ENV_FILE", DEFAULT_ENV_FILE),
        help="Optional env file to parse without shell evaluation. Missing files are allowed.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the redacted Google Playwright environment report JSON.",
    )
    parser.add_argument(
        "--require-ready-smoke",
        action="store_true",
        help="Exit non-zero unless the environment is ready for one Google Playwright smoke capture.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    env_file_path = Path(args.env_file) if args.env_file else None
    report = build_google_playwright_env_report(
        runbook_path=Path(args.runbook_path),
        env_file_path=env_file_path,
        output_path=output_path,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if args.require_ready_smoke and report["ready_for_playwright_smoke"] is not True:
        raise SystemExit(2)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
