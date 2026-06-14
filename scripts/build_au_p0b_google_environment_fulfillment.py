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

from scripts.build_au_p0b_google_environment_request_packet import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_ENVIRONMENT_REQUEST_PATH,
    build_au_p0b_google_environment_request_packet,
)
from scripts.build_au_p0b_google_playwright_env_report import (  # noqa: E402
    DEFAULT_ENV_FILE as DEFAULT_PLAYWRIGHT_ENV_FILE,
    DEFAULT_OUTPUT_PATH as DEFAULT_PLAYWRIGHT_ENV_REPORT_PATH,
    build_google_playwright_env_report,
)
from scripts.verify_au_p0b_google_environment_request_packet import (  # noqa: E402
    verify_au_p0b_google_environment_request_packet,
)
from scripts.verify_au_p0b_google_playwright_env_report import verify_google_playwright_env_report  # noqa: E402


FULFILLMENT_VERSION = "au_p0b_google_environment_fulfillment_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0b-google-environment-fulfillment-latest.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_p0b_google_environment_fulfillment_hash(payload: dict[str, Any]) -> str:
    payload_for_hash = dict(payload)
    payload_for_hash.pop("p0b_google_environment_fulfillment_hash", None)
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


def _request_item_key(kind: str, item: dict[str, Any]) -> str:
    if kind == "selector":
        return str(item.get("group") or "")
    return str(item.get("name") or "")


def _request_items(environment_request: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items: dict[str, dict[str, Any]] = {}
    for kind, field in (
        ("environment", "environment_items"),
        ("selector", "selector_items"),
        ("file", "file_items"),
        ("dependency", "dependency_items"),
    ):
        for value in _as_list(environment_request.get(field)):
            item = _as_dict(value)
            key = _request_item_key(kind, item)
            if key:
                items[f"{kind}:{key}"] = {**item, "item_type": kind, "item_key": key}
    return items


def _env_report_items(env_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items: dict[str, dict[str, Any]] = {}
    for field in ("required", "full_run_required"):
        for value in _as_list(env_report.get(field)):
            item = _as_dict(value)
            name = str(item.get("name") or "")
            if name:
                items[f"environment:{name}"] = {**item, "item_type": "environment", "item_key": name}
    for value in _as_list(env_report.get("selector_groups")):
        item = _as_dict(value)
        group = str(item.get("group") or "")
        if group:
            items[f"selector:{group}"] = {**item, "item_type": "selector", "item_key": group}
    for value in _as_list(env_report.get("file_checks")):
        item = _as_dict(value)
        name = str(item.get("name") or "")
        if name:
            items[f"file:{name}"] = {**item, "item_type": "file", "item_key": name}
    for value in _as_list(env_report.get("dependency_checks")):
        item = _as_dict(value)
        name = str(item.get("name") or "")
        if name:
            items[f"dependency:{name}"] = {**item, "item_type": "dependency", "item_key": name}
    return items


def _request_present(item: dict[str, Any]) -> bool:
    item_type = str(item.get("item_type") or "")
    if item_type == "environment":
        if item.get("required") is True and item.get("truthy") is False:
            return False
        return item.get("present") is True
    if item_type == "selector":
        return item.get("present") is True
    if item_type == "file":
        if item.get("present") is not True:
            return False
        expected_type = str(item.get("expected_type") or "")
        if expected_type == "file":
            return item.get("is_file") is True
        if expected_type == "directory":
            return item.get("is_dir") is True
        return item.get("exists") is True
    if item_type == "dependency":
        return item.get("present") is True
    return False


def _environment_present(item: dict[str, Any]) -> bool:
    item_type = str(item.get("item_type") or "")
    if item_type == "environment":
        if item.get("item_key") == "GOOGLE_PLAYWRIGHT_ENABLED" and item.get("truthy") is not True:
            return False
        return item.get("present") is True
    if item_type == "selector":
        return item.get("present") is True
    if item_type == "file":
        if item.get("present") is not True:
            return False
        expected_type = str(item.get("expected_type") or "")
        if expected_type == "file":
            return item.get("is_file") is True
        if expected_type == "directory":
            return item.get("is_dir") is True
        return item.get("exists") is True
    if item_type == "dependency":
        return item.get("present") is True
    return False


def _required(item: dict[str, Any]) -> bool:
    item_type = str(item.get("item_type") or "")
    if item_type in {"environment", "selector"}:
        return True
    if item_type == "file":
        return str(item.get("name") or item.get("item_key") or "") == "MANUAL_BACKFILL_PATH"
    if item_type == "dependency":
        return True
    return False


def _owner_hint(request_item: dict[str, Any]) -> str:
    return str(request_item.get("owner_hint") or "runtime_operator")


def _fulfillment_items(environment_request: dict[str, Any], env_report: dict[str, Any]) -> list[dict[str, Any]]:
    request_items = _request_items(environment_request)
    env_items = _env_report_items(env_report)
    keys = sorted(set(request_items) | set(env_items))
    items: list[dict[str, Any]] = []
    for key in keys:
        requested = request_items.get(key, {})
        env_item = env_items.get(key, {})
        item_type, _, item_key = key.partition(":")
        requested_present = _request_present(requested) if requested else False
        environment_present = _environment_present(env_item) if env_item else False
        presence_mismatch = requested_present != environment_present
        required = _required({**env_item, **requested, "item_type": item_type, "item_key": item_key})
        fulfilled = required and requested_present and environment_present and not presence_mismatch
        blocking_reasons: list[str] = []
        if not requested:
            blocking_reasons.append("environment_request_item_missing")
        if not env_item:
            blocking_reasons.append("playwright_env_check_missing")
        if required and not requested_present:
            blocking_reasons.append("environment_request_missing")
        if required and not environment_present:
            blocking_reasons.append("playwright_env_value_missing")
        if presence_mismatch:
            blocking_reasons.append("request_env_presence_mismatch")
        items.append(
            {
                "key": key,
                "item_type": item_type,
                "name": item_key,
                "required": required,
                "fulfilled": fulfilled,
                "requested_present": requested_present,
                "environment_present": environment_present,
                "presence_mismatch": presence_mismatch,
                "request_source": str(requested.get("source") or "missing"),
                "environment_source": str(env_item.get("source") or "missing"),
                "owner_hint": _owner_hint(requested),
                "env_file_key": str(requested.get("env_file_key") or item_key),
                "expected_type": str(requested.get("expected_type") or env_item.get("expected_type") or ""),
                "truthy": env_item.get("truthy") if isinstance(env_item.get("truthy"), bool) else requested.get("truthy"),
                "value_length": int(env_item.get("value_length") or requested.get("value_length") or 0),
                "sha256_prefix": str(env_item.get("sha256_prefix") or requested.get("sha256_prefix") or ""),
                "secret_redacted": requested.get("secret_redacted") is True and env_item.get("secret_redacted") is True,
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
            owners.setdefault(owner, []).append(str(item.get("key") or ""))
    return {owner: sorted(names) for owner, names in sorted(owners.items())}


def _next_action(*, env_ready: bool, missing: list[str], mismatched: list[str]) -> str:
    if missing:
        return "populate_google_environment_inputs"
    if mismatched:
        return "refresh_p0b_google_environment_request"
    if not env_ready:
        return "fix_google_playwright_env_report"
    return "run_p0b_google_environment_strict_gate"


def build_au_p0b_google_environment_fulfillment(
    *,
    environment_request_path: Path = Path(DEFAULT_ENVIRONMENT_REQUEST_PATH),
    playwright_env_report_path: Path = Path(DEFAULT_PLAYWRIGHT_ENV_REPORT_PATH),
    playwright_env_file_path: Path | None = Path(DEFAULT_PLAYWRIGHT_ENV_FILE),
    environment_request: dict[str, Any] | None = None,
    playwright_env_report: dict[str, Any] | None = None,
    output_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if environment_request is None:
        environment_request, request_source = _load_or_build_environment_request(
            environment_request_path,
            generated_at=generated_at,
        )
    else:
        request_source = {"path": str(environment_request_path), "exists": True, "source": "provided_payload", "errors": []}
    if playwright_env_report is None:
        playwright_env_report, env_source = _load_or_build_playwright_env_report(
            playwright_env_report_path,
            env_file_path=playwright_env_file_path,
            generated_at=generated_at,
        )
    else:
        env_source = {"path": str(playwright_env_report_path), "exists": True, "source": "provided_payload", "errors": []}

    request_verifier = verify_au_p0b_google_environment_request_packet(environment_request, path=environment_request_path)
    env_verifier = verify_google_playwright_env_report(playwright_env_report, path=playwright_env_report_path)
    items = _fulfillment_items(environment_request, playwright_env_report)
    required_items = [item for item in items if item.get("required") is True]
    fulfilled_required = [item for item in required_items if item.get("fulfilled") is True]
    missing_required = [str(item.get("key") or "") for item in required_items if item.get("fulfilled") is not True]
    mismatched = [str(item.get("key") or "") for item in items if item.get("presence_mismatch") is True]
    environment_fulfilled = bool(required_items) and len(fulfilled_required) == len(required_items) and not mismatched
    request_ready = request_verifier.get("status") == "pass" and request_verifier.get("hash_valid") is True
    env_ready = env_verifier.get("status") == "pass" and env_verifier.get("hash_valid") is True
    fulfillment_ready = request_ready and env_ready
    ready_for_smoke = env_verifier.get("ready_for_playwright_smoke") is True
    ready_for_full_run = env_verifier.get("ready_for_full_google_run") is True
    summary = {
        "environment_fulfilled": environment_fulfilled,
        "environment_handoff_ready": environment_request.get("environment_handoff_ready") is True,
        "playwright_env_ready_for_smoke": ready_for_smoke,
        "playwright_env_ready_for_full_google_run": ready_for_full_run,
        "required_count": len(required_items),
        "fulfilled_required_count": len(fulfilled_required),
        "missing_required_count": len(missing_required),
        "missing_required": sorted(missing_required),
        "presence_mismatch_count": len(mismatched),
        "presence_mismatches": sorted(mismatched),
        "owner_counts": _owner_counts(items),
        "missing_required_by_owner": _missing_by_owner(items),
        "cross_stage_reuse_hint_count": len(_as_list(environment_request.get("cross_stage_reuse_hints"))),
        "database_url_reuse_available": _as_dict(environment_request.get("summary")).get("database_url_reuse_available")
        is True,
        "next_action": _next_action(env_ready=ready_for_smoke, missing=missing_required, mismatched=mismatched),
        "next_command": "make au-p0b-google-playwright-env"
        if missing_required
        else "make verify-au-p0b-google-environment-fulfillment",
        "strict_gate_command": (
            "PYTHONPATH=packages/geno_core:apps/api python3 "
            "scripts/verify_au_p0b_google_environment_fulfillment.py "
            "${GENO_AU_P0B_GOOGLE_ENVIRONMENT_FULFILLMENT_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-environment-fulfillment-latest.json} "
            "--require-fulfilled"
        ),
        "ready_smoke_strict_gate_command": (
            "PYTHONPATH=packages/geno_core:apps/api python3 "
            "scripts/verify_au_p0b_google_playwright_env_report.py "
            "${GENO_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-playwright-env-latest.json} "
            "--require-ready-smoke"
        ),
        "raw_secret_values_allowed": False,
    }

    payload: dict[str, Any] = {
        "p0b_google_environment_fulfillment_version": FULFILLMENT_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if fulfillment_ready else "fail",
        "environment_fulfillment_ready": fulfillment_ready,
        "environment_fulfilled": environment_fulfilled,
        "ready_for_playwright_smoke": environment_fulfilled and ready_for_smoke,
        "ready_for_full_google_run": environment_fulfilled and ready_for_full_run,
        "google_main_scoring_allowed": (
            environment_fulfilled
            and ready_for_full_run
            and environment_request.get("google_main_scoring_allowed") is True
        ),
        "output_path": str(output_path) if output_path else "",
        "source_p0b_google_environment_request": {
            "path": str(environment_request_path),
            "source": request_source,
            "p0b_google_environment_request_packet_hash": str(
                environment_request.get("p0b_google_environment_request_packet_hash") or ""
            ),
            "google_environment_request_packet_ready": environment_request.get(
                "google_environment_request_packet_ready"
            )
            is True,
            "environment_handoff_ready": environment_request.get("environment_handoff_ready") is True,
            "google_main_scoring_allowed": environment_request.get("google_main_scoring_allowed") is True,
        },
        "source_p0b_google_playwright_env_report": {
            "path": str(playwright_env_report_path),
            "source": env_source,
            "environment_report_hash": str(playwright_env_report.get("environment_report_hash") or ""),
            "ready_for_playwright_smoke": playwright_env_report.get("ready_for_playwright_smoke") is True,
            "ready_for_full_google_run": playwright_env_report.get("ready_for_full_google_run") is True,
            "missing_required": _strings(playwright_env_report.get("missing_required")),
            "missing_full_run_required": _strings(playwright_env_report.get("missing_full_run_required")),
            "missing_selector_groups": _strings(playwright_env_report.get("missing_selector_groups")),
        },
        "p0b_google_environment_request_verifier": {
            "status": request_verifier.get("status", ""),
            "hash_valid": request_verifier.get("hash_valid") is True,
            "p0b_google_environment_request_packet_hash": str(
                request_verifier.get("p0b_google_environment_request_packet_hash") or ""
            ),
            "google_environment_request_packet_ready": request_verifier.get(
                "google_environment_request_packet_ready"
            )
            is True,
            "environment_handoff_ready": request_verifier.get("environment_handoff_ready") is True,
            "errors": _strings(request_verifier.get("errors")),
        },
        "p0b_google_playwright_env_report_verifier": {
            "status": env_verifier.get("status", ""),
            "hash_valid": env_verifier.get("hash_valid") is True,
            "environment_report_hash": str(env_verifier.get("environment_report_hash") or ""),
            "ready_for_playwright_smoke": env_verifier.get("ready_for_playwright_smoke") is True,
            "ready_for_full_google_run": env_verifier.get("ready_for_full_google_run") is True,
            "collector_health": str(env_verifier.get("collector_health") or ""),
            "missing_required": _strings(env_verifier.get("missing_required")),
            "missing_full_run_required": _strings(env_verifier.get("missing_full_run_required")),
            "missing_selector_groups": _strings(env_verifier.get("missing_selector_groups")),
            "env_file_hygiene_ready": env_verifier.get("env_file_hygiene_ready") is True,
            "errors": _strings(env_verifier.get("errors")),
        },
        "summary": summary,
        "environment_fulfillment_items": items,
        "verification_commands": [
            "make au-p0b-google-environment-request",
            "make verify-au-p0b-google-environment-request",
            "make au-p0b-google-playwright-env",
            "make verify-au-p0b-google-playwright-env",
            "make verify-au-p0b-google-environment-fulfillment",
        ],
        "hard_gate_commands": [
            "make verify-au-p0b-google-environment-fulfillment",
            summary["strict_gate_command"],
            summary["ready_smoke_strict_gate_command"],
        ],
        "runtime_endpoints": {
            "p0b_google_environment_fulfillment": "GET /v1/p0b-google-environment-fulfillment/au",
            "p0b_google_environment_request": "GET /v1/p0b-google-environment-request/au",
            "p0b_google_execution_checklist": "GET /v1/p0b-google-execution-checklist/au",
            "external_dependency_clearance": "GET /v1/external-dependency-clearance/au",
        },
        "redaction_policy": {
            "raw_secret_values_allowed": False,
            "recorded_fields": [
                "present",
                "source",
                "truthy",
                "exists",
                "is_file",
                "is_dir",
                "value_length",
                "sha256_prefix",
                "secret_redacted",
            ],
            "forbidden_exact_secret_field_count": 8,
            "secret_redacted": True,
        },
    }
    payload["p0b_google_environment_fulfillment_hash"] = compute_p0b_google_environment_fulfillment_hash(payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU P0b Google environment fulfillment JSON")
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
        "--env-file",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_ENV_FILE", DEFAULT_PLAYWRIGHT_ENV_FILE),
        help="Optional env file to parse if the Playwright environment report must be generated in memory.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_ENVIRONMENT_FULFILLMENT_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU P0b Google environment fulfillment JSON.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    payload = build_au_p0b_google_environment_fulfillment(
        environment_request_path=Path(args.environment_request_path),
        playwright_env_report_path=Path(args.playwright_env_report_path),
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
