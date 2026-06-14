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

from scripts.build_au_p0b_google_phase_execution_request_packet import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    PACKET_VERSION,
    compute_p0b_google_phase_execution_request_packet_hash,
)


REQUIRED_FIELDS = (
    "p0b_google_phase_execution_request_packet_version",
    "generated_at",
    "status",
    "phase_execution_request_packet_ready",
    "google_spike_phase_handoff_ready",
    "google_main_scoring_allowed",
    "output_path",
    "source_p0b_google_execution_checklist",
    "p0b_google_execution_checklist_verifier",
    "summary",
    "phase_requests",
    "setup_commands",
    "phase_commands",
    "verification_commands",
    "evidence_outputs",
    "redaction_policy",
    "runtime_endpoints",
    "hard_gate_commands",
    "evidence_sources",
    "p0b_google_phase_execution_request_packet_hash",
)

EXPECTED_PHASE_ORDER = [
    "environment",
    "browser_smoke",
    "manual_backfill",
    "health_check",
    "full_spike",
    "main_scoring",
]
EXPECTED_COMMAND_IDS = {
    "environment": {"verify_playwright_env"},
    "browser_smoke": {"run_smoke", "verify_smoke_strict"},
    "manual_backfill": {"build_manual_template", "verify_manual_backfill"},
    "health_check": {"run_health", "manifest_health"},
    "full_spike": {"run_full_spike", "manifest_full_spike"},
    "main_scoring": {"refresh_status", "refresh_package"},
}
EXPECTED_ARTIFACT_KEYS = {
    "environment": {"playwright_env"},
    "browser_smoke": {"playwright_smoke"},
    "manual_backfill": {"manual_backfill"},
    "health_check": {"health", "health_manifest"},
    "full_spike": {"spike", "spike_manifest"},
    "main_scoring": {"status_report", "evidence_package"},
}
EXPECTED_PREREQUISITE_PHASES = {
    "environment": "",
    "browser_smoke": "environment",
    "manual_backfill": "browser_smoke",
    "health_check": "manual_backfill",
    "full_spike": "health_check",
    "main_scoring": "full_spike",
}
EXPECTED_PLANNED_RUNS = {
    "environment": 0,
    "browser_smoke": 1,
    "manual_backfill": 120,
    "health_check": 240,
    "full_spike": 240,
    "main_scoring": 0,
}


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _string_list(value: object) -> list[str]:
    return [str(item) for item in _as_list(value)]


def _find_forbidden_payload_fields(value: object, *, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in {
                "value",
                "raw_value",
                "answer_text",
                "raw_answer",
                "citation_urls",
                "raw_citation",
                "screenshot_url",
                "html_snapshot_url",
                "raw_asset_url",
            }:
                findings.append(child_path)
            findings.extend(_find_forbidden_payload_fields(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_find_forbidden_payload_fields(child, path=f"{path}[{index}]"))
    return findings


def _phase_expected_ready(phase: dict[str, Any]) -> bool:
    artifacts = [_as_dict(artifact) for artifact in _as_list(phase.get("artifacts"))]
    return bool(artifacts) and all(artifact.get("ready") is True for artifact in artifacts)


def _phase_blocking_reasons(phase: dict[str, Any]) -> list[str]:
    phase_id = str(phase.get("id") or "")
    return [f"{phase_id}:{reason}" for reason in _string_list(phase.get("blocking_reasons"))]


def verify_au_p0b_google_phase_execution_request_packet(
    payload: Any,
    *,
    path: Path | None = None,
    require_google_phases_ready: bool = False,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "status": "fail",
            "errors": ["p0b_google_phase_execution_request_packet_not_json_object"],
            "hash_valid": False,
            "phase_execution_request_packet_ready": False,
            "google_spike_phase_handoff_ready": False,
        }

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in payload:
            errors.append(f"field_missing:{field}")
    if payload.get("p0b_google_phase_execution_request_packet_version") != PACKET_VERSION:
        errors.append("p0b_google_phase_execution_request_packet_version_invalid")

    expected_hash = payload.get("p0b_google_phase_execution_request_packet_hash")
    computed_hash = compute_p0b_google_phase_execution_request_packet_hash(payload)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("p0b_google_phase_execution_request_packet_hash_mismatch")

    verifier = _as_dict(payload.get("p0b_google_execution_checklist_verifier"))
    source = _as_dict(payload.get("source_p0b_google_execution_checklist"))
    summary = _as_dict(payload.get("summary"))
    phases = [_as_dict(phase) for phase in _as_list(payload.get("phase_requests"))]
    setup_commands = _string_list(payload.get("setup_commands"))
    phase_commands = _string_list(payload.get("phase_commands"))
    verification_commands = _string_list(payload.get("verification_commands"))
    evidence_outputs = _string_list(payload.get("evidence_outputs"))
    redaction_policy = _as_dict(payload.get("redaction_policy"))
    endpoints = _as_dict(payload.get("runtime_endpoints"))
    hard_gate_commands = _string_list(payload.get("hard_gate_commands"))

    packet_ready = verifier.get("status") == "pass" and verifier.get("hash_valid") is True
    if payload.get("phase_execution_request_packet_ready") is not packet_ready:
        errors.append("phase_execution_request_packet_ready_mismatch")
    if payload.get("status") != ("pass" if packet_ready else "fail"):
        errors.append("status_mismatch")
    if source.get("google_execution_checklist_hash") != verifier.get("google_execution_checklist_hash") and verifier.get(
        "google_execution_checklist_hash"
    ):
        errors.append("source_p0b_google_execution_checklist_hash_mismatch")

    phase_ids = [str(phase.get("id") or "") for phase in phases]
    if phase_ids != EXPECTED_PHASE_ORDER:
        errors.append("phase_request_order_invalid")
    if summary.get("source_google_spike_phase_handoff_version") != "au_p0b_google_spike_phase_handoff_v1":
        errors.append("summary_source_google_spike_phase_handoff_version_invalid")
    if _string_list(summary.get("phase_order")) != EXPECTED_PHASE_ORDER:
        errors.append("summary_phase_order_invalid")
    if summary.get("phase_count") != len(EXPECTED_PHASE_ORDER):
        errors.append("summary_phase_count_mismatch")
    if summary.get("phase_request_count") != len(phases):
        errors.append("summary_phase_request_count_mismatch")

    ready_phase_count = 0
    observed_blocking_reasons: list[str] = []
    observed_phase_commands: list[str] = []
    observed_evidence_outputs: list[str] = []
    expected_next_phase = "complete"
    previous_ready_by_id: dict[str, bool] = {"": True}
    for phase in phases:
        phase_id = str(phase.get("id") or "")
        command_ids = set(_string_list(phase.get("command_ids")))
        artifact_keys = set(_string_list(phase.get("artifact_keys")))
        prerequisite_phase_id = str(phase.get("prerequisite_phase_id") or "")
        if command_ids != EXPECTED_COMMAND_IDS.get(phase_id, set()):
            errors.append(f"phase_command_ids_mismatch:{phase_id}")
        if artifact_keys != EXPECTED_ARTIFACT_KEYS.get(phase_id, set()):
            errors.append(f"phase_artifact_keys_mismatch:{phase_id}")
        if prerequisite_phase_id != EXPECTED_PREREQUISITE_PHASES.get(phase_id):
            errors.append(f"phase_prerequisite_phase_mismatch:{phase_id}")
        expected_ready = _phase_expected_ready(phase)
        if phase_id == "main_scoring":
            expected_ready = expected_ready and payload.get("google_main_scoring_allowed") is True
        if phase.get("ready") is not expected_ready:
            errors.append(f"phase_ready_mismatch:{phase_id}")
        expected_can_start = previous_ready_by_id.get(prerequisite_phase_id, False)
        if phase.get("can_start") is not expected_can_start:
            errors.append(f"phase_can_start_mismatch:{phase_id}")
        if expected_ready:
            ready_phase_count += 1
        elif expected_next_phase == "complete":
            expected_next_phase = phase_id
        previous_ready_by_id[phase_id] = expected_ready
        planned_runs = phase.get("planned_runs")
        if planned_runs != EXPECTED_PLANNED_RUNS.get(phase_id):
            errors.append(f"phase_planned_runs_mismatch:{phase_id}")
        observed_blocking_reasons.extend(_phase_blocking_reasons(phase))
        observed_phase_commands.extend(_string_list(phase.get("commands")))
        observed_evidence_outputs.extend(_string_list(phase.get("evidence_outputs")))
        for artifact in [_as_dict(artifact) for artifact in _as_list(phase.get("artifacts"))]:
            for field in ("key", "path", "exists", "status", "ready", "errors"):
                if field not in artifact:
                    errors.append(f"phase_artifact_field_missing:{phase_id}:{artifact.get('key', '')}:{field}")

    if summary.get("ready_phase_count") != ready_phase_count:
        errors.append("summary_ready_phase_count_mismatch")
    if summary.get("blocked_phase_count") != len(EXPECTED_PHASE_ORDER) - ready_phase_count:
        errors.append("summary_blocked_phase_count_mismatch")
    if summary.get("google_spike_phase_handoff_ready") is not (ready_phase_count == len(EXPECTED_PHASE_ORDER)):
        errors.append("summary_google_spike_phase_handoff_ready_mismatch")
    if payload.get("google_spike_phase_handoff_ready") is not (ready_phase_count == len(EXPECTED_PHASE_ORDER)):
        errors.append("google_spike_phase_handoff_ready_mismatch")
    if summary.get("next_phase") != expected_next_phase:
        errors.append("summary_next_phase_mismatch")
    if summary.get("full_spike_planned_runs") != EXPECTED_PLANNED_RUNS["full_spike"]:
        errors.append("summary_full_spike_planned_runs_mismatch")
    if summary.get("manual_expected_record_count") != EXPECTED_PLANNED_RUNS["manual_backfill"]:
        errors.append("summary_manual_expected_record_count_mismatch")
    if summary.get("command_count") != len(phase_commands):
        errors.append("summary_command_count_mismatch")
    if phase_commands != observed_phase_commands:
        errors.append("phase_commands_mismatch")
    if summary.get("setup_command_count") != len(setup_commands):
        errors.append("summary_setup_command_count_mismatch")
    if summary.get("verification_command_count") != len(verification_commands):
        errors.append("summary_verification_command_count_mismatch")
    if summary.get("evidence_output_count") != len(evidence_outputs):
        errors.append("summary_evidence_output_count_mismatch")
    if sorted(evidence_outputs) != sorted(dict.fromkeys(observed_evidence_outputs)):
        errors.append("evidence_outputs_mismatch")
    deduped_blocking_reasons = sorted(dict.fromkeys(observed_blocking_reasons))
    if summary.get("blocking_reason_count") != len(deduped_blocking_reasons):
        errors.append("summary_blocking_reason_count_mismatch")
    if _string_list(summary.get("blocking_reasons")) != deduped_blocking_reasons:
        errors.append("summary_blocking_reasons_mismatch")
    if phase_commands and summary.get("next_command") != phase_commands[0]:
        errors.append("summary_next_command_mismatch")
    if verification_commands and summary.get("post_update_verification_command") != verification_commands[0]:
        errors.append("summary_post_update_verification_command_mismatch")

    for command in (
        "make au-p0b-google-environment-request",
        "make verify-au-p0b-google-environment-request",
        "make au-p0b-google-manual-backfill-request",
        "make verify-au-p0b-google-manual-backfill-request",
        "make au-p0b-google-runbook-dry-run",
        "make verify-au-p0b-google-runbook-execution",
    ):
        if command not in setup_commands:
            errors.append(f"setup_command_missing:{command}")
    for command in (
        "make au-p0b-google-playwright-env",
        "make verify-au-p0b-google-playwright-env",
        "make au-p0b-google-playwright-smoke",
        "make verify-au-p0b-google-playwright-smoke",
        "make verify-au-p0b-google-manual-backfill",
        "make au-p0b-google-spike-health",
        "make au-p0b-google-spike",
        "make au-p0b-google-status",
        "make verify-au-p0b-google-status",
        "make au-p0b-google-package",
        "make verify-au-p0b-google-package",
        "make au-p0b-google-execution-checklist",
        "make verify-au-p0b-google-execution-checklist",
    ):
        if command not in verification_commands:
            errors.append(f"verification_command_missing:{command}")
    if not any("verify_au_p0b_google_playwright_smoke.py" in command for command in phase_commands):
        errors.append("phase_command_missing:verify_smoke_strict")
    if not any(command == "make verify-au-p0b-google-manual-backfill" for command in phase_commands):
        errors.append("phase_command_missing:verify_manual_backfill")
    if not any(command == "make au-p0b-google-spike" for command in phase_commands):
        errors.append("phase_command_missing:run_full_spike")
    if not any(command == "make au-p0b-google-package && make verify-au-p0b-google-package" for command in phase_commands):
        errors.append("phase_command_missing:refresh_package")

    if redaction_policy.get("raw_secret_values_allowed") is not False:
        errors.append("redaction_policy_raw_secret_invalid")
    if redaction_policy.get("raw_answer_values_allowed") is not False:
        errors.append("redaction_policy_raw_answer_invalid")
    if redaction_policy.get("raw_citation_values_allowed") is not False:
        errors.append("redaction_policy_raw_citation_invalid")
    if redaction_policy.get("raw_asset_urls_allowed") is not False:
        errors.append("redaction_policy_raw_asset_invalid")
    if redaction_policy.get("phase_entries_reference_command_ids_and_artifact_paths_only") is not True:
        errors.append("redaction_policy_phase_reference_invalid")
    if summary.get("raw_secret_values_allowed") is not False:
        errors.append("summary_raw_secret_policy_invalid")
    if summary.get("raw_answer_values_allowed") is not False:
        errors.append("summary_raw_answer_policy_invalid")
    if summary.get("raw_citation_values_allowed") is not False:
        errors.append("summary_raw_citation_policy_invalid")
    if summary.get("raw_asset_urls_allowed") is not False:
        errors.append("summary_raw_asset_policy_invalid")
    if summary.get("phase_entries_reference_command_ids_and_artifact_paths_only") is not True:
        errors.append("summary_phase_reference_policy_invalid")
    for finding in _find_forbidden_payload_fields(payload):
        errors.append(f"forbidden_payload_field:{finding}")

    if endpoints.get("p0b_google_phase_execution_request") != "GET /v1/p0b-google-phase-execution-request/au":
        errors.append("runtime_endpoint_p0b_google_phase_execution_request_invalid")
    if endpoints.get("p0b_google_execution_checklist") != "GET /v1/p0b-google-execution-checklist/au":
        errors.append("runtime_endpoint_p0b_google_execution_checklist_invalid")
    if endpoints.get("p0b_google_environment_request") != "GET /v1/p0b-google-environment-request/au":
        errors.append("runtime_endpoint_p0b_google_environment_request_invalid")
    if endpoints.get("p0b_google_manual_backfill_request") != "GET /v1/p0b-google-manual-backfill-request/au":
        errors.append("runtime_endpoint_p0b_google_manual_backfill_request_invalid")
    if endpoints.get("external_dependency_handoff") != "GET /v1/external-dependency-handoff/au":
        errors.append("runtime_endpoint_external_dependency_handoff_invalid")
    for required in (
        "make au-p0b-google-phase-execution-request",
        "make verify-au-p0b-google-phase-execution-request",
        "make au-p0b-google-playwright-smoke",
        "make verify-au-p0b-google-playwright-smoke",
        "make verify-au-p0b-google-manual-backfill",
        "make au-p0b-google-spike",
        "make verify-au-p0b-google-package",
    ):
        if required not in hard_gate_commands:
            errors.append(f"hard_gate_missing:{required}")
    if not any(command.endswith("--require-google-phases-ready") for command in hard_gate_commands):
        errors.append("hard_gate_missing:require_google_phases_ready")
    if not any(command.endswith("--require-google-main-scoring-ready") for command in hard_gate_commands):
        errors.append("hard_gate_missing:require_google_main_scoring_ready")
    if require_google_phases_ready and payload.get("google_spike_phase_handoff_ready") is not True:
        errors.append("p0b_google_phases_not_ready")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "p0b_google_phase_execution_request_packet_version": payload.get(
            "p0b_google_phase_execution_request_packet_version",
            "",
        ),
        "p0b_google_phase_execution_request_packet_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_p0b_google_phase_execution_request_packet_hash": computed_hash,
        "hash_valid": hash_valid,
        "phase_execution_request_packet_ready": packet_ready,
        "google_spike_phase_handoff_ready": payload.get("google_spike_phase_handoff_ready") is True,
        "google_main_scoring_allowed": payload.get("google_main_scoring_allowed") is True,
        "next_phase": summary.get("next_phase", ""),
        "full_spike_planned_runs": summary.get("full_spike_planned_runs", 0),
        "manual_expected_record_count": summary.get("manual_expected_record_count", 0),
        "blocking_reason_count": len(deduped_blocking_reasons),
        "next_command": summary.get("next_command", ""),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU P0b Google phase execution request packet JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_PHASE_EXECUTION_REQUEST_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU P0b Google phase execution request packet JSON.",
    )
    parser.add_argument(
        "--require-google-phases-ready",
        action="store_true",
        help="Fail unless Google environment, smoke, manual, health, full spike and main scoring phases are ready.",
    )
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
            "errors": ["p0b_google_phase_execution_request_packet_file_missing"],
            "hash_valid": False,
            "phase_execution_request_packet_ready": False,
            "google_spike_phase_handoff_ready": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"p0b_google_phase_execution_request_packet_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "phase_execution_request_packet_ready": False,
            "google_spike_phase_handoff_ready": False,
        }
    else:
        result = verify_au_p0b_google_phase_execution_request_packet(
            payload,
            path=path,
            require_google_phases_ready=args.require_google_phases_ready,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
