from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from geno_core.bootstrap import build_au_project_bootstrap
from geno_core.collection import collect_prompt_once
from geno_core.collectors import PlaywrightAIModeCollector, PlaywrightGoogleAIOCollector
from geno_core.contracts import CollectorBackend
from geno_core.google_spike import select_google_spike_prompts
from geno_core.models import RawEvidenceRecord


SMOKE_VERSION = "au_p0b_google_playwright_smoke_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0b-google-playwright-smoke-latest.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_payload_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_smoke_payload_hash(payload: dict[str, Any]) -> str:
    payload_for_hash = dict(payload)
    payload_for_hash.pop("smoke_payload_hash", None)
    return hashlib.sha256(_stable_payload_bytes(payload_for_hash)).hexdigest()


def _with_hash(payload: dict[str, Any]) -> dict[str, Any]:
    payload["smoke_payload_hash"] = compute_smoke_payload_hash(payload)
    return payload


def _collector_for_surface(surface: str) -> CollectorBackend:
    if surface == "google_aio":
        return PlaywrightGoogleAIOCollector()
    if surface == "google_ai_mode":
        return PlaywrightAIModeCollector()
    raise ValueError("surface must be google_aio or google_ai_mode")


def _evidence_payload(record: RawEvidenceRecord) -> dict[str, Any]:
    asset_hashes = {
        asset.asset_type: asset.content_hash
        for asset in record.evidence_assets
        if asset.content_hash
    }
    return {
        "answer_run": asdict(record.answer_run),
        "raw_answer": {
            "id": record.raw_answer.id,
            "answer_run_id": record.raw_answer.answer_run_id,
            "answer_text_length": len(record.raw_answer.answer_text),
            "raw_payload_hash": record.raw_answer.raw_payload_hash,
            "raw_payload": record.raw_answer.raw_payload,
        },
        "citation_count": len(record.citations),
        "citations": [asdict(citation) for citation in record.citations],
        "asset_count": len(record.evidence_assets),
        "evidence_assets": [asdict(asset) for asset in record.evidence_assets],
        "evidence_asset_hashes": asset_hashes,
        "collector_logs": [asdict(log) for log in record.collector_logs],
        "collection_cost": asdict(record.collection_cost),
        "audit_events": [asdict(event) for event in record.audit_events],
    }


def run_google_playwright_smoke(
    *,
    surface: str = "google_aio",
    city: str = "Sydney",
    device: str = "desktop",
    prompt_index: int = 0,
    collector: CollectorBackend | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    bootstrap = build_au_project_bootstrap()
    prompts = select_google_spike_prompts(bootstrap.prompt_questions)
    if prompt_index < 0 or prompt_index >= len(prompts):
        raise ValueError(f"prompt_index must be between 0 and {len(prompts) - 1}")
    prompt = prompts[prompt_index]
    selected_collector = collector or _collector_for_surface(surface)
    collector_health = selected_collector.health()
    capabilities = selected_collector.capabilities()
    base_payload: dict[str, Any] = {
        "smoke_version": SMOKE_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "fail",
        "phase": "collector_health",
        "errors": [],
        "secrets_redacted": True,
        "planned_runs": 1,
        "record_count": 0,
        "success_count": 0,
        "failure_count": 0,
        "surface": surface,
        "collector_backend_id": selected_collector.id(),
        "collector_health": collector_health,
        "collector_capabilities": capabilities,
        "project_id": bootstrap.project.id,
        "prompt_question_id": prompt.id,
        "prompt_text": prompt.text,
        "city": city,
        "language": prompt.language,
        "device": device,
        "answer_present": False,
        "surface_triggered": False,
        "citation_count": 0,
        "asset_count": 0,
        "evidence": None,
    }
    if collector_health != "ready":
        base_payload["errors"] = [f"collector_health:{collector_health}"]
        return _with_hash(base_payload)
    try:
        record = collect_prompt_once(
            project_id=bootstrap.project.id,
            prompt=prompt,
            market_profile=bootstrap.market_profile,
            collector=selected_collector,
            city=city,
            sample_index=1,
            sample_size=1,
            device=device,
        )
    except Exception as exc:
        base_payload.update(
            {
                "phase": "collection_failed",
                "failure_count": 1,
                "errors": [f"{exc.__class__.__name__}:{exc}"],
            }
        )
        return _with_hash(base_payload)
    evidence = _evidence_payload(record)
    base_payload.update(
        {
            "status": "pass",
            "phase": "collection_completed",
            "record_count": 1,
            "success_count": 1,
            "failure_count": 0,
            "answer_present": record.answer_run.answer_present,
            "surface_triggered": record.answer_run.surface_triggered,
            "citation_count": len(record.citations),
            "asset_count": len(record.evidence_assets),
            "collector_version": record.answer_run.collector_version,
            "account_state": record.answer_run.account_state,
            "raw_payload_hash": record.raw_answer.raw_payload_hash,
            "evidence_asset_hashes": evidence["evidence_asset_hashes"],
            "evidence": evidence,
        }
    )
    return _with_hash(base_payload)


def write_smoke_payload(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one AU P0b Google Playwright smoke capture")
    parser.add_argument("--surface", choices=["google_aio", "google_ai_mode"], default="google_aio")
    parser.add_argument("--city", default="Sydney")
    parser.add_argument("--device", default="desktop")
    parser.add_argument("--prompt-index", type=int, default=0)
    parser.add_argument(
        "--output-path",
        default=DEFAULT_OUTPUT_PATH,
        help="Path to write the smoke JSON payload.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        payload = run_google_playwright_smoke(
            surface=args.surface,
            city=args.city,
            device=args.device,
            prompt_index=args.prompt_index,
            generated_at=args.generated_at,
        )
    except ValueError as exc:
        payload = _with_hash(
            {
                "smoke_version": SMOKE_VERSION,
                "generated_at": args.generated_at or _utc_now_iso(),
                "status": "fail",
                "phase": "input_invalid",
                "errors": [str(exc)],
                "secrets_redacted": True,
                "planned_runs": 1,
                "record_count": 0,
                "success_count": 0,
                "failure_count": 1,
                "surface": args.surface,
            }
        )
    output_path = Path(args.output_path)
    write_smoke_payload(payload, output_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if payload.get("status") == "pass" else 3)


if __name__ == "__main__":
    main()
