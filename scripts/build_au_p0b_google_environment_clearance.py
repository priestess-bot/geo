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

from scripts.build_au_p0b_google_environment_fulfillment import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_ENVIRONMENT_FULFILLMENT_PATH,
    build_au_p0b_google_environment_fulfillment,
)
from scripts.build_au_p0b_google_environment_request_packet import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_ENVIRONMENT_REQUEST_PATH,
    build_au_p0b_google_environment_request_packet,
)
from scripts.build_au_p0b_google_playwright_env_report import (  # noqa: E402
    DEFAULT_ENV_FILE as DEFAULT_PLAYWRIGHT_ENV_FILE,
    DEFAULT_OUTPUT_PATH as DEFAULT_PLAYWRIGHT_ENV_REPORT_PATH,
    build_google_playwright_env_report,
)
from scripts.run_au_external_dependency_clearance import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_EXTERNAL_DEPENDENCY_CLEARANCE_PATH,
    run_au_external_dependency_clearance,
)
from scripts.verify_au_p0b_google_environment_fulfillment import (  # noqa: E402
    verify_au_p0b_google_environment_fulfillment,
)
from scripts.verify_au_p0b_google_environment_request_packet import (  # noqa: E402
    verify_au_p0b_google_environment_request_packet,
)
from scripts.verify_au_p0b_google_playwright_env_report import verify_google_playwright_env_report  # noqa: E402


CLEARANCE_VERSION = "au_p0b_google_environment_clearance_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0b-google-environment-clearance-latest.json"
STEP_ID = "p0b_google_environment"
PREREQUISITE_STEP_ID = "p0a_real_batches"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_p0b_google_environment_clearance_hash(payload: dict[str, Any]) -> str:
    payload_for_hash = dict(payload)
    payload_for_hash.pop("p0b_google_environment_clearance_hash", None)
    return hashlib.sha256(_stable_bytes(payload_for_hash)).hexdigest()


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _strings(value: object) -> list[str]:
    items: list[str] = []
    for item in _as_list(value):
        if isinstance(item, dict):
            text = str(item.get("shell") or item.get("command") or item.get("id") or "").strip()
        else:
            text = str(item).strip()
        if text:
            items.append(text)
    return items


def _unique_strings(values: list[str]) -> list[str]:
    observed: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in observed:
            observed.add(value)
            result.append(value)
    return result


def _load_json(path: Path) -> tuple[dict[str, Any] | None, dict[str, Any]]:
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
    if not isinstance(payload, dict):
        return None, {"path": str(path), "exists": True, "source": "invalid_file", "errors": ["not_json_object"]}
    return payload, {"path": str(path), "exists": True, "source": "existing_file", "errors": []}


def _load_or_build_environment_request(
    path: Path,
    *,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if payload is not None:
        return payload, source
    request = build_au_p0b_google_environment_request_packet(output_path=path, generated_at=generated_at)
    return request, {**source, "source": "generated_in_memory"}


def _load_or_build_playwright_env_report(
    path: Path,
    *,
    env_file_path: Path | None,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if payload is not None:
        return payload, source
    report = build_google_playwright_env_report(
        env_file_path=env_file_path,
        output_path=path,
        generated_at=generated_at,
    )
    return report, {**source, "source": "generated_in_memory"}


def _load_or_build_fulfillment(
    path: Path,
    *,
    environment_request_path: Path,
    environment_request: dict[str, Any],
    playwright_env_report_path: Path,
    playwright_env_report: dict[str, Any],
    playwright_env_file_path: Path | None,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if payload is not None:
        return payload, source
    fulfillment = build_au_p0b_google_environment_fulfillment(
        environment_request_path=environment_request_path,
        playwright_env_report_path=playwright_env_report_path,
        playwright_env_file_path=playwright_env_file_path,
        environment_request=environment_request,
        playwright_env_report=playwright_env_report,
        output_path=path,
        generated_at=generated_at,
    )
    return fulfillment, {**source, "source": "generated_in_memory"}


def _load_or_build_external_clearance(
    path: Path,
    *,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if payload is not None:
        return payload, source
    clearance = run_au_external_dependency_clearance(output_path=path, generated_at=generated_at)
    return clearance, {**source, "source": "generated_in_memory"}


def _step_by_id(external_clearance: dict[str, Any], step_id: str) -> dict[str, Any]:
    for step in _as_list(external_clearance.get("steps")):
        step_dict = _as_dict(step)
        if step_dict.get("id") == step_id:
            return step_dict
    return {}


def _environment_items(environment_fulfillment: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for value in _as_list(environment_fulfillment.get("environment_fulfillment_items")):
        item = _as_dict(value)
        key = str(item.get("key") or "")
        items.append(
            {
                "key": key,
                "item_type": str(item.get("item_type") or ""),
                "name": str(item.get("name") or key),
                "required": item.get("required") is True,
                "fulfilled": item.get("fulfilled") is True,
                "requested_present": item.get("requested_present") is True,
                "environment_present": item.get("environment_present") is True,
                "presence_mismatch": item.get("presence_mismatch") is True,
                "request_source": str(item.get("request_source") or "missing"),
                "environment_source": str(item.get("environment_source") or "missing"),
                "owner_hint": str(item.get("owner_hint") or "runtime_operator"),
                "env_file_key": str(item.get("env_file_key") or item.get("name") or key),
                "expected_type": str(item.get("expected_type") or ""),
                "truthy": item.get("truthy") if isinstance(item.get("truthy"), bool) else None,
                "value_length": int(item.get("value_length") or 0),
                "sha256_prefix": str(item.get("sha256_prefix") or ""),
                "secret_redacted": item.get("secret_redacted") is True,
                "accepted_injection_methods": _strings(item.get("accepted_injection_methods")),
                "post_update_checks": _strings(item.get("post_update_checks")),
                "blocking_reasons": _strings(item.get("blocking_reasons")),
            }
        )
    return items


def _owner_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        owner = str(item.get("owner_hint") or "unknown")
        counts[owner] = counts.get(owner, 0) + 1
    return dict(sorted(counts.items()))


def _missing_by_owner(items: list[dict[str, Any]]) -> dict[str, list[str]]:
    owners: dict[str, list[str]] = {}
    for item in items:
        if item.get("required") is True and item.get("fulfilled") is not True:
            owner = str(item.get("owner_hint") or "unknown")
            owners.setdefault(owner, []).append(str(item.get("key") or ""))
    return {owner: sorted(keys) for owner, keys in sorted(owners.items())}


def _operator_steps(
    *,
    environment_fulfillment: dict[str, Any],
    external_clearance: dict[str, Any],
    blocked_by_prerequisite: bool,
) -> list[dict[str, Any]]:
    summary = _as_dict(environment_fulfillment.get("summary"))
    steps: list[dict[str, Any]] = [
        {
            "order": 1,
            "id": "clear_p0a_real_batches",
            "command": "make au-p0a-real-batch-clearance && make verify-au-p0a-real-batch-clearance",
            "purpose": "clear_prerequisite_p0a_real_batches_before_google_environment",
            "external_call_risk": "provider_api_calls",
            "required_before_google_environment": True,
            "blocked": blocked_by_prerequisite,
        },
        {
            "order": 2,
            "id": "refresh_environment_request",
            "command": "make au-p0b-google-environment-request",
            "purpose": "refresh_google_environment_request_packet",
            "external_call_risk": "none",
        },
        {
            "order": 3,
            "id": "refresh_playwright_env_report",
            "command": "make au-p0b-google-playwright-env",
            "purpose": "refresh_redacted_google_playwright_environment_report",
            "external_call_risk": "none",
        },
        {
            "order": 4,
            "id": "refresh_environment_fulfillment",
            "command": "make au-p0b-google-environment-fulfillment",
            "purpose": "align_environment_request_with_current_playwright_env_report",
            "external_call_risk": "none",
        },
        {
            "order": 5,
            "id": "apply_current_environment_fix",
            "command": str(summary.get("next_command") or "make au-p0b-google-playwright-env"),
            "purpose": "apply_or_verify_current_unfulfilled_google_environment_input",
            "external_call_risk": "none",
            "next_action": str(summary.get("next_action") or ""),
        },
        {
            "order": 6,
            "id": "verify_environment_fulfillment",
            "command": "make verify-au-p0b-google-environment-fulfillment",
            "purpose": "prove_google_environment_inputs_are_fulfilled_or_still_blocked",
            "external_call_risk": "none",
        },
        {
            "order": 7,
            "id": "run_strict_gate",
            "command": str(summary.get("strict_gate_command") or ""),
            "purpose": "require_all_p0b_google_environment_inputs_fulfilled",
            "external_call_risk": "none",
        },
        {
            "order": 8,
            "id": "continue_clearance_sequence",
            "command": "then follow p0b_google_environment recommended_sequence from external dependency clearance",
            "purpose": "continue_to_p0b_google_manual_backfill_after_environment_clear",
            "external_call_risk": "depends_on_next_sequence_step",
        },
    ]
    if _strings(external_clearance.get("current_recommended_sequence")):
        steps[0]["current_global_clearance_sequence"] = _strings(external_clearance.get("current_recommended_sequence"))
    return steps


def _post_update_validation_sequence(
    *,
    environment_request: dict[str, Any],
    environment_fulfillment: dict[str, Any],
    environment_step: dict[str, Any],
) -> list[str]:
    summary = _as_dict(environment_fulfillment.get("summary"))
    commands = [
        "make au-p0a-real-batch-clearance",
        "make verify-au-p0a-real-batch-clearance",
        "make au-p0b-google-environment-request",
        "make verify-au-p0b-google-environment-request",
        "make au-p0b-google-playwright-env",
        "make verify-au-p0b-google-playwright-env",
        "make au-p0b-google-environment-fulfillment",
        "make verify-au-p0b-google-environment-fulfillment",
        str(summary.get("strict_gate_command") or ""),
        str(summary.get("ready_smoke_strict_gate_command") or ""),
    ]
    commands.extend(_strings(environment_request.get("setup_commands")))
    commands.extend(_strings(environment_request.get("verification_commands")))
    commands.extend(_strings(environment_fulfillment.get("verification_commands")))
    commands.extend(_strings(environment_fulfillment.get("hard_gate_commands")))
    commands.extend(_strings(environment_step.get("recommended_sequence")))
    return _unique_strings(commands)


def build_au_p0b_google_environment_clearance(
    *,
    environment_request_path: Path = Path(DEFAULT_ENVIRONMENT_REQUEST_PATH),
    playwright_env_report_path: Path = Path(DEFAULT_PLAYWRIGHT_ENV_REPORT_PATH),
    environment_fulfillment_path: Path = Path(DEFAULT_ENVIRONMENT_FULFILLMENT_PATH),
    external_dependency_clearance_path: Path = Path(DEFAULT_EXTERNAL_DEPENDENCY_CLEARANCE_PATH),
    playwright_env_file_path: Path | None = Path(DEFAULT_PLAYWRIGHT_ENV_FILE),
    environment_request: dict[str, Any] | None = None,
    playwright_env_report: dict[str, Any] | None = None,
    environment_fulfillment: dict[str, Any] | None = None,
    external_dependency_clearance: dict[str, Any] | None = None,
    output_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if environment_request is None:
        environment_request, request_source = _load_or_build_environment_request(
            environment_request_path,
            generated_at=generated_at,
        )
    else:
        request_source = {
            "path": str(environment_request_path),
            "exists": True,
            "source": "provided_payload",
            "errors": [],
        }

    if playwright_env_report is None:
        playwright_env_report, env_source = _load_or_build_playwright_env_report(
            playwright_env_report_path,
            env_file_path=playwright_env_file_path,
            generated_at=generated_at,
        )
    else:
        env_source = {
            "path": str(playwright_env_report_path),
            "exists": True,
            "source": "provided_payload",
            "errors": [],
        }

    if environment_fulfillment is None:
        environment_fulfillment, fulfillment_source = _load_or_build_fulfillment(
            environment_fulfillment_path,
            environment_request_path=environment_request_path,
            environment_request=environment_request,
            playwright_env_report_path=playwright_env_report_path,
            playwright_env_report=playwright_env_report,
            playwright_env_file_path=playwright_env_file_path,
            generated_at=generated_at,
        )
    else:
        fulfillment_source = {
            "path": str(environment_fulfillment_path),
            "exists": True,
            "source": "provided_payload",
            "errors": [],
        }

    if external_dependency_clearance is None:
        external_dependency_clearance, clearance_source = _load_or_build_external_clearance(
            external_dependency_clearance_path,
            generated_at=generated_at,
        )
    else:
        clearance_source = {
            "path": str(external_dependency_clearance_path),
            "exists": True,
            "source": "provided_payload",
            "errors": [],
        }

    request_verifier = verify_au_p0b_google_environment_request_packet(
        environment_request,
        path=environment_request_path,
    )
    env_verifier = verify_google_playwright_env_report(playwright_env_report, path=playwright_env_report_path)
    fulfillment_verifier = verify_au_p0b_google_environment_fulfillment(
        environment_fulfillment,
        path=environment_fulfillment_path,
    )
    request_ok = request_verifier.get("status") == "pass" and request_verifier.get("hash_valid") is True
    env_ok = env_verifier.get("status") == "pass" and env_verifier.get("hash_valid") is True
    fulfillment_ok = fulfillment_verifier.get("status") == "pass" and fulfillment_verifier.get("hash_valid") is True
    clearance_ok = external_dependency_clearance.get("status") == "pass"
    packet_ready = request_ok and env_ok and fulfillment_ok and clearance_ok

    environment_step = _step_by_id(external_dependency_clearance, STEP_ID)
    prerequisite_step = _step_by_id(external_dependency_clearance, PREREQUISITE_STEP_ID)
    items = _environment_items(environment_fulfillment)
    required_items = [item for item in items if item.get("required") is True]
    fulfilled_required = [item for item in required_items if item.get("fulfilled") is True]
    missing_required = sorted(str(item.get("key") or "") for item in required_items if item.get("fulfilled") is not True)
    presence_mismatches = sorted(str(item.get("key") or "") for item in items if item.get("presence_mismatch") is True)
    environment_fulfilled = (
        bool(required_items) and len(fulfilled_required) == len(required_items) and not presence_mismatches
    )
    blocked_by_prerequisite = prerequisite_step.get("ready") is not True
    clearance_step_ready = environment_step.get("ready") is True
    clearance_step_can_start = environment_step.get("can_start") is True
    ready_for_next_clearance_step = environment_fulfilled and not blocked_by_prerequisite
    environment_clearance_ready = environment_fulfilled and clearance_step_ready and not blocked_by_prerequisite
    operator_steps = _operator_steps(
        environment_fulfillment=environment_fulfillment,
        external_clearance=external_dependency_clearance,
        blocked_by_prerequisite=blocked_by_prerequisite,
    )
    validation_sequence = _post_update_validation_sequence(
        environment_request=environment_request,
        environment_fulfillment=environment_fulfillment,
        environment_step=environment_step,
    )
    fulfillment_summary = _as_dict(environment_fulfillment.get("summary"))
    payload: dict[str, Any] = {
        "p0b_google_environment_clearance_version": CLEARANCE_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if packet_ready else "fail",
        "environment_clearance_packet_ready": packet_ready,
        "environment_fulfilled": environment_fulfilled,
        "environment_clearance_ready": environment_clearance_ready,
        "ready_for_next_clearance_step": ready_for_next_clearance_step,
        "blocked_by_prerequisite_step": blocked_by_prerequisite,
        "output_path": str(output_path) if output_path else "",
        "clearance_step": {
            "id": STEP_ID,
            "current_global_step_id": str(external_dependency_clearance.get("current_step_id") or ""),
            "current_global_step_is_prerequisite": external_dependency_clearance.get("current_step_id")
            == PREREQUISITE_STEP_ID,
            "step_recorded": bool(environment_step),
            "step_ready": clearance_step_ready,
            "step_can_start": clearance_step_can_start,
            "step_status": str(environment_step.get("status") or ""),
            "blocked_by": _strings(environment_step.get("blocked_by")),
            "would_execute": environment_step.get("would_execute") is True,
            "strict_gate_command": str(
                environment_step.get("strict_gate_command") or fulfillment_summary.get("strict_gate_command") or ""
            ),
        },
        "prerequisite_step": {
            "id": PREREQUISITE_STEP_ID,
            "ready": prerequisite_step.get("ready") is True,
            "status": str(prerequisite_step.get("status") or ""),
            "would_execute": prerequisite_step.get("would_execute") is True,
            "strict_gate_command": str(prerequisite_step.get("strict_gate_command") or ""),
            "blocked_by": _strings(prerequisite_step.get("blocked_by")),
            "runtime_endpoint": str(
                _as_dict(prerequisite_step.get("linked_request_context")).get("runtime_endpoint") or ""
            ),
        },
        "source_artifacts": {
            "environment_request": {
                "path": str(environment_request_path),
                "source": request_source,
                "hash_field": "p0b_google_environment_request_packet_hash",
                "hash": str(environment_request.get("p0b_google_environment_request_packet_hash") or ""),
                "verifier_status": request_verifier.get("status", ""),
                "hash_valid": request_verifier.get("hash_valid") is True,
            },
            "playwright_env_report": {
                "path": str(playwright_env_report_path),
                "source": env_source,
                "hash_field": "environment_report_hash",
                "hash": str(playwright_env_report.get("environment_report_hash") or ""),
                "verifier_status": env_verifier.get("status", ""),
                "hash_valid": env_verifier.get("hash_valid") is True,
            },
            "environment_fulfillment": {
                "path": str(environment_fulfillment_path),
                "source": fulfillment_source,
                "hash_field": "p0b_google_environment_fulfillment_hash",
                "hash": str(environment_fulfillment.get("p0b_google_environment_fulfillment_hash") or ""),
                "verifier_status": fulfillment_verifier.get("status", ""),
                "hash_valid": fulfillment_verifier.get("hash_valid") is True,
            },
            "external_dependency_clearance": {
                "path": str(external_dependency_clearance_path),
                "source": clearance_source,
                "hash_field": "clearance_execution_hash",
                "hash": str(external_dependency_clearance.get("clearance_execution_hash") or ""),
                "verifier_status": str(_as_dict(external_dependency_clearance.get("handoff_verification")).get("status") or ""),
                "hash_valid": _as_dict(external_dependency_clearance.get("handoff_verification")).get("hash_valid")
                is True,
            },
        },
        "p0b_google_environment_request_verifier": request_verifier,
        "p0b_google_playwright_env_report_verifier": env_verifier,
        "p0b_google_environment_fulfillment_verifier": fulfillment_verifier,
        "summary": {
            "required_count": len(required_items),
            "fulfilled_required_count": len(fulfilled_required),
            "missing_required_count": len(missing_required),
            "missing_required": missing_required,
            "presence_mismatch_count": len(presence_mismatches),
            "presence_mismatches": presence_mismatches,
            "owner_counts": _owner_counts(items),
            "missing_required_by_owner": _missing_by_owner(items),
            "environment_fulfilled": environment_fulfilled,
            "environment_fulfillment_ready": environment_fulfillment.get("environment_fulfillment_ready") is True,
            "ready_for_playwright_smoke": environment_fulfillment.get("ready_for_playwright_smoke") is True,
            "ready_for_full_google_run": environment_fulfillment.get("ready_for_full_google_run") is True,
            "google_main_scoring_allowed": environment_fulfillment.get("google_main_scoring_allowed") is True,
            "environment_handoff_ready": fulfillment_summary.get("environment_handoff_ready") is True,
            "database_url_reuse_available": fulfillment_summary.get("database_url_reuse_available") is True,
            "blocked_by_prerequisite_step": blocked_by_prerequisite,
            "prerequisite_step_id": PREREQUISITE_STEP_ID,
            "prerequisite_step_ready": prerequisite_step.get("ready") is True,
            "current_global_clearance_step_id": str(external_dependency_clearance.get("current_step_id") or ""),
            "target_clearance_step_id": STEP_ID,
            "target_clearance_step_can_start": clearance_step_can_start,
            "target_clearance_step_ready": clearance_step_ready,
            "next_action": (
                "clear_p0a_real_batches_first"
                if blocked_by_prerequisite
                else (
                    "continue_external_dependency_clearance"
                    if environment_fulfilled
                    else str(fulfillment_summary.get("next_action") or "populate_google_environment_inputs")
                )
            ),
            "next_command": (
                "make au-p0a-real-batch-clearance"
                if blocked_by_prerequisite
                else str(fulfillment_summary.get("next_command") or "make au-p0b-google-playwright-env")
            ),
            "strict_gate_command": str(fulfillment_summary.get("strict_gate_command") or ""),
            "ready_smoke_strict_gate_command": str(fulfillment_summary.get("ready_smoke_strict_gate_command") or ""),
            "operator_step_count": len(operator_steps),
            "post_update_validation_command_count": len(validation_sequence),
            "raw_secret_values_allowed": False,
            "selector_values_allowed": False,
            "database_urls_allowed": False,
            "provider_response_values_allowed": False,
        },
        "environment_clearance_items": items,
        "operator_steps": operator_steps,
        "post_update_validation_sequence": validation_sequence,
        "runtime_endpoints": {
            "p0b_google_environment_clearance": "GET /v1/p0b-google-environment-clearance/au",
            "p0b_google_environment_request": "GET /v1/p0b-google-environment-request/au",
            "p0b_google_environment_fulfillment": "GET /v1/p0b-google-environment-fulfillment/au",
            "p0b_google_execution_checklist": "GET /v1/p0b-google-execution-checklist/au",
            "p0a_real_batch_clearance": "GET /v1/p0a-real-batch-clearance/au",
            "external_dependency_clearance": "GET /v1/external-dependency-clearance/au",
            "delivery_progress": "GET /v1/delivery-progress/au",
        },
        "hard_gate_commands": _unique_strings(
            [
                "make au-p0b-google-environment-clearance",
                "make verify-au-p0b-google-environment-clearance",
                "make au-p0b-google-environment-request",
                "make verify-au-p0b-google-environment-request",
                "make au-p0b-google-playwright-env",
                "make verify-au-p0b-google-playwright-env",
                "make au-p0b-google-environment-fulfillment",
                "make verify-au-p0b-google-environment-fulfillment",
                "make au-p0a-real-batch-clearance",
                "make verify-au-p0a-real-batch-clearance",
                str(fulfillment_summary.get("strict_gate_command") or ""),
                str(fulfillment_summary.get("ready_smoke_strict_gate_command") or ""),
                "PYTHONPATH=packages/geno_core:apps/api python3 "
                "scripts/verify_au_p0b_google_environment_clearance.py "
                "${GENO_AU_P0B_GOOGLE_ENVIRONMENT_CLEARANCE_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-environment-clearance-latest.json} "
                "--require-cleared",
            ]
        ),
        "redaction_policy": {
            "raw_secret_values_allowed": False,
            "selector_values_allowed": False,
            "database_urls_allowed": False,
            "provider_response_values_allowed": False,
            "environment_entries_reference_presence_and_hash_prefix_only": True,
            "forbidden_exact_secret_field_count": 9,
            "recorded_fields": [
                "key",
                "item_type",
                "required",
                "fulfilled",
                "requested_present",
                "environment_present",
                "presence_mismatch",
                "source",
                "value_length",
                "sha256_prefix",
                "blocking_reasons",
            ],
        },
    }
    payload["p0b_google_environment_clearance_hash"] = compute_p0b_google_environment_clearance_hash(payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU P0b Google environment clearance JSON")
    parser.add_argument(
        "--environment-request-path",
        default=os.environ.get(
            "GENO_AU_P0B_GOOGLE_ENVIRONMENT_REQUEST_OUTPUT_PATH",
            DEFAULT_ENVIRONMENT_REQUEST_PATH,
        ),
        help="Path to the AU P0b Google environment request packet JSON.",
    )
    parser.add_argument(
        "--playwright-env-report-path",
        default=os.environ.get(
            "GENO_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH",
            DEFAULT_PLAYWRIGHT_ENV_REPORT_PATH,
        ),
        help="Path to the AU P0b Google Playwright environment report JSON.",
    )
    parser.add_argument(
        "--environment-fulfillment-path",
        default=os.environ.get(
            "GENO_AU_P0B_GOOGLE_ENVIRONMENT_FULFILLMENT_OUTPUT_PATH",
            DEFAULT_ENVIRONMENT_FULFILLMENT_PATH,
        ),
        help="Path to the AU P0b Google environment fulfillment JSON.",
    )
    parser.add_argument(
        "--external-dependency-clearance-path",
        default=os.environ.get(
            "GENO_AU_EXTERNAL_DEPENDENCY_CLEARANCE_OUTPUT_PATH",
            DEFAULT_EXTERNAL_DEPENDENCY_CLEARANCE_PATH,
        ),
        help="Path to the AU external dependency clearance JSON.",
    )
    parser.add_argument(
        "--env-file",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_ENV_FILE", DEFAULT_PLAYWRIGHT_ENV_FILE),
        help="Optional env file to parse if the Playwright environment report must be generated in memory.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_ENVIRONMENT_CLEARANCE_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU P0b Google environment clearance JSON.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    payload = build_au_p0b_google_environment_clearance(
        environment_request_path=Path(args.environment_request_path),
        playwright_env_report_path=Path(args.playwright_env_report_path),
        environment_fulfillment_path=Path(args.environment_fulfillment_path),
        external_dependency_clearance_path=Path(args.external_dependency_clearance_path),
        playwright_env_file_path=Path(args.env_file) if args.env_file else None,
        output_path=output_path,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if payload["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
