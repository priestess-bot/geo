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

from scripts.build_au_p0a_real_batch_request_packet import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    PACKET_VERSION,
    compute_p0a_real_batch_request_packet_hash,
)


REQUIRED_FIELDS = (
    "p0a_real_batch_request_packet_version",
    "generated_at",
    "status",
    "real_batch_request_packet_ready",
    "real_batch_phase_handoff_ready",
    "ready_for_design_partner",
    "output_path",
    "source_p0a_execution_checklist",
    "p0a_execution_checklist_verifier",
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
    "p0a_real_batch_request_packet_hash",
)

EXPECTED_PHASE_ORDER = ["preflight", "small_batch", "full_batch"]
EXPECTED_COMMAND_IDS = {
    "preflight": {
        "preflight_collect",
        "preflight_verify_audit",
        "preflight_manifest_audit",
        "preflight_design_partner_gate",
    },
    "small_batch": {"small_batch_collect", "small_batch_manifest_gate"},
    "full_batch": {"full_batch_collect", "full_batch_manifest_gate"},
}
EXPECTED_ARTIFACT_KEYS = {
    "preflight": {"preflight_json", "preflight_manifest"},
    "small_batch": {"small_batch_json", "small_batch_manifest"},
    "full_batch": {"full_batch_json", "full_batch_manifest"},
}
EXPECTED_GATE_IDS = {
    "preflight": {"hard_environment_gate", "hard_runbook_execution_gate"},
    "small_batch": {"hard_preflight_gate"},
    "full_batch": {"hard_package_gate", "hard_status_gate"},
}
EXPECTED_PLANNED_RUNS = {"preflight": 6, "small_batch": 30, "full_batch": 2400}


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _string_list(value: object) -> list[str]:
    return [str(item) for item in _as_list(value)]


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


def _phase_expected_ready(phase: dict[str, Any]) -> bool:
    artifacts = [_as_dict(artifact) for artifact in _as_list(phase.get("artifacts"))]
    return bool(artifacts) and all(artifact.get("ready") is True for artifact in artifacts)


def _phase_blocking_reasons(phase: dict[str, Any]) -> list[str]:
    phase_id = str(phase.get("id") or "")
    return [f"{phase_id}:{reason}" for reason in _string_list(phase.get("blocking_reasons"))]


def verify_au_p0a_real_batch_request_packet(
    payload: Any,
    *,
    path: Path | None = None,
    require_real_batches_ready: bool = False,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "status": "fail",
            "errors": ["p0a_real_batch_request_packet_not_json_object"],
            "hash_valid": False,
            "real_batch_request_packet_ready": False,
            "real_batch_phase_handoff_ready": False,
        }

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in payload:
            errors.append(f"field_missing:{field}")
    if payload.get("p0a_real_batch_request_packet_version") != PACKET_VERSION:
        errors.append("p0a_real_batch_request_packet_version_invalid")

    expected_hash = payload.get("p0a_real_batch_request_packet_hash")
    computed_hash = compute_p0a_real_batch_request_packet_hash(payload)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("p0a_real_batch_request_packet_hash_mismatch")

    verifier = _as_dict(payload.get("p0a_execution_checklist_verifier"))
    source = _as_dict(payload.get("source_p0a_execution_checklist"))
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
    if payload.get("real_batch_request_packet_ready") is not packet_ready:
        errors.append("real_batch_request_packet_ready_mismatch")
    if payload.get("status") != ("pass" if packet_ready else "fail"):
        errors.append("status_mismatch")
    if source.get("p0a_execution_checklist_hash") != verifier.get("p0a_execution_checklist_hash") and verifier.get(
        "p0a_execution_checklist_hash"
    ):
        errors.append("source_p0a_execution_checklist_hash_mismatch")

    phase_ids = [str(phase.get("id") or "") for phase in phases]
    if phase_ids != EXPECTED_PHASE_ORDER:
        errors.append("phase_request_order_invalid")
    if summary.get("source_real_batch_phase_handoff_version") != "au_p0a_real_batch_phase_handoff_v1":
        errors.append("summary_source_real_batch_phase_handoff_version_invalid")
    if _string_list(summary.get("phase_order")) != EXPECTED_PHASE_ORDER:
        errors.append("summary_phase_order_invalid")
    if summary.get("phase_count") != len(EXPECTED_PHASE_ORDER):
        errors.append("summary_phase_count_mismatch")
    if summary.get("phase_request_count") != len(phases):
        errors.append("summary_phase_request_count_mismatch")

    ready_phase_count = 0
    total_planned_runs = 0
    observed_blocking_reasons: list[str] = []
    observed_phase_commands: list[str] = []
    observed_evidence_outputs: list[str] = []
    expected_next_phase = "complete"
    previous_ready = False
    for index, phase in enumerate(phases):
        phase_id = str(phase.get("id") or "")
        command_ids = set(_string_list(phase.get("command_ids")))
        artifact_keys = set(_string_list(phase.get("artifact_keys")))
        gate_ids = set(_string_list(phase.get("prerequisite_gate_ids")))
        artifacts = [_as_dict(artifact) for artifact in _as_list(phase.get("artifacts"))]
        if command_ids != EXPECTED_COMMAND_IDS.get(phase_id, set()):
            errors.append(f"phase_command_ids_mismatch:{phase_id}")
        if artifact_keys != EXPECTED_ARTIFACT_KEYS.get(phase_id, set()):
            errors.append(f"phase_artifact_keys_mismatch:{phase_id}")
        if gate_ids != EXPECTED_GATE_IDS.get(phase_id, set()):
            errors.append(f"phase_gate_ids_mismatch:{phase_id}")
        expected_ready = _phase_expected_ready(phase)
        if phase.get("ready") is not expected_ready:
            errors.append(f"phase_ready_mismatch:{phase_id}")
        expected_can_start = previous_ready if index > 0 else (phase.get("can_start") is True)
        if index == 0:
            expected_can_start = phase.get("can_start") is True
        if index > 0 and phase.get("can_start") is not expected_can_start:
            errors.append(f"phase_can_start_mismatch:{phase_id}")
        if expected_ready:
            ready_phase_count += 1
        elif expected_next_phase == "complete":
            expected_next_phase = phase_id
        previous_ready = expected_ready
        planned_runs = phase.get("planned_runs")
        if planned_runs != EXPECTED_PLANNED_RUNS.get(phase_id):
            errors.append(f"phase_planned_runs_mismatch:{phase_id}")
        total_planned_runs += int(planned_runs or 0)
        observed_blocking_reasons.extend(_phase_blocking_reasons(phase))
        observed_phase_commands.extend(_string_list(phase.get("commands")))
        observed_evidence_outputs.extend(_string_list(phase.get("evidence_outputs")))
        for artifact in artifacts:
            for field in ("key", "path", "exists", "status", "ready_for_design_partner", "ready", "errors"):
                if field not in artifact:
                    errors.append(f"phase_artifact_field_missing:{phase_id}:{artifact.get('key', '')}:{field}")

    if summary.get("ready_phase_count") != ready_phase_count:
        errors.append("summary_ready_phase_count_mismatch")
    if summary.get("blocked_phase_count") != len(EXPECTED_PHASE_ORDER) - ready_phase_count:
        errors.append("summary_blocked_phase_count_mismatch")
    if summary.get("real_batch_phase_handoff_ready") is not (ready_phase_count == len(EXPECTED_PHASE_ORDER)):
        errors.append("summary_real_batch_phase_handoff_ready_mismatch")
    if payload.get("real_batch_phase_handoff_ready") is not (ready_phase_count == len(EXPECTED_PHASE_ORDER)):
        errors.append("real_batch_phase_handoff_ready_mismatch")
    if summary.get("next_phase") != expected_next_phase:
        errors.append("summary_next_phase_mismatch")
    if summary.get("total_planned_runs") != total_planned_runs:
        errors.append("summary_total_planned_runs_mismatch")
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
        "make au-p0a-credential-request",
        "make verify-au-p0a-credential-request",
        "make au-p0a-env",
        "make verify-au-p0a-env",
        "make au-p0a-runbook-dry-run",
        "make verify-au-p0a-runbook-execution",
    ):
        if command not in setup_commands:
            errors.append(f"setup_command_missing:{command}")
    for command in (
        "make api-preflight",
        "make verify-api-preflight",
        "make preflight-manifest",
        "make au-p0a-status",
        "make verify-au-p0a-status",
        "make au-p0a-execution-checklist",
        "make verify-au-p0a-execution-checklist",
    ):
        if command not in verification_commands:
            errors.append(f"verification_command_missing:{command}")
    if not any("run_collection_slice.py --mode api --prompt-limit 5" in command for command in phase_commands):
        errors.append("phase_command_missing:small_batch_collect")
    if not any("run_collection_slice.py --mode api --prompt-limit 100" in command for command in phase_commands):
        errors.append("phase_command_missing:full_batch_collect")
    expected_artifact_output_count = sum(len(EXPECTED_ARTIFACT_KEYS[phase_id]) for phase_id in EXPECTED_PHASE_ORDER)
    if len(evidence_outputs) != expected_artifact_output_count:
        errors.append("evidence_output_count_invalid")

    if redaction_policy.get("raw_secret_values_allowed") is not False:
        errors.append("redaction_policy_raw_secret_invalid")
    if redaction_policy.get("phase_entries_reference_command_ids_and_artifact_paths_only") is not True:
        errors.append("redaction_policy_phase_reference_invalid")
    if summary.get("raw_secret_values_allowed") is not False:
        errors.append("summary_raw_secret_policy_invalid")
    if summary.get("phase_entries_reference_command_ids_and_artifact_paths_only") is not True:
        errors.append("summary_phase_reference_policy_invalid")
    for finding in _find_forbidden_secret_fields(payload):
        errors.append(f"forbidden_secret_field:{finding}")

    if endpoints.get("p0a_real_batch_request") != "GET /v1/p0a-real-batch-request/au":
        errors.append("runtime_endpoint_p0a_real_batch_request_invalid")
    if endpoints.get("p0a_credential_request") != "GET /v1/p0a-credential-request/au":
        errors.append("runtime_endpoint_p0a_credential_request_invalid")
    if endpoints.get("p0a_execution_checklist") != "GET /v1/p0a-execution-checklist/au":
        errors.append("runtime_endpoint_p0a_execution_checklist_invalid")
    if endpoints.get("external_dependency_handoff") != "GET /v1/external-dependency-handoff/au":
        errors.append("runtime_endpoint_external_dependency_handoff_invalid")
    for required in (
        "make au-p0a-real-batch-request",
        "make verify-au-p0a-real-batch-request",
        "make api-preflight",
        "make verify-api-preflight",
    ):
        if required not in hard_gate_commands:
            errors.append(f"hard_gate_missing:{required}")
    if not any(command.endswith("--require-real-batches-ready") for command in hard_gate_commands):
        errors.append("hard_gate_missing:require_real_batches_ready")
    if not any(command.endswith("--require-design-partner-ready") for command in hard_gate_commands):
        errors.append("hard_gate_missing:require_design_partner_ready")
    if require_real_batches_ready and payload.get("real_batch_phase_handoff_ready") is not True:
        errors.append("p0a_real_batches_not_ready")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "p0a_real_batch_request_packet_version": payload.get("p0a_real_batch_request_packet_version", ""),
        "p0a_real_batch_request_packet_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_p0a_real_batch_request_packet_hash": computed_hash,
        "hash_valid": hash_valid,
        "real_batch_request_packet_ready": packet_ready,
        "real_batch_phase_handoff_ready": payload.get("real_batch_phase_handoff_ready") is True,
        "next_phase": summary.get("next_phase", ""),
        "total_planned_runs": total_planned_runs,
        "blocking_reason_count": len(deduped_blocking_reasons),
        "next_command": summary.get("next_command", ""),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU P0a real batch request packet JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GEO_AU_P0A_REAL_BATCH_REQUEST_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU P0a real batch request packet JSON.",
    )
    parser.add_argument(
        "--require-real-batches-ready",
        action="store_true",
        help="Fail unless P0a preflight, small batch, and full batch artifacts are ready.",
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
            "errors": ["p0a_real_batch_request_packet_file_missing"],
            "hash_valid": False,
            "real_batch_request_packet_ready": False,
            "real_batch_phase_handoff_ready": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"p0a_real_batch_request_packet_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "real_batch_request_packet_ready": False,
            "real_batch_phase_handoff_ready": False,
        }
    else:
        result = verify_au_p0a_real_batch_request_packet(
            payload,
            path=path,
            require_real_batches_ready=args.require_real_batches_ready,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
