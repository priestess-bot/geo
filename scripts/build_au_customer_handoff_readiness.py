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
    CUSTOMER_HANDOFF_READINESS_AUDIT_VERSION,
    build_au_handoff_dossier,
)
from scripts.au_trial_handoff import build_trial_handoff_audit, compact_trial_handoff_summary  # noqa: E402
from scripts.verify_au_handoff_dossier import verify_au_handoff_dossier  # noqa: E402


READINESS_VERSION = "au_customer_handoff_readiness_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-customer-handoff-readiness-latest.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_customer_handoff_readiness_hash(readiness: dict[str, Any]) -> str:
    payload = dict(readiness)
    payload.pop("customer_handoff_readiness_hash", None)
    return hashlib.sha256(_stable_bytes(payload)).hexdigest()


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


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _append_unique(commands: list[str], command: str) -> None:
    if command not in commands:
        commands.append(command)


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


def build_au_customer_handoff_readiness(
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
    audit = _as_dict(handoff_dossier.get("customer_handoff_readiness_audit"))
    source_hash = str(handoff_dossier.get("handoff_dossier_hash") or "")
    ready_for_customer = audit.get("customer_report_handoff_ready") is True
    readiness_audit_ready = (
        verifier.get("status") == "pass"
        and verifier.get("hash_valid") is True
        and audit.get("audit_version") == CUSTOMER_HANDOFF_READINESS_AUDIT_VERSION
    )
    trial_handoff_audit = build_trial_handoff_audit(
        launch_status=_as_dict(handoff_dossier.get("launch_status")),
        handoff_dossier=handoff_dossier,
        customer_handoff_package_manifest_ready=False,
    )
    trial_summary = compact_trial_handoff_summary(trial_handoff_audit)
    blocked_gate_ids = [str(value) for value in _as_list(audit.get("blocked_customer_gate_ids"))]
    hard_gate_commands = [str(value) for value in _as_list(audit.get("hard_gate_commands"))]
    _append_unique(hard_gate_commands, "make au-customer-handoff-readiness")
    _append_unique(hard_gate_commands, "make verify-au-customer-handoff-readiness")
    _append_unique(
        hard_gate_commands,
        "PYTHONPATH=packages/geo_core:apps/api python3 scripts/verify_au_customer_handoff_readiness.py "
        "${GEO_AU_CUSTOMER_HANDOFF_READINESS_OUTPUT_PATH:-docs/runtime_preflight/au-customer-handoff-readiness-latest.json} "
        "--require-customer-ready",
    )
    payload: dict[str, Any] = {
        "customer_handoff_readiness_version": READINESS_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if readiness_audit_ready else "fail",
        "readiness_audit_ready": readiness_audit_ready,
        "ready_for_customer_report_handoff": ready_for_customer,
        "ready_for_trial_customer_handoff": trial_summary["ready_for_trial_customer_handoff"],
        "output_path": str(output_path) if output_path else "",
        "source_handoff_dossier": {
            "path": str(handoff_dossier_path),
            "handoff_dossier_version": handoff_dossier.get("handoff_dossier_version", ""),
            "handoff_dossier_hash": source_hash,
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
            "customer_report_handoff_readiness_percent": audit.get(
                "customer_report_handoff_readiness_percent",
                0.0,
            ),
            "structural_auditability_percent": audit.get("structural_auditability_percent", 0.0),
            **trial_summary,
            "customer_ready_gate_count": audit.get("customer_ready_gate_count", 0),
            "customer_total_gate_count": audit.get("customer_total_gate_count", 0),
            "blocked_customer_gate_count": audit.get("blocked_customer_gate_count", 0),
            "blocked_customer_gate_ids": blocked_gate_ids,
            "structural_ready_gate_count": audit.get("structural_ready_gate_count", 0),
            "structural_total_gate_count": audit.get("structural_total_gate_count", 0),
            "next_action": audit.get("next_action", ""),
            "next_work_item_id": audit.get("next_work_item_id", ""),
            "remaining_blocker_count": audit.get("remaining_blocker_count", 0),
            "external_dependency_blocker_count": audit.get("external_dependency_blocker_count", 0),
            "readiness_statement": audit.get("readiness_statement", ""),
        },
        "readiness_audit": audit,
        "trial_handoff_audit": trial_handoff_audit,
        "runtime_endpoints": {
            "customer_handoff_readiness": "GET /v1/customer-handoff-readiness/au",
            "handoff_dossier": "GET /v1/handoff-dossier/au",
            "launch_status": "GET /v1/launch-status/au",
            "external_dependency_handoff": "GET /v1/external-dependency-handoff/au",
            "external_dependency_clearance": "GET /v1/external-dependency-clearance/au",
        },
        "hard_gate_commands": hard_gate_commands,
        "evidence_sources": [_source_file_entry("handoff_dossier", handoff_dossier_path)],
    }
    payload["customer_handoff_readiness_hash"] = compute_customer_handoff_readiness_hash(payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU customer handoff readiness JSON")
    parser.add_argument(
        "--handoff-dossier-path",
        default=os.environ.get("GEO_AU_HANDOFF_DOSSIER_OUTPUT_PATH", DEFAULT_HANDOFF_DOSSIER_PATH),
        help="Path to the AU handoff dossier JSON.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GEO_AU_CUSTOMER_HANDOFF_READINESS_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU customer handoff readiness JSON.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    payload = build_au_customer_handoff_readiness(
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
