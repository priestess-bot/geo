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

from scripts.build_au_p0b_google_execution_checklist import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0B_GOOGLE_EXECUTION_CHECKLIST_PATH,
    build_au_p0b_google_execution_checklist,
)
from scripts.verify_au_p0b_google_execution_checklist import (  # noqa: E402
    verify_au_p0b_google_execution_checklist,
)


PACKET_VERSION = "au_p0b_google_manual_backfill_request_packet_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0b-google-manual-backfill-request-latest.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_p0b_google_manual_backfill_request_packet_hash(packet: dict[str, Any]) -> str:
    payload = dict(packet)
    payload.pop("p0b_google_manual_backfill_request_packet_hash", None)
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


def _int_value(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


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


def _load_or_build_p0b_google_execution_checklist(
    path: Path,
    *,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        checklist = build_au_p0b_google_execution_checklist(output_path=path, generated_at=generated_at)
        return checklist, {"path": str(path), "exists": False, "source": "generated_in_memory", "errors": ["file_missing"]}
    except json.JSONDecodeError as exc:
        checklist = build_au_p0b_google_execution_checklist(output_path=path, generated_at=generated_at)
        return checklist, {
            "path": str(path),
            "exists": True,
            "source": "generated_in_memory",
            "errors": [f"json_invalid:{exc.msg}"],
        }
    if isinstance(payload, dict):
        return payload, {"path": str(path), "exists": True, "source": "existing_file", "errors": []}
    checklist = build_au_p0b_google_execution_checklist(output_path=path, generated_at=generated_at)
    return checklist, {"path": str(path), "exists": True, "source": "generated_in_memory", "errors": ["not_json_object"]}


def _manual_backfill_request(handoff: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_manual_backfill_handoff_version": str(handoff.get("version") or ""),
        "status": str(handoff.get("status") or "fail"),
        "hash_valid": handoff.get("hash_valid") is True,
        "manual_backfill_ready": handoff.get("manual_backfill_ready") is True,
        "ready": handoff.get("ready") is True,
        "manual_jsonl_env_var": str(handoff.get("manual_jsonl_env_var") or "MANUAL_BACKFILL_PATH"),
        "target_jsonl_path": str(handoff.get("target_jsonl_path") or ""),
        "target_jsonl_path_source": str(handoff.get("target_jsonl_path_source") or ""),
        "manual_jsonl_path_redacted": handoff.get("manual_jsonl_path_redacted") is True,
        "template_path": str(handoff.get("template_path") or ""),
        "template_manifest_path": str(handoff.get("template_manifest_path") or ""),
        "verification_path": str(handoff.get("verification_path") or ""),
        "expected_record_count": _int_value(handoff.get("expected_record_count")),
        "record_count": _int_value(handoff.get("record_count")),
        "expected_prompt_city_count": _int_value(handoff.get("expected_prompt_city_count")),
        "covered_prompt_city_count": _int_value(handoff.get("covered_prompt_city_count")),
        "expected_sample_size": _int_value(handoff.get("expected_sample_size")),
        "prompt_count": _int_value(handoff.get("prompt_count")),
        "geo_cities": _string_list(handoff.get("geo_cities")),
        "file_sha256": str(handoff.get("file_sha256") or ""),
        "verification_hash": str(handoff.get("verification_hash") or ""),
        "missing_reason_count": len(_string_list(handoff.get("missing_reasons"))),
        "missing_reasons": _string_list(handoff.get("missing_reasons")),
    }


def build_au_p0b_google_manual_backfill_request_packet(
    *,
    p0b_google_execution_checklist_path: Path = Path(DEFAULT_P0B_GOOGLE_EXECUTION_CHECKLIST_PATH),
    p0b_google_execution_checklist: dict[str, Any] | None = None,
    output_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if p0b_google_execution_checklist is None:
        p0b_google_execution_checklist, source = _load_or_build_p0b_google_execution_checklist(
            p0b_google_execution_checklist_path,
            generated_at=generated_at,
        )
    else:
        source = {
            "path": str(p0b_google_execution_checklist_path),
            "exists": True,
            "source": "provided_payload",
            "errors": [],
        }

    verifier = verify_au_p0b_google_execution_checklist(
        p0b_google_execution_checklist,
        path=p0b_google_execution_checklist_path,
    )
    handoff = _as_dict(p0b_google_execution_checklist.get("manual_backfill_handoff"))
    manual_request = _manual_backfill_request(handoff)
    required_fields = _string_list(handoff.get("required_fields"))
    operator_requirements = _string_list(handoff.get("operator_requirements"))
    setup_commands = _string_list(handoff.get("setup_commands"))
    verification_commands = _string_list(handoff.get("verification_commands"))
    evidence_outputs = _string_list(handoff.get("evidence_outputs"))
    redaction_policy = _as_dict(handoff.get("redaction_policy"))
    packet_ready = verifier.get("status") == "pass" and verifier.get("hash_valid") is True
    content_redacted = (
        redaction_policy.get("raw_answer_values_allowed") is False
        and redaction_policy.get("raw_citation_values_allowed") is False
        and redaction_policy.get("raw_asset_urls_allowed") is False
        and redaction_policy.get("manual_jsonl_path_redacted") is True
    )

    hard_gate_commands = [
        "make au-p0b-google-manual-backfill-request",
        "make verify-au-p0b-google-manual-backfill-request",
        "make au-p0b-google-manual-template",
        "make verify-au-p0b-google-manual-backfill",
        "make au-p0b-google-status",
        "make verify-au-p0b-google-status",
        "make au-p0b-google-package",
        "make verify-au-p0b-google-package",
        "make au-p0b-google-execution-checklist",
        "make verify-au-p0b-google-execution-checklist",
        "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_manual_backfill_request_packet.py "
        "${GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_REQUEST_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-manual-backfill-request-latest.json} --require-manual-backfill-ready",
    ]

    payload: dict[str, Any] = {
        "p0b_google_manual_backfill_request_packet_version": PACKET_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if packet_ready else "fail",
        "manual_backfill_request_packet_ready": packet_ready,
        "manual_backfill_handoff_ready": handoff.get("ready") is True,
        "google_main_scoring_allowed": p0b_google_execution_checklist.get("google_main_scoring_allowed") is True,
        "output_path": str(output_path) if output_path else "",
        "source_p0b_google_execution_checklist": {
            "path": str(p0b_google_execution_checklist_path),
            "execution_checklist_version": str(
                p0b_google_execution_checklist.get("execution_checklist_version") or ""
            ),
            "google_execution_checklist_hash": str(
                p0b_google_execution_checklist.get("google_execution_checklist_hash") or ""
            ),
            "google_execution_checklist_ready": p0b_google_execution_checklist.get(
                "google_execution_checklist_ready"
            )
            is True,
            "google_main_scoring_allowed": p0b_google_execution_checklist.get("google_main_scoring_allowed") is True,
            "source": source,
        },
        "p0b_google_execution_checklist_verifier": {
            "status": verifier.get("status", ""),
            "hash_valid": verifier.get("hash_valid") is True,
            "google_execution_checklist_hash": str(verifier.get("google_execution_checklist_hash") or ""),
            "errors": [str(value) for value in _as_list(verifier.get("errors"))],
            "next_action": str(verifier.get("next_action") or ""),
        },
        "summary": {
            "source_manual_backfill_handoff_version": manual_request["source_manual_backfill_handoff_version"],
            "manual_backfill_handoff_status": manual_request["status"],
            "hash_valid": manual_request["hash_valid"],
            "manual_backfill_ready": manual_request["manual_backfill_ready"],
            "manual_backfill_handoff_ready": manual_request["ready"],
            "manual_jsonl_env_var": manual_request["manual_jsonl_env_var"],
            "target_jsonl_path": manual_request["target_jsonl_path"],
            "target_jsonl_path_source": manual_request["target_jsonl_path_source"],
            "manual_jsonl_path_redacted": manual_request["manual_jsonl_path_redacted"],
            "template_path": manual_request["template_path"],
            "template_manifest_path": manual_request["template_manifest_path"],
            "verification_path": manual_request["verification_path"],
            "expected_record_count": manual_request["expected_record_count"],
            "record_count": manual_request["record_count"],
            "expected_prompt_city_count": manual_request["expected_prompt_city_count"],
            "covered_prompt_city_count": manual_request["covered_prompt_city_count"],
            "expected_sample_size": manual_request["expected_sample_size"],
            "prompt_count": manual_request["prompt_count"],
            "geo_city_count": len(manual_request["geo_cities"]),
            "geo_cities": manual_request["geo_cities"],
            "missing_reason_count": manual_request["missing_reason_count"],
            "missing_reasons": manual_request["missing_reasons"],
            "required_field_count": len(required_fields),
            "operator_requirement_count": len(operator_requirements),
            "setup_command_count": len(setup_commands),
            "verification_command_count": len(verification_commands),
            "evidence_output_count": len(evidence_outputs),
            "raw_answer_values_allowed": redaction_policy.get("raw_answer_values_allowed") is True,
            "raw_citation_values_allowed": redaction_policy.get("raw_citation_values_allowed") is True,
            "raw_asset_urls_allowed": redaction_policy.get("raw_asset_urls_allowed") is True,
            "content_redacted": content_redacted,
            "next_command": setup_commands[0] if setup_commands else "",
            "post_update_verification_command": verification_commands[0] if verification_commands else "",
            "google_next_action": str(p0b_google_execution_checklist.get("next_action") or ""),
        },
        "manual_backfill_request": manual_request,
        "required_fields": required_fields,
        "operator_requirements": operator_requirements,
        "setup_commands": setup_commands,
        "verification_commands": verification_commands,
        "evidence_outputs": evidence_outputs,
        "redaction_policy": {
            "raw_answer_values_allowed": redaction_policy.get("raw_answer_values_allowed") is True,
            "raw_citation_values_allowed": redaction_policy.get("raw_citation_values_allowed") is True,
            "raw_asset_urls_allowed": redaction_policy.get("raw_asset_urls_allowed") is True,
            "manual_jsonl_path_redacted": redaction_policy.get("manual_jsonl_path_redacted") is True,
            "recorded_fields": _string_list(redaction_policy.get("recorded_fields")),
        },
        "runtime_endpoints": {
            "p0b_google_manual_backfill_request": "GET /v1/p0b-google-manual-backfill-request/au",
            "p0b_google_execution_checklist": "GET /v1/p0b-google-execution-checklist/au",
            "p0b_google_environment_request": "GET /v1/p0b-google-environment-request/au",
            "external_dependency_handoff": "GET /v1/external-dependency-handoff/au",
            "external_dependency_clearance": "GET /v1/external-dependency-clearance/au",
            "next_work_item": "GET /v1/next-work-item/au",
        },
        "hard_gate_commands": hard_gate_commands,
        "evidence_sources": [_source_file_entry("p0b_google_execution_checklist", p0b_google_execution_checklist_path)],
    }
    payload["p0b_google_manual_backfill_request_packet_hash"] = (
        compute_p0b_google_manual_backfill_request_packet_hash(payload)
    )
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU P0b Google manual backfill request packet JSON")
    parser.add_argument(
        "--p0b-google-execution-checklist-path",
        default=os.environ.get(
            "GENO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH",
            DEFAULT_P0B_GOOGLE_EXECUTION_CHECKLIST_PATH,
        ),
        help="Path to the AU P0b Google execution checklist JSON.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_REQUEST_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU P0b Google manual backfill request packet JSON.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    payload = build_au_p0b_google_manual_backfill_request_packet(
        p0b_google_execution_checklist_path=Path(args.p0b_google_execution_checklist_path),
        output_path=output_path,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if payload["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
