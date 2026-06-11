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

from scripts.build_au_p0a_runbook import DEFAULT_OUTPUT_PATH as DEFAULT_RUNBOOK_PATH  # noqa: E402
from scripts.verify_au_p0a_runbook import REQUIRED_ENV, verify_au_p0a_runbook  # noqa: E402


ENV_REPORT_VERSION = "au_p0a_environment_report_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0a-env-latest.json"
DEFAULT_ENV_FILE = ".env.au-p0a"
RECOMMENDED_ENV = (
    "OBJECT_STORE_ENDPOINT",
    "OBJECT_STORE_BUCKET",
    "OBJECT_STORE_ACCESS_KEY",
    "OBJECT_STORE_SECRET_KEY",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_report_bytes(report: dict[str, Any]) -> bytes:
    return json.dumps(
        report,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def compute_env_report_hash(report: dict[str, Any]) -> str:
    payload_for_hash = dict(report)
    payload_for_hash.pop("environment_report_hash", None)
    return hashlib.sha256(_stable_report_bytes(payload_for_hash)).hexdigest()


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _strip_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _load_env_file(path: Path | None) -> tuple[dict[str, str], dict[str, Any]]:
    if path is None:
        return {}, {"path": "", "exists": False, "loaded": False, "errors": []}
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, {"path": str(path), "exists": False, "loaded": False, "errors": []}

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
        "secrets_redacted": True,
    }


def _load_runbook(path: Path) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, {
            "path": str(path),
            "exists": False,
            "status": "fail",
            "errors": ["runbook_file_missing"],
            "hash_valid": False,
        }
    except json.JSONDecodeError as exc:
        return None, {
            "path": str(path),
            "exists": True,
            "status": "fail",
            "errors": [f"runbook_json_invalid:{exc.msg}"],
            "hash_valid": False,
        }
    if not isinstance(payload, dict):
        return None, {
            "path": str(path),
            "exists": True,
            "status": "fail",
            "errors": ["runbook_not_json_object"],
            "hash_valid": False,
        }
    verification = verify_au_p0a_runbook(payload, path=path)
    return payload, {
        "path": str(path),
        "exists": True,
        "status": verification["status"],
        "errors": verification["errors"],
        "hash_valid": verification["hash_valid"],
        "runbook_version": verification.get("runbook_version", ""),
        "runbook_payload_hash": verification.get("runbook_payload_hash", ""),
        "small_batch_planned_runs": verification.get("small_batch_planned_runs"),
        "full_batch_planned_runs": verification.get("full_batch_planned_runs"),
        "step_count": verification.get("step_count"),
    }


def _as_sequence(value: object) -> tuple[str, ...]:
    return tuple(str(item) for item in value) if isinstance(value, list | tuple) else ()


def _env_names(runbook: dict[str, Any] | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    required = _as_sequence((runbook or {}).get("required_env")) or REQUIRED_ENV
    recommended = _as_sequence((runbook or {}).get("recommended_env")) or RECOMMENDED_ENV
    return required, recommended


def _check_env_names(
    names: tuple[str, ...],
    *,
    env_file_values: Mapping[str, str],
    process_env: Mapping[str, str],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for name in names:
        source = "missing"
        value = ""
        if process_env.get(name):
            value = str(process_env[name])
            source = "process"
        elif env_file_values.get(name):
            value = str(env_file_values[name])
            source = "env_file"
        checks.append(
            {
                "name": name,
                "present": bool(value),
                "source": source,
                "value_length": len(value),
                "sha256_prefix": _fingerprint(value) if value else "",
                "secret_redacted": True,
            }
        )
    return checks


def _next_action(runbook_status: dict[str, Any], env_file: dict[str, Any], missing_required: list[str]) -> str:
    if runbook_status.get("status") != "pass":
        return "run_or_fix_au_p0a_runbook"
    if env_file.get("errors"):
        return "fix_environment_file"
    if missing_required:
        return "populate_required_environment"
    return "run_au_p0a_runbook_dry_run"


def build_au_p0a_env_report(
    *,
    runbook_path: Path = Path(DEFAULT_RUNBOOK_PATH),
    env_file_path: Path | None = None,
    output_path: Path | None = None,
    env: Mapping[str, str] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    runbook, runbook_status = _load_runbook(runbook_path)
    env_file_values, env_file = _load_env_file(env_file_path)
    process_env = os.environ if env is None else env
    required_names, recommended_names = _env_names(runbook)
    required = _check_env_names(required_names, env_file_values=env_file_values, process_env=process_env)
    recommended = _check_env_names(recommended_names, env_file_values=env_file_values, process_env=process_env)
    missing_required = [item["name"] for item in required if not item["present"]]
    missing_recommended = [item["name"] for item in recommended if not item["present"]]
    env_file_errors = list(env_file.get("errors", []))
    ready_for_real_batch = runbook_status.get("status") == "pass" and not missing_required and not env_file_errors
    report: dict[str, Any] = {
        "environment_report_version": ENV_REPORT_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if ready_for_real_batch else "fail",
        "ready_for_real_batch": ready_for_real_batch,
        "next_action": _next_action(runbook_status, env_file, missing_required),
        "runbook_path": str(runbook_path),
        "output_path": str(output_path) if output_path else "",
        "runbook": runbook_status,
        "env_file": env_file,
        "required": required,
        "recommended": recommended,
        "missing_required": missing_required,
        "missing_recommended": missing_recommended,
        "warnings": [f"recommended_env_missing:{name}" for name in missing_recommended],
        "errors": [
            *[f"runbook:{error}" for error in runbook_status.get("errors", [])],
            *[f"env_file:{error}" for error in env_file_errors],
            *[f"required_env_missing:{name}" for name in missing_required],
        ],
        "secrets_redacted": True,
    }
    report["environment_report_hash"] = compute_env_report_hash(report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a redacted AU P0a environment readiness report")
    parser.add_argument(
        "--runbook-path",
        default=os.environ.get("GENO_AU_P0A_RUNBOOK_OUTPUT_PATH", DEFAULT_RUNBOOK_PATH),
        help="Path to the generated AU P0a runbook JSON.",
    )
    parser.add_argument(
        "--env-file",
        default=os.environ.get("GENO_AU_P0A_ENV_FILE", DEFAULT_ENV_FILE),
        help="Optional env file to parse without shell evaluation. Missing files are allowed.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GENO_AU_P0A_ENV_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the redacted environment report JSON.",
    )
    parser.add_argument(
        "--require-ready-environment",
        action="store_true",
        help="Exit non-zero unless required AU P0a environment is present and runbook verifies.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    env_file_path = Path(args.env_file) if args.env_file else None
    report = build_au_p0a_env_report(
        runbook_path=Path(args.runbook_path),
        env_file_path=env_file_path,
        output_path=output_path,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if args.require_ready_environment and report["ready_for_real_batch"] is not True:
        raise SystemExit(2)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
