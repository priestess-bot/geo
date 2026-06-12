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

from scripts.build_au_p0a_env_report import (  # noqa: E402
    DEFAULT_ENV_FILE,
    DEFAULT_OUTPUT_PATH as DEFAULT_ENV_REPORT_PATH,
    build_au_p0a_env_report,
)
from scripts.build_au_p0a_runbook import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_RUNBOOK_PATH,
    build_au_p0a_runbook,
)
from scripts.build_au_p0a_status_report import DEFAULT_OUTPUT_PATH as DEFAULT_STATUS_PATH  # noqa: E402
from scripts.run_au_p0a_runbook import DEFAULT_OUTPUT_PATH as DEFAULT_RUNBOOK_EXECUTION_PATH  # noqa: E402
from scripts.verify_au_p0a_env_report import verify_au_p0a_env_report  # noqa: E402
from scripts.verify_au_p0a_readiness import DEFAULT_OUTPUT_PATH as DEFAULT_READINESS_PATH  # noqa: E402
from scripts.verify_au_p0a_runbook import verify_au_p0a_runbook  # noqa: E402


CHECKLIST_VERSION = "au_p0a_environment_checklist_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0a-environment-checklist-latest.json"
DEFAULT_PACKAGE_PATH = "docs/runtime_preflight/au-p0a-evidence-package-latest.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_environment_checklist_hash(checklist: dict[str, Any]) -> str:
    payload = dict(checklist)
    payload.pop("environment_checklist_hash", None)
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
    return build_au_p0a_runbook(generated_at=generated_at), {
        **source,
        "source": "generated_in_memory",
    }


def _load_or_build_environment_report(
    path: Path,
    *,
    runbook_path: Path,
    env_file_path: Path | None,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if isinstance(payload, dict):
        return payload, source
    report = build_au_p0a_env_report(
        runbook_path=runbook_path,
        env_file_path=env_file_path,
        output_path=path,
        generated_at=generated_at,
    )
    return report, {**source, "source": "generated_in_memory"}


def _load_status_summary(path: Path) -> dict[str, Any]:
    payload, source = _load_json(path)
    if not isinstance(payload, dict):
        return {"source": source, "status": "missing", "remaining_blocker_count": 0, "environment_blockers": []}
    blockers = [str(item) for item in _as_list(payload.get("remaining_blockers"))]
    environment_blockers = [item for item in blockers if "required_env_missing:" in item]
    return {
        "source": source,
        "status": payload.get("status", ""),
        "ready_for_design_partner": payload.get("ready_for_design_partner") is True,
        "next_action": payload.get("next_action", ""),
        "status_report_hash": payload.get("status_report_hash", ""),
        "remaining_blocker_count": len(blockers),
        "environment_blockers": environment_blockers,
    }


def _environment_tasks(checks: list[object], *, required: bool) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for item in checks:
        check = _as_dict(item)
        present = check.get("present") is True
        tasks.append(
            {
                "name": str(check.get("name", "")),
                "required": required,
                "present": present,
                "source": check.get("source", "missing"),
                "value_length": check.get("value_length", 0),
                "sha256_prefix": check.get("sha256_prefix", ""),
                "secret_redacted": check.get("secret_redacted") is True,
                "action": "keep_current_redacted_value"
                if present
                else ("set_required_environment" if required else "optional_configure_durable_evidence"),
                "accepted_sources": ["process", "env_file"],
            }
        )
    return tasks


def _setup_commands() -> list[dict[str, str]]:
    return [
        {
            "id": "verify_env_template",
            "shell": "make verify-au-p0a-env-template",
            "purpose": "Verify the committed env template is complete and does not contain provider secrets.",
        },
        {
            "id": "copy_env_template",
            "shell": "cp .env.au-p0a.example .env.au-p0a",
            "purpose": "Create a local env file for real AU P0a credentials without committing secrets.",
        },
        {"id": "build_runbook", "shell": "make au-p0a-runbook", "purpose": "Freeze the P0a command plan."},
        {"id": "build_env_report", "shell": "make au-p0a-env", "purpose": "Generate the redacted env report."},
        {"id": "verify_env_report", "shell": "make verify-au-p0a-env", "purpose": "Verify env report hash and schema."},
    ]


def _verification_commands() -> list[dict[str, str]]:
    return [
        {
            "id": "hard_env_gate",
            "shell": (
                "PYTHONPATH=packages/geno_core:apps/api "
                "python3 scripts/verify_au_p0a_env_report.py "
                "${GENO_AU_P0A_ENV_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-env-latest.json} "
                "--require-ready-environment"
            ),
            "purpose": "Fail until PERPLEXITY_API_KEY, OPENAI_API_KEY and DATABASE_URL are present.",
        },
        {
            "id": "dry_run_runbook",
            "shell": "make au-p0a-runbook-dry-run && make verify-au-p0a-runbook-execution",
            "purpose": "Prove the next command sequence is auditable before external calls.",
        },
        {
            "id": "readiness_with_db",
            "shell": "GENO_AU_P0A_REQUIRE_DB_CHECK=1 make au-p0a-readiness",
            "purpose": "Optionally verify DATABASE_URL with a read-only PostgreSQL check before real batches.",
        },
        {"id": "refresh_status", "shell": "make au-p0a-status && make verify-au-p0a-status", "purpose": "Refresh P0a status blockers."},
    ]


def _next_action(*, runbook_ok: bool, env_report_ok: bool, missing_required: list[str]) -> str:
    if not runbook_ok:
        return "run_make_au_p0a_runbook"
    if missing_required:
        return "populate_required_environment"
    if not env_report_ok:
        return "fix_au_p0a_environment_report"
    return "run_au_p0a_runbook_dry_run"


def build_au_p0a_environment_checklist(
    *,
    runbook_path: Path = Path(DEFAULT_RUNBOOK_PATH),
    environment_path: Path = Path(DEFAULT_ENV_REPORT_PATH),
    status_path: Path = Path(DEFAULT_STATUS_PATH),
    env_file_path: Path | None = Path(DEFAULT_ENV_FILE),
    output_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    runbook, runbook_source = _load_or_build_runbook(runbook_path, generated_at=generated_at)
    environment_report, environment_source = _load_or_build_environment_report(
        environment_path,
        runbook_path=runbook_path,
        env_file_path=env_file_path,
        generated_at=generated_at,
    )
    runbook_verifier = verify_au_p0a_runbook(runbook, path=runbook_path)
    environment_verifier = verify_au_p0a_env_report(environment_report, path=environment_path)
    required_tasks = _environment_tasks(_as_list(environment_report.get("required")), required=True)
    recommended_tasks = _environment_tasks(_as_list(environment_report.get("recommended")), required=False)
    missing_required = [task["name"] for task in required_tasks if not task["present"]]
    missing_recommended = [task["name"] for task in recommended_tasks if not task["present"]]
    runbook_ok = runbook_verifier.get("status") == "pass" and runbook_verifier.get("hash_valid") is True
    env_report_ok = environment_verifier.get("status") == "pass" and environment_verifier.get("hash_valid") is True
    ready = runbook_ok and env_report_ok and environment_report.get("ready_for_real_batch") is True and not missing_required
    next_action = _next_action(runbook_ok=runbook_ok, env_report_ok=env_report_ok, missing_required=missing_required)
    checklist: dict[str, Any] = {
        "environment_checklist_version": CHECKLIST_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if ready else "fail",
        "environment_checklist_ready": ready,
        "next_action": next_action,
        "paths": {
            "runbook": str(runbook_path),
            "environment_report": str(environment_path),
            "status_report": str(status_path),
            "runbook_execution": DEFAULT_RUNBOOK_EXECUTION_PATH,
            "readiness": DEFAULT_READINESS_PATH,
            "p0a_package": DEFAULT_PACKAGE_PATH,
            "output": str(output_path) if output_path else "",
            "env_file": str(env_file_path) if env_file_path else "",
        },
        "summary": {
            "required_count": len(required_tasks),
            "required_present_count": len(required_tasks) - len(missing_required),
            "missing_required_count": len(missing_required),
            "missing_required": missing_required,
            "recommended_count": len(recommended_tasks),
            "missing_recommended_count": len(missing_recommended),
            "missing_recommended": missing_recommended,
            "runbook_verifier_status": runbook_verifier.get("status", ""),
            "environment_verifier_status": environment_verifier.get("status", ""),
            "environment_report_ready": environment_report.get("ready_for_real_batch") is True,
        },
        "runbook_source": runbook_source,
        "runbook_verifier": runbook_verifier,
        "environment_report_source": environment_source,
        "environment_report": {
            "environment_report_version": environment_report.get("environment_report_version", ""),
            "status": environment_report.get("status", ""),
            "ready_for_real_batch": environment_report.get("ready_for_real_batch") is True,
            "next_action": environment_report.get("next_action", ""),
            "environment_report_hash": environment_report.get("environment_report_hash", ""),
            "secrets_redacted": environment_report.get("secrets_redacted") is True,
        },
        "environment_report_verifier": environment_verifier,
        "status_report_summary": _load_status_summary(status_path),
        "required_environment": required_tasks,
        "recommended_environment": recommended_tasks,
        "setup_commands": _setup_commands(),
        "verification_commands": _verification_commands(),
        "evidence_outputs": [
            str(runbook_path),
            str(environment_path),
            DEFAULT_RUNBOOK_EXECUTION_PATH,
            DEFAULT_READINESS_PATH,
            DEFAULT_PACKAGE_PATH,
            str(status_path),
        ],
        "current_boundary": [
            "This checklist proves P0a environment configuration is auditable and redacted.",
            "It does not prove real provider calls, small batch, full batch, P0b Google or customer handoff are complete.",
        ],
    }
    checklist["environment_checklist_hash"] = compute_environment_checklist_hash(checklist)
    return checklist


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU P0a environment setup checklist JSON")
    parser.add_argument(
        "--runbook-path",
        default=os.environ.get("GENO_AU_P0A_RUNBOOK_OUTPUT_PATH", DEFAULT_RUNBOOK_PATH),
        help="Path to the AU P0a runbook JSON.",
    )
    parser.add_argument(
        "--environment-path",
        default=os.environ.get("GENO_AU_P0A_ENV_OUTPUT_PATH", DEFAULT_ENV_REPORT_PATH),
        help="Path to the AU P0a environment report JSON.",
    )
    parser.add_argument(
        "--status-path",
        default=os.environ.get("GENO_AU_P0A_STATUS_OUTPUT_PATH", DEFAULT_STATUS_PATH),
        help="Path to the AU P0a status report JSON.",
    )
    parser.add_argument(
        "--env-file",
        default=os.environ.get("GENO_AU_P0A_ENV_FILE", DEFAULT_ENV_FILE),
        help="Optional env file to parse if the environment report is missing.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GENO_AU_P0A_ENVIRONMENT_CHECKLIST_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU P0a environment checklist JSON.",
    )
    parser.add_argument(
        "--require-ready-environment",
        action="store_true",
        help="Exit non-zero unless the checklist proves the P0a environment is ready.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    checklist = build_au_p0a_environment_checklist(
        runbook_path=Path(args.runbook_path),
        environment_path=Path(args.environment_path),
        status_path=Path(args.status_path),
        env_file_path=Path(args.env_file) if args.env_file else None,
        output_path=output_path,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(checklist, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(checklist, ensure_ascii=False, indent=2, default=str))
    if args.require_ready_environment and checklist["environment_checklist_ready"] is not True:
        raise SystemExit(2)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
