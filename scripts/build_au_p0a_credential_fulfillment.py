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

from scripts.build_au_p0a_credential_request_packet import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_CREDENTIAL_REQUEST_PATH,
    build_au_p0a_credential_request_packet,
)
from scripts.build_au_p0a_env_report import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_ENV_REPORT_PATH,
    build_au_p0a_env_report,
)
from scripts.verify_au_p0a_credential_request_packet import verify_au_p0a_credential_request_packet  # noqa: E402
from scripts.verify_au_p0a_env_report import verify_au_p0a_env_report  # noqa: E402


FULFILLMENT_VERSION = "au_p0a_credential_fulfillment_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0a-credential-fulfillment-latest.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compute_p0a_credential_fulfillment_hash(payload: dict[str, Any]) -> str:
    payload_for_hash = dict(payload)
    payload_for_hash.pop("p0a_credential_fulfillment_hash", None)
    return hashlib.sha256(_stable_bytes(payload_for_hash)).hexdigest()


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _strings(value: object) -> list[str]:
    return [str(item) for item in _as_list(value)]


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
    return payload, {
        "path": str(path),
        "exists": True,
        "source": "existing_file",
        "file_sha256": _file_sha256(path),
        "errors": [],
    }


def _load_or_build_credential_request(
    path: Path,
    *,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if payload is not None:
        return payload, source
    request = build_au_p0a_credential_request_packet(output_path=path, generated_at=generated_at)
    return request, {**source, "source": "generated_in_memory"}


def _load_or_build_env_report(
    path: Path,
    *,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if payload is not None:
        return payload, source
    report = build_au_p0a_env_report(output_path=path, generated_at=generated_at)
    return report, {**source, "source": "generated_in_memory"}


def _credential_request_items(credential_request: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("name") or ""): _as_dict(item)
        for item in [_as_dict(value) for value in _as_list(credential_request.get("requested_credentials"))]
        if str(item.get("name") or "")
    }


def _env_checks(env_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    checks: dict[str, dict[str, Any]] = {}
    for item in [_as_dict(value) for value in _as_list(env_report.get("required"))]:
        name = str(item.get("name") or "")
        if name:
            checks[name] = item
    return checks


def _fulfillment_items(credential_request: dict[str, Any], env_report: dict[str, Any]) -> list[dict[str, Any]]:
    request_items = _credential_request_items(credential_request)
    env_items = _env_checks(env_report)
    names = sorted(set(request_items) | set(env_items))
    items: list[dict[str, Any]] = []
    for name in names:
        requested = request_items.get(name, {})
        env_check = env_items.get(name, {})
        requested_present = requested.get("present") is True
        env_present = env_check.get("present") is True
        mismatch = requested_present != env_present
        fulfilled = requested.get("required") is True and requested_present and env_present and not mismatch
        blocking_reasons: list[str] = []
        if not requested:
            blocking_reasons.append("credential_request_item_missing")
        if not env_check:
            blocking_reasons.append("environment_check_missing")
        if requested.get("required") is True and not requested_present:
            blocking_reasons.append("credential_request_missing")
        if requested.get("required") is True and not env_present:
            blocking_reasons.append("environment_value_missing")
        if mismatch:
            blocking_reasons.append("request_env_presence_mismatch")
        items.append(
            {
                "name": name,
                "required": requested.get("required") is True,
                "fulfilled": fulfilled,
                "requested_present": requested_present,
                "environment_present": env_present,
                "presence_mismatch": mismatch,
                "request_source": str(requested.get("source") or "missing"),
                "environment_source": str(env_check.get("source") or "missing"),
                "owner_hint": str(requested.get("owner_hint") or "unknown"),
                "env_file_key": str(requested.get("env_file_key") or name),
                "value_length": int(env_check.get("value_length") or requested.get("value_length") or 0),
                "sha256_prefix": str(env_check.get("sha256_prefix") or requested.get("sha256_prefix") or ""),
                "secret_redacted": requested.get("secret_redacted") is True and env_check.get("secret_redacted") is True,
                "accepted_injection_methods": _strings(requested.get("accepted_injection_methods")),
                "post_update_checks": _strings(requested.get("post_update_checks")),
                "blocking_reasons": blocking_reasons,
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
            owners.setdefault(owner, []).append(str(item.get("name") or ""))
    return {owner: sorted(names) for owner, names in sorted(owners.items())}


def _next_action(*, env_ready: bool, missing: list[str], mismatched: list[str]) -> str:
    if missing:
        return "populate_required_environment"
    if mismatched:
        return "refresh_p0a_execution_checklist_and_credential_request"
    if not env_ready:
        return "fix_au_p0a_env_report"
    return "run_p0a_credential_strict_gate"


def build_au_p0a_credential_fulfillment(
    *,
    credential_request_path: Path = Path(DEFAULT_CREDENTIAL_REQUEST_PATH),
    env_report_path: Path = Path(DEFAULT_ENV_REPORT_PATH),
    credential_request: dict[str, Any] | None = None,
    env_report: dict[str, Any] | None = None,
    output_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if credential_request is None:
        credential_request, credential_source = _load_or_build_credential_request(
            credential_request_path,
            generated_at=generated_at,
        )
    else:
        credential_source = {"path": str(credential_request_path), "exists": True, "source": "provided_payload", "errors": []}
    if env_report is None:
        env_report, env_source = _load_or_build_env_report(env_report_path, generated_at=generated_at)
    else:
        env_source = {"path": str(env_report_path), "exists": True, "source": "provided_payload", "errors": []}

    request_verifier = verify_au_p0a_credential_request_packet(credential_request, path=credential_request_path)
    env_verifier = verify_au_p0a_env_report(env_report, path=env_report_path)
    items = _fulfillment_items(credential_request, env_report)
    required_items = [item for item in items if item.get("required") is True]
    fulfilled_required = [item for item in required_items if item.get("fulfilled") is True]
    missing_required = [str(item.get("name") or "") for item in required_items if item.get("fulfilled") is not True]
    mismatched = [str(item.get("name") or "") for item in items if item.get("presence_mismatch") is True]
    credentials_fulfilled = bool(required_items) and len(fulfilled_required) == len(required_items) and not mismatched
    env_ready = env_verifier.get("ready_for_real_batch") is True
    fulfillment_ready = (
        request_verifier.get("status") == "pass"
        and request_verifier.get("hash_valid") is True
        and env_verifier.get("status") == "pass"
        and env_verifier.get("hash_valid") is True
    )
    summary = {
        "credentials_fulfilled": credentials_fulfilled,
        "credential_handoff_ready": credential_request.get("credential_handoff_ready") is True,
        "environment_ready": env_ready,
        "required_count": len(required_items),
        "fulfilled_required_count": len(fulfilled_required),
        "missing_required_count": len(missing_required),
        "missing_required": sorted(missing_required),
        "presence_mismatch_count": len(mismatched),
        "presence_mismatches": sorted(mismatched),
        "owner_counts": _owner_counts(items),
        "missing_required_by_owner": _missing_by_owner(items),
        "next_action": _next_action(env_ready=env_ready, missing=missing_required, mismatched=mismatched),
        "next_command": "make au-p0a-env" if missing_required else "make verify-au-p0a-credential-fulfillment",
        "strict_gate_command": (
            "PYTHONPATH=packages/geo_core:apps/api python3 "
            "scripts/verify_au_p0a_credential_fulfillment.py "
            "${GEO_AU_P0A_CREDENTIAL_FULFILLMENT_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-credential-fulfillment-latest.json} "
            "--require-fulfilled"
        ),
        "raw_secret_values_allowed": False,
    }

    payload: dict[str, Any] = {
        "p0a_credential_fulfillment_version": FULFILLMENT_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if fulfillment_ready else "fail",
        "credential_fulfillment_ready": fulfillment_ready,
        "credentials_fulfilled": credentials_fulfilled,
        "ready_for_design_partner": (
            credentials_fulfilled
            and credential_request.get("ready_for_design_partner") is True
            and env_report.get("ready_for_real_batch") is True
        ),
        "output_path": str(output_path) if output_path else "",
        "source_p0a_credential_request": {
            "path": str(credential_request_path),
            "source": credential_source,
            "p0a_credential_request_packet_hash": str(
                credential_request.get("p0a_credential_request_packet_hash") or ""
            ),
            "credential_request_packet_ready": credential_request.get("credential_request_packet_ready") is True,
            "credential_handoff_ready": credential_request.get("credential_handoff_ready") is True,
        },
        "source_p0a_env_report": {
            "path": str(env_report_path),
            "source": env_source,
            "environment_report_hash": str(env_report.get("environment_report_hash") or ""),
            "ready_for_real_batch": env_report.get("ready_for_real_batch") is True,
            "missing_required": _strings(env_report.get("missing_required")),
        },
        "p0a_credential_request_verifier": {
            "status": request_verifier.get("status", ""),
            "hash_valid": request_verifier.get("hash_valid") is True,
            "p0a_credential_request_packet_hash": str(
                request_verifier.get("p0a_credential_request_packet_hash") or ""
            ),
            "credential_handoff_ready": request_verifier.get("credential_handoff_ready") is True,
            "errors": _strings(request_verifier.get("errors")),
        },
        "p0a_env_report_verifier": {
            "status": env_verifier.get("status", ""),
            "hash_valid": env_verifier.get("hash_valid") is True,
            "environment_report_hash": str(env_verifier.get("environment_report_hash") or ""),
            "ready_for_real_batch": env_verifier.get("ready_for_real_batch") is True,
            "missing_required": _strings(env_verifier.get("missing_required")),
            "env_file_hygiene_ready": env_verifier.get("env_file_hygiene_ready") is True,
            "errors": _strings(env_verifier.get("errors")),
        },
        "summary": summary,
        "credential_fulfillment_items": items,
        "verification_commands": [
            "make au-p0a-credential-request",
            "make verify-au-p0a-credential-request",
            "make au-p0a-env",
            "make verify-au-p0a-env",
            "make verify-au-p0a-credential-fulfillment",
        ],
        "hard_gate_commands": [
            "make verify-au-p0a-credential-fulfillment",
            "PYTHONPATH=packages/geo_core:apps/api python3 scripts/verify_au_p0a_credential_fulfillment.py "
            "${GEO_AU_P0A_CREDENTIAL_FULFILLMENT_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-credential-fulfillment-latest.json} "
            "--require-fulfilled",
            "PYTHONPATH=packages/geo_core:apps/api python3 scripts/verify_au_p0a_env_report.py "
            "${GEO_AU_P0A_ENV_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-env-latest.json} --require-ready-environment",
            "PYTHONPATH=packages/geo_core:apps/api python3 scripts/verify_au_p0a_credential_request_packet.py "
            "${GEO_AU_P0A_CREDENTIAL_REQUEST_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-credential-request-latest.json} "
            "--require-credentials-ready",
        ],
        "runtime_endpoints": {
            "p0a_credential_fulfillment": "GET /v1/p0a-credential-fulfillment/au",
            "p0a_credential_request": "GET /v1/p0a-credential-request/au",
            "p0a_environment_checklist": "GET /v1/p0a-environment-checklist/au",
            "external_dependency_clearance": "GET /v1/external-dependency-clearance/au",
        },
        "redaction_policy": {
            "raw_secret_values_allowed": False,
            "recorded_fields": ["present", "source", "value_length", "sha256_prefix", "secret_redacted"],
            "forbidden_exact_secret_field_count": 5,
            "secret_redacted": True,
        },
    }
    payload["p0a_credential_fulfillment_hash"] = compute_p0a_credential_fulfillment_hash(payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU P0a credential fulfillment JSON")
    parser.add_argument(
        "--credential-request-path",
        default=os.environ.get("GEO_AU_P0A_CREDENTIAL_REQUEST_OUTPUT_PATH", DEFAULT_CREDENTIAL_REQUEST_PATH),
        help="Path to the AU P0a credential request packet JSON.",
    )
    parser.add_argument(
        "--env-report-path",
        default=os.environ.get("GEO_AU_P0A_ENV_OUTPUT_PATH", DEFAULT_ENV_REPORT_PATH),
        help="Path to the AU P0a environment report JSON.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GEO_AU_P0A_CREDENTIAL_FULFILLMENT_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU P0a credential fulfillment JSON.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    payload = build_au_p0a_credential_fulfillment(
        credential_request_path=Path(args.credential_request_path),
        env_report_path=Path(args.env_report_path),
        output_path=output_path,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if payload["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
