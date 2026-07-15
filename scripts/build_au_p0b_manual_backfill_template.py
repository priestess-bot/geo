from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from geo_core.bootstrap import build_au_project_bootstrap
from geo_core.google_spike import (
    GOOGLE_SPIKE_GEO_CITIES,
    GOOGLE_SPIKE_SAMPLE_SIZE,
    select_google_spike_prompts,
)


TEMPLATE_VERSION = "au_p0b_manual_backfill_template_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0b-google-manual-backfill-template.jsonl"
DEFAULT_MANIFEST_PATH = "docs/runtime_preflight/au-p0b-google-manual-backfill-template-manifest.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _jsonl_hash(lines: list[dict[str, Any]]) -> str:
    payload = "\n".join(
        json.dumps(line, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for line in lines
    )
    return hashlib.sha256((payload + "\n").encode("utf-8")).hexdigest()


def _manifest_hash(manifest: dict[str, Any]) -> str:
    payload = dict(manifest)
    payload.pop("manifest_hash", None)
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def build_manual_backfill_template(*, generated_at: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    bootstrap = build_au_project_bootstrap()
    prompts = select_google_spike_prompts(bootstrap.prompt_questions)
    lines: list[dict[str, Any]] = []
    for prompt in prompts:
        for city in GOOGLE_SPIKE_GEO_CITIES:
            for sample_index in range(1, GOOGLE_SPIKE_SAMPLE_SIZE + 1):
                lines.append(
                    {
                        "template_version": TEMPLATE_VERSION,
                        "project_id": bootstrap.project.id,
                        "prompt_question_id": prompt.id,
                        "prompt": prompt.text,
                        "intent_type": prompt.intent_type,
                        "market_code": prompt.market_code,
                        "city": city,
                        "language": prompt.language,
                        "device": "desktop",
                        "platform": "google",
                        "surface": "google_ai_mode",
                        "sample_index": sample_index,
                        "sample_size": GOOGLE_SPIKE_SAMPLE_SIZE,
                        "answer_text": "",
                        "citation_urls": [],
                        "screenshot_url": "",
                        "html_snapshot_url": "",
                        "answer_present": True,
                        "surface_triggered": True,
                        "submitted_by": "",
                        "notes": "Fill from Google AI Mode manual capture before running google-spike.",
                    }
                )
    manifest: dict[str, Any] = {
        "template_version": TEMPLATE_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "project_id": bootstrap.project.id,
        "market_code": bootstrap.market_profile.market_code,
        "surface": "google_ai_mode",
        "access_method": "manual",
        "prompt_count": len(prompts),
        "geo_cities": GOOGLE_SPIKE_GEO_CITIES,
        "sample_size": GOOGLE_SPIKE_SAMPLE_SIZE,
        "expected_record_count": len(prompts) * len(GOOGLE_SPIKE_GEO_CITIES) * GOOGLE_SPIKE_SAMPLE_SIZE,
        "record_count": len(lines),
        "jsonl_sha256": _jsonl_hash(lines),
        "required_fields": (
            "prompt",
            "city",
            "language",
            "device",
            "answer_text",
            "citation_urls",
            "screenshot_url or html_snapshot_url",
        ),
        "consumer": "ManualBackfillCollector via MANUAL_BACKFILL_PATH",
    }
    manifest["manifest_hash"] = _manifest_hash(manifest)
    return lines, manifest


def write_template(*, output_path: Path, manifest_path: Path, generated_at: str | None = None) -> dict[str, Any]:
    lines, manifest = build_manual_backfill_template(generated_at=generated_at)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(
            json.dumps(line, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for line in lines
        ),
        encoding="utf-8",
    )
    manifest = {
        **manifest,
        "output_path": str(output_path),
        "manifest_path": str(manifest_path),
    }
    manifest["manifest_hash"] = _manifest_hash(manifest)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build AU P0b Google AI Mode manual backfill JSONL template")
    parser.add_argument(
        "--output-path",
        default=DEFAULT_OUTPUT_PATH,
        help="Path to write the manual backfill JSONL template.",
    )
    parser.add_argument(
        "--manifest-path",
        default=DEFAULT_MANIFEST_PATH,
        help="Path to write the template manifest JSON.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = write_template(
        output_path=Path(args.output_path),
        manifest_path=Path(args.manifest_path),
        generated_at=args.generated_at,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
