from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from geo_core.bootstrap import build_au_project_bootstrap
from geo_core.google_spike import (
    GOOGLE_SPIKE_GEO_CITIES,
    GOOGLE_SPIKE_SAMPLE_SIZE,
    select_google_spike_prompts,
)


DEFAULT_INPUT_PATH = "docs/runtime_preflight/au-p0b-google-manual-backfill-template.jsonl"
DEFAULT_VERIFICATION_PATH = "docs/runtime_preflight/au-p0b-google-manual-backfill-verification-latest.json"
VERIFIER_VERSION = "au_p0b_manual_backfill_verifier_v1"
REQUIRED_VERIFICATION_FIELDS = (
    "verifier_version",
    "status",
    "errors",
    "path",
    "file_sha256",
    "allow_template_placeholders",
    "expected_prompt_city_count",
    "expected_sample_size",
    "expected_record_count",
    "record_count",
    "covered_prompt_city_count",
    "missing_prompt_city_sample_count",
    "duplicate_prompt_city_sample_count",
    "unexpected_prompt_city_record_count",
    "missing_answer_line_count",
    "missing_citation_line_count",
    "missing_asset_line_count",
    "summary",
    "verification_hash",
)
FORBIDDEN_MANUAL_FIELDS = {
    "answer_text",
    "answer",
    "citation_urls",
    "citations",
    "sources",
    "screenshot_url",
    "screenshot",
    "html_snapshot_url",
    "html_snapshot",
    "raw_answer",
    "raw_citation",
    "raw_asset_url",
}


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable_verification_bytes(result: dict[str, Any]) -> bytes:
    return json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_manual_backfill_verification_hash(result: dict[str, Any]) -> str:
    payload = dict(result)
    payload.pop("verification_hash", None)
    return hashlib.sha256(_stable_verification_bytes(payload)).hexdigest()


def _entry_text(entry: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _entry_urls(entry: dict[str, Any]) -> list[str]:
    raw_urls = entry.get("citation_urls") or entry.get("citations") or entry.get("sources") or []
    urls: list[str] = []
    if isinstance(raw_urls, str):
        raw_urls = [raw_urls]
    if isinstance(raw_urls, list):
        for item in raw_urls:
            if isinstance(item, str):
                url = item.strip()
            elif isinstance(item, dict) and isinstance(item.get("url"), str):
                url = str(item["url"]).strip()
            else:
                continue
            if url:
                urls.append(url)
    return urls


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _strings(value: object) -> list[str]:
    return [str(item) for item in _as_list(value)]


def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _find_forbidden_fields(value: object, *, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in FORBIDDEN_MANUAL_FIELDS:
                findings.append(child_path)
            findings.extend(_find_forbidden_fields(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_find_forbidden_fields(child, path=f"{path}[{index}]"))
    return findings


def _next_action(*, status: str, errors: list[str], allow_template_placeholders: bool) -> str:
    if status == "pass" and not allow_template_placeholders:
        return "build_manual_backfill_fulfillment"
    if status == "pass" and allow_template_placeholders:
        return "complete_manual_backfill_jsonl"
    if any(error.startswith("manual_backfill_file_missing") for error in errors):
        return "build_manual_backfill_template"
    if any(error.startswith(("jsonl_invalid", "jsonl_line_not_object")) for error in errors):
        return "fix_manual_backfill_jsonl"
    if any(
        error.startswith(("record_count_invalid", "missing_prompt_city_samples", "duplicate_prompt_city_samples", "unexpected_prompt_city_records"))
        for error in errors
    ):
        return "fix_google_manual_backfill_coverage"
    if any(error.startswith(("answer_text_missing", "citation_urls_missing", "evidence_asset_missing")) for error in errors):
        return "complete_manual_backfill_jsonl"
    return "rerun_manual_backfill_verification"


def _summary(
    *,
    status: str,
    errors: list[str],
    allow_template_placeholders: bool,
    expected_prompt_city_count: int,
    expected_sample_size: int,
    expected_record_count: int,
    record_count: int,
    covered_prompt_city_count: int,
    missing_prompt_city_sample_count: int,
    duplicate_prompt_city_sample_count: int,
    unexpected_prompt_city_record_count: int,
    missing_answer_line_count: int,
    missing_citation_line_count: int,
    missing_asset_line_count: int,
    file_sha256: str,
) -> dict[str, Any]:
    coverage_complete = (
        record_count == expected_record_count
        and covered_prompt_city_count == expected_prompt_city_count
        and missing_prompt_city_sample_count == 0
        and duplicate_prompt_city_sample_count == 0
        and unexpected_prompt_city_record_count == 0
    )
    content_complete = (
        record_count == expected_record_count
        and missing_answer_line_count == 0
        and missing_citation_line_count == 0
        and missing_asset_line_count == 0
    )
    strict_ready = status == "pass" and coverage_complete and content_complete and not allow_template_placeholders
    return {
        "manual_backfill_status": status,
        "manual_backfill_ready": strict_ready,
        "template_placeholder_mode": allow_template_placeholders,
        "coverage_complete": coverage_complete,
        "content_complete": content_complete,
        "expected_prompt_city_count": expected_prompt_city_count,
        "expected_sample_size": expected_sample_size,
        "expected_record_count": expected_record_count,
        "record_count": record_count,
        "covered_prompt_city_count": covered_prompt_city_count,
        "missing_prompt_city_sample_count": missing_prompt_city_sample_count,
        "duplicate_prompt_city_sample_count": duplicate_prompt_city_sample_count,
        "unexpected_prompt_city_record_count": unexpected_prompt_city_record_count,
        "missing_answer_line_count": missing_answer_line_count,
        "missing_citation_line_count": missing_citation_line_count,
        "missing_asset_line_count": missing_asset_line_count,
        "error_count": len(errors),
        "errors": errors,
        "file_sha256_present": bool(file_sha256),
        "next_action": _next_action(
            status=status,
            errors=errors,
            allow_template_placeholders=allow_template_placeholders,
        ),
        "raw_answer_values_allowed": False,
        "raw_citation_values_allowed": False,
        "raw_asset_urls_allowed": False,
        "line_number_samples_allowed": True,
        "manual_jsonl_path_recorded": True,
    }


def _expected_keys() -> set[tuple[str, str]]:
    bootstrap = build_au_project_bootstrap()
    prompts = select_google_spike_prompts(bootstrap.prompt_questions)
    return {(prompt.text, city) for prompt in prompts for city in GOOGLE_SPIKE_GEO_CITIES}


def _read_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    entries: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return [], ["manual_backfill_file_missing"]
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            entry = json.loads(stripped)
        except json.JSONDecodeError as exc:
            errors.append(f"jsonl_invalid:{line_number}:{exc.msg}")
            continue
        if not isinstance(entry, dict):
            errors.append(f"jsonl_line_not_object:{line_number}")
            continue
        entry["_line_number"] = line_number
        entries.append(entry)
    return entries, errors


def verify_manual_backfill(path: Path, *, allow_template_placeholders: bool = False) -> dict[str, Any]:
    entries, errors = _read_jsonl(path)
    expected_keys = _expected_keys()
    expected_record_count = len(expected_keys) * GOOGLE_SPIKE_SAMPLE_SIZE
    counts: Counter[tuple[str, str]] = Counter()
    unexpected_keys: list[str] = []
    missing_answer_lines: list[int] = []
    missing_citation_lines: list[int] = []
    missing_asset_lines: list[int] = []

    for entry in entries:
        prompt = _entry_text(entry, "prompt", "prompt_text", "question")
        city = _entry_text(entry, "city", "geo_city", "location")
        key = (prompt, city)
        counts[key] += 1
        if key not in expected_keys:
            unexpected_keys.append(f"{entry['_line_number']}:{city}:{prompt[:80]}")
        answer_text = _entry_text(entry, "answer_text", "answer", "content")
        if not answer_text:
            missing_answer_lines.append(int(entry["_line_number"]))
        if not _entry_urls(entry):
            missing_citation_lines.append(int(entry["_line_number"]))
        if not _entry_text(entry, "screenshot_url", "screenshot") and not _entry_text(
            entry,
            "html_snapshot_url",
            "html_snapshot",
        ):
            missing_asset_lines.append(int(entry["_line_number"]))

    missing_keys = sorted(
        f"{city}:{prompt[:80]}"
        for prompt, city in expected_keys
        if counts[(prompt, city)] < GOOGLE_SPIKE_SAMPLE_SIZE
    )
    duplicate_keys = sorted(
        f"{city}:{prompt[:80]}:{count}"
        for (prompt, city), count in counts.items()
        if (prompt, city) in expected_keys and count > GOOGLE_SPIKE_SAMPLE_SIZE
    )

    if len(entries) != expected_record_count:
        errors.append(f"record_count_invalid:{len(entries)}/{expected_record_count}")
    if missing_keys:
        errors.append(f"missing_prompt_city_samples:{len(missing_keys)}")
    if duplicate_keys:
        errors.append(f"duplicate_prompt_city_samples:{len(duplicate_keys)}")
    if unexpected_keys:
        errors.append(f"unexpected_prompt_city_records:{len(unexpected_keys)}")
    if not allow_template_placeholders:
        if missing_answer_lines:
            errors.append(f"answer_text_missing:{len(missing_answer_lines)}")
        if missing_citation_lines:
            errors.append(f"citation_urls_missing:{len(missing_citation_lines)}")
        if missing_asset_lines:
            errors.append(f"evidence_asset_missing:{len(missing_asset_lines)}")

    file_exists = path.exists()
    status = "pass" if not errors else "fail"
    file_sha256 = _file_hash(path) if file_exists else ""
    result: dict[str, Any] = {
        "verifier_version": VERIFIER_VERSION,
        "status": status,
        "errors": errors,
        "path": str(path),
        "file_sha256": file_sha256,
        "allow_template_placeholders": allow_template_placeholders,
        "expected_prompt_city_count": len(expected_keys),
        "expected_sample_size": GOOGLE_SPIKE_SAMPLE_SIZE,
        "expected_record_count": expected_record_count,
        "record_count": len(entries),
        "covered_prompt_city_count": sum(1 for key in expected_keys if counts[key] >= GOOGLE_SPIKE_SAMPLE_SIZE),
        "missing_prompt_city_sample_count": len(missing_keys),
        "duplicate_prompt_city_sample_count": len(duplicate_keys),
        "unexpected_prompt_city_record_count": len(unexpected_keys),
        "missing_answer_line_count": len(missing_answer_lines),
        "missing_citation_line_count": len(missing_citation_lines),
        "missing_asset_line_count": len(missing_asset_lines),
        "missing_prompt_city_samples": missing_keys[:20],
        "duplicate_prompt_city_samples": duplicate_keys[:20],
        "unexpected_prompt_city_records": unexpected_keys[:20],
        "missing_answer_line_numbers": missing_answer_lines[:20],
        "missing_citation_line_numbers": missing_citation_lines[:20],
        "missing_asset_line_numbers": missing_asset_lines[:20],
    }
    result["summary"] = _summary(
        status=status,
        errors=errors,
        allow_template_placeholders=allow_template_placeholders,
        expected_prompt_city_count=len(expected_keys),
        expected_sample_size=GOOGLE_SPIKE_SAMPLE_SIZE,
        expected_record_count=expected_record_count,
        record_count=len(entries),
        covered_prompt_city_count=sum(1 for key in expected_keys if counts[key] >= GOOGLE_SPIKE_SAMPLE_SIZE),
        missing_prompt_city_sample_count=len(missing_keys),
        duplicate_prompt_city_sample_count=len(duplicate_keys),
        unexpected_prompt_city_record_count=len(unexpected_keys),
        missing_answer_line_count=len(missing_answer_lines),
        missing_citation_line_count=len(missing_citation_lines),
        missing_asset_line_count=len(missing_asset_lines),
        file_sha256=file_sha256,
    )
    result["verification_hash"] = compute_manual_backfill_verification_hash(result)
    return result


def verify_manual_backfill_verification_result(
    result: Any,
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {
            "status": "fail",
            "errors": ["manual_backfill_verification_not_json_object"],
            "path": str(path) if path else "",
            "hash_valid": False,
            "manual_backfill_status": "",
        }

    errors: list[str] = []
    for field in REQUIRED_VERIFICATION_FIELDS:
        if field not in result:
            errors.append(f"field_missing:{field}")
    for forbidden_path in _find_forbidden_fields(result):
        errors.append(f"forbidden_manual_payload_field:{forbidden_path}")
    if result.get("verifier_version") != VERIFIER_VERSION:
        errors.append("verifier_version_invalid")
    if result.get("status") not in {"pass", "fail"}:
        errors.append("manual_backfill_status_invalid")
    if result.get("status") == "pass" and result.get("errors") not in ([], ()):
        errors.append("manual_backfill_pass_has_errors")
    summary = _as_dict(result.get("summary"))
    errors_list = _strings(result.get("errors"))
    expected_summary = _summary(
        status=str(result.get("status") or ""),
        errors=errors_list,
        allow_template_placeholders=result.get("allow_template_placeholders") is True,
        expected_prompt_city_count=_int(result.get("expected_prompt_city_count")),
        expected_sample_size=_int(result.get("expected_sample_size")),
        expected_record_count=_int(result.get("expected_record_count")),
        record_count=_int(result.get("record_count")),
        covered_prompt_city_count=_int(result.get("covered_prompt_city_count")),
        missing_prompt_city_sample_count=_int(result.get("missing_prompt_city_sample_count")),
        duplicate_prompt_city_sample_count=_int(result.get("duplicate_prompt_city_sample_count")),
        unexpected_prompt_city_record_count=_int(result.get("unexpected_prompt_city_record_count")),
        missing_answer_line_count=_int(result.get("missing_answer_line_count")),
        missing_citation_line_count=_int(result.get("missing_citation_line_count")),
        missing_asset_line_count=_int(result.get("missing_asset_line_count")),
        file_sha256=str(result.get("file_sha256") or ""),
    )
    for key, expected_value in expected_summary.items():
        if summary.get(key) != expected_value:
            errors.append(f"summary_{key}_mismatch")
    if result.get("status") == "pass" and result.get("allow_template_placeholders") is not True:
        if summary.get("manual_backfill_ready") is not True:
            errors.append("summary_manual_backfill_ready_mismatch")
    if result.get("status") == "pass" and result.get("allow_template_placeholders") is True:
        if summary.get("manual_backfill_ready") is not False:
            errors.append("summary_template_placeholder_ready_invalid")

    expected_hash = result.get("verification_hash")
    computed_hash = compute_manual_backfill_verification_hash(result)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("manual_backfill_verification_hash_mismatch")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "verification_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_verification_hash": computed_hash,
        "hash_valid": hash_valid,
        "manual_backfill_status": result.get("status", ""),
        "manual_backfill_ready": summary.get("manual_backfill_ready") is True,
        "coverage_complete": summary.get("coverage_complete") is True,
        "content_complete": summary.get("content_complete") is True,
        "expected_prompt_city_count": _int(result.get("expected_prompt_city_count")),
        "expected_sample_size": _int(result.get("expected_sample_size")),
        "expected_record_count": _int(result.get("expected_record_count")),
        "record_count": _int(result.get("record_count")),
        "covered_prompt_city_count": _int(result.get("covered_prompt_city_count")),
        "missing_prompt_city_sample_count": _int(result.get("missing_prompt_city_sample_count")),
        "duplicate_prompt_city_sample_count": _int(result.get("duplicate_prompt_city_sample_count")),
        "unexpected_prompt_city_record_count": _int(result.get("unexpected_prompt_city_record_count")),
        "missing_answer_line_count": _int(result.get("missing_answer_line_count")),
        "missing_citation_line_count": _int(result.get("missing_citation_line_count")),
        "missing_asset_line_count": _int(result.get("missing_asset_line_count")),
        "error_count": len(errors_list),
        "next_action": str(summary.get("next_action") or ""),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify AU P0b Google AI Mode manual backfill JSONL coverage")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("MANUAL_BACKFILL_PATH", DEFAULT_INPUT_PATH),
        help="Path to the manual backfill JSONL file.",
    )
    parser.add_argument(
        "--output-path",
        default="",
        help=(
            "Optional path to write the machine-readable verification result JSON. "
            f"The Make target writes {DEFAULT_VERIFICATION_PATH}."
        ),
    )
    parser.add_argument(
        "--allow-template-placeholders",
        action="store_true",
        help="Allow empty answer/citation/asset fields when validating the generated template skeleton.",
    )
    parser.add_argument(
        "--allow-blocked-output",
        action="store_true",
        help="Exit 0 after writing a failed verification artifact; strict verification without this still exits non-zero.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = verify_manual_backfill(Path(args.path), allow_template_placeholders=args.allow_template_placeholders)
    if args.output_path:
        output_path = Path(args.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" or args.allow_blocked_output else 2)


if __name__ == "__main__":
    main()
