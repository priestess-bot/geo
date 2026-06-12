from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_au_p0b_google_playwright_smoke import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    SMOKE_VERSION,
    compute_smoke_payload_hash,
)


EXPECTED_COLLECTORS = {
    "google_aio": "google_aio.playwright",
    "google_ai_mode": "google_ai_mode.playwright",
}
EXPECTED_COLLECTOR_VERSION = "google-playwright-browser-v1"
EXPECTED_CAPTURE_TYPE = "google_browser_ui"
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _append_if(errors: list[str], condition: bool, error: str) -> None:
    if condition:
        errors.append(error)


def _is_hash(value: object) -> bool:
    return isinstance(value, str) and bool(HASH_PATTERN.fullmatch(value))


def _expected_collector(surface: object) -> str:
    return EXPECTED_COLLECTORS.get(str(surface or ""), "")


def _verify_success_payload(payload: dict[str, Any], errors: list[str]) -> None:
    evidence = _as_dict(payload.get("evidence"))
    answer_run = _as_dict(evidence.get("answer_run"))
    raw_answer = _as_dict(evidence.get("raw_answer"))
    raw_payload = _as_dict(raw_answer.get("raw_payload"))
    browser_capture = _as_dict(raw_payload.get("_geno_browser_capture"))
    asset_hashes = _as_dict(payload.get("evidence_asset_hashes"))
    evidence_asset_hashes = _as_dict(evidence.get("evidence_asset_hashes"))
    audit_events = evidence.get("audit_events") if isinstance(evidence.get("audit_events"), list) else []

    _append_if(errors, payload.get("phase") != "collection_completed", "success_phase_invalid")
    _append_if(errors, _as_int(payload.get("record_count")) != 1, "success_record_count_invalid")
    _append_if(errors, _as_int(payload.get("success_count")) != 1, "success_count_invalid")
    _append_if(errors, _as_int(payload.get("failure_count")) != 0, "success_failure_count_invalid")
    _append_if(errors, payload.get("answer_present") is not True, "answer_present_missing")
    _append_if(errors, payload.get("surface_triggered") is not True, "surface_triggered_missing")
    _append_if(errors, payload.get("collector_version") != EXPECTED_COLLECTOR_VERSION, "collector_version_invalid")
    _append_if(errors, not _is_hash(payload.get("raw_payload_hash")), "raw_payload_hash_invalid")
    _append_if(errors, not evidence, "evidence_missing")
    _append_if(errors, answer_run.get("collector_backend_id") != payload.get("collector_backend_id"), "answer_run_collector_mismatch")
    _append_if(errors, answer_run.get("surface") != payload.get("surface"), "answer_run_surface_mismatch")
    _append_if(errors, answer_run.get("access_method") != "browser", "answer_run_access_method_invalid")
    _append_if(errors, raw_answer.get("raw_payload_hash") != payload.get("raw_payload_hash"), "raw_answer_hash_mismatch")
    _append_if(errors, browser_capture.get("capture_type") != EXPECTED_CAPTURE_TYPE, "browser_capture_type_invalid")
    _append_if(errors, _as_int(evidence.get("asset_count")) < 2, "evidence_asset_count_too_low")
    _append_if(errors, _as_int(payload.get("asset_count")) < 2, "payload_asset_count_too_low")
    for asset_type in ("html_snapshot", "screenshot"):
        _append_if(errors, not _is_hash(asset_hashes.get(asset_type)), f"asset_hash_invalid:{asset_type}")
        _append_if(
            errors,
            asset_hashes.get(asset_type) != evidence_asset_hashes.get(asset_type),
            f"asset_hash_mismatch:{asset_type}",
        )
    _append_if(
        errors,
        not any(_as_dict(event).get("event_type") == "answer_run_collected" for event in audit_events),
        "answer_run_collected_audit_missing",
    )


def verify_google_playwright_smoke(
    payload: Any,
    *,
    path: Path | None = None,
    require_success: bool = False,
) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return {
            "status": "fail",
            "errors": ["smoke_payload_not_json_object"],
            "path": str(path) if path else "",
            "hash_valid": False,
            "smoke_status": "",
            "smoke_success": False,
        }

    expected_hash = payload.get("smoke_payload_hash")
    computed_hash = compute_smoke_payload_hash(payload)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("smoke_payload_hash_mismatch")

    surface = payload.get("surface")
    collector_backend_id = payload.get("collector_backend_id")
    smoke_status = str(payload.get("status") or "")
    phase = str(payload.get("phase") or "")
    collector_health = str(payload.get("collector_health") or "")

    _append_if(errors, payload.get("smoke_version") != SMOKE_VERSION, "smoke_version_invalid")
    _append_if(errors, payload.get("secrets_redacted") is not True, "secrets_redacted_missing")
    _append_if(errors, _as_int(payload.get("planned_runs")) != 1, "planned_runs_invalid")
    _append_if(errors, surface not in EXPECTED_COLLECTORS, "surface_invalid")
    _append_if(errors, collector_backend_id != _expected_collector(surface), "collector_backend_invalid")
    _append_if(errors, not collector_health and phase != "input_invalid", "collector_health_missing")
    _append_if(errors, smoke_status not in {"pass", "fail"}, "smoke_status_invalid")
    _append_if(errors, _as_int(payload.get("record_count")) not in {0, 1}, "record_count_invalid")
    _append_if(errors, _as_int(payload.get("success_count")) not in {0, 1}, "success_count_invalid")
    _append_if(errors, _as_int(payload.get("failure_count")) not in {0, 1}, "failure_count_invalid")

    smoke_success = smoke_status == "pass"
    if smoke_success:
        _verify_success_payload(payload, errors)
    elif require_success:
        errors.append("smoke_not_successful")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "smoke_version": payload.get("smoke_version"),
        "smoke_payload_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_smoke_payload_hash": computed_hash,
        "hash_valid": hash_valid,
        "smoke_status": smoke_status,
        "smoke_success": smoke_success,
        "phase": phase,
        "collector_health": collector_health,
        "surface": surface,
        "collector_backend_id": collector_backend_id,
        "planned_runs": payload.get("planned_runs"),
        "record_count": payload.get("record_count"),
        "success_count": payload.get("success_count"),
        "failure_count": payload.get("failure_count"),
        "answer_present": payload.get("answer_present"),
        "surface_triggered": payload.get("surface_triggered"),
        "citation_count": payload.get("citation_count"),
        "asset_count": payload.get("asset_count"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU P0b Google Playwright smoke payload")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_PLAYWRIGHT_SMOKE_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the Google Playwright smoke JSON payload.",
    )
    parser.add_argument(
        "--require-success",
        action="store_true",
        help="Fail unless the smoke payload contains one successful browser capture.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = Path(args.path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": ["google_playwright_smoke_file_missing"],
            "hash_valid": False,
            "smoke_success": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"google_playwright_smoke_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "smoke_success": False,
        }
    else:
        result = verify_google_playwright_smoke(payload, path=path, require_success=args.require_success)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
