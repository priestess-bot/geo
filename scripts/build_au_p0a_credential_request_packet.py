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

from scripts.build_au_p0a_execution_checklist import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0A_EXECUTION_CHECKLIST_PATH,
    build_au_p0a_execution_checklist,
)
from scripts.verify_au_p0a_execution_checklist import verify_au_p0a_execution_checklist  # noqa: E402


PACKET_VERSION = "au_p0a_credential_request_packet_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0a-credential-request-latest.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_p0a_credential_request_packet_hash(packet: dict[str, Any]) -> str:
    payload = dict(packet)
    payload.pop("p0a_credential_request_packet_hash", None)
    return hashlib.sha256(_stable_bytes(payload)).hexdigest()


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _string_list(value: object) -> list[str]:
    items: list[str] = []
    for item in _as_list(value):
        if isinstance(item, dict):
            text = str(item.get("shell") or item.get("command") or item.get("id") or "").strip()
        else:
            text = str(item).strip()
        if text:
            items.append(text)
    return items


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_file_entry(name: str, path: Path) -> dict[str, Any]:
    entry: dict[str, Any] = {"name": name, "path": str(path), "exists": path.exists()}
    if path.is_file():
        entry["size_bytes"] = path.stat().st_size
        entry["file_sha256"] = _file_sha256(path)
    return entry


def _load_or_build_p0a_execution_checklist(
    path: Path,
    *,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        checklist = build_au_p0a_execution_checklist(output_path=path, generated_at=generated_at)
        return checklist, {"path": str(path), "exists": False, "source": "generated_in_memory", "errors": ["file_missing"]}
    except json.JSONDecodeError as exc:
        checklist = build_au_p0a_execution_checklist(output_path=path, generated_at=generated_at)
        return checklist, {
            "path": str(path),
            "exists": True,
            "source": "generated_in_memory",
            "errors": [f"json_invalid:{exc.msg}"],
        }
    if isinstance(payload, dict):
        return payload, {"path": str(path), "exists": True, "source": "existing_file", "errors": []}
    checklist = build_au_p0a_execution_checklist(output_path=path, generated_at=generated_at)
    return checklist, {"path": str(path), "exists": True, "source": "generated_in_memory", "errors": ["not_json_object"]}


def _owner_counts(credential_items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in credential_items:
        owner = str(item.get("owner_hint") or "unknown")
        counts[owner] = counts.get(owner, 0) + 1
    return dict(sorted(counts.items()))


def _missing_by_owner(credential_items: list[dict[str, Any]]) -> dict[str, list[str]]:
    owners: dict[str, list[str]] = {}
    for item in credential_items:
        if item.get("required") is True and item.get("present") is not True:
            owner = str(item.get("owner_hint") or "unknown")
            owners.setdefault(owner, []).append(str(item.get("name") or ""))
    return {owner: sorted(names) for owner, names in sorted(owners.items())}


def _requested_items(credential_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    requested: list[dict[str, Any]] = []
    for item in credential_items:
        requested.append(
            {
                "name": str(item.get("name") or ""),
                "required": item.get("required") is True,
                "present": item.get("present") is True,
                "source": str(item.get("source") or "missing"),
                "owner_hint": str(item.get("owner_hint") or "unknown"),
                "accepted_injection_methods": _string_list(item.get("accepted_injection_methods")),
                "env_file_key": str(item.get("env_file_key") or ""),
                "value_length": int(item.get("value_length") or 0),
                "sha256_prefix": str(item.get("sha256_prefix") or ""),
                "secret_redacted": item.get("secret_redacted") is True,
                "post_update_checks": _string_list(item.get("post_update_checks")),
            }
        )
    return requested


def build_au_p0a_credential_request_packet(
    *,
    p0a_execution_checklist_path: Path = Path(DEFAULT_P0A_EXECUTION_CHECKLIST_PATH),
    p0a_execution_checklist: dict[str, Any] | None = None,
    output_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if p0a_execution_checklist is None:
        p0a_execution_checklist, source = _load_or_build_p0a_execution_checklist(
            p0a_execution_checklist_path,
            generated_at=generated_at,
        )
    else:
        source = {"path": str(p0a_execution_checklist_path), "exists": True, "source": "provided_payload", "errors": []}

    verifier = verify_au_p0a_execution_checklist(p0a_execution_checklist, path=p0a_execution_checklist_path)
    credential_handoff = _as_dict(p0a_execution_checklist.get("credential_handoff"))
    credential_items = [_as_dict(item) for item in _as_list(credential_handoff.get("credential_items"))]
    requested_items = _requested_items(credential_items)
    missing_required = _string_list(credential_handoff.get("missing_required"))
    setup_commands = _string_list(credential_handoff.get("setup_commands"))
    verification_commands = _string_list(credential_handoff.get("verification_commands"))
    evidence_outputs = _string_list(credential_handoff.get("evidence_outputs"))
    redaction_policy = _as_dict(credential_handoff.get("redaction_policy"))
    packet_ready = verifier.get("status") == "pass" and verifier.get("hash_valid") is True

    hard_gate_commands = [
        "make au-p0a-credential-request",
        "make verify-au-p0a-credential-request",
        "make au-p0a-env",
        "make verify-au-p0a-env",
        "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_env_report.py "
        "${GENO_AU_P0A_ENV_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-env-latest.json} --require-ready-environment",
    ]

    payload: dict[str, Any] = {
        "p0a_credential_request_packet_version": PACKET_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if packet_ready else "fail",
        "credential_request_packet_ready": packet_ready,
        "credential_handoff_ready": credential_handoff.get("ready") is True,
        "ready_for_design_partner": p0a_execution_checklist.get("ready_for_design_partner") is True,
        "output_path": str(output_path) if output_path else "",
        "source_p0a_execution_checklist": {
            "path": str(p0a_execution_checklist_path),
            "execution_checklist_version": str(p0a_execution_checklist.get("execution_checklist_version") or ""),
            "p0a_execution_checklist_hash": str(p0a_execution_checklist.get("p0a_execution_checklist_hash") or ""),
            "p0a_execution_checklist_ready": p0a_execution_checklist.get("p0a_execution_checklist_ready") is True,
            "ready_for_design_partner": p0a_execution_checklist.get("ready_for_design_partner") is True,
            "source": source,
        },
        "p0a_execution_checklist_verifier": {
            "status": verifier.get("status", ""),
            "hash_valid": verifier.get("hash_valid") is True,
            "p0a_execution_checklist_hash": str(verifier.get("p0a_execution_checklist_hash") or ""),
            "errors": [str(value) for value in _as_list(verifier.get("errors"))],
            "next_action": str(verifier.get("next_action") or ""),
        },
        "summary": {
            "target_env_file": str(credential_handoff.get("target_env_file") or ""),
            "credential_handoff_ready": credential_handoff.get("ready") is True,
            "missing_required_count": len(missing_required),
            "missing_required": missing_required,
            "credential_item_count": len(requested_items),
            "required_item_count": sum(1 for item in requested_items if item.get("required") is True),
            "present_required_count": sum(
                1 for item in requested_items if item.get("required") is True and item.get("present") is True
            ),
            "owner_counts": _owner_counts(requested_items),
            "missing_required_by_owner": _missing_by_owner(requested_items),
            "setup_command_count": len(setup_commands),
            "verification_command_count": len(verification_commands),
            "evidence_output_count": len(evidence_outputs),
            "raw_secret_values_allowed": redaction_policy.get("raw_secret_values_allowed") is True,
            "forbidden_exact_secret_fields_redacted": redaction_policy.get("forbidden_exact_secret_fields_redacted")
            is True,
            "next_command": setup_commands[0] if setup_commands else "",
            "post_update_verification_command": verification_commands[0] if verification_commands else "",
        },
        "requested_credentials": requested_items,
        "setup_commands": setup_commands,
        "verification_commands": verification_commands,
        "evidence_outputs": evidence_outputs,
        "redaction_policy": {
            "raw_secret_values_allowed": redaction_policy.get("raw_secret_values_allowed") is True,
            "recorded_fields": _string_list(redaction_policy.get("recorded_fields")),
            "forbidden_exact_secret_field_count": int(redaction_policy.get("forbidden_exact_secret_field_count") or 0),
            "forbidden_exact_secret_fields_redacted": redaction_policy.get("forbidden_exact_secret_fields_redacted")
            is True,
        },
        "runtime_endpoints": {
            "p0a_credential_request": "GET /v1/p0a-credential-request/au",
            "p0a_execution_checklist": "GET /v1/p0a-execution-checklist/au",
            "p0a_environment_checklist": "GET /v1/p0a-environment-checklist/au",
            "next_work_item": "GET /v1/next-work-item/au",
            "external_dependency_handoff": "GET /v1/external-dependency-handoff/au",
        },
        "hard_gate_commands": hard_gate_commands,
        "evidence_sources": [_source_file_entry("p0a_execution_checklist", p0a_execution_checklist_path)],
    }
    payload["p0a_credential_request_packet_hash"] = compute_p0a_credential_request_packet_hash(payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU P0a credential request packet JSON")
    parser.add_argument(
        "--p0a-execution-checklist-path",
        default=os.environ.get("GENO_AU_P0A_EXECUTION_CHECKLIST_OUTPUT_PATH", DEFAULT_P0A_EXECUTION_CHECKLIST_PATH),
        help="Path to the AU P0a execution checklist JSON.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GENO_AU_P0A_CREDENTIAL_REQUEST_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU P0a credential request packet JSON.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    payload = build_au_p0a_credential_request_packet(
        p0a_execution_checklist_path=Path(args.p0a_execution_checklist_path),
        output_path=output_path,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if payload["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
