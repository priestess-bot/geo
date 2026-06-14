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


PACKET_VERSION = "au_p0b_google_environment_request_packet_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0b-google-environment-request-latest.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_p0b_google_environment_request_packet_hash(packet: dict[str, Any]) -> str:
    payload = dict(packet)
    payload.pop("p0b_google_environment_request_packet_hash", None)
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


def _environment_items(handoff: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in _as_list(handoff.get("environment_items")):
        source = _as_dict(item)
        items.append(
            {
                "name": str(source.get("name") or ""),
                "gate": str(source.get("gate") or ""),
                "required": source.get("required") is True,
                "present": source.get("present") is True,
                "truthy": source.get("truthy") if isinstance(source.get("truthy"), bool) else None,
                "source": str(source.get("source") or "missing"),
                "owner_hint": str(source.get("owner_hint") or "platform_operator"),
                "accepted_injection_methods": _string_list(source.get("accepted_injection_methods")),
                "env_file_key": str(source.get("env_file_key") or ""),
                "value_length": int(source.get("value_length") or 0),
                "sha256_prefix": str(source.get("sha256_prefix") or ""),
                "secret_redacted": source.get("secret_redacted") is True,
                "post_update_checks": _string_list(source.get("post_update_checks")),
            }
        )
    return items


def _selector_items(handoff: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in _as_list(handoff.get("selector_items")):
        source = _as_dict(item)
        items.append(
            {
                "group": str(source.get("group") or ""),
                "candidate_names": _string_list(source.get("candidate_names")),
                "present": source.get("present") is True,
                "selected_name": str(source.get("selected_name") or ""),
                "source": str(source.get("source") or "missing"),
                "owner_hint": str(source.get("owner_hint") or "browser_automation_operator"),
                "accepted_injection_methods": _string_list(source.get("accepted_injection_methods")),
                "value_length": int(source.get("value_length") or 0),
                "sha256_prefix": str(source.get("sha256_prefix") or ""),
                "secret_redacted": source.get("secret_redacted") is True,
                "post_update_checks": _string_list(source.get("post_update_checks")),
            }
        )
    return items


def _file_items(handoff: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in _as_list(handoff.get("file_items")):
        source = _as_dict(item)
        items.append(
            {
                "name": str(source.get("name") or ""),
                "expected_type": str(source.get("expected_type") or ""),
                "present": source.get("present") is True,
                "exists": source.get("exists") is True,
                "is_file": source.get("is_file") is True,
                "is_dir": source.get("is_dir") is True,
                "source": str(source.get("source") or "missing"),
                "owner_hint": str(source.get("owner_hint") or "platform_operator"),
                "accepted_injection_methods": _string_list(source.get("accepted_injection_methods")),
                "value_length": int(source.get("value_length") or 0),
                "sha256_prefix": str(source.get("sha256_prefix") or ""),
                "secret_redacted": source.get("secret_redacted") is True,
                "post_update_checks": _string_list(source.get("post_update_checks")),
            }
        )
    return items


def _dependency_items(handoff: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in _as_list(handoff.get("dependency_items")):
        source = _as_dict(item)
        items.append(
            {
                "name": str(source.get("name") or ""),
                "present": source.get("present") is True,
                "source": str(source.get("source") or "unknown"),
                "owner_hint": str(source.get("owner_hint") or "runtime_operator"),
                "secret_redacted": source.get("secret_redacted") is True,
                "post_update_checks": _string_list(source.get("post_update_checks")),
            }
        )
    return items


def _all_items(
    environment_items: list[dict[str, Any]],
    selector_items: list[dict[str, Any]],
    file_items: list[dict[str, Any]],
    dependency_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [*environment_items, *selector_items, *file_items, *dependency_items]


def _owner_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        owner = str(item.get("owner_hint") or "unknown")
        counts[owner] = counts.get(owner, 0) + 1
    return dict(sorted(counts.items()))


def _environment_missing(item: dict[str, Any]) -> str:
    name = str(item.get("name") or "")
    gate = str(item.get("gate") or "")
    if gate == "playwright_smoke":
        return f"smoke_env:{name}"
    if gate == "full_google_run":
        return f"full_run_env:{name}"
    return f"environment:{name}"


def _file_issue(item: dict[str, Any], environment_missing: set[str]) -> str:
    name = str(item.get("name") or "")
    expected_type = str(item.get("expected_type") or "")
    present = item.get("present") is True
    if name == "MANUAL_BACKFILL_PATH" and (not present or item.get("is_file") is not True):
        if "full_run_env:MANUAL_BACKFILL_PATH" in environment_missing:
            return ""
        return f"file_gate:{name}:file_missing"
    if present and expected_type == "file" and item.get("is_file") is not True:
        return f"file_gate:{name}:file_missing"
    if present and expected_type == "directory" and item.get("is_dir") is not True:
        return f"file_gate:{name}:directory_missing"
    return ""


def _missing_by_owner(
    environment_items: list[dict[str, Any]],
    selector_items: list[dict[str, Any]],
    file_items: list[dict[str, Any]],
    dependency_items: list[dict[str, Any]],
) -> dict[str, list[str]]:
    owners: dict[str, list[str]] = {}
    environment_missing: set[str] = set()
    for item in environment_items:
        if item.get("required") is True and (item.get("present") is not True or item.get("truthy") is False):
            missing = _environment_missing(item)
            environment_missing.add(missing)
            owners.setdefault(str(item.get("owner_hint") or "unknown"), []).append(missing)
    for item in selector_items:
        if item.get("present") is not True:
            owners.setdefault(str(item.get("owner_hint") or "unknown"), []).append(
                f"selector_group:{item.get('group') or ''}"
            )
    for item in dependency_items:
        if item.get("present") is not True:
            owners.setdefault(str(item.get("owner_hint") or "unknown"), []).append(
                f"dependency:{item.get('name') or ''}"
            )
    for item in file_items:
        issue = _file_issue(item, environment_missing)
        if issue:
            owners.setdefault(str(item.get("owner_hint") or "unknown"), []).append(issue)
    return {owner: sorted(names) for owner, names in sorted(owners.items())}


def build_au_p0b_google_environment_request_packet(
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
    handoff = _as_dict(p0b_google_execution_checklist.get("environment_handoff"))
    environment_items = _environment_items(handoff)
    selector_items = _selector_items(handoff)
    file_items = _file_items(handoff)
    dependency_items = _dependency_items(handoff)
    all_items = _all_items(environment_items, selector_items, file_items, dependency_items)
    missing_required = _string_list(handoff.get("missing_required"))
    setup_commands = _string_list(handoff.get("setup_commands"))
    verification_commands = _string_list(handoff.get("verification_commands"))
    evidence_outputs = _string_list(handoff.get("evidence_outputs"))
    redaction_policy = _as_dict(handoff.get("redaction_policy"))
    packet_ready = verifier.get("status") == "pass" and verifier.get("hash_valid") is True

    hard_gate_commands = [
        "make au-p0b-google-environment-request",
        "make verify-au-p0b-google-environment-request",
        "make au-p0b-google-playwright-env",
        "make verify-au-p0b-google-playwright-env",
        "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_playwright_env_report.py "
        "${GENO_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-playwright-env-latest.json} --require-ready-smoke",
    ]

    payload: dict[str, Any] = {
        "p0b_google_environment_request_packet_version": PACKET_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if packet_ready else "fail",
        "google_environment_request_packet_ready": packet_ready,
        "environment_handoff_ready": handoff.get("ready") is True,
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
            "source_environment_handoff_version": str(handoff.get("version") or ""),
            "target_env_file": str(handoff.get("target_env_file") or ""),
            "environment_handoff_ready": handoff.get("ready") is True,
            "missing_required_count": len(missing_required),
            "missing_required": missing_required,
            "environment_item_count": len(environment_items),
            "selector_item_count": len(selector_items),
            "file_item_count": len(file_items),
            "dependency_item_count": len(dependency_items),
            "owner_counts": _owner_counts(all_items),
            "missing_required_by_owner": _missing_by_owner(
                environment_items,
                selector_items,
                file_items,
                dependency_items,
            ),
            "setup_command_count": len(setup_commands),
            "verification_command_count": len(verification_commands),
            "evidence_output_count": len(evidence_outputs),
            "env_file_hygiene_ready": _as_dict(p0b_google_execution_checklist.get("summary")).get(
                "env_file_hygiene_ready"
            )
            is True,
            "raw_secret_values_allowed": redaction_policy.get("raw_secret_values_allowed") is True,
            "forbidden_exact_secret_fields_redacted": redaction_policy.get("forbidden_exact_secret_fields_redacted")
            is True,
            "next_command": setup_commands[0] if setup_commands else "",
            "post_update_verification_command": verification_commands[0] if verification_commands else "",
            "google_next_action": str(p0b_google_execution_checklist.get("next_action") or ""),
        },
        "environment_items": environment_items,
        "selector_items": selector_items,
        "file_items": file_items,
        "dependency_items": dependency_items,
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
            "p0b_google_environment_request": "GET /v1/p0b-google-environment-request/au",
            "p0b_google_execution_checklist": "GET /v1/p0b-google-execution-checklist/au",
            "external_dependency_handoff": "GET /v1/external-dependency-handoff/au",
            "external_dependency_clearance": "GET /v1/external-dependency-clearance/au",
            "next_work_item": "GET /v1/next-work-item/au",
        },
        "hard_gate_commands": hard_gate_commands,
        "evidence_sources": [_source_file_entry("p0b_google_execution_checklist", p0b_google_execution_checklist_path)],
    }
    payload["p0b_google_environment_request_packet_hash"] = compute_p0b_google_environment_request_packet_hash(payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU P0b Google environment request packet JSON")
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
        default=os.environ.get("GENO_AU_P0B_GOOGLE_ENVIRONMENT_REQUEST_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU P0b Google environment request packet JSON.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    payload = build_au_p0b_google_environment_request_packet(
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
