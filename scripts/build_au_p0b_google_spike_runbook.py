from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RUNBOOK_VERSION = "au_p0b_google_spike_runbook_v1"
DEFAULT_ARTIFACT_DIR = "docs/runtime_preflight"
DEFAULT_OUTPUT_PATH = f"{DEFAULT_ARTIFACT_DIR}/au-p0b-google-spike-runbook-latest.json"
DEFAULT_GEO_CITIES = ("Australia", "Sydney")
DEFAULT_COLLECTION_PATHS = ("browser", "manual")
DEFAULT_PROMPT_COUNT = 30
DEFAULT_SAMPLE_SIZE = 2
DEFAULT_SURFACE_COUNT = 2


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_runbook_bytes(runbook: dict[str, Any]) -> bytes:
    return json.dumps(runbook, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_google_spike_runbook_hash(runbook: dict[str, Any]) -> str:
    payload = dict(runbook)
    payload.pop("runbook_payload_hash", None)
    return hashlib.sha256(_stable_runbook_bytes(payload)).hexdigest()


def _shell_command(command: list[str], env: dict[str, str] | None = None) -> str:
    env_prefix = [f"{key}={shlex.quote(value)}" for key, value in (env or {}).items()]
    return " ".join((*env_prefix, shlex.join(command)))


def _planned_runs(prompt_count: int, geo_cities: tuple[str, ...], sample_size: int, surface_count: int) -> int:
    return prompt_count * len(geo_cities) * sample_size * surface_count


def _make_command(target: str) -> list[str]:
    return ["make", target]


def _command_step(
    *,
    step_id: str,
    title: str,
    command: list[str],
    output_paths: tuple[str, ...],
    planned_runs: int | None = None,
    env: dict[str, str] | None = None,
    notes: tuple[str, ...] = (),
) -> dict[str, Any]:
    step: dict[str, Any] = {
        "id": step_id,
        "title": title,
        "type": "command",
        "command": command,
        "env": env or {},
        "shell_command": _shell_command(command, env),
        "output_paths": output_paths,
        "stop_on_failure": True,
        "notes": notes,
    }
    if planned_runs is not None:
        step["planned_runs"] = planned_runs
    return step


def build_au_p0b_google_spike_runbook(
    *,
    artifact_dir: str = DEFAULT_ARTIFACT_DIR,
    runbook_path: str = DEFAULT_OUTPUT_PATH,
    prompt_count: int = DEFAULT_PROMPT_COUNT,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    geo_cities: tuple[str, ...] = DEFAULT_GEO_CITIES,
    collection_paths: tuple[str, ...] = DEFAULT_COLLECTION_PATHS,
    persist: bool = True,
    generated_at: str | None = None,
) -> dict[str, Any]:
    artifact_root = artifact_dir.rstrip("/")
    health_path = f"{artifact_root}/au-p0b-google-spike-health-latest.json"
    health_manifest_path = f"{artifact_root}/au-p0b-google-spike-health-manifest-latest.json"
    spike_path = f"{artifact_root}/au-p0b-google-spike-latest.json"
    spike_manifest_path = f"{artifact_root}/au-p0b-google-spike-manifest-latest.json"
    playwright_env_path = f"{artifact_root}/au-p0b-google-playwright-env-latest.json"
    smoke_path = f"{artifact_root}/au-p0b-google-playwright-smoke-latest.json"
    manual_backfill_verification_path = f"{artifact_root}/au-p0b-google-manual-backfill-verification-latest.json"
    planned_runs = _planned_runs(prompt_count, geo_cities, sample_size, DEFAULT_SURFACE_COUNT)
    python_env = {"PYTHONPATH": "packages/geo_core:apps/api"}
    runbook: dict[str, Any] = {
        "runbook_version": RUNBOOK_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "scope": {
            "market": "AU",
            "phase": "P0b Google AIO / AI Mode Spike",
            "prompt_count": prompt_count,
            "surfaces": ("google_aio", "google_ai_mode"),
            "geo_cities": geo_cities,
            "sample_size": sample_size,
            "collection_paths": collection_paths,
            "planned_runs": planned_runs,
            "pass_gate": {
                "google_aio_success_rate_threshold": 0.80,
                "required_collection_path_count": 2,
                "required_assets": ("screenshot", "html_snapshot"),
            },
        },
        "required_env": ("GOOGLE_PLAYWRIGHT_ENABLED", "MANUAL_BACKFILL_PATH", "DATABASE_URL"),
        "recommended_env": (
            "GOOGLE_PLAYWRIGHT_PROMPT_SELECTOR",
            "GOOGLE_PLAYWRIGHT_ANSWER_SELECTOR",
            "GOOGLE_PLAYWRIGHT_SUBMIT_SELECTOR",
            "GOOGLE_PLAYWRIGHT_CITATION_SELECTOR",
            "GOOGLE_PLAYWRIGHT_STORAGE_STATE",
            "GOOGLE_AIO_PLAYWRIGHT_START_URL",
            "GOOGLE_AI_MODE_PLAYWRIGHT_START_URL",
            "GOOGLE_PLAYWRIGHT_BROWSER_NAME",
            "GOOGLE_PLAYWRIGHT_TIMEOUT_SECONDS",
            "GOOGLE_PLAYWRIGHT_VENDOR_COST",
            "SERP_API_KEY",
            "SERP_API_ENDPOINT",
            "SERP_API_ENGINE",
            "SERP_API_GL",
            "SERP_API_HL",
            "SERP_API_LOCATION",
            "SERP_API_VENDOR_COST",
            "OBJECT_STORE_ENDPOINT",
            "OBJECT_STORE_BUCKET",
            "OBJECT_STORE_ACCESS_KEY",
            "OBJECT_STORE_SECRET_KEY",
            "GEO_BROWSER_ARTIFACT_DIR",
        ),
        "artifact_paths": {
            "playwright_env_json": playwright_env_path,
            "playwright_smoke_json": smoke_path,
            "manual_backfill_verification_json": manual_backfill_verification_path,
            "health_json": health_path,
            "health_manifest": health_manifest_path,
            "spike_json": spike_path,
            "spike_manifest": spike_manifest_path,
        },
        "gates": {
            "health_gate": "collector_health_gate must pass before any real Google spike collection.",
            "spike_gate": "worker must pass both google_spike_gate and google_spike_readiness_gate.",
            "limited_coverage_gate": "If either Google gate fails, Google remains limited coverage and must not enter the main scoring denominator.",
        },
        "steps": (
            {
                "id": "prepare_environment",
                "title": "Prepare Google browser capture, third-party SERP API, manual backfill, database, and optional object storage",
                "type": "manual",
                "required_env": ("GOOGLE_PLAYWRIGHT_ENABLED", "MANUAL_BACKFILL_PATH", "DATABASE_URL"),
                "recommended_env": (
                    "GOOGLE_PLAYWRIGHT_PROMPT_SELECTOR",
                    "GOOGLE_PLAYWRIGHT_ANSWER_SELECTOR",
                    "GOOGLE_PLAYWRIGHT_SUBMIT_SELECTOR",
                    "GOOGLE_PLAYWRIGHT_CITATION_SELECTOR",
                    "GOOGLE_PLAYWRIGHT_STORAGE_STATE",
                    "GOOGLE_AIO_PLAYWRIGHT_START_URL",
                    "GOOGLE_AI_MODE_PLAYWRIGHT_START_URL",
                    "GOOGLE_PLAYWRIGHT_BROWSER_NAME",
                    "GOOGLE_PLAYWRIGHT_TIMEOUT_SECONDS",
                    "GOOGLE_PLAYWRIGHT_VENDOR_COST",
                    "SERP_API_KEY",
                    "SERP_API_ENDPOINT",
                    "SERP_API_ENGINE",
                    "SERP_API_GL",
                    "SERP_API_HL",
                    "SERP_API_LOCATION",
                    "SERP_API_VENDOR_COST",
                    "OBJECT_STORE_ENDPOINT",
                    "OBJECT_STORE_BUCKET",
                    "OBJECT_STORE_ACCESS_KEY",
                    "OBJECT_STORE_SECRET_KEY",
                    "GEO_BROWSER_ARTIFACT_DIR",
                ),
                "stop_on_failure": True,
                "notes": (
                    "The first real Google spike path is selector-driven browser capture for google_aio.",
                    "Browser health fails fast with selector_missing, session_state_missing, or playwright_missing before collection.",
                    "The second path is manual backfill for google_ai_mode until AI Mode browser capture is implemented.",
                    "Generate, fill, and verify MANUAL_BACKFILL_PATH with au-p0b-google-manual-template and verify-au-p0b-google-manual-backfill before collection.",
                    "Run au-p0b-google-playwright-env and verify-au-p0b-google-playwright-env before the smoke capture to confirm selectors, Playwright package, and optional storage state are ready without leaking raw values.",
                    "Run au-p0b-google-playwright-smoke and verify-au-p0b-google-playwright-smoke before the 240-run matrix; use --require-success on the verifier before promoting the browser path.",
                    "Run verify-au-p0b-google-manual-backfill after filling MANUAL_BACKFILL_PATH so the strict 120-row manual verification artifact can be read by the status report.",
                    "Third-party SERP JSON capture is implemented as an alternate google_aio backend, but not part of the default 240-run matrix.",
                    "Do not persist secrets in generated JSON artifacts.",
                ),
            },
            _command_step(
                step_id="google_playwright_env",
                title="Build redacted Google Playwright environment readiness report",
                command=[
                    "python3",
                    "scripts/build_au_p0b_google_playwright_env_report.py",
                    "--runbook-path",
                    runbook_path,
                    "--env-file",
                    ".env.au-p0b-google",
                    "--output-path",
                    playwright_env_path,
                ],
                env=python_env,
                output_paths=(playwright_env_path,),
                notes=(
                    "The environment report records presence/source/length/hash prefixes only; it must not persist raw selectors, secrets, or database URLs.",
                    "Default verification proves the readiness report is auditable; strict verification is used before smoke.",
                ),
            ),
            _command_step(
                step_id="google_playwright_env_verify",
                title="Verify Google Playwright environment report and require smoke readiness",
                command=[
                    "python3",
                    "scripts/verify_au_p0b_google_playwright_env_report.py",
                    playwright_env_path,
                    "--require-ready-smoke",
                ],
                env=python_env,
                output_paths=(),
            ),
            _command_step(
                step_id="google_playwright_smoke",
                title="Run one Google Playwright browser smoke capture before the full matrix",
                command=[
                    "python3",
                    "scripts/run_au_p0b_google_playwright_smoke.py",
                    "--output-path",
                    smoke_path,
                ],
                env=python_env,
                output_paths=(smoke_path,),
                planned_runs=1,
                notes=(
                    "The smoke runner writes an auditable JSON payload even when collector health is not ready.",
                    "Use scripts/verify_au_p0b_google_playwright_smoke.py --require-success for the final browser-path promotion gate.",
                ),
            ),
            _command_step(
                step_id="google_playwright_smoke_verify",
                title="Verify Google Playwright smoke payload integrity and browser evidence structure",
                command=[
                    "python3",
                    "scripts/verify_au_p0b_google_playwright_smoke.py",
                    smoke_path,
                    "--require-success",
                ],
                env=python_env,
                output_paths=(),
                planned_runs=1,
            ),
            _command_step(
                step_id="google_manual_backfill_verify",
                title="Verify strict Google AI Mode manual backfill coverage before the full matrix",
                command=[
                    "python3",
                    "scripts/verify_au_p0b_manual_backfill.py",
                    "--output-path",
                    manual_backfill_verification_path,
                ],
                env=python_env,
                output_paths=(manual_backfill_verification_path,),
                planned_runs=prompt_count * len(geo_cities) * sample_size,
                notes=(
                    "The verifier reads MANUAL_BACKFILL_PATH when it is set, otherwise the generated template path.",
                    "Strict mode requires 120 rows, two samples for each prompt/city, answer text, citation URLs, and screenshot or HTML evidence.",
                    "The output JSON includes file_sha256 and verification_hash for status-report replay.",
                ),
            ),
            _command_step(
                step_id="google_spike_health_check",
                title="Check Google spike collector readiness without external collection",
                command=_make_command("au-p0b-google-spike-health"),
                env={
                    "GEO_AU_P0B_GOOGLE_SPIKE_HEALTH_OUTPUT_PATH": health_path,
                },
                output_paths=(health_path,),
                planned_runs=planned_runs,
            ),
            _command_step(
                step_id="google_spike_health_manifest",
                title="Build audit manifest for the Google spike health check",
                command=_make_command("au-p0b-google-spike-health-manifest"),
                env={
                    "GEO_AU_P0B_GOOGLE_SPIKE_HEALTH_OUTPUT_PATH": health_path,
                    "GEO_AU_P0B_GOOGLE_SPIKE_HEALTH_MANIFEST_PATH": health_manifest_path,
                },
                output_paths=(health_manifest_path,),
            ),
            _command_step(
                step_id="google_spike_collect",
                title="Run the full Google spike matrix and require both Google gates",
                command=_make_command("au-p0b-google-spike"),
                env={
                    **({"GEO_AU_P0B_GOOGLE_SPIKE_PERSIST_ARGS": ""} if not persist else {}),
                    "GEO_AU_P0B_GOOGLE_SPIKE_OUTPUT_PATH": spike_path,
                },
                output_paths=(spike_path,),
                planned_runs=planned_runs,
                notes=(
                    "The worker exits non-zero if collection failures occur or either Google spike gate fails.",
                    "Default matrix is 30 prompts x 2 geo cities x k=2 x 2 Google surfaces/paths. Third-party SERP can be run as a separate comparison slice.",
                ),
            ),
            _command_step(
                step_id="google_spike_manifest",
                title="Build audit manifest for the Google spike payload",
                command=_make_command("au-p0b-google-spike-manifest"),
                env={
                    "GEO_AU_P0B_GOOGLE_SPIKE_OUTPUT_PATH": spike_path,
                    "GEO_AU_P0B_GOOGLE_SPIKE_MANIFEST_PATH": spike_manifest_path,
                },
                output_paths=(spike_manifest_path,),
            ),
            {
                "id": "google_spike_decision_handoff",
                "title": "Record pass/fail conclusion in report method disclosure",
                "type": "manual",
                "stop_on_failure": True,
                "output_paths": (),
                "notes": (
                    "If google_spike_gate and google_spike_readiness_gate both pass, Google can enter the main scoring denominator.",
                    "If either gate fails, keep Google in limited coverage appendix and record failure reasons.",
                ),
            },
        ),
    }
    runbook["runbook_payload_hash"] = compute_google_spike_runbook_hash(runbook)
    return runbook


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a command runbook for the AU P0b Google spike")
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the generated Google spike runbook JSON.",
    )
    parser.add_argument(
        "--artifact-dir",
        default=os.environ.get("GEO_AU_P0B_GOOGLE_ARTIFACT_DIR", DEFAULT_ARTIFACT_DIR),
        help="Directory for generated Google spike evidence JSON files.",
    )
    parser.add_argument("--prompt-count", type=int, default=int(os.environ.get("GEO_AU_P0B_GOOGLE_PROMPT_COUNT", "30")))
    parser.add_argument("--sample-size", type=int, default=int(os.environ.get("GEO_AU_P0B_GOOGLE_SAMPLE_SIZE", "2")))
    parser.add_argument("--no-persist", action="store_true", help="Omit --persist from the Google spike collection command.")
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runbook = build_au_p0b_google_spike_runbook(
        artifact_dir=args.artifact_dir,
        prompt_count=args.prompt_count,
        sample_size=args.sample_size,
        runbook_path=args.output_path,
        persist=not args.no_persist,
        generated_at=args.generated_at,
    )
    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(runbook, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(runbook, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
