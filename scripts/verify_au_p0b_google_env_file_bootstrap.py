from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.bootstrap_au_p0b_google_env_file import (  # noqa: E402
    BOOTSTRAP_VERSION,
    DEFAULT_OUTPUT_PATH,
    compute_env_file_bootstrap_hash,
)


REQUIRED_FIELDS = (
    "env_file_bootstrap_version",
    "generated_at",
    "status",
    "env_file_bootstrap_ready",
    "output_path",
    "action",
    "overwrite",
    "template",
    "env_file",
    "summary",
    "next_commands",
    "verification_commands",
    "evidence_outputs",
    "errors",
    "warnings",
    "redaction_policy",
    "env_file_bootstrap_hash",
)


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _find_forbidden_secret_fields(value: object, *, prefix: str = "") -> list[str]:
    forbidden: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if key in {"value", "raw_value", "secret", "api_key", "database_url", "selector_value"}:
                forbidden.append(path)
            forbidden.extend(_find_forbidden_secret_fields(child, prefix=path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            forbidden.extend(_find_forbidden_secret_fields(child, prefix=f"{prefix}[{index}]"))
    return forbidden


def verify_au_p0b_google_env_file_bootstrap(
    payload: Any,
    *,
    path: Path | None = None,
    require_ready: bool = False,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "status": "fail",
            "errors": ["env_file_bootstrap_not_json_object"],
            "hash_valid": False,
            "env_file_bootstrap_ready": False,
        }

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in payload:
            errors.append(f"field_missing:{field}")
    if payload.get("env_file_bootstrap_version") != BOOTSTRAP_VERSION:
        errors.append("env_file_bootstrap_version_invalid")

    expected_hash = payload.get("env_file_bootstrap_hash")
    computed_hash = compute_env_file_bootstrap_hash(payload)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("env_file_bootstrap_hash_mismatch")

    template = _as_dict(payload.get("template"))
    env_file = _as_dict(payload.get("env_file"))
    hygiene = _as_dict(env_file.get("hygiene"))
    summary = _as_dict(payload.get("summary"))
    payload_errors = [str(item) for item in _as_list(payload.get("errors"))]
    payload_warnings = [str(item) for item in _as_list(payload.get("warnings"))]

    for forbidden in _find_forbidden_secret_fields(payload):
        errors.append(f"forbidden_secret_field:{forbidden}")
    if template.get("template_verifier_status") != "pass":
        errors.append("template_verifier_not_pass")
    if not template.get("template_verification_hash"):
        errors.append("template_verification_hash_missing")
    if env_file.get("exists") is not True:
        errors.append("env_file_missing")
    if hygiene.get("secret_redacted") is not True:
        errors.append("env_file_hygiene_secret_redaction_missing")
    if hygiene.get("hygiene_ready") is not True:
        errors.append("env_file_hygiene_not_ready")
    if hygiene.get("permission_safe") is not True:
        errors.append("env_file_permission_not_safe")
    if hygiene.get("git_safe") is not True:
        errors.append("env_file_git_not_safe")
    if hygiene.get("file_mode") != "0600":
        errors.append("env_file_mode_not_0600")
    if summary.get("env_file_exists") is not env_file.get("exists"):
        errors.append("summary_env_file_exists_mismatch")
    if summary.get("env_file_permission_safe") is not (hygiene.get("permission_safe") is True):
        errors.append("summary_env_file_permission_safe_mismatch")
    if summary.get("env_file_hygiene_ready") is not (hygiene.get("hygiene_ready") is True):
        errors.append("summary_env_file_hygiene_ready_mismatch")
    if summary.get("error_count") != len(payload_errors):
        errors.append("summary_error_count_mismatch")
    if summary.get("warning_count") != len(payload_warnings):
        errors.append("summary_warning_count_mismatch")

    expected_ready = not payload_errors and hygiene.get("hygiene_ready") is True and template.get("template_verifier_status") == "pass"
    if payload.get("env_file_bootstrap_ready") is not expected_ready:
        errors.append("env_file_bootstrap_ready_mismatch")
    if payload.get("status") != ("pass" if expected_ready else "fail"):
        errors.append("status_mismatch")
    if "make verify-au-p0b-google-env-bootstrap" not in [str(item) for item in _as_list(payload.get("verification_commands"))]:
        errors.append("verification_command_missing:make verify-au-p0b-google-env-bootstrap")
    if "make au-p0b-google-playwright-env" not in [str(item) for item in _as_list(payload.get("next_commands"))]:
        errors.append("next_command_missing:make au-p0b-google-playwright-env")
    redaction_policy = _as_dict(payload.get("redaction_policy"))
    if redaction_policy.get("raw_secret_values_allowed") is not False:
        errors.append("raw_secret_policy_invalid")
    if redaction_policy.get("secret_redacted") is not True:
        errors.append("redaction_policy_secret_redacted_missing")
    if require_ready and not expected_ready:
        errors.append("env_file_bootstrap_not_ready")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "env_file_bootstrap_version": payload.get("env_file_bootstrap_version", ""),
        "env_file_bootstrap_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_env_file_bootstrap_hash": computed_hash,
        "hash_valid": hash_valid,
        "env_file_bootstrap_ready": expected_ready,
        "action": payload.get("action", ""),
        "env_file_mode": hygiene.get("file_mode", ""),
        "env_file_git_ignored": hygiene.get("git_ignored"),
        "env_file_git_tracked": hygiene.get("git_tracked"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU P0b Google env-file bootstrap audit JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_ENV_BOOTSTRAP_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU P0b Google env-file bootstrap audit JSON.",
    )
    parser.add_argument("--require-ready", action="store_true", help="Fail unless the env-file bootstrap is ready.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = Path(args.path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": ["env_file_bootstrap_file_missing"],
            "hash_valid": False,
            "env_file_bootstrap_ready": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"env_file_bootstrap_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "env_file_bootstrap_ready": False,
        }
    else:
        result = verify_au_p0b_google_env_file_bootstrap(payload, path=path, require_ready=args.require_ready)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
