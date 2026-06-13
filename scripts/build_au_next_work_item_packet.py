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

from scripts.build_au_handoff_dossier import (  # noqa: E402
    DEFAULT_MARKDOWN_OUTPUT_PATH as DEFAULT_HANDOFF_DOSSIER_MARKDOWN_PATH,
    DEFAULT_OUTPUT_PATH as DEFAULT_HANDOFF_DOSSIER_PATH,
    build_au_handoff_dossier,
)
from scripts.verify_au_handoff_dossier import verify_au_handoff_dossier  # noqa: E402


PACKET_VERSION = "au_next_work_item_packet_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-next-work-item-latest.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_next_work_item_packet_hash(packet: dict[str, Any]) -> str:
    payload = dict(packet)
    payload.pop("next_work_item_packet_hash", None)
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


def _append_unique(items: list[str], item: str) -> None:
    if item not in items:
        items.append(item)


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


def _load_or_build_handoff_dossier(
    path: Path,
    *,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        dossier = build_au_handoff_dossier(
            output_path=path,
            markdown_output_path=Path(DEFAULT_HANDOFF_DOSSIER_MARKDOWN_PATH),
            generated_at=generated_at,
        )
        return dossier, {"path": str(path), "exists": False, "source": "generated_in_memory", "errors": ["file_missing"]}
    except json.JSONDecodeError as exc:
        dossier = build_au_handoff_dossier(
            output_path=path,
            markdown_output_path=Path(DEFAULT_HANDOFF_DOSSIER_MARKDOWN_PATH),
            generated_at=generated_at,
        )
        return dossier, {
            "path": str(path),
            "exists": True,
            "source": "generated_in_memory",
            "errors": [f"json_invalid:{exc.msg}"],
        }
    if isinstance(payload, dict):
        return payload, {"path": str(path), "exists": True, "source": "existing_file"}
    dossier = build_au_handoff_dossier(
        output_path=path,
        markdown_output_path=Path(DEFAULT_HANDOFF_DOSSIER_MARKDOWN_PATH),
        generated_at=generated_at,
    )
    return dossier, {"path": str(path), "exists": True, "source": "generated_in_memory", "errors": ["not_json_object"]}


def build_au_next_work_item_packet(
    *,
    handoff_dossier_path: Path = Path(DEFAULT_HANDOFF_DOSSIER_PATH),
    handoff_dossier: dict[str, Any] | None = None,
    output_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if handoff_dossier is None:
        handoff_dossier, source = _load_or_build_handoff_dossier(handoff_dossier_path, generated_at=generated_at)
    else:
        source = {"path": str(handoff_dossier_path), "exists": True, "source": "provided_payload"}

    verifier = verify_au_handoff_dossier(handoff_dossier, path=handoff_dossier_path)
    summary = _as_dict(handoff_dossier.get("summary"))
    next_work_item = _as_dict(handoff_dossier.get("next_work_item"))
    next_work_item_id = str(summary.get("next_work_item_id") or next_work_item.get("id") or "none")
    commands = _string_list(next_work_item.get("commands"))
    verification_commands = _string_list(next_work_item.get("verification_commands"))
    evidence_outputs = _string_list(next_work_item.get("evidence_outputs"))
    blocked_customer_gate_ids = _string_list(
        _as_dict(handoff_dossier.get("customer_handoff_readiness_audit")).get("blocked_customer_gate_ids")
    )
    packet_ready = (
        verifier.get("status") == "pass"
        and verifier.get("hash_valid") is True
        and bool(next_work_item_id)
        and (next_work_item_id == "none" or next_work_item.get("id") == next_work_item_id)
    )

    hard_gate_commands = [
        "make au-next-work-item",
        "make verify-au-next-work-item",
        "make au-customer-handoff-readiness",
        "make verify-au-customer-handoff-readiness",
    ]
    _append_unique(
        hard_gate_commands,
        "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_customer_handoff_readiness.py "
        "${GENO_AU_CUSTOMER_HANDOFF_READINESS_OUTPUT_PATH:-docs/runtime_preflight/au-customer-handoff-readiness-latest.json} "
        "--require-customer-ready",
    )
    for command in verification_commands:
        _append_unique(hard_gate_commands, command)

    payload: dict[str, Any] = {
        "next_work_item_packet_version": PACKET_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if packet_ready else "fail",
        "next_work_item_packet_ready": packet_ready,
        "ready_for_customer_report_handoff": handoff_dossier.get("ready_for_customer_report_handoff") is True,
        "output_path": str(output_path) if output_path else "",
        "source_handoff_dossier": {
            "path": str(handoff_dossier_path),
            "handoff_dossier_version": handoff_dossier.get("handoff_dossier_version", ""),
            "handoff_dossier_hash": str(handoff_dossier.get("handoff_dossier_hash") or ""),
            "handoff_dossier_ready": handoff_dossier.get("handoff_dossier_ready") is True,
            "ready_for_customer_report_handoff": handoff_dossier.get("ready_for_customer_report_handoff") is True,
            "source": source,
        },
        "handoff_dossier_verifier": {
            "status": verifier.get("status", ""),
            "hash_valid": verifier.get("hash_valid") is True,
            "handoff_dossier_hash": str(verifier.get("handoff_dossier_hash") or ""),
            "errors": [str(value) for value in _as_list(verifier.get("errors"))],
            "handoff_posture": verifier.get("handoff_posture", ""),
            "remaining_blocker_count": int(verifier.get("remaining_blocker_count") or 0),
            "work_item_count": int(verifier.get("work_item_count") or 0),
            "next_work_item_id": str(verifier.get("next_work_item_id") or ""),
        },
        "summary": {
            "next_work_item_id": next_work_item_id,
            "next_action": str(summary.get("next_action") or next_work_item_id),
            "stage": str(next_work_item.get("stage") or ""),
            "title": str(next_work_item.get("title") or ""),
            "status": str(next_work_item.get("status") or ""),
            "dependency_class": str(next_work_item.get("dependency_class") or ""),
            "external_dependency": next_work_item.get("external_dependency") is True,
            "blocker_count": int(next_work_item.get("blocker_count") or 0),
            "remaining_blocker_count": int(summary.get("remaining_blocker_count") or 0),
            "external_dependency_blocker_count": int(summary.get("external_dependency_blocker_count") or 0),
            "customer_report_handoff_readiness_percent": _as_dict(
                handoff_dossier.get("customer_handoff_readiness_audit")
            ).get("customer_report_handoff_readiness_percent", 0.0),
            "structural_auditability_percent": _as_dict(
                handoff_dossier.get("customer_handoff_readiness_audit")
            ).get("structural_auditability_percent", 0.0),
            "runnable_now": bool(commands),
            "command_count": len(commands),
            "verification_command_count": len(verification_commands),
            "evidence_output_count": len(evidence_outputs),
            "blocked_customer_gate_count": len(blocked_customer_gate_ids),
            "blocked_customer_gate_ids": blocked_customer_gate_ids,
        },
        "next_work_item": next_work_item,
        "commands": commands,
        "verification_commands": verification_commands,
        "evidence_outputs": evidence_outputs,
        "runtime_endpoints": {
            "next_work_item": "GET /v1/next-work-item/au",
            "handoff_dossier": "GET /v1/handoff-dossier/au",
            "launch_status": "GET /v1/launch-status/au",
            "launch_remediation_plan": "GET /v1/launch-remediation-plan/au",
            "customer_handoff_readiness": "GET /v1/customer-handoff-readiness/au",
            "external_dependency_handoff": "GET /v1/external-dependency-handoff/au",
            "external_dependency_clearance": "GET /v1/external-dependency-clearance/au",
        },
        "hard_gate_commands": hard_gate_commands,
        "evidence_sources": [_source_file_entry("handoff_dossier", handoff_dossier_path)],
    }
    payload["next_work_item_packet_hash"] = compute_next_work_item_packet_hash(payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU next work item packet JSON")
    parser.add_argument(
        "--handoff-dossier-path",
        default=os.environ.get("GENO_AU_HANDOFF_DOSSIER_OUTPUT_PATH", DEFAULT_HANDOFF_DOSSIER_PATH),
        help="Path to the AU handoff dossier JSON.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GENO_AU_NEXT_WORK_ITEM_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU next work item packet JSON.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    payload = build_au_next_work_item_packet(
        handoff_dossier_path=Path(args.handoff_dossier_path),
        output_path=output_path,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if payload["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
