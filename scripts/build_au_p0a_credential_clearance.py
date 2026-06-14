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

from scripts.build_au_p0a_credential_fulfillment import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_CREDENTIAL_FULFILLMENT_PATH,
    build_au_p0a_credential_fulfillment,
)
from scripts.build_au_p0a_credential_request_packet import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_CREDENTIAL_REQUEST_PATH,
    build_au_p0a_credential_request_packet,
)
from scripts.build_au_p0a_env_report import DEFAULT_OUTPUT_PATH as DEFAULT_ENV_REPORT_PATH  # noqa: E402
from scripts.run_au_external_dependency_clearance import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_EXTERNAL_DEPENDENCY_CLEARANCE_PATH,
    run_au_external_dependency_clearance,
)
from scripts.verify_au_p0a_credential_fulfillment import verify_au_p0a_credential_fulfillment  # noqa: E402
from scripts.verify_au_p0a_credential_request_packet import verify_au_p0a_credential_request_packet  # noqa: E402


CLEARANCE_VERSION = "au_p0a_credential_clearance_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0a-credential-clearance-latest.json"
STEP_ID = "p0a_provider_credentials"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_p0a_credential_clearance_hash(payload: dict[str, Any]) -> str:
    payload_for_hash = dict(payload)
    payload_for_hash.pop("p0a_credential_clearance_hash", None)
    return hashlib.sha256(_stable_bytes(payload_for_hash)).hexdigest()


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _strings(value: object) -> list[str]:
    return [str(item) for item in _as_list(value)]


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


def _load_or_build_request(path: Path, *, generated_at: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if payload is not None:
        return payload, source
    return build_au_p0a_credential_request_packet(output_path=path, generated_at=generated_at), {
        **source,
        "source": "generated_in_memory",
    }


def _load_or_build_fulfillment(
    path: Path,
    *,
    credential_request_path: Path,
    credential_request: dict[str, Any],
    env_report_path: Path,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if payload is not None:
        return payload, source
    fulfillment = build_au_p0a_credential_fulfillment(
        credential_request_path=credential_request_path,
        env_report_path=env_report_path,
        credential_request=credential_request,
        output_path=path,
        generated_at=generated_at,
    )
    return fulfillment, {**source, "source": "generated_in_memory"}


def _load_or_build_clearance(path: Path, *, generated_at: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if payload is not None:
        return payload, source
    clearance = run_au_external_dependency_clearance(output_path=path, generated_at=generated_at)
    return clearance, {**source, "source": "generated_in_memory"}


def _missing_items(
    credential_request: dict[str, Any],
    credential_fulfillment: dict[str, Any],
) -> list[dict[str, Any]]:
    requested_by_name = {
        str(item.get("name") or ""): _as_dict(item)
        for item in [_as_dict(value) for value in _as_list(credential_request.get("requested_credentials"))]
        if str(item.get("name") or "")
    }
    fulfillment_by_name = {
        str(item.get("name") or ""): _as_dict(item)
        for item in [_as_dict(value) for value in _as_list(credential_fulfillment.get("credential_fulfillment_items"))]
        if str(item.get("name") or "")
    }
    names = sorted(
        set(_strings(_as_dict(credential_request.get("summary")).get("missing_required")))
        | set(_strings(_as_dict(credential_fulfillment.get("summary")).get("missing_required")))
    )
    items: list[dict[str, Any]] = []
    for name in names:
        request_item = requested_by_name.get(name, {})
        fulfillment_item = fulfillment_by_name.get(name, {})
        items.append(
            {
                "name": name,
                "owner_hint": str(
                    fulfillment_item.get("owner_hint") or request_item.get("owner_hint") or "unknown"
                ),
                "env_file_key": str(
                    fulfillment_item.get("env_file_key") or request_item.get("env_file_key") or name
                ),
                "target_env_file": str(_as_dict(credential_request.get("summary")).get("target_env_file") or ""),
                "request_present": request_item.get("present") is True
                or fulfillment_item.get("requested_present") is True,
                "environment_present": fulfillment_item.get("environment_present") is True,
                "accepted_injection_methods": _strings(request_item.get("accepted_injection_methods")),
                "post_update_checks": _strings(request_item.get("post_update_checks")),
                "blocking_reasons": _strings(fulfillment_item.get("blocking_reasons"))
                or ["credential_value_missing"],
                "raw_value_required_in_packet": False,
            }
        )
    return items


def _operator_steps(
    *,
    credential_request: dict[str, Any],
    credential_fulfillment: dict[str, Any],
    external_clearance: dict[str, Any],
) -> list[dict[str, Any]]:
    request_summary = _as_dict(credential_request.get("summary"))
    fulfillment_summary = _as_dict(credential_fulfillment.get("summary"))
    steps = [
        {
            "order": 1,
            "id": "verify_p0a_env_template",
            "command": "make verify-au-p0a-env-template",
            "purpose": "confirm_safe_committed_template_before_secret_injection",
            "external_call_risk": "none",
        },
        {
            "order": 2,
            "id": "bootstrap_local_env_file",
            "command": "make au-p0a-env-bootstrap",
            "purpose": "create_or_repair_gitignored_0600_env_file",
            "external_call_risk": "none",
        },
        {
            "order": 3,
            "id": "populate_missing_credentials",
            "command": "edit .env.au-p0a or set process env with missing keys",
            "purpose": "supply_required_provider_keys_without_recording_raw_values",
            "external_call_risk": "manual_secret_input",
        },
        {
            "order": 4,
            "id": "refresh_redacted_env_report",
            "command": str(fulfillment_summary.get("next_command") or "make au-p0a-env"),
            "purpose": "write_redacted_environment_presence_hashes",
            "external_call_risk": "none",
        },
        {
            "order": 5,
            "id": "verify_fulfillment",
            "command": "make verify-au-p0a-credential-fulfillment",
            "purpose": "prove_request_and_environment_report_are_aligned",
            "external_call_risk": "none",
        },
        {
            "order": 6,
            "id": "run_strict_gate",
            "command": str(fulfillment_summary.get("strict_gate_command") or ""),
            "purpose": "require_all_p0a_credentials_fulfilled",
            "external_call_risk": "none",
        },
    ]
    clearance_sequence = _strings(external_clearance.get("current_recommended_sequence"))
    if clearance_sequence:
        steps.append(
            {
                "order": 7,
                "id": "continue_clearance_sequence",
                "command": "then follow current_recommended_sequence from external dependency clearance",
                "purpose": "continue_to_p0a_real_batches_after_credentials_clear",
                "external_call_risk": "depends_on_next_sequence_step",
            }
        )
    for step in steps:
        if step["id"] == "populate_missing_credentials":
            step["missing_required"] = _strings(request_summary.get("missing_required"))
            step["target_env_file"] = str(request_summary.get("target_env_file") or ".env.au-p0a")
            step["allowed_injection_methods"] = sorted(
                {
                    method
                    for item in _missing_items(credential_request, credential_fulfillment)
                    for method in _strings(item.get("accepted_injection_methods"))
                }
            )
    return steps


def _post_update_validation_sequence(
    credential_request: dict[str, Any],
    credential_fulfillment: dict[str, Any],
    external_clearance: dict[str, Any],
) -> list[str]:
    commands = [
        "make verify-au-p0a-env-bootstrap",
        "make au-p0a-env",
        "make verify-au-p0a-env",
        "make au-p0a-credential-fulfillment",
        "make verify-au-p0a-credential-fulfillment",
        str(_as_dict(credential_fulfillment.get("summary")).get("strict_gate_command") or ""),
    ]
    commands.extend(_strings(credential_request.get("verification_commands")))
    commands.extend(_strings(external_clearance.get("current_recommended_sequence")))
    return _unique_strings(commands)


def build_au_p0a_credential_clearance(
    *,
    credential_request_path: Path = Path(DEFAULT_CREDENTIAL_REQUEST_PATH),
    env_report_path: Path = Path(DEFAULT_ENV_REPORT_PATH),
    credential_fulfillment_path: Path = Path(DEFAULT_CREDENTIAL_FULFILLMENT_PATH),
    external_dependency_clearance_path: Path = Path(DEFAULT_EXTERNAL_DEPENDENCY_CLEARANCE_PATH),
    credential_request: dict[str, Any] | None = None,
    credential_fulfillment: dict[str, Any] | None = None,
    external_dependency_clearance: dict[str, Any] | None = None,
    output_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if credential_request is None:
        credential_request, request_source = _load_or_build_request(
            credential_request_path,
            generated_at=generated_at,
        )
    else:
        request_source = {"path": str(credential_request_path), "exists": True, "source": "provided_payload", "errors": []}

    if credential_fulfillment is None:
        credential_fulfillment, fulfillment_source = _load_or_build_fulfillment(
            credential_fulfillment_path,
            credential_request_path=credential_request_path,
            credential_request=credential_request,
            env_report_path=env_report_path,
            generated_at=generated_at,
        )
    else:
        fulfillment_source = {
            "path": str(credential_fulfillment_path),
            "exists": True,
            "source": "provided_payload",
            "errors": [],
        }

    if external_dependency_clearance is None:
        external_dependency_clearance, clearance_source = _load_or_build_clearance(
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

    request_verifier = verify_au_p0a_credential_request_packet(credential_request, path=credential_request_path)
    fulfillment_verifier = verify_au_p0a_credential_fulfillment(
        credential_fulfillment,
        path=credential_fulfillment_path,
    )
    request_summary = _as_dict(credential_request.get("summary"))
    fulfillment_summary = _as_dict(credential_fulfillment.get("summary"))
    missing_items = _missing_items(credential_request, credential_fulfillment)
    missing_required = [str(item.get("name") or "") for item in missing_items]
    provider_missing = [
        str(item.get("name") or "")
        for item in missing_items
        if str(item.get("owner_hint") or "") == "provider_admin"
    ]
    runtime_db_missing = [
        str(item.get("name") or "")
        for item in missing_items
        if str(item.get("owner_hint") or "") == "runtime_database_admin"
    ]
    credentials_fulfilled = credential_fulfillment.get("credentials_fulfilled") is True
    current_step_id = str(external_dependency_clearance.get("current_step_id") or "")
    clearance_step_matches = current_step_id == STEP_ID
    packet_ready = (
        request_verifier.get("status") == "pass"
        and request_verifier.get("hash_valid") is True
        and fulfillment_verifier.get("status") == "pass"
        and fulfillment_verifier.get("hash_valid") is True
        and external_dependency_clearance.get("status") == "pass"
    )
    operator_steps = _operator_steps(
        credential_request=credential_request,
        credential_fulfillment=credential_fulfillment,
        external_clearance=external_dependency_clearance,
    )
    validation_sequence = _post_update_validation_sequence(
        credential_request,
        credential_fulfillment,
        external_dependency_clearance,
    )
    strict_gate_command = str(fulfillment_summary.get("strict_gate_command") or "")
    payload: dict[str, Any] = {
        "p0a_credential_clearance_version": CLEARANCE_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if packet_ready else "fail",
        "credential_clearance_packet_ready": packet_ready,
        "credentials_fulfilled": credentials_fulfilled,
        "credential_clearance_ready": credentials_fulfilled and clearance_step_matches,
        "ready_for_next_clearance_step": credentials_fulfilled and clearance_step_matches,
        "output_path": str(output_path) if output_path else "",
        "clearance_step": {
            "id": STEP_ID,
            "current_step_id": current_step_id,
            "current_step_matches": clearance_step_matches,
            "would_execute_step_count": int(external_dependency_clearance.get("would_execute_step_count") or 0),
            "next_command": str(external_dependency_clearance.get("next_command") or ""),
            "current_strict_gate_command": str(external_dependency_clearance.get("current_strict_gate_command") or ""),
        },
        "source_artifacts": {
            "credential_request": {
                "path": str(credential_request_path),
                "source": request_source,
                "hash_field": "p0a_credential_request_packet_hash",
                "hash": str(credential_request.get("p0a_credential_request_packet_hash") or ""),
                "verifier_status": request_verifier.get("status", ""),
                "hash_valid": request_verifier.get("hash_valid") is True,
            },
            "credential_fulfillment": {
                "path": str(credential_fulfillment_path),
                "source": fulfillment_source,
                "hash_field": "p0a_credential_fulfillment_hash",
                "hash": str(credential_fulfillment.get("p0a_credential_fulfillment_hash") or ""),
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
        "p0a_credential_request_verifier": request_verifier,
        "p0a_credential_fulfillment_verifier": fulfillment_verifier,
        "summary": {
            "target_env_file": str(request_summary.get("target_env_file") or ".env.au-p0a"),
            "credentials_fulfilled": credentials_fulfilled,
            "missing_required_count": len(missing_required),
            "missing_required": sorted(missing_required),
            "provider_missing_required": sorted(provider_missing),
            "runtime_database_missing_required": sorted(runtime_db_missing),
            "credential_handoff_ready": credential_request.get("credential_handoff_ready") is True,
            "credential_fulfillment_ready": credential_fulfillment.get("credential_fulfillment_ready") is True,
            "environment_ready": fulfillment_summary.get("environment_ready") is True,
            "current_clearance_step_id": current_step_id,
            "clearance_step_matches": clearance_step_matches,
            "next_action": (
                "continue_external_dependency_clearance"
                if credentials_fulfilled
                else "populate_required_p0a_credentials"
            ),
            "next_command": "make au-p0a-env" if missing_required else "make au-external-dependency-clearance",
            "strict_gate_command": strict_gate_command,
            "operator_step_count": len(operator_steps),
            "post_update_validation_command_count": len(validation_sequence),
            "raw_secret_values_allowed": False,
        },
        "missing_credential_items": missing_items,
        "operator_steps": operator_steps,
        "post_update_validation_sequence": validation_sequence,
        "runtime_endpoints": {
            "p0a_credential_clearance": "GET /v1/p0a-credential-clearance/au",
            "p0a_credential_request": "GET /v1/p0a-credential-request/au",
            "p0a_credential_fulfillment": "GET /v1/p0a-credential-fulfillment/au",
            "external_dependency_clearance": "GET /v1/external-dependency-clearance/au",
            "delivery_progress": "GET /v1/delivery-progress/au",
        },
        "hard_gate_commands": _unique_strings(
            [
                "make au-p0a-credential-clearance",
                "make verify-au-p0a-credential-clearance",
                "make au-p0a-credential-request",
                "make verify-au-p0a-credential-request",
                "make au-p0a-credential-fulfillment",
                "make verify-au-p0a-credential-fulfillment",
                strict_gate_command,
                "PYTHONPATH=packages/geno_core:apps/api python3 "
                "scripts/verify_au_p0a_credential_clearance.py "
                "${GENO_AU_P0A_CREDENTIAL_CLEARANCE_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-credential-clearance-latest.json} "
                "--require-cleared",
            ]
        ),
        "redaction_policy": {
            "raw_secret_values_allowed": False,
            "recorded_fields": ["present", "source", "value_length", "sha256_prefix", "secret_redacted"],
            "forbidden_exact_secret_field_count": 5,
            "secret_redacted": True,
        },
    }
    payload["p0a_credential_clearance_hash"] = compute_p0a_credential_clearance_hash(payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU P0a credential clearance JSON")
    parser.add_argument(
        "--credential-request-path",
        default=os.environ.get("GENO_AU_P0A_CREDENTIAL_REQUEST_OUTPUT_PATH", DEFAULT_CREDENTIAL_REQUEST_PATH),
        help="Path to the AU P0a credential request packet JSON.",
    )
    parser.add_argument(
        "--env-report-path",
        default=os.environ.get("GENO_AU_P0A_ENV_OUTPUT_PATH", DEFAULT_ENV_REPORT_PATH),
        help="Path to the AU P0a environment report JSON.",
    )
    parser.add_argument(
        "--credential-fulfillment-path",
        default=os.environ.get(
            "GENO_AU_P0A_CREDENTIAL_FULFILLMENT_OUTPUT_PATH",
            DEFAULT_CREDENTIAL_FULFILLMENT_PATH,
        ),
        help="Path to the AU P0a credential fulfillment JSON.",
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
        "--output-path",
        default=os.environ.get("GENO_AU_P0A_CREDENTIAL_CLEARANCE_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU P0a credential clearance JSON.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    payload = build_au_p0a_credential_clearance(
        credential_request_path=Path(args.credential_request_path),
        env_report_path=Path(args.env_report_path),
        credential_fulfillment_path=Path(args.credential_fulfillment_path),
        external_dependency_clearance_path=Path(args.external_dependency_clearance_path),
        output_path=output_path,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if payload["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
