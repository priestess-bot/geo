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

from scripts.build_au_p0a_evidence_package import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_PACKAGE_PATH,
    build_au_p0a_evidence_package,
)
from scripts.build_au_p0a_env_report import DEFAULT_ENV_FILE, DEFAULT_OUTPUT_PATH as DEFAULT_ENV_REPORT_PATH  # noqa: E402
from scripts.build_au_p0a_runbook import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_RUNBOOK_PATH,
    build_au_p0a_runbook,
)
from scripts.build_au_p0a_status_report import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_STATUS_PATH,
    build_au_p0a_status_report,
)
from scripts.run_au_p0a_runbook import DEFAULT_OUTPUT_PATH as DEFAULT_RUNBOOK_EXECUTION_PATH  # noqa: E402
from scripts.verify_au_p0a_evidence_package import verify_au_p0a_evidence_package  # noqa: E402
from scripts.verify_au_p0a_env_report import verify_au_p0a_env_report  # noqa: E402
from scripts.verify_au_p0a_readiness import DEFAULT_OUTPUT_PATH as DEFAULT_READINESS_PATH  # noqa: E402
from scripts.verify_au_p0a_runbook import verify_au_p0a_runbook  # noqa: E402
from scripts.verify_au_p0a_runbook_execution import verify_au_p0a_runbook_execution  # noqa: E402
from scripts.verify_au_p0a_status_report import verify_au_p0a_status_report  # noqa: E402


CHECKLIST_VERSION = "au_p0a_execution_checklist_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0a-execution-checklist-latest.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_p0a_execution_checklist_hash(checklist: dict[str, Any]) -> str:
    payload = dict(checklist)
    payload.pop("p0a_execution_checklist_hash", None)
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
    return build_au_p0a_runbook(generated_at=generated_at), {**source, "source": "generated_in_memory"}


def _load_or_build_package(
    path: Path,
    *,
    runbook_path: Path,
    environment_path: Path,
    readiness_path: Path,
    runbook_execution_path: Path,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if isinstance(payload, dict):
        return payload, source
    package = build_au_p0a_evidence_package(
        runbook_path=runbook_path,
        environment_path=environment_path,
        readiness_path=readiness_path,
        runbook_execution_path=runbook_execution_path,
        output_path=path,
        generated_at=generated_at,
    )
    return package, {**source, "source": "generated_in_memory"}


def _load_or_build_status(
    path: Path,
    *,
    runbook_path: Path,
    environment_path: Path,
    readiness_path: Path,
    runbook_execution_path: Path,
    package_path: Path,
    env_file_path: Path | None,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if isinstance(payload, dict):
        return payload, source
    status = build_au_p0a_status_report(
        runbook_path=runbook_path,
        environment_path=environment_path,
        readiness_path=readiness_path,
        runbook_execution_path=runbook_execution_path,
        package_path=package_path,
        output_path=path,
        env_file_path=env_file_path,
        generated_at=generated_at,
    )
    return status, {**source, "source": "generated_in_memory"}


def _verify_json_artifact(
    path: Path,
    *,
    missing_error: str,
    verifier: Any,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if not isinstance(payload, dict):
        return {}, source, {"status": "fail", "errors": [missing_error], "hash_valid": False}
    return payload, source, verifier(payload, path=path)


def _command_text(command: object) -> str:
    if isinstance(command, list):
        return " ".join(str(part) for part in command)
    if isinstance(command, str):
        return command
    return ""


def _artifact_paths(runbook: dict[str, Any]) -> dict[str, str]:
    return {
        key: value
        for key, value in _as_dict(runbook.get("artifact_paths")).items()
        if isinstance(key, str) and isinstance(value, str)
    }


def _runbook_execution_commands(runbook: dict[str, Any]) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    for step in _as_list(runbook.get("steps")):
        item = _as_dict(step)
        step_id = str(item.get("id", ""))
        command_text = _command_text(item.get("command"))
        if not step_id or not command_text:
            continue
        command = {
            "id": step_id,
            "shell": command_text,
            "purpose": str(item.get("description") or item.get("name") or step_id),
            "output_paths": [str(path) for path in _as_list(item.get("output_paths"))],
            "external_call_risk": item.get("external_call_risk") is True,
            "stop_on_failure": item.get("stop_on_failure") is not False,
        }
        if isinstance(item.get("planned_runs"), int):
            command["planned_runs"] = item["planned_runs"]
        commands.append(command)
    return commands


def _artifact_summary(package: dict[str, Any], status_report: dict[str, Any]) -> dict[str, Any]:
    package_summary = _as_dict(package.get("summary"))
    status_completion = _as_dict(status_report.get("completion"))
    return {
        "artifact_count": status_completion.get("artifact_count", package_summary.get("artifact_count", 0)),
        "missing_artifacts": [str(value) for value in _as_list(package_summary.get("missing_artifacts"))],
        "failed_artifacts": [str(value) for value in _as_list(package_summary.get("failed_artifacts"))],
        "ready_artifacts": [str(value) for value in _as_list(package_summary.get("ready_artifacts"))],
        "blocking_reasons": [str(value) for value in _as_list(package_summary.get("blocking_reasons"))],
        "completion_percent": status_completion.get("completion_percent", 0.0),
        "design_ready_artifact_percent": status_completion.get("design_ready_artifact_percent", 0.0),
    }


def _setup_commands() -> list[dict[str, str]]:
    return [
        {
            "id": "verify_env_template",
            "shell": "make verify-au-p0a-env-template",
            "purpose": "Verify the committed P0a env template before creating a local secret file.",
        },
        {
            "id": "copy_env_template",
            "shell": "cp .env.au-p0a.example .env.au-p0a",
            "purpose": "Create the local P0a env file without committing provider/database secrets.",
        },
        {
            "id": "chmod_env_file",
            "shell": "chmod 600 .env.au-p0a",
            "purpose": "Constrain the local P0a env file before writing provider/database credentials.",
        },
        {"id": "build_runbook", "shell": "make au-p0a-runbook", "purpose": "Freeze the P0a command plan."},
        {"id": "build_env_report", "shell": "make au-p0a-env", "purpose": "Generate the redacted P0a env report."},
        {"id": "verify_env_report", "shell": "make verify-au-p0a-env", "purpose": "Verify env report hash and redaction."},
        {
            "id": "build_environment_checklist",
            "shell": "make au-p0a-environment-checklist && make verify-au-p0a-environment-checklist",
            "purpose": "Refresh the focused P0a environment checklist before external calls.",
        },
        {
            "id": "dry_run_runbook",
            "shell": "make au-p0a-runbook-dry-run && make verify-au-p0a-runbook-execution",
            "purpose": "Confirm the P0a sequence is auditable before external provider calls.",
        },
    ]


def _verification_commands() -> list[dict[str, str]]:
    return [
        {
            "id": "hard_environment_gate",
            "shell": (
                "PYTHONPATH=packages/geno_core:apps/api "
                "python3 scripts/verify_au_p0a_env_report.py "
                "${GENO_AU_P0A_ENV_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-env-latest.json} "
                "--require-ready-environment"
            ),
            "purpose": "Fail until PERPLEXITY_API_KEY, OPENAI_API_KEY and DATABASE_URL are present.",
        },
        {
            "id": "hard_runbook_execution_gate",
            "shell": (
                "PYTHONPATH=packages/geno_core:apps/api "
                "python3 scripts/verify_au_p0a_runbook_execution.py "
                "${GENO_AU_P0A_RUNBOOK_EXECUTION_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-runbook-execution-latest.json} "
                "--require-ready-to-execute"
            ),
            "purpose": "Fail until dry-run proves the P0a command sequence can execute with required env.",
        },
        {
            "id": "hard_preflight_gate",
            "shell": (
                "PYTHONPATH=packages/geno_core:apps/api "
                "python3 scripts/verify_preflight_payload.py "
                "${GENO_API_PREFLIGHT_OUTPUT_PATH:-docs/runtime_preflight/api-preflight-latest.json} "
                "--require-design-partner-ready"
            ),
            "purpose": "Fail until the minimal provider preflight is design-partner ready.",
        },
        {
            "id": "hard_package_gate",
            "shell": (
                "PYTHONPATH=packages/geno_core:apps/api "
                "python3 scripts/verify_au_p0a_evidence_package.py "
                "${GENO_AU_P0A_PACKAGE_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-evidence-package-latest.json} "
                "--require-design-partner-ready"
            ),
            "purpose": "Fail until preflight, small batch and full batch payloads/manifests are ready.",
        },
        {
            "id": "hard_status_gate",
            "shell": (
                "PYTHONPATH=packages/geno_core:apps/api "
                "python3 scripts/verify_au_p0a_status_report.py "
                "${GENO_AU_P0A_STATUS_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-status-latest.json} "
                "--require-design-partner-ready"
            ),
            "purpose": "Fail until P0a status report is ready for design partner handoff.",
        },
    ]


def _work_items() -> list[dict[str, Any]]:
    return [
        {
            "id": "p0a_environment",
            "stage": "P0a",
            "commands": [
                "make verify-au-p0a-env-template",
                "cp .env.au-p0a.example .env.au-p0a",
                "make au-p0a-env",
                "make au-p0a-environment-checklist",
                "make au-p0a-runbook-dry-run",
            ],
            "hard_gate": "hard_runbook_execution_gate",
        },
        {
            "id": "p0a_preflight",
            "stage": "P0a",
            "commands": ["make api-preflight", "make verify-api-preflight", "make preflight-manifest"],
            "hard_gate": "hard_preflight_gate",
        },
        {
            "id": "p0a_small_batch",
            "stage": "P0a",
            "commands": [
                "python3 workers/collector_worker/run_collection_slice.py --mode api --prompt-limit 5 --cities Sydney --sample-size 3 --require-ready-collectors --require-p0a-readiness --require-no-collection-failures --preflight-output-path docs/runtime_preflight/au-p0a-small-batch.json --persist --persist-analysis",
                "python3 scripts/build_preflight_manifest.py docs/runtime_preflight/au-p0a-small-batch.json --manifest-path docs/runtime_preflight/au-p0a-small-batch-manifest.json --require-design-partner-ready",
            ],
            "hard_gate": "hard_package_gate",
        },
        {
            "id": "p0a_full_batch",
            "stage": "P0a",
            "commands": [
                "python3 workers/collector_worker/run_collection_slice.py --mode api --prompt-limit 100 --cities Australia,Sydney,Melbourne,Brisbane --sample-size 3 --require-ready-collectors --require-p0a-readiness --require-no-collection-failures --preflight-output-path docs/runtime_preflight/au-p0a-full-batch.json --persist --persist-analysis",
                "python3 scripts/build_preflight_manifest.py docs/runtime_preflight/au-p0a-full-batch.json --manifest-path docs/runtime_preflight/au-p0a-full-batch-manifest.json --require-design-partner-ready",
                "make au-p0a-package",
                "make au-p0a-status",
            ],
            "hard_gate": "hard_status_gate",
        },
    ]


def _commands_by_id(runbook: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(command.get("id", "")): command for command in _runbook_execution_commands(runbook)}


def _commands_for_phase(commands_by_id: dict[str, dict[str, Any]], command_ids: tuple[str, ...]) -> list[dict[str, Any]]:
    return [commands_by_id[command_id] for command_id in command_ids if command_id in commands_by_id]


def _artifact_gate_entry(package: dict[str, Any], artifact_key: str) -> dict[str, Any]:
    artifact = _as_dict(_as_dict(package.get("artifacts")).get(artifact_key))
    status = str(artifact.get("status") or "missing")
    errors = [str(value) for value in _as_list(artifact.get("errors"))]
    ready_for_design_partner = artifact.get("ready_for_design_partner") is True
    hash_valid = artifact.get("hash_valid")
    ready = status == "pass" and ready_for_design_partner
    return {
        "key": artifact_key,
        "path": str(artifact.get("path") or ""),
        "exists": artifact.get("exists") is True,
        "status": status,
        "ready_for_design_partner": ready_for_design_partner,
        "hash_valid": hash_valid,
        "ready": ready,
        "errors": errors,
    }


def _phase_blocking_reasons(
    *,
    artifact_entries: list[dict[str, Any]],
    package_summary: dict[str, Any],
    credential_handoff: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if credential_handoff.get("ready") is not True:
        for name in _as_list(credential_handoff.get("missing_required")):
            reasons.append(f"credential_handoff_missing_required:{name}")
    package_blocking_reasons = [str(value) for value in _as_list(package_summary.get("blocking_reasons"))]
    for artifact in artifact_entries:
        key = str(artifact.get("key", ""))
        if artifact.get("ready") is True:
            continue
        for error in _as_list(artifact.get("errors")):
            reasons.append(f"{key}:{error}")
        if artifact.get("status") != "pass":
            reasons.append(f"{key}:status_not_pass")
        if artifact.get("ready_for_design_partner") is not True:
            reasons.append(f"{key}:design_partner_not_ready")
        for reason in package_blocking_reasons:
            if reason.startswith(f"{key}:") and reason not in reasons:
                reasons.append(reason)
    return sorted(dict.fromkeys(reasons))


def _phase_handoff_phase(
    *,
    phase_id: str,
    title: str,
    planned_runs: int,
    command_ids: tuple[str, ...],
    artifact_keys: tuple[str, ...],
    prerequisite_gate_ids: tuple[str, ...],
    commands_by_id: dict[str, dict[str, Any]],
    package: dict[str, Any],
    package_summary: dict[str, Any],
    credential_handoff: dict[str, Any],
    can_start: bool,
) -> dict[str, Any]:
    artifact_entries = [_artifact_gate_entry(package, key) for key in artifact_keys]
    ready = all(entry.get("ready") is True for entry in artifact_entries)
    blocking_reasons = _phase_blocking_reasons(
        artifact_entries=artifact_entries,
        package_summary=package_summary,
        credential_handoff=credential_handoff,
    )
    return {
        "id": phase_id,
        "title": title,
        "planned_runs": planned_runs,
        "ready": ready,
        "can_start": can_start,
        "command_ids": list(command_ids),
        "commands": _commands_for_phase(commands_by_id, command_ids),
        "artifact_keys": list(artifact_keys),
        "artifacts": artifact_entries,
        "evidence_outputs": [str(entry.get("path") or "") for entry in artifact_entries],
        "prerequisite_gate_ids": list(prerequisite_gate_ids),
        "blocking_reasons": blocking_reasons,
    }


def _real_batch_phase_handoff(
    runbook: dict[str, Any],
    package: dict[str, Any],
    *,
    credential_handoff: dict[str, Any],
) -> dict[str, Any]:
    commands_by_id = _commands_by_id(runbook)
    scope = _as_dict(runbook.get("scope"))
    small_scope = _as_dict(scope.get("small_batch"))
    full_scope = _as_dict(scope.get("full_batch"))
    package_summary = _as_dict(package.get("summary"))
    preflight_planned_runs = int(commands_by_id.get("preflight_collect", {}).get("planned_runs") or 0)
    small_planned_runs = int(small_scope.get("planned_runs") or commands_by_id.get("small_batch_collect", {}).get("planned_runs") or 0)
    full_planned_runs = int(full_scope.get("planned_runs") or commands_by_id.get("full_batch_collect", {}).get("planned_runs") or 0)
    preflight_can_start = credential_handoff.get("ready") is True
    preflight = _phase_handoff_phase(
        phase_id="preflight",
        title="Provider preflight and manifest gate",
        planned_runs=preflight_planned_runs,
        command_ids=(
            "preflight_collect",
            "preflight_verify_audit",
            "preflight_manifest_audit",
            "preflight_design_partner_gate",
        ),
        artifact_keys=("preflight_json", "preflight_manifest"),
        prerequisite_gate_ids=("hard_environment_gate", "hard_runbook_execution_gate"),
        commands_by_id=commands_by_id,
        package=package,
        package_summary=package_summary,
        credential_handoff=credential_handoff,
        can_start=preflight_can_start,
    )
    small_batch = _phase_handoff_phase(
        phase_id="small_batch",
        title="Small AU batch and manifest gate",
        planned_runs=small_planned_runs,
        command_ids=("small_batch_collect", "small_batch_manifest_gate"),
        artifact_keys=("small_batch_json", "small_batch_manifest"),
        prerequisite_gate_ids=("hard_preflight_gate",),
        commands_by_id=commands_by_id,
        package=package,
        package_summary=package_summary,
        credential_handoff=credential_handoff,
        can_start=preflight.get("ready") is True,
    )
    full_batch = _phase_handoff_phase(
        phase_id="full_batch",
        title="Full AU P0a batch and package/status gate",
        planned_runs=full_planned_runs,
        command_ids=("full_batch_collect", "full_batch_manifest_gate"),
        artifact_keys=("full_batch_json", "full_batch_manifest"),
        prerequisite_gate_ids=("hard_package_gate", "hard_status_gate"),
        commands_by_id=commands_by_id,
        package=package,
        package_summary=package_summary,
        credential_handoff=credential_handoff,
        can_start=small_batch.get("ready") is True,
    )
    phases = [preflight, small_batch, full_batch]
    ready_phase_count = sum(1 for phase in phases if phase.get("ready") is True)
    next_phase = next((str(phase.get("id")) for phase in phases if phase.get("ready") is not True), "complete")
    return {
        "version": "au_p0a_real_batch_phase_handoff_v1",
        "ready": ready_phase_count == len(phases),
        "phase_count": len(phases),
        "ready_phase_count": ready_phase_count,
        "blocked_phase_count": len(phases) - ready_phase_count,
        "next_phase": next_phase,
        "total_planned_runs": sum(int(phase.get("planned_runs") or 0) for phase in phases),
        "phase_order": [str(phase.get("id")) for phase in phases],
        "phases": phases,
        "redaction_policy": {
            "raw_secret_values_allowed": False,
            "phase_entries_reference_command_ids_and_artifact_paths_only": True,
        },
    }


def _credential_handoff(
    environment_report: dict[str, Any],
    *,
    env_file_path: Path | None,
) -> dict[str, Any]:
    required_checks = [_as_dict(item) for item in _as_list(environment_report.get("required"))]
    missing_required = [str(check.get("name", "")) for check in required_checks if check.get("present") is not True]
    credential_items: list[dict[str, Any]] = []
    owners = {
        "PERPLEXITY_API_KEY": "provider_admin",
        "OPENAI_API_KEY": "provider_admin",
        "DATABASE_URL": "runtime_database_admin",
    }
    for check in required_checks:
        name = str(check.get("name", ""))
        credential_items.append(
            {
                "name": name,
                "required": True,
                "present": check.get("present") is True,
                "source": check.get("source", "missing"),
                "owner_hint": owners.get(name, "platform_operator"),
                "accepted_injection_methods": ["process_environment", "GENO_AU_P0A_ENV_FILE", ".env.au-p0a"],
                "env_file_key": name,
                "value_length": check.get("value_length", 0),
                "sha256_prefix": check.get("sha256_prefix", ""),
                "secret_redacted": check.get("secret_redacted") is True,
                "post_update_checks": [
                    "make au-p0a-env",
                    "make verify-au-p0a-env",
                    "make au-p0a-environment-checklist",
                    "make verify-au-p0a-environment-checklist",
                    "make au-p0a-runbook-dry-run",
                    "make verify-au-p0a-runbook-execution",
                ],
            }
        )
    return {
        "version": "au_p0a_credential_handoff_v1",
        "ready": not missing_required,
        "missing_required_count": len(missing_required),
        "missing_required": missing_required,
        "target_env_file": str(env_file_path) if env_file_path else "",
        "setup_commands": [
            "make verify-au-p0a-env-template",
            "cp .env.au-p0a.example .env.au-p0a",
            "chmod 600 .env.au-p0a",
        ],
        "credential_items": credential_items,
        "verification_commands": [
            "make au-p0a-env",
            "make verify-au-p0a-env",
            "make au-p0a-environment-checklist",
            "make verify-au-p0a-environment-checklist",
            "make au-p0a-runbook-dry-run",
            "make verify-au-p0a-runbook-execution",
            "make au-p0a-readiness",
            "make au-p0a-status",
            "make verify-au-p0a-status",
        ],
        "evidence_outputs": [
            "docs/runtime_preflight/au-p0a-env-latest.json",
            "docs/runtime_preflight/au-p0a-environment-checklist-latest.json",
            "docs/runtime_preflight/au-p0a-runbook-execution-latest.json",
            "docs/runtime_preflight/au-p0a-readiness-latest.json",
            "docs/runtime_preflight/au-p0a-status-latest.json",
        ],
        "redaction_policy": {
            "raw_secret_values_allowed": False,
            "recorded_fields": ["present", "source", "value_length", "sha256_prefix", "secret_redacted"],
            "forbidden_exact_secret_field_count": 2,
            "forbidden_exact_secret_fields_redacted": True,
        },
    }


def _expected_next_action(*, runbook_ok: bool, env_ok: bool, execution_ok: bool, status_next_action: str) -> str:
    if not runbook_ok:
        return "run_make_au_p0a_runbook"
    if not env_ok:
        return "populate_required_environment"
    if not execution_ok:
        return "run_au_p0a_runbook_dry_run"
    return status_next_action or "run_au_p0a_status"


def build_au_p0a_execution_checklist(
    *,
    runbook_path: Path = Path(DEFAULT_RUNBOOK_PATH),
    environment_path: Path = Path(DEFAULT_ENV_REPORT_PATH),
    runbook_execution_path: Path = Path(DEFAULT_RUNBOOK_EXECUTION_PATH),
    readiness_path: Path = Path(DEFAULT_READINESS_PATH),
    package_path: Path = Path(DEFAULT_PACKAGE_PATH),
    status_path: Path = Path(DEFAULT_STATUS_PATH),
    env_file_path: Path | None = Path(DEFAULT_ENV_FILE),
    output_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    runbook, runbook_source = _load_or_build_runbook(runbook_path, generated_at=generated_at)
    environment_report, environment_source, environment_verifier = _verify_json_artifact(
        environment_path,
        missing_error="environment_report_file_missing",
        verifier=verify_au_p0a_env_report,
    )
    runbook_execution, execution_source, execution_verifier = _verify_json_artifact(
        runbook_execution_path,
        missing_error="runbook_execution_file_missing",
        verifier=verify_au_p0a_runbook_execution,
    )
    package, package_source = _load_or_build_package(
        package_path,
        runbook_path=runbook_path,
        environment_path=environment_path,
        readiness_path=readiness_path,
        runbook_execution_path=runbook_execution_path,
        generated_at=generated_at,
    )
    status_report, status_source = _load_or_build_status(
        status_path,
        runbook_path=runbook_path,
        environment_path=environment_path,
        readiness_path=readiness_path,
        runbook_execution_path=runbook_execution_path,
        package_path=package_path,
        env_file_path=env_file_path,
        generated_at=generated_at,
    )

    runbook_verifier = verify_au_p0a_runbook(runbook, path=runbook_path)
    package_verifier = verify_au_p0a_evidence_package(package, path=package_path)
    status_verifier = verify_au_p0a_status_report(status_report, path=status_path)
    artifact_paths = _artifact_paths(runbook)
    artifact_summary = _artifact_summary(package, status_report)
    remaining_blockers = [str(value) for value in _as_list(status_report.get("remaining_blockers"))]
    runbook_ok = runbook_verifier.get("status") == "pass" and runbook_verifier.get("hash_valid") is True
    env_ok = environment_verifier.get("status") == "pass" and environment_verifier.get("hash_valid") is True
    execution_ok = execution_verifier.get("status") == "pass" and execution_verifier.get("hash_valid") is True
    package_ok = package_verifier.get("status") == "pass" and package_verifier.get("hash_valid") is True
    status_ok = status_verifier.get("status") == "pass" and status_verifier.get("hash_valid") is True
    ready_for_design_partner = status_report.get("ready_for_design_partner") is True
    ready = runbook_ok and env_ok and execution_ok and package_ok and status_ok and ready_for_design_partner and not remaining_blockers
    next_action = _expected_next_action(
        runbook_ok=runbook_ok,
        env_ok=env_ok,
        execution_ok=execution_ok,
        status_next_action=str(status_report.get("next_action") or ""),
    )
    credential_handoff = _credential_handoff(environment_report, env_file_path=env_file_path)
    real_batch_phase_handoff = _real_batch_phase_handoff(
        runbook,
        package,
        credential_handoff=credential_handoff,
    )
    checklist: dict[str, Any] = {
        "execution_checklist_version": CHECKLIST_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if ready else "fail",
        "p0a_execution_checklist_ready": ready,
        "ready_for_design_partner": ready_for_design_partner,
        "next_action": next_action,
        "paths": {
            "runbook": str(runbook_path),
            "environment_report": str(environment_path),
            "runbook_execution": str(runbook_execution_path),
            "readiness": str(readiness_path),
            "package": str(package_path),
            "status_report": str(status_path),
            "preflight": artifact_paths.get("preflight_json", "docs/runtime_preflight/api-preflight-latest.json"),
            "preflight_manifest": artifact_paths.get(
                "preflight_manifest", "docs/runtime_preflight/api-preflight-manifest-latest.json"
            ),
            "small_batch": artifact_paths.get("small_batch_json", "docs/runtime_preflight/au-p0a-small-batch.json"),
            "small_batch_manifest": artifact_paths.get(
                "small_batch_manifest", "docs/runtime_preflight/au-p0a-small-batch-manifest.json"
            ),
            "full_batch": artifact_paths.get("full_batch_json", "docs/runtime_preflight/au-p0a-full-batch.json"),
            "full_batch_manifest": artifact_paths.get(
                "full_batch_manifest", "docs/runtime_preflight/au-p0a-full-batch-manifest.json"
            ),
            "output": str(output_path) if output_path else "",
            "env_file": str(env_file_path) if env_file_path else "",
        },
        "summary": {
            "small_batch_planned_runs": runbook_verifier.get("small_batch_planned_runs"),
            "full_batch_planned_runs": runbook_verifier.get("full_batch_planned_runs"),
            "step_count": runbook_verifier.get("step_count"),
            "artifact_count": artifact_summary["artifact_count"],
            "missing_artifact_count": len(artifact_summary["missing_artifacts"]),
            "missing_artifacts": artifact_summary["missing_artifacts"],
            "failed_artifact_count": len(artifact_summary["failed_artifacts"]),
            "failed_artifacts": artifact_summary["failed_artifacts"],
            "ready_artifact_count": len(artifact_summary["ready_artifacts"]),
            "ready_artifacts": artifact_summary["ready_artifacts"],
            "blocking_reason_count": len(artifact_summary["blocking_reasons"]),
            "blocking_reasons": artifact_summary["blocking_reasons"],
            "remaining_blocker_count": len(remaining_blockers),
            "remaining_blockers": remaining_blockers,
            "completion_percent": artifact_summary["completion_percent"],
            "design_ready_artifact_percent": artifact_summary["design_ready_artifact_percent"],
            "runbook_verifier_status": runbook_verifier.get("status", ""),
            "environment_verifier_status": environment_verifier.get("status", ""),
            "runbook_execution_verifier_status": execution_verifier.get("status", ""),
            "package_verifier_status": package_verifier.get("status", ""),
            "status_verifier_status": status_verifier.get("status", ""),
            "real_batch_phase_handoff_ready": real_batch_phase_handoff.get("ready") is True,
            "real_batch_phase_handoff_next_phase": real_batch_phase_handoff.get("next_phase", ""),
            "real_batch_phase_handoff_ready_phase_count": real_batch_phase_handoff.get("ready_phase_count", 0),
            "real_batch_phase_handoff_blocked_phase_count": real_batch_phase_handoff.get("blocked_phase_count", 0),
            "real_batch_phase_handoff_total_planned_runs": real_batch_phase_handoff.get("total_planned_runs", 0),
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
        "runbook_execution_source": execution_source,
        "runbook_execution": {
            "execution_version": runbook_execution.get("execution_version", ""),
            "status": runbook_execution.get("status", ""),
            "mode": runbook_execution.get("mode", ""),
            "ready_to_execute": runbook_execution.get("ready_to_execute") is True,
            "execution_payload_hash": runbook_execution.get("execution_payload_hash", ""),
            "executed_command_count": runbook_execution.get("executed_command_count", 0),
        },
        "runbook_execution_verifier": execution_verifier,
        "package_source": package_source,
        "evidence_package": {
            "package_version": package.get("package_version", ""),
            "status": package.get("status", ""),
            "ready_for_design_partner": package.get("ready_for_design_partner") is True,
            "package_payload_hash": package.get("package_payload_hash", ""),
            "summary": package.get("summary", {}),
        },
        "evidence_package_verifier": package_verifier,
        "status_report_source": status_source,
        "status_report": {
            "status_report_version": status_report.get("status_report_version", ""),
            "status": status_report.get("status", ""),
            "ready_for_design_partner": ready_for_design_partner,
            "next_action": status_report.get("next_action", ""),
            "status_report_hash": status_report.get("status_report_hash", ""),
            "completion": status_report.get("completion", {}),
        },
        "status_report_verifier": status_verifier,
        "setup_commands": _setup_commands(),
        "credential_handoff": credential_handoff,
        "real_batch_phase_handoff": real_batch_phase_handoff,
        "execution_commands": _runbook_execution_commands(runbook),
        "verification_commands": _verification_commands(),
        "work_items": _work_items(),
        "evidence_outputs": [
            str(runbook_path),
            str(environment_path),
            str(runbook_execution_path),
            str(readiness_path),
            artifact_paths.get("preflight_json", "docs/runtime_preflight/api-preflight-latest.json"),
            artifact_paths.get("preflight_manifest", "docs/runtime_preflight/api-preflight-manifest-latest.json"),
            artifact_paths.get("small_batch_json", "docs/runtime_preflight/au-p0a-small-batch.json"),
            artifact_paths.get("small_batch_manifest", "docs/runtime_preflight/au-p0a-small-batch-manifest.json"),
            artifact_paths.get("full_batch_json", "docs/runtime_preflight/au-p0a-full-batch.json"),
            artifact_paths.get("full_batch_manifest", "docs/runtime_preflight/au-p0a-full-batch-manifest.json"),
            str(package_path),
            str(status_path),
        ],
        "current_boundary": [
            "This checklist proves the AU P0a real-batch execution path is auditable, ordered and redacted.",
            "It does not prove provider keys, database connectivity, preflight, small batch or 2400-run full batch are complete.",
            "P0a is design-partner ready only when package/status hard gates pass with no remaining blockers.",
        ],
    }
    checklist["p0a_execution_checklist_hash"] = compute_p0a_execution_checklist_hash(checklist)
    return checklist


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU P0a execution checklist JSON")
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
        "--runbook-execution-path",
        default=os.environ.get("GENO_AU_P0A_RUNBOOK_EXECUTION_OUTPUT_PATH", DEFAULT_RUNBOOK_EXECUTION_PATH),
        help="Path to the AU P0a runbook execution JSON.",
    )
    parser.add_argument(
        "--readiness-path",
        default=os.environ.get("GENO_AU_P0A_READINESS_OUTPUT_PATH", DEFAULT_READINESS_PATH),
        help="Path to the AU P0a readiness JSON.",
    )
    parser.add_argument(
        "--package-path",
        default=os.environ.get("GENO_AU_P0A_PACKAGE_OUTPUT_PATH", DEFAULT_PACKAGE_PATH),
        help="Path to the AU P0a evidence package JSON.",
    )
    parser.add_argument(
        "--status-path",
        default=os.environ.get("GENO_AU_P0A_STATUS_OUTPUT_PATH", DEFAULT_STATUS_PATH),
        help="Path to the AU P0a status report JSON.",
    )
    parser.add_argument(
        "--env-file",
        default=os.environ.get("GENO_AU_P0A_ENV_FILE", DEFAULT_ENV_FILE),
        help="Optional env file used when status needs in-memory rebuilding.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GENO_AU_P0A_EXECUTION_CHECKLIST_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU P0a execution checklist JSON.",
    )
    parser.add_argument(
        "--require-design-partner-ready",
        action="store_true",
        help="Exit non-zero unless the checklist proves P0a is design-partner ready.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    checklist = build_au_p0a_execution_checklist(
        runbook_path=Path(args.runbook_path),
        environment_path=Path(args.environment_path),
        runbook_execution_path=Path(args.runbook_execution_path),
        readiness_path=Path(args.readiness_path),
        package_path=Path(args.package_path),
        status_path=Path(args.status_path),
        env_file_path=Path(args.env_file) if args.env_file else None,
        output_path=output_path,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(checklist, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(checklist, ensure_ascii=False, indent=2, default=str))
    if args.require_design_partner_ready and checklist["p0a_execution_checklist_ready"] is not True:
        raise SystemExit(2)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
