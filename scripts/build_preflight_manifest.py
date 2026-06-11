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


DEFAULT_MANIFEST_PATH = "docs/runtime_preflight/api-preflight-manifest-latest.json"
DEFAULT_PREFLIGHT_PATH = "docs/runtime_preflight/api-preflight-latest.json"
MANIFEST_VERSION = "provider_preflight_evidence_manifest_v1"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def compute_manifest_payload_hash(manifest: dict[str, Any]) -> str:
    payload_for_hash = dict(manifest)
    payload_for_hash.pop("manifest_payload_hash", None)
    return hashlib.sha256(_stable_manifest_bytes(payload_for_hash)).hexdigest()


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def build_preflight_manifest(
    *,
    preflight_path: Path,
    payload: dict[str, Any],
    verifier: dict[str, Any],
    generated_at: str | None = None,
) -> dict[str, Any]:
    summary = _as_dict(payload.get("preflight_summary"))
    checklist = _as_dict(payload.get("preflight_audit_checklist"))
    manifest: dict[str, Any] = {
        "manifest_version": MANIFEST_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "preflight_payload": {
            "path": str(preflight_path),
            "size_bytes": preflight_path.stat().st_size,
            "file_sha256": _file_sha256(preflight_path),
            "payload_hash": payload.get("preflight_payload_hash", ""),
        },
        "verifier": verifier,
        "run_summary": {
            "mode": payload.get("mode", ""),
            "phase": summary.get("phase", ""),
            "exit_code": summary.get("exit_code"),
            "ready_for_design_partner": verifier.get("ready_for_design_partner", False),
            "recommended_next_action": summary.get("recommended_next_action", ""),
            "planned_runs": summary.get("planned_runs", payload.get("planned_runs")),
            "record_count": summary.get("record_count", payload.get("record_count")),
            "success_count": summary.get("success_count", payload.get("success_count")),
            "failure_count": summary.get("failure_count", payload.get("failure_count")),
            "cities": _as_list(summary.get("cities")),
            "sample_size": summary.get("sample_size"),
            "prompt_limit": summary.get("prompt_limit"),
        },
        "audit_checklist": {
            "overall_status": checklist.get("overall_status", ""),
            "blocking_reasons": _as_list(checklist.get("blocking_reasons")),
            "worker_args": _as_list(checklist.get("worker_args")),
            "evidence_refs": _as_dict(checklist.get("evidence_refs")),
            "run_totals": _as_dict(checklist.get("run_totals")),
        },
    }
    manifest["manifest_payload_hash"] = compute_manifest_payload_hash(manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an audit manifest for a GENO provider preflight JSON payload")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_API_PREFLIGHT_OUTPUT_PATH", DEFAULT_PREFLIGHT_PATH),
        help="Path to the preflight JSON payload.",
    )
    parser.add_argument(
        "--manifest-path",
        default=os.environ.get("GENO_API_PREFLIGHT_MANIFEST_PATH", DEFAULT_MANIFEST_PATH),
        help="Path to write the preflight evidence manifest.",
    )
    parser.add_argument(
        "--require-design-partner-ready",
        action="store_true",
        help="Mark the manifest command failed unless the preflight verifier proves design-partner readiness.",
    )
    parser.add_argument(
        "--generated-at",
        default=None,
        help="Override manifest generated_at timestamp, primarily for deterministic replay tests.",
    )
    return parser.parse_args()


def main() -> None:
    from scripts.verify_preflight_payload import verify_preflight_payload

    args = parse_args()
    preflight_path = Path(args.path)
    manifest_path = Path(args.manifest_path)
    try:
        payload = json.loads(preflight_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("preflight_payload_not_json_object")
    except FileNotFoundError:
        result = {
            "manifest_version": MANIFEST_VERSION,
            "generated_at": args.generated_at or _utc_now_iso(),
            "status": "fail",
            "errors": ["preflight_payload_file_missing"],
            "preflight_payload": {"path": str(preflight_path)},
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        raise SystemExit(2)
    except (json.JSONDecodeError, ValueError) as exc:
        result = {
            "manifest_version": MANIFEST_VERSION,
            "generated_at": args.generated_at or _utc_now_iso(),
            "status": "fail",
            "errors": [f"preflight_payload_invalid:{exc}"],
            "preflight_payload": {"path": str(preflight_path)},
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        raise SystemExit(2)

    verifier = verify_preflight_payload(
        payload,
        path=preflight_path,
        require_design_partner_ready=args.require_design_partner_ready,
    )
    manifest = build_preflight_manifest(
        preflight_path=preflight_path,
        payload=payload,
        verifier=verifier,
        generated_at=args.generated_at,
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if verifier["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
