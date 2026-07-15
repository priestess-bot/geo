from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TEMPLATE_VERIFIER_VERSION = "au_p0b_google_env_template_verifier_v1"
DEFAULT_TEMPLATE_PATH = ".env.au-p0b-google.example"
REQUIRED_KEYS = (
    "GOOGLE_PLAYWRIGHT_ENABLED",
    "GOOGLE_PLAYWRIGHT_PROMPT_SELECTOR",
    "GOOGLE_PLAYWRIGHT_ANSWER_SELECTOR",
    "MANUAL_BACKFILL_PATH",
    "DATABASE_URL",
)
MUST_BE_EMPTY_KEYS = (
    "GOOGLE_PLAYWRIGHT_PROMPT_SELECTOR",
    "GOOGLE_PLAYWRIGHT_ANSWER_SELECTOR",
    "GOOGLE_PLAYWRIGHT_SUBMIT_SELECTOR",
    "GOOGLE_PLAYWRIGHT_CITATION_SELECTOR",
    "GOOGLE_AIO_PLAYWRIGHT_PROMPT_SELECTOR",
    "GOOGLE_AIO_PLAYWRIGHT_ANSWER_SELECTOR",
    "GOOGLE_AI_MODE_PLAYWRIGHT_PROMPT_SELECTOR",
    "GOOGLE_AI_MODE_PLAYWRIGHT_ANSWER_SELECTOR",
    "GOOGLE_PLAYWRIGHT_STORAGE_STATE",
    "GOOGLE_AIO_PLAYWRIGHT_START_URL",
    "GOOGLE_AI_MODE_PLAYWRIGHT_START_URL",
    "GOOGLE_PLAYWRIGHT_VENDOR_COST",
    "MANUAL_BACKFILL_PATH",
    "DATABASE_URL",
    "SERP_API_KEY",
    "SERP_API_ENDPOINT",
    "SERP_API_VENDOR_COST",
    "GEO_BROWSER_ARTIFACT_DIR",
    "OBJECT_STORE_ENDPOINT",
    "OBJECT_STORE_BUCKET",
    "OBJECT_STORE_ACCESS_KEY",
    "OBJECT_STORE_SECRET_KEY",
)
SAFE_DEFAULTS = {
    "GOOGLE_PLAYWRIGHT_ENABLED": "0",
    "GOOGLE_PLAYWRIGHT_BROWSER_NAME": "chromium",
    "GOOGLE_PLAYWRIGHT_TIMEOUT_SECONDS": "45",
    "SERP_API_ENGINE": "google_ai_overview",
    "SERP_API_GL": "au",
    "SERP_API_HL": "en",
    "SERP_API_LOCATION": "Australia",
    "GEO_AU_P0B_GOOGLE_ENV_FILE": ".env.au-p0b-google",
}
OUTPUT_PATH_KEYS = (
    "GEO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH",
    "GEO_AU_P0B_GOOGLE_RUNBOOK_EXECUTION_OUTPUT_PATH",
    "GEO_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH",
    "GEO_AU_P0B_GOOGLE_PLAYWRIGHT_SMOKE_OUTPUT_PATH",
    "GEO_AU_P0B_GOOGLE_MANUAL_BACKFILL_TEMPLATE_PATH",
    "GEO_AU_P0B_GOOGLE_MANUAL_BACKFILL_TEMPLATE_MANIFEST_PATH",
    "GEO_AU_P0B_GOOGLE_MANUAL_BACKFILL_VERIFICATION_PATH",
    "GEO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH",
)
FORBIDDEN_VALUE_MARKERS = (
    "sk-",
    "AIza",
    "serpapi.com",
    "postgresql://user:pass@",
    "storage_state",
    "cookies",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_template_verification_hash(report: dict[str, Any]) -> str:
    payload = dict(report)
    payload.pop("template_verification_hash", None)
    return hashlib.sha256(_stable_bytes(payload)).hexdigest()


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12] if value else ""


def _strip_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_env_template(path: Path) -> tuple[dict[str, str], dict[str, Any]]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, {"path": str(path), "exists": False, "errors": ["template_file_missing"]}

    values: dict[str, str] = {}
    errors: list[str] = []
    duplicate_keys: list[str] = []
    for line_number, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].strip()
        if "=" not in stripped:
            errors.append(f"env_template_line_invalid:{line_number}")
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key or not key.replace("_", "").isalnum() or key[0].isdigit():
            errors.append(f"env_template_key_invalid:{line_number}")
            continue
        if key in values:
            duplicate_keys.append(key)
        values[key] = _strip_env_value(value)

    errors.extend(f"env_template_key_duplicate:{key}" for key in sorted(set(duplicate_keys)))
    return values, {
        "path": str(path),
        "exists": True,
        "entry_count": len(values),
        "file_sha256": _file_sha256(path),
        "errors": errors,
    }


def _base_check(name: str, values: dict[str, str], *, category: str) -> dict[str, Any]:
    present = name in values
    value = values.get(name, "")
    return {
        "name": name,
        "category": category,
        "present": present,
        "empty": value == "",
        "value_length": len(value),
        "sha256_prefix": _fingerprint(value),
        "secret_redacted": True,
    }


def _check_required(values: dict[str, str]) -> tuple[list[dict[str, Any]], list[str]]:
    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    for name in REQUIRED_KEYS:
        check = _base_check(name, values, category="required")
        value = values.get(name, "")
        if not check["present"]:
            check["status"] = "fail"
            check["reason"] = "template_key_missing"
            errors.append(f"template_key_missing:{name}")
        elif name == "GOOGLE_PLAYWRIGHT_ENABLED" and value.strip().lower() not in {"0", "false", "off", "no"}:
            check["status"] = "fail"
            check["reason"] = "google_playwright_must_default_disabled"
            errors.append("google_playwright_must_default_disabled")
        elif name in MUST_BE_EMPTY_KEYS and value:
            check["status"] = "fail"
            check["reason"] = "template_runtime_value_must_be_empty"
            errors.append(f"template_runtime_value_must_be_empty:{name}")
        else:
            check["status"] = "pass"
            check["reason"] = "template_default_valid"
        checks.append(check)
    return checks, errors


def _check_empty_runtime_values(values: dict[str, str]) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    for name in MUST_BE_EMPTY_KEYS:
        check = _base_check(name, values, category="runtime_value")
        value = values.get(name, "")
        if not check["present"]:
            check["status"] = "warn"
            check["reason"] = "template_key_missing"
            warnings.append(f"runtime_template_key_missing:{name}")
        elif value:
            check["status"] = "fail"
            check["reason"] = "template_runtime_value_must_be_empty"
            errors.append(f"template_runtime_value_must_be_empty:{name}")
        else:
            check["status"] = "pass"
            check["reason"] = "runtime_value_empty_in_template"
        checks.append(check)
    return checks, errors, warnings


def _check_safe_defaults(values: dict[str, str]) -> tuple[list[dict[str, Any]], list[str]]:
    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    for name, expected_value in SAFE_DEFAULTS.items():
        check = _base_check(name, values, category="safe_default")
        value = values.get(name, "")
        if not check["present"]:
            check["status"] = "fail"
            check["reason"] = "template_key_missing"
            errors.append(f"template_key_missing:{name}")
        elif value != expected_value:
            check["status"] = "fail"
            check["reason"] = "safe_default_mismatch"
            errors.append(f"safe_default_mismatch:{name}")
        else:
            check["status"] = "pass"
            check["reason"] = "safe_default_valid"
        checks.append(check)
    return checks, errors


def _check_output_paths(values: dict[str, str]) -> tuple[list[dict[str, Any]], list[str]]:
    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    for name in OUTPUT_PATH_KEYS:
        check = _base_check(name, values, category="output_path")
        value = values.get(name, "")
        valid_suffix = value.endswith(".json") or value.endswith(".jsonl")
        if not check["present"]:
            check["status"] = "fail"
            check["reason"] = "template_key_missing"
            errors.append(f"template_key_missing:{name}")
        elif not value.startswith("docs/runtime_preflight/") or not valid_suffix:
            check["status"] = "fail"
            check["reason"] = "runtime_output_path_invalid"
            errors.append(f"runtime_output_path_invalid:{name}")
        else:
            check["status"] = "pass"
            check["reason"] = "runtime_output_path_gitignored"
        checks.append(check)
    return checks, errors


def _secret_marker_errors(values: dict[str, str]) -> list[str]:
    errors: list[str] = []
    for name, value in values.items():
        lowered = value.lower()
        for marker in FORBIDDEN_VALUE_MARKERS:
            if marker.lower() in lowered:
                errors.append(f"forbidden_secret_like_template_value:{name}:{marker}")
    return errors


def verify_au_p0b_google_env_template(
    *,
    template_path: Path = Path(DEFAULT_TEMPLATE_PATH),
    generated_at: str | None = None,
) -> dict[str, Any]:
    values, source = _load_env_template(template_path)
    required_checks, required_errors = _check_required(values)
    runtime_checks, runtime_errors, runtime_warnings = _check_empty_runtime_values(values)
    safe_default_checks, safe_default_errors = _check_safe_defaults(values)
    output_path_checks, output_path_errors = _check_output_paths(values)
    secret_marker_errors = _secret_marker_errors(values)

    errors = (
        list(source.get("errors", []))
        + required_errors
        + runtime_errors
        + safe_default_errors
        + output_path_errors
        + secret_marker_errors
    )
    warnings = runtime_warnings
    failed_checks = [
        check["name"]
        for check in required_checks + runtime_checks + safe_default_checks + output_path_checks
        if check.get("status") == "fail"
    ]
    runtime_empty_count = len([check for check in runtime_checks if check["present"] and check["empty"]])

    report: dict[str, Any] = {
        "template_verifier_version": TEMPLATE_VERIFIER_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if not errors else "fail",
        "template_path": str(template_path),
        "source": source,
        "summary": {
            "entry_count": len(values),
            "required_count": len(REQUIRED_KEYS),
            "required_present_count": len([check for check in required_checks if check["present"]]),
            "runtime_value_count": len(MUST_BE_EMPTY_KEYS),
            "runtime_empty_count": runtime_empty_count,
            "safe_default_count": len(SAFE_DEFAULTS),
            "output_path_count": len(OUTPUT_PATH_KEYS),
            "failed_check_count": len(failed_checks),
            "failed_checks": failed_checks,
            "google_playwright_default_disabled": values.get("GOOGLE_PLAYWRIGHT_ENABLED", "").strip().lower()
            in {"0", "false", "off", "no"},
            "runtime_values_empty": runtime_empty_count == len(MUST_BE_EMPTY_KEYS),
            "secrets_redacted": True,
        },
        "required": required_checks,
        "runtime_values": runtime_checks,
        "safe_defaults": safe_default_checks,
        "output_paths": output_path_checks,
        "errors": errors,
        "warnings": warnings,
        "current_boundary": [
            "This verifier checks only the committed AU P0b Google env template.",
            "It does not validate the real local .env.au-p0b-google file, selectors, browser session, manual file, database, SERP provider, or Google readiness.",
        ],
    }
    report["template_verification_hash"] = compute_template_verification_hash(report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the committed AU P0b Google env template is complete and redacted")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_ENV_TEMPLATE_PATH", DEFAULT_TEMPLATE_PATH),
        help="Path to the committed AU P0b Google env template.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = verify_au_p0b_google_env_template(template_path=Path(args.path), generated_at=args.generated_at)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
