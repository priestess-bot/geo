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

from scripts.build_au_p0a_execution_checklist import (  # noqa: E402
    CHECKLIST_VERSION,
    DEFAULT_OUTPUT_PATH,
    compute_p0a_execution_checklist_hash,
)


REQUIRED_FIELDS = (
    "execution_checklist_version",
    "generated_at",
    "status",
    "p0a_execution_checklist_ready",
    "ready_for_design_partner",
    "next_action",
    "paths",
    "summary",
    "runbook_source",
    "runbook_verifier",
    "environment_report_source",
    "environment_report",
    "environment_report_verifier",
    "runbook_execution_source",
    "runbook_execution",
    "runbook_execution_verifier",
    "package_source",
    "evidence_package",
    "evidence_package_verifier",
    "status_report_source",
    "status_report",
    "status_report_verifier",
    "setup_commands",
    "credential_handoff",
    "real_batch_phase_handoff",
    "execution_commands",
    "verification_commands",
    "work_items",
    "evidence_outputs",
    "current_boundary",
    "p0a_execution_checklist_hash",
)


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _find_forbidden_secret_fields(value: object, *, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in {"value", "raw_value"}:
                findings.append(child_path)
            findings.extend(_find_forbidden_secret_fields(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_find_forbidden_secret_fields(child, path=f"{path}[{index}]"))
    return findings


def _command_ids(commands: list[object]) -> set[str]:
    return {str(_as_dict(item).get("id", "")) for item in commands}


def _validate_credential_handoff(
    handoff: dict[str, Any],
    *,
    errors: list[str],
) -> None:
    if handoff.get("version") != "au_p0a_credential_handoff_v1":
        errors.append("credential_handoff_version_invalid")
    for field in (
        "ready",
        "missing_required_count",
        "missing_required",
        "target_env_file",
        "setup_commands",
        "credential_items",
        "verification_commands",
        "evidence_outputs",
        "redaction_policy",
    ):
        if field not in handoff:
            errors.append(f"credential_handoff_field_missing:{field}")
    credential_items = [_as_dict(item) for item in _as_list(handoff.get("credential_items"))]
    item_names = [str(item.get("name", "")) for item in credential_items]
    for required_name in {"PERPLEXITY_API_KEY", "OPENAI_API_KEY", "DATABASE_URL"}:
        if required_name not in item_names:
            errors.append(f"credential_handoff_required_item_missing:{required_name}")
    missing_required = sorted(str(item) for item in _as_list(handoff.get("missing_required")))
    expected_missing = sorted(
        str(item.get("name", ""))
        for item in credential_items
        if item.get("required") is True and item.get("present") is not True
    )
    if missing_required != expected_missing:
        errors.append("credential_handoff_missing_required_mismatch")
    if handoff.get("missing_required_count") != len(missing_required):
        errors.append("credential_handoff_missing_required_count_mismatch")
    if handoff.get("ready") is not (not missing_required):
        errors.append("credential_handoff_ready_mismatch")
    setup_commands = [str(item) for item in _as_list(handoff.get("setup_commands"))]
    for command in {
        "make verify-au-p0a-env-template",
        "make au-p0a-env-bootstrap",
        "make verify-au-p0a-env-bootstrap",
    }:
        if command not in setup_commands:
            errors.append(f"credential_handoff_setup_command_missing:{command}")
    verification_commands = [str(item) for item in _as_list(handoff.get("verification_commands"))]
    for command in {
        "make verify-au-p0a-env-bootstrap",
        "make au-p0a-env",
        "make verify-au-p0a-env",
        "make au-p0a-environment-checklist",
        "make verify-au-p0a-environment-checklist",
        "make au-p0a-runbook-dry-run",
        "make verify-au-p0a-runbook-execution",
        "make au-p0a-status",
        "make verify-au-p0a-status",
    }:
        if command not in verification_commands:
            errors.append(f"credential_handoff_verification_command_missing:{command}")
    redaction_policy = _as_dict(handoff.get("redaction_policy"))
    if redaction_policy.get("raw_secret_values_allowed") is not False:
        errors.append("credential_handoff_raw_secret_policy_invalid")
    if redaction_policy.get("forbidden_exact_secret_field_count") != 2:
        errors.append("credential_handoff_forbidden_field_count_invalid")
    if redaction_policy.get("forbidden_exact_secret_fields_redacted") is not True:
        errors.append("credential_handoff_forbidden_field_redaction_missing")
    for item in credential_items:
        name = str(item.get("name", ""))
        for field in (
            "required",
            "present",
            "source",
            "owner_hint",
            "accepted_injection_methods",
            "env_file_key",
            "value_length",
            "sha256_prefix",
            "secret_redacted",
            "post_update_checks",
        ):
            if field not in item:
                errors.append(f"credential_handoff_item_field_missing:{name}:{field}")
        if item.get("secret_redacted") is not True:
            errors.append(f"credential_handoff_item_secret_redaction_missing:{name}")
        if item.get("env_file_key") != name:
            errors.append(f"credential_handoff_item_env_key_mismatch:{name}")
        accepted_methods = {str(value) for value in _as_list(item.get("accepted_injection_methods"))}
        if not {"process_environment", "GEO_AU_P0A_ENV_FILE", ".env.au-p0a"}.issubset(accepted_methods):
            errors.append(f"credential_handoff_item_injection_methods_incomplete:{name}")


def _artifact_ready(artifact: dict[str, Any]) -> bool:
    return artifact.get("status") == "pass" and artifact.get("ready_for_design_partner") is True


def _phase_expected_ready(phase: dict[str, Any]) -> bool:
    return all(_artifact_ready(_as_dict(artifact)) for artifact in _as_list(phase.get("artifacts")))


def _validate_real_batch_phase_handoff(
    handoff: dict[str, Any],
    *,
    summary: dict[str, Any],
    credential_handoff: dict[str, Any],
    errors: list[str],
) -> None:
    if handoff.get("version") != "au_p0a_real_batch_phase_handoff_v1":
        errors.append("real_batch_phase_handoff_version_invalid")
    for field in (
        "ready",
        "phase_count",
        "ready_phase_count",
        "blocked_phase_count",
        "next_phase",
        "total_planned_runs",
        "phase_order",
        "phases",
        "redaction_policy",
    ):
        if field not in handoff:
            errors.append(f"real_batch_phase_handoff_field_missing:{field}")

    expected_order = ["preflight", "small_batch", "full_batch"]
    if _string_list(handoff.get("phase_order")) != expected_order:
        errors.append("real_batch_phase_handoff_phase_order_invalid")
    phases = [_as_dict(phase) for phase in _as_list(handoff.get("phases"))]
    if [str(phase.get("id", "")) for phase in phases] != expected_order:
        errors.append("real_batch_phase_handoff_phases_invalid")
    if handoff.get("phase_count") != len(expected_order):
        errors.append("real_batch_phase_handoff_phase_count_mismatch")

    expected_commands = {
        "preflight": {
            "preflight_collect",
            "preflight_verify_audit",
            "preflight_manifest_audit",
            "preflight_design_partner_gate",
        },
        "small_batch": {"small_batch_collect", "small_batch_manifest_gate"},
        "full_batch": {"full_batch_collect", "full_batch_manifest_gate"},
    }
    expected_artifacts = {
        "preflight": {"preflight_json", "preflight_manifest"},
        "small_batch": {"small_batch_json", "small_batch_manifest"},
        "full_batch": {"full_batch_json", "full_batch_manifest"},
    }
    expected_gate_ids = {
        "preflight": {"hard_environment_gate", "hard_runbook_execution_gate"},
        "small_batch": {"hard_preflight_gate"},
        "full_batch": {"hard_package_gate", "hard_status_gate"},
    }

    ready_phase_count = 0
    total_planned_runs = 0
    expected_next_phase = "complete"
    previous_ready = credential_handoff.get("ready") is True
    for phase in phases:
        phase_id = str(phase.get("id", ""))
        artifacts = [_as_dict(artifact) for artifact in _as_list(phase.get("artifacts"))]
        artifact_keys = {str(artifact.get("key", "")) for artifact in artifacts}
        command_ids = set(_string_list(phase.get("command_ids")))
        command_item_ids = {str(_as_dict(command).get("id", "")) for command in _as_list(phase.get("commands"))}
        prerequisite_gate_ids = set(_string_list(phase.get("prerequisite_gate_ids")))
        if phase_id in expected_commands and command_ids != expected_commands[phase_id]:
            errors.append(f"real_batch_phase_handoff_command_ids_mismatch:{phase_id}")
        if phase_id in expected_commands and command_item_ids != expected_commands[phase_id]:
            errors.append(f"real_batch_phase_handoff_commands_mismatch:{phase_id}")
        if phase_id in expected_artifacts and artifact_keys != expected_artifacts[phase_id]:
            errors.append(f"real_batch_phase_handoff_artifact_keys_mismatch:{phase_id}")
        if phase_id in expected_gate_ids and prerequisite_gate_ids != expected_gate_ids[phase_id]:
            errors.append(f"real_batch_phase_handoff_gate_ids_mismatch:{phase_id}")
        expected_ready = _phase_expected_ready(phase)
        if phase.get("ready") is not expected_ready:
            errors.append(f"real_batch_phase_handoff_phase_ready_mismatch:{phase_id}")
        if phase.get("can_start") is not previous_ready:
            errors.append(f"real_batch_phase_handoff_can_start_mismatch:{phase_id}")
        if expected_ready:
            ready_phase_count += 1
        elif expected_next_phase == "complete":
            expected_next_phase = phase_id
        previous_ready = expected_ready
        planned_runs = phase.get("planned_runs", 0)
        if not isinstance(planned_runs, int):
            errors.append(f"real_batch_phase_handoff_planned_runs_invalid:{phase_id}")
            planned_runs = 0
        total_planned_runs += planned_runs
        for artifact in artifacts:
            if "path" not in artifact or "status" not in artifact or "ready_for_design_partner" not in artifact:
                errors.append(f"real_batch_phase_handoff_artifact_incomplete:{phase_id}:{artifact.get('key', '')}")

    if handoff.get("ready_phase_count") != ready_phase_count:
        errors.append("real_batch_phase_handoff_ready_phase_count_mismatch")
    if handoff.get("blocked_phase_count") != len(expected_order) - ready_phase_count:
        errors.append("real_batch_phase_handoff_blocked_phase_count_mismatch")
    if handoff.get("ready") is not (ready_phase_count == len(expected_order)):
        errors.append("real_batch_phase_handoff_ready_mismatch")
    if handoff.get("next_phase") != expected_next_phase:
        errors.append("real_batch_phase_handoff_next_phase_mismatch")
    if handoff.get("total_planned_runs") != total_planned_runs:
        errors.append("real_batch_phase_handoff_total_planned_runs_mismatch")
    if summary.get("real_batch_phase_handoff_ready") is not handoff.get("ready"):
        errors.append("summary_real_batch_phase_handoff_ready_mismatch")
    if summary.get("real_batch_phase_handoff_next_phase") != handoff.get("next_phase"):
        errors.append("summary_real_batch_phase_handoff_next_phase_mismatch")
    if summary.get("real_batch_phase_handoff_ready_phase_count") != handoff.get("ready_phase_count"):
        errors.append("summary_real_batch_phase_handoff_ready_phase_count_mismatch")
    if summary.get("real_batch_phase_handoff_blocked_phase_count") != handoff.get("blocked_phase_count"):
        errors.append("summary_real_batch_phase_handoff_blocked_phase_count_mismatch")
    if summary.get("real_batch_phase_handoff_total_planned_runs") != handoff.get("total_planned_runs"):
        errors.append("summary_real_batch_phase_handoff_total_planned_runs_mismatch")
    redaction_policy = _as_dict(handoff.get("redaction_policy"))
    if redaction_policy.get("raw_secret_values_allowed") is not False:
        errors.append("real_batch_phase_handoff_raw_secret_policy_invalid")


def _expected_next_action(*, runbook_ok: bool, env_ok: bool, execution_ok: bool, status_next_action: str) -> str:
    if not runbook_ok:
        return "run_make_au_p0a_runbook"
    if not env_ok:
        return "populate_required_environment"
    if not execution_ok:
        return "run_au_p0a_runbook_dry_run"
    return status_next_action or "run_au_p0a_status"


def _string_list(value: object) -> list[str]:
    return [str(item) for item in _as_list(value)]


def verify_au_p0a_execution_checklist(
    checklist: Any,
    *,
    path: Path | None = None,
    require_design_partner_ready: bool = False,
) -> dict[str, Any]:
    if not isinstance(checklist, dict):
        return {
            "status": "fail",
            "errors": ["execution_checklist_not_json_object"],
            "hash_valid": False,
            "p0a_execution_checklist_ready": False,
            "ready_for_design_partner": False,
        }

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in checklist:
            errors.append(f"field_missing:{field}")
    if checklist.get("execution_checklist_version") != CHECKLIST_VERSION:
        errors.append("execution_checklist_version_invalid")
    for forbidden_path in _find_forbidden_secret_fields(checklist):
        errors.append(f"forbidden_secret_field:{forbidden_path}")

    expected_hash = checklist.get("p0a_execution_checklist_hash")
    computed_hash = compute_p0a_execution_checklist_hash(checklist)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("p0a_execution_checklist_hash_mismatch")

    summary = _as_dict(checklist.get("summary"))
    runbook_verifier = _as_dict(checklist.get("runbook_verifier"))
    env_verifier = _as_dict(checklist.get("environment_report_verifier"))
    execution_verifier = _as_dict(checklist.get("runbook_execution_verifier"))
    package = _as_dict(checklist.get("evidence_package"))
    package_summary = _as_dict(package.get("summary"))
    package_verifier = _as_dict(checklist.get("evidence_package_verifier"))
    status_report = _as_dict(checklist.get("status_report"))
    status_verifier = _as_dict(checklist.get("status_report_verifier"))
    credential_handoff = _as_dict(checklist.get("credential_handoff"))
    real_batch_phase_handoff = _as_dict(checklist.get("real_batch_phase_handoff"))

    missing_artifacts = _string_list(package_summary.get("missing_artifacts"))
    failed_artifacts = _string_list(package_summary.get("failed_artifacts"))
    ready_artifacts = _string_list(package_summary.get("ready_artifacts"))
    blocking_reasons = _string_list(package_summary.get("blocking_reasons"))
    remaining_blockers = _string_list(_as_dict(status_report).get("remaining_blockers"))
    if not remaining_blockers:
        remaining_blockers = _string_list(summary.get("remaining_blockers"))

    if summary.get("missing_artifacts") != missing_artifacts:
        errors.append("summary_missing_artifacts_mismatch")
    if summary.get("missing_artifact_count") != len(missing_artifacts):
        errors.append("summary_missing_artifact_count_mismatch")
    if summary.get("failed_artifacts") != failed_artifacts:
        errors.append("summary_failed_artifacts_mismatch")
    if summary.get("failed_artifact_count") != len(failed_artifacts):
        errors.append("summary_failed_artifact_count_mismatch")
    if summary.get("ready_artifacts") != ready_artifacts:
        errors.append("summary_ready_artifacts_mismatch")
    if summary.get("ready_artifact_count") != len(ready_artifacts):
        errors.append("summary_ready_artifact_count_mismatch")
    if summary.get("blocking_reasons") != blocking_reasons:
        errors.append("summary_blocking_reasons_mismatch")
    if summary.get("blocking_reason_count") != len(blocking_reasons):
        errors.append("summary_blocking_reason_count_mismatch")
    if sorted(str(item) for item in _as_list(summary.get("remaining_blockers"))) != sorted(remaining_blockers):
        errors.append("summary_remaining_blockers_mismatch")
    if summary.get("remaining_blocker_count") != len(remaining_blockers):
        errors.append("summary_remaining_blocker_count_mismatch")

    runbook_ok = runbook_verifier.get("status") == "pass" and runbook_verifier.get("hash_valid") is True
    env_ok = env_verifier.get("status") == "pass" and env_verifier.get("hash_valid") is True
    execution_ok = execution_verifier.get("status") == "pass" and execution_verifier.get("hash_valid") is True
    package_ok = package_verifier.get("status") == "pass" and package_verifier.get("hash_valid") is True
    status_ok = status_verifier.get("status") == "pass" and status_verifier.get("hash_valid") is True
    ready_for_design_partner = status_report.get("ready_for_design_partner") is True
    expected_ready = (
        runbook_ok
        and env_ok
        and execution_ok
        and package_ok
        and status_ok
        and ready_for_design_partner
        and not remaining_blockers
    )
    if checklist.get("p0a_execution_checklist_ready") is not expected_ready:
        errors.append("p0a_execution_checklist_ready_mismatch")
    if checklist.get("ready_for_design_partner") is not ready_for_design_partner:
        errors.append("ready_for_design_partner_mismatch")
    if checklist.get("status") != ("pass" if expected_ready else "fail"):
        errors.append("status_mismatch")
    expected_next = _expected_next_action(
        runbook_ok=runbook_ok,
        env_ok=env_ok,
        execution_ok=execution_ok,
        status_next_action=str(status_report.get("next_action") or ""),
    )
    if checklist.get("next_action") != expected_next:
        errors.append("next_action_mismatch")
    if require_design_partner_ready and not expected_ready:
        errors.append("p0a_execution_not_ready")

    setup_ids = _command_ids(_as_list(checklist.get("setup_commands")))
    execution_ids = _command_ids(_as_list(checklist.get("execution_commands")))
    verification_ids = _command_ids(_as_list(checklist.get("verification_commands")))
    for command_id in {
        "verify_env_template",
        "bootstrap_env_file",
        "verify_env_file_bootstrap",
        "build_runbook",
        "build_env_report",
        "verify_env_report",
        "build_environment_checklist",
        "dry_run_runbook",
    }:
        if command_id not in setup_ids:
            errors.append(f"setup_command_missing:{command_id}")
    _validate_credential_handoff(credential_handoff, errors=errors)
    _validate_real_batch_phase_handoff(
        real_batch_phase_handoff,
        summary=summary,
        credential_handoff=credential_handoff,
        errors=errors,
    )
    for command_id in {
        "preflight_collect",
        "preflight_verify_audit",
        "preflight_manifest_audit",
        "preflight_design_partner_gate",
        "small_batch_collect",
        "small_batch_manifest_gate",
        "full_batch_collect",
        "full_batch_manifest_gate",
    }:
        if command_id not in execution_ids:
            errors.append(f"execution_command_missing:{command_id}")
    for command_id in {
        "hard_environment_gate",
        "hard_runbook_execution_gate",
        "hard_preflight_gate",
        "hard_package_gate",
        "hard_status_gate",
    }:
        if command_id not in verification_ids:
            errors.append(f"verification_command_missing:{command_id}")
    if len(_as_list(checklist.get("work_items"))) < 4:
        errors.append("work_items_incomplete")
    if len(_as_list(checklist.get("evidence_outputs"))) < 12:
        errors.append("evidence_outputs_incomplete")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "execution_checklist_version": checklist.get("execution_checklist_version", ""),
        "p0a_execution_checklist_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_p0a_execution_checklist_hash": computed_hash,
        "hash_valid": hash_valid,
        "p0a_execution_checklist_ready": expected_ready,
        "ready_for_design_partner": ready_for_design_partner,
        "next_action": expected_next,
        "missing_artifacts": missing_artifacts,
        "failed_artifacts": failed_artifacts,
        "remaining_blocker_count": len(remaining_blockers),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU P0a execution checklist JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GEO_AU_P0A_EXECUTION_CHECKLIST_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU P0a execution checklist JSON.",
    )
    parser.add_argument(
        "--require-design-partner-ready",
        action="store_true",
        help="Fail unless the checklist proves P0a design-partner readiness.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = Path(args.path)
    try:
        checklist = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": ["execution_checklist_file_missing"],
            "hash_valid": False,
            "p0a_execution_checklist_ready": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"execution_checklist_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "p0a_execution_checklist_ready": False,
        }
    else:
        result = verify_au_p0a_execution_checklist(
            checklist,
            path=path,
            require_design_partner_ready=args.require_design_partner_ready,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
