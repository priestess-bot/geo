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

from scripts.build_au_launch_status import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_LAUNCH_STATUS_PATH,
    build_au_launch_status,
)
from scripts.verify_au_launch_status import verify_au_launch_status  # noqa: E402


PLAN_VERSION = "au_launch_remediation_plan_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-launch-remediation-plan-latest.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_plan_bytes(plan: dict[str, Any]) -> bytes:
    return json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_remediation_plan_hash(plan: dict[str, Any]) -> str:
    payload = dict(plan)
    payload.pop("remediation_plan_hash", None)
    return hashlib.sha256(_stable_plan_bytes(payload)).hexdigest()


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _load_or_build_launch_status(path: Path, *, generated_at: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        report = build_au_launch_status(output_path=path, generated_at=generated_at)
        return report, {"path": str(path), "exists": False, "source": "generated_in_memory", "errors": ["file_missing"]}
    except json.JSONDecodeError as exc:
        report = build_au_launch_status(output_path=path, generated_at=generated_at)
        return report, {
            "path": str(path),
            "exists": True,
            "source": "generated_in_memory",
            "errors": [f"json_invalid:{exc.msg}"],
        }
    if isinstance(payload, dict):
        return payload, {"path": str(path), "exists": True, "source": "existing_file"}
    report = build_au_launch_status(output_path=path, generated_at=generated_at)
    return report, {"path": str(path), "exists": True, "source": "generated_in_memory", "errors": ["not_json_object"]}


def _command(value: str) -> dict[str, str]:
    return {"shell": value}


def _p0a_environment_item(blockers: list[str]) -> dict[str, Any]:
    missing_env = sorted({blocker.rsplit(":", 1)[-1] for blocker in blockers if "required_env_missing:" in blocker})
    return {
        "id": "p0a_environment",
        "stage": "P0a",
        "title": "Configure AU P0a provider keys and runtime database",
        "status": "requires_external_input",
        "external_dependency": True,
        "dependency_class": "provider_keys_and_database",
        "required_inputs": missing_env or ["PERPLEXITY_API_KEY", "OPENAI_API_KEY", "DATABASE_URL"],
        "commands": [
            _command("cp .env.au-p0a.example .env.au-p0a"),
            _command("make au-p0a-runbook"),
            _command("make au-p0a-env"),
            _command("make verify-au-p0a-env"),
            _command("make au-p0a-environment-checklist"),
            _command("make verify-au-p0a-environment-checklist"),
            _command("make au-p0a-readiness"),
        ],
        "verification_commands": [
            _command(
                "PYTHONPATH=packages/geno_core:apps/api "
                "python3 scripts/verify_au_p0a_env_report.py "
                "${GENO_AU_P0A_ENV_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-env-latest.json} "
                "--require-ready-environment"
            ),
            _command("make au-p0a-status"),
            _command("make verify-au-p0a-status"),
        ],
        "evidence_outputs": [
            "docs/runtime_preflight/au-p0a-runbook-latest.json",
            "docs/runtime_preflight/au-p0a-env-latest.json",
            "docs/runtime_preflight/au-p0a-environment-checklist-latest.json",
            "docs/runtime_preflight/au-p0a-readiness-latest.json",
            "docs/runtime_preflight/au-p0a-status-latest.json",
        ],
        "acceptance": "P0a environment report is ready and AU P0a status no longer reports required_env_missing blockers.",
    }


def _p0a_preflight_item() -> dict[str, Any]:
    return {
        "id": "p0a_preflight",
        "stage": "P0a",
        "title": "Run and manifest the AU P0a provider preflight",
        "status": "pending_after_environment",
        "external_dependency": True,
        "dependency_class": "provider_api_execution",
        "required_inputs": ["PERPLEXITY_API_KEY", "OPENAI_API_KEY", "DATABASE_URL"],
        "commands": [
            _command("make api-preflight"),
            _command("make verify-api-preflight"),
            _command("make preflight-manifest"),
            _command(
                "PYTHONPATH=packages/geno_core:apps/api "
                "python3 scripts/verify_preflight_payload.py "
                "${GENO_API_PREFLIGHT_OUTPUT_PATH:-docs/runtime_preflight/api-preflight-latest.json} "
                "--require-design-partner-ready"
            ),
        ],
        "verification_commands": [_command("make au-p0a-status"), _command("make verify-au-p0a-status")],
        "evidence_outputs": [
            "docs/runtime_preflight/api-preflight-latest.json",
            "docs/runtime_preflight/api-preflight-manifest-latest.json",
            "docs/runtime_preflight/au-p0a-status-latest.json",
        ],
        "acceptance": "Provider preflight payload and manifest are design-partner ready.",
    }


def _p0a_small_batch_item() -> dict[str, Any]:
    return {
        "id": "p0a_small_batch",
        "stage": "P0a",
        "title": "Run and manifest the AU P0a small batch",
        "status": "pending_after_preflight",
        "external_dependency": True,
        "dependency_class": "provider_api_execution",
        "required_inputs": ["P0a preflight design-partner gate pass"],
        "commands": [
            _command(
                "PYTHONPATH=packages/geno_core:apps/api "
                "python3 workers/collector_worker/run_collection_slice.py --mode api "
                "--prompt-limit 5 --cities Sydney --sample-size 3 --require-ready-collectors "
                "--require-p0a-readiness --require-no-collection-failures --persist --persist-analysis "
                "--preflight-output-path docs/runtime_preflight/au-p0a-small-batch.json"
            ),
            _command(
                "PYTHONPATH=packages/geno_core:apps/api "
                "python3 scripts/build_preflight_manifest.py docs/runtime_preflight/au-p0a-small-batch.json "
                "--manifest-path docs/runtime_preflight/au-p0a-small-batch-manifest.json "
                "--require-design-partner-ready"
            ),
        ],
        "verification_commands": [_command("make au-p0a-package"), _command("make au-p0a-status"), _command("make verify-au-p0a-status")],
        "evidence_outputs": [
            "docs/runtime_preflight/au-p0a-small-batch.json",
            "docs/runtime_preflight/au-p0a-small-batch-manifest.json",
            "docs/runtime_preflight/au-p0a-evidence-package-latest.json",
        ],
        "acceptance": "Small batch payload and manifest are present and design-partner ready.",
    }


def _p0a_full_batch_item() -> dict[str, Any]:
    return {
        "id": "p0a_full_batch",
        "stage": "P0a",
        "title": "Run and manifest the full AU P0a design-partner batch",
        "status": "pending_after_small_batch",
        "external_dependency": True,
        "dependency_class": "provider_api_execution",
        "required_inputs": ["P0a small batch design-partner gate pass"],
        "commands": [
            _command(
                "PYTHONPATH=packages/geno_core:apps/api "
                "python3 workers/collector_worker/run_collection_slice.py --mode api "
                "--prompt-limit 100 --cities Australia,Sydney,Melbourne,Brisbane --sample-size 3 "
                "--require-ready-collectors --require-p0a-readiness --require-no-collection-failures "
                "--persist --persist-analysis "
                "--preflight-output-path docs/runtime_preflight/au-p0a-full-batch.json"
            ),
            _command(
                "PYTHONPATH=packages/geno_core:apps/api "
                "python3 scripts/build_preflight_manifest.py docs/runtime_preflight/au-p0a-full-batch.json "
                "--manifest-path docs/runtime_preflight/au-p0a-full-batch-manifest.json "
                "--require-design-partner-ready"
            ),
        ],
        "verification_commands": [_command("make au-p0a-package"), _command("make au-p0a-status"), _command("make verify-au-p0a-status")],
        "evidence_outputs": [
            "docs/runtime_preflight/au-p0a-full-batch.json",
            "docs/runtime_preflight/au-p0a-full-batch-manifest.json",
            "docs/runtime_preflight/au-p0a-evidence-package-latest.json",
        ],
        "acceptance": "Full batch payload and manifest are present and P0a design partner gate is ready.",
    }


def _p0b_playwright_env_item() -> dict[str, Any]:
    return {
        "id": "p0b_google_playwright_env",
        "stage": "P0b",
        "title": "Configure Google Playwright smoke environment",
        "status": "requires_external_input",
        "external_dependency": True,
        "dependency_class": "google_ui_selectors_session_and_database",
        "required_inputs": [
            "GOOGLE_PLAYWRIGHT_ENABLED=1",
            "GOOGLE_PLAYWRIGHT_PROMPT_SELECTOR or surface-specific prompt selector",
            "GOOGLE_PLAYWRIGHT_ANSWER_SELECTOR or surface-specific answer selector",
            "AU-capable browser/session setup",
            "DATABASE_URL",
        ],
        "commands": [
            _command("cp .env.au-p0b-google.example .env.au-p0b-google"),
            _command("make au-p0b-google-runbook"),
            _command("make au-p0b-google-playwright-env"),
            _command("make au-p0b-google-execution-checklist"),
        ],
        "verification_commands": [
            _command("make verify-au-p0b-google-execution-checklist"),
            _command(
                "PYTHONPATH=packages/geno_core:apps/api "
                "python3 scripts/verify_au_p0b_google_playwright_env_report.py "
                "${GENO_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-playwright-env-latest.json} "
                "--require-ready-smoke"
            )
        ],
        "evidence_outputs": [
            "docs/runtime_preflight/au-p0b-google-spike-runbook-latest.json",
            "docs/runtime_preflight/au-p0b-google-playwright-env-latest.json",
            "docs/runtime_preflight/au-p0b-google-execution-checklist-latest.json",
        ],
        "acceptance": "Google Playwright environment report is ready for smoke and contains no raw secret values.",
    }


def _p0b_playwright_smoke_item() -> dict[str, Any]:
    return {
        "id": "p0b_google_playwright_smoke",
        "stage": "P0b",
        "title": "Run one successful Google Playwright smoke capture",
        "status": "pending_after_playwright_env",
        "external_dependency": True,
        "dependency_class": "google_browser_execution",
        "required_inputs": ["P0b Google Playwright environment ready"],
        "commands": [_command("make au-p0b-google-playwright-smoke")],
        "verification_commands": [
            _command(
                "PYTHONPATH=packages/geno_core:apps/api "
                "python3 scripts/verify_au_p0b_google_playwright_smoke.py "
                "${GENO_AU_P0B_GOOGLE_PLAYWRIGHT_SMOKE_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-playwright-smoke-latest.json} "
                "--require-success"
            )
        ],
        "evidence_outputs": ["docs/runtime_preflight/au-p0b-google-playwright-smoke-latest.json"],
        "acceptance": "Smoke payload has one successful browser capture, screenshot/html hashes, and answer_run_collected audit.",
    }


def _p0b_manual_backfill_item() -> dict[str, Any]:
    return {
        "id": "p0b_google_manual_backfill",
        "stage": "P0b",
        "title": "Generate, fill, and verify Google AI Mode manual backfill",
        "status": "requires_external_input",
        "external_dependency": True,
        "dependency_class": "manual_google_ai_mode_sampling",
        "required_inputs": ["120-row MANUAL_BACKFILL_PATH JSONL with answer text, citations, and screenshot or HTML evidence"],
        "commands": [
            _command("make au-p0b-google-manual-template"),
            _command("make verify-au-p0b-google-manual-backfill"),
        ],
        "verification_commands": [_command("make verify-au-p0b-google-manual-backfill")],
        "evidence_outputs": [
            "docs/runtime_preflight/au-p0b-google-manual-backfill-template.jsonl",
            "docs/runtime_preflight/au-p0b-google-manual-backfill-verification-latest.json",
        ],
        "acceptance": "Manual backfill verification is strict-pass for the 120-row browser+manual matrix.",
    }


def _p0b_spike_health_item() -> dict[str, Any]:
    return {
        "id": "p0b_google_spike_health",
        "stage": "P0b",
        "title": "Run Google spike health-only check and manifest it",
        "status": "pending_after_smoke_and_manual",
        "external_dependency": True,
        "dependency_class": "google_collector_health",
        "required_inputs": ["Playwright smoke success", "manual backfill verification pass"],
        "commands": [
            _command("make au-p0b-google-spike-health"),
            _command("make au-p0b-google-spike-health-manifest"),
        ],
        "verification_commands": [_command("make au-p0b-google-status"), _command("make verify-au-p0b-google-status")],
        "evidence_outputs": [
            "docs/runtime_preflight/au-p0b-google-spike-health-latest.json",
            "docs/runtime_preflight/au-p0b-google-spike-health-manifest-latest.json",
        ],
        "acceptance": "Health JSON and manifest exist, hash-verify, and status no longer reports health missing.",
    }


def _p0b_full_spike_item() -> dict[str, Any]:
    return {
        "id": "p0b_google_full_spike",
        "stage": "P0b",
        "title": "Run full Google spike matrix and manifest it",
        "status": "pending_after_spike_health",
        "external_dependency": True,
        "dependency_class": "google_browser_manual_spike_execution",
        "required_inputs": ["Google spike health pass"],
        "commands": [
            _command("make au-p0b-google-spike"),
            _command("make au-p0b-google-spike-manifest"),
            _command("make au-p0b-google-status"),
            _command("make au-p0b-google-package"),
            _command("make au-p0b-google-execution-checklist"),
            _command("make au-launch-status"),
        ],
        "verification_commands": [
            _command("make verify-au-p0b-google-status"),
            _command("make verify-au-p0b-google-execution-checklist"),
            _command(
                "PYTHONPATH=packages/geno_core:apps/api "
                "python3 scripts/verify_au_p0b_google_evidence_package.py "
                "${GENO_AU_P0B_GOOGLE_PACKAGE_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-evidence-package-latest.json} "
                "--require-google-main-scoring-allowed"
            ),
            _command("make verify-au-launch-status"),
        ],
        "evidence_outputs": [
            "docs/runtime_preflight/au-p0b-google-spike-latest.json",
            "docs/runtime_preflight/au-p0b-google-spike-manifest-latest.json",
            "docs/runtime_preflight/au-p0b-google-evidence-package-latest.json",
            "docs/runtime_preflight/au-p0b-google-execution-checklist-latest.json",
            "docs/runtime_preflight/au-launch-status-latest.json",
        ],
        "acceptance": "P0b package allows Google main scoring or the launch report explicitly keeps Google limited coverage.",
    }


def _p0c_report_item() -> dict[str, Any]:
    return {
        "id": "p0c_report_package",
        "stage": "P0c",
        "title": "Regenerate and verify the P0c customer report package",
        "status": "runnable_now",
        "external_dependency": False,
        "dependency_class": "local_fixture_report_package",
        "required_inputs": [],
        "commands": [_command("make au-p0c-report-package")],
        "verification_commands": [_command("make verify-au-p0c-report-package"), _command("make au-launch-status")],
        "evidence_outputs": ["docs/runtime_preflight/au-p0c-report-package-latest.json"],
        "acceptance": "P0c package verifier passes and AU launch status records p0c_report_contract_ready=true.",
    }


WORK_ITEM_BUILDERS = {
    "p0a_environment": _p0a_environment_item,
    "p0a_preflight": lambda blockers: _p0a_preflight_item(),
    "p0a_small_batch": lambda blockers: _p0a_small_batch_item(),
    "p0a_full_batch": lambda blockers: _p0a_full_batch_item(),
    "p0b_google_playwright_env": lambda blockers: _p0b_playwright_env_item(),
    "p0b_google_playwright_smoke": lambda blockers: _p0b_playwright_smoke_item(),
    "p0b_google_manual_backfill": lambda blockers: _p0b_manual_backfill_item(),
    "p0b_google_spike_health": lambda blockers: _p0b_spike_health_item(),
    "p0b_google_full_spike": lambda blockers: _p0b_full_spike_item(),
    "p0c_report_package": lambda blockers: _p0c_report_item(),
}
WORK_ITEM_ORDER = (
    "p0a_environment",
    "p0a_preflight",
    "p0a_small_batch",
    "p0a_full_batch",
    "p0b_google_playwright_env",
    "p0b_google_playwright_smoke",
    "p0b_google_manual_backfill",
    "p0b_google_spike_health",
    "p0b_google_full_spike",
    "p0c_report_package",
)


def _work_item_id_for_blocker(blocker: str) -> str:
    if blocker.startswith("p0a:"):
        detail = blocker.removeprefix("p0a:")
        if "required_env_missing:" in detail or detail.startswith("readiness:readiness_file_missing"):
            return "p0a_environment"
        if detail.startswith("preflight:") or detail.startswith("preflight_json") or detail.startswith("preflight_manifest"):
            return "p0a_preflight"
        if "small_batch_json" in detail or "small_batch_manifest" in detail or detail.startswith("small_batch:"):
            return "p0a_small_batch"
        if "full_batch_json" in detail or "full_batch_manifest" in detail or detail.startswith("full_batch:"):
            return "p0a_full_batch"
    if blocker.startswith("p0b_google:"):
        detail = blocker.removeprefix("p0b_google:")
        if detail.startswith("playwright_env:"):
            return "p0b_google_playwright_env"
        if detail.startswith("playwright_smoke:"):
            return "p0b_google_playwright_smoke"
        if detail.startswith("manual_backfill:"):
            return "p0b_google_manual_backfill"
        if detail.startswith("health:") or detail.startswith("health_manifest:"):
            return "p0b_google_spike_health"
        if detail.startswith("spike:") or detail.startswith("spike_manifest:"):
            return "p0b_google_full_spike"
    if blocker.startswith("p0c:"):
        return "p0c_report_package"
    return "unmapped"


def _build_remediation(blocker: str, work_item: dict[str, Any] | None) -> dict[str, Any]:
    if work_item is None:
        return {
            "blocker": blocker,
            "work_item_id": "unmapped",
            "mapped": False,
            "external_dependency": True,
            "dependency_class": "unknown",
            "next_command": "",
            "verification_commands": [],
            "evidence_outputs": [],
        }
    commands = _as_list(work_item.get("commands"))
    return {
        "blocker": blocker,
        "work_item_id": work_item["id"],
        "mapped": True,
        "external_dependency": work_item["external_dependency"],
        "dependency_class": work_item["dependency_class"],
        "next_command": _as_dict(commands[0]).get("shell", "") if commands else "",
        "verification_commands": work_item["verification_commands"],
        "evidence_outputs": work_item["evidence_outputs"],
    }


def build_au_launch_remediation_plan(
    *,
    launch_status: dict[str, Any] | None = None,
    launch_status_path: Path = Path(DEFAULT_LAUNCH_STATUS_PATH),
    output_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    source: dict[str, Any]
    if launch_status is None:
        launch_status, source = _load_or_build_launch_status(launch_status_path, generated_at=generated_at)
    else:
        source = {"path": str(launch_status_path), "exists": True, "source": "provided_payload"}

    launch_verification = verify_au_launch_status(launch_status, path=launch_status_path)
    blockers = sorted(str(item) for item in _as_list(launch_status.get("remaining_blockers")))
    blockers_by_work_item: dict[str, list[str]] = {}
    unmapped_blockers: list[str] = []
    for blocker in blockers:
        work_item_id = _work_item_id_for_blocker(blocker)
        if work_item_id == "unmapped":
            unmapped_blockers.append(blocker)
        blockers_by_work_item.setdefault(work_item_id, []).append(blocker)

    work_items: list[dict[str, Any]] = []
    work_item_by_id: dict[str, dict[str, Any]] = {}
    for work_item_id in WORK_ITEM_ORDER:
        item_blockers = blockers_by_work_item.get(work_item_id, [])
        if not item_blockers:
            continue
        work_item = WORK_ITEM_BUILDERS[work_item_id](item_blockers)
        work_item["clears_blockers"] = item_blockers
        work_item["blocker_count"] = len(item_blockers)
        work_items.append(work_item)
        work_item_by_id[work_item_id] = work_item

    blocker_remediations = [
        _build_remediation(blocker, work_item_by_id.get(_work_item_id_for_blocker(blocker))) for blocker in blockers
    ]
    next_work_item = work_items[0]["id"] if work_items else "none"
    external_dependency_blockers = [
        item["blocker"] for item in blocker_remediations if item.get("external_dependency") is True
    ]
    runnable_now_items = [item["id"] for item in work_items if item.get("status") == "runnable_now"]
    plan_ready = not unmapped_blockers and launch_verification["status"] == "pass"
    plan: dict[str, Any] = {
        "remediation_plan_version": PLAN_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if plan_ready else "fail",
        "remediation_plan_ready": plan_ready,
        "next_work_item_id": next_work_item,
        "output_path": str(output_path) if output_path else "",
        "launch_status": {
            "path": str(launch_status_path),
            "status": launch_status.get("status", ""),
            "ready_for_customer_report_handoff": launch_status.get("ready_for_customer_report_handoff") is True,
            "next_action": launch_status.get("next_action", ""),
            "launch_status_hash": launch_status.get("launch_status_hash", ""),
            "remaining_blockers": blockers,
        },
        "launch_status_source": source,
        "launch_status_verifier": launch_verification,
        "summary": {
            "blocker_count": len(blockers),
            "covered_blocker_count": len(blockers) - len(unmapped_blockers),
            "unmapped_blocker_count": len(unmapped_blockers),
            "work_item_count": len(work_items),
            "external_dependency_blocker_count": len(external_dependency_blockers),
            "runnable_now_work_item_count": len(runnable_now_items),
            "runnable_now_work_items": runnable_now_items,
            "unmapped_blockers": unmapped_blockers,
        },
        "work_items": work_items,
        "blocker_remediations": blocker_remediations,
    }
    plan["remediation_plan_hash"] = compute_remediation_plan_hash(plan)
    return plan


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU launch blocker remediation plan JSON")
    parser.add_argument(
        "--launch-status-path",
        default=os.environ.get("GENO_AU_LAUNCH_STATUS_OUTPUT_PATH", DEFAULT_LAUNCH_STATUS_PATH),
        help="Path to the AU launch status JSON.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GENO_AU_LAUNCH_REMEDIATION_PLAN_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the remediation plan JSON.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    plan = build_au_launch_remediation_plan(
        launch_status_path=Path(args.launch_status_path),
        output_path=output_path,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(plan, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if plan["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
