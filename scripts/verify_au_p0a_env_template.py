from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


TEMPLATE_VERIFIER_VERSION = "au_p0a_env_template_verifier_v1"
DEFAULT_TEMPLATE_PATH = ".env.au-p0a.example"
REQUIRED_KEYS = ("PERPLEXITY_API_KEY", "OPENAI_API_KEY", "DATABASE_URL")
REQUIRED_EMPTY_KEYS = ("PERPLEXITY_API_KEY", "OPENAI_API_KEY")
RECOMMENDED_KEYS = (
    "OBJECT_STORE_ENDPOINT",
    "OBJECT_STORE_BUCKET",
    "OBJECT_STORE_ACCESS_KEY",
    "OBJECT_STORE_SECRET_KEY",
    "OBJECT_STORE_REGION",
)
OUTPUT_PATH_KEYS = (
    "GEO_AU_P0A_ENV_OUTPUT_PATH",
    "GEO_AU_P0A_RUNBOOK_OUTPUT_PATH",
    "GEO_AU_P0A_RUNBOOK_EXECUTION_OUTPUT_PATH",
    "GEO_AU_P0A_READINESS_OUTPUT_PATH",
    "GEO_AU_P0A_PACKAGE_OUTPUT_PATH",
    "GEO_AU_P0A_STATUS_OUTPUT_PATH",
)
LOCAL_DATABASE_HOSTS = {"localhost", "127.0.0.1", "postgres"}
LOCAL_OBJECT_STORE_HOSTS = {"localhost", "127.0.0.1", "minio"}
PLACEHOLDER_VALUES = {"", "changeme", "change-me", "example", "placeholder", "minio", "minio123"}
FORBIDDEN_VALUE_MARKERS = ("sk-", "pplx-", "AIza", "serpapi.com")


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


def _is_local_database_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"postgres", "postgresql"} and (parsed.hostname or "") in LOCAL_DATABASE_HOSTS


def _is_local_object_store_endpoint(value: str) -> bool:
    if not value:
        return True
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and (parsed.hostname or "") in LOCAL_OBJECT_STORE_HOSTS


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
        elif name in REQUIRED_EMPTY_KEYS and value:
            check["status"] = "fail"
            check["reason"] = "provider_secret_must_be_empty_in_template"
            errors.append(f"template_provider_secret_must_be_empty:{name}")
        elif name == "DATABASE_URL" and not _is_local_database_url(value):
            check["status"] = "fail"
            check["reason"] = "database_url_must_be_local_placeholder"
            errors.append("database_url_must_be_local_placeholder")
        else:
            check["status"] = "pass"
            check["reason"] = "template_default_valid"
        checks.append(check)
    return checks, errors


def _check_recommended(values: dict[str, str]) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    for name in RECOMMENDED_KEYS:
        check = _base_check(name, values, category="recommended")
        value = values.get(name, "")
        normalized = value.strip().lower()
        if not check["present"]:
            check["status"] = "warn"
            check["reason"] = "template_key_missing"
            warnings.append(f"recommended_template_key_missing:{name}")
        elif name == "OBJECT_STORE_ENDPOINT" and not _is_local_object_store_endpoint(value):
            check["status"] = "fail"
            check["reason"] = "object_store_endpoint_must_be_local_placeholder"
            errors.append("object_store_endpoint_must_be_local_placeholder")
        elif name in {"OBJECT_STORE_ACCESS_KEY", "OBJECT_STORE_SECRET_KEY"} and normalized not in PLACEHOLDER_VALUES:
            check["status"] = "fail"
            check["reason"] = "object_store_credential_must_be_placeholder"
            errors.append(f"object_store_credential_must_be_placeholder:{name}")
        else:
            check["status"] = "pass"
            check["reason"] = "template_default_valid"
        checks.append(check)
    return checks, errors, warnings


def _check_output_paths(values: dict[str, str]) -> tuple[list[dict[str, Any]], list[str]]:
    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    for name in OUTPUT_PATH_KEYS:
        check = _base_check(name, values, category="output_path")
        value = values.get(name, "")
        if not check["present"]:
            check["status"] = "fail"
            check["reason"] = "template_key_missing"
            errors.append(f"template_key_missing:{name}")
        elif not value.startswith("docs/runtime_preflight/") or not value.endswith(".json"):
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


def verify_au_p0a_env_template(
    *,
    template_path: Path = Path(DEFAULT_TEMPLATE_PATH),
    generated_at: str | None = None,
) -> dict[str, Any]:
    values, source = _load_env_template(template_path)
    required_checks, required_errors = _check_required(values)
    recommended_checks, recommended_errors, recommended_warnings = _check_recommended(values)
    output_path_checks, output_path_errors = _check_output_paths(values)
    secret_marker_errors = _secret_marker_errors(values)

    errors = list(source.get("errors", [])) + required_errors + recommended_errors + output_path_errors + secret_marker_errors
    warnings = recommended_warnings
    required_present = [check["name"] for check in required_checks if check["present"]]
    required_empty = [check["name"] for check in required_checks if check["empty"]]
    failed_checks = [
        check["name"]
        for check in required_checks + recommended_checks + output_path_checks
        if check.get("status") == "fail"
    ]

    report: dict[str, Any] = {
        "template_verifier_version": TEMPLATE_VERIFIER_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if not errors else "fail",
        "template_path": str(template_path),
        "source": source,
        "summary": {
            "entry_count": len(values),
            "required_count": len(REQUIRED_KEYS),
            "required_present_count": len(required_present),
            "required_empty_count": len(required_empty),
            "recommended_count": len(RECOMMENDED_KEYS),
            "output_path_count": len(OUTPUT_PATH_KEYS),
            "failed_check_count": len(failed_checks),
            "failed_checks": failed_checks,
            "provider_keys_empty": all(values.get(name, "") == "" for name in REQUIRED_EMPTY_KEYS),
            "database_url_local_placeholder": _is_local_database_url(values.get("DATABASE_URL", "")),
            "secrets_redacted": True,
        },
        "required": required_checks,
        "recommended": recommended_checks,
        "output_paths": output_path_checks,
        "errors": errors,
        "warnings": warnings,
        "current_boundary": [
            "This verifier checks only the committed AU P0a env template.",
            "It does not validate the real local .env.au-p0a file or prove provider/database readiness.",
        ],
    }
    report["template_verification_hash"] = compute_template_verification_hash(report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the committed AU P0a env template is complete and redacted")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GEO_AU_P0A_ENV_TEMPLATE_PATH", DEFAULT_TEMPLATE_PATH),
        help="Path to the committed AU P0a env template.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = verify_au_p0a_env_template(template_path=Path(args.path), generated_at=args.generated_at)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
