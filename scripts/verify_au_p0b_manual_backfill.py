from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from geno_core.bootstrap import build_au_project_bootstrap
from geno_core.google_spike import (
    GOOGLE_SPIKE_GEO_CITIES,
    GOOGLE_SPIKE_SAMPLE_SIZE,
    select_google_spike_prompts,
)


DEFAULT_INPUT_PATH = "docs/runtime_preflight/au-p0b-google-manual-backfill-template.jsonl"
VERIFIER_VERSION = "au_p0b_manual_backfill_verifier_v1"


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    return {
        "verifier_version": VERIFIER_VERSION,
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path),
        "file_sha256": _file_hash(path) if file_exists else "",
        "allow_template_placeholders": allow_template_placeholders,
        "expected_prompt_city_count": len(expected_keys),
        "expected_sample_size": GOOGLE_SPIKE_SAMPLE_SIZE,
        "expected_record_count": expected_record_count,
        "record_count": len(entries),
        "covered_prompt_city_count": sum(1 for key in expected_keys if counts[key] >= GOOGLE_SPIKE_SAMPLE_SIZE),
        "missing_prompt_city_samples": missing_keys[:20],
        "duplicate_prompt_city_samples": duplicate_keys[:20],
        "unexpected_prompt_city_records": unexpected_keys[:20],
        "missing_answer_line_numbers": missing_answer_lines[:20],
        "missing_citation_line_numbers": missing_citation_lines[:20],
        "missing_asset_line_numbers": missing_asset_lines[:20],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify AU P0b Google AI Mode manual backfill JSONL coverage")
    parser.add_argument(
        "path",
        nargs="?",
        default=DEFAULT_INPUT_PATH,
        help="Path to the manual backfill JSONL file.",
    )
    parser.add_argument(
        "--allow-template-placeholders",
        action="store_true",
        help="Allow empty answer/citation/asset fields when validating the generated template skeleton.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = verify_manual_backfill(Path(args.path), allow_template_placeholders=args.allow_template_placeholders)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
