from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RUNBOOK_VERSION = "au_p0a_real_batch_runbook_v1"
DEFAULT_ARTIFACT_DIR = "docs/runtime_preflight"
DEFAULT_OUTPUT_PATH = f"{DEFAULT_ARTIFACT_DIR}/au-p0a-runbook-latest.json"
DEFAULT_CITIES = ("Australia", "Sydney", "Melbourne", "Brisbane")
DEFAULT_SMALL_CITIES = ("Sydney",)
PLATFORM_COUNT = 2


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _csv_tuple(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _stable_runbook_bytes(runbook: dict[str, Any]) -> bytes:
    return json.dumps(
        runbook,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def compute_runbook_payload_hash(runbook: dict[str, Any]) -> str:
    payload_for_hash = dict(runbook)
    payload_for_hash.pop("runbook_payload_hash", None)
    return hashlib.sha256(_stable_runbook_bytes(payload_for_hash)).hexdigest()


def _shell_command(command: list[str], env: dict[str, str] | None = None) -> str:
    env_prefix = [f"{key}={shlex.quote(value)}" for key, value in (env or {}).items()]
    return " ".join((*env_prefix, shlex.join(command)))


def _worker_command(
    *,
    prompt_limit: int,
    cities: tuple[str, ...],
    sample_size: int,
    output_path: str,
    persist: bool,
    persist_analysis: bool,
) -> list[str]:
    command = [
        "python3",
        "workers/collector_worker/run_collection_slice.py",
        "--mode",
        "api",
        "--prompt-limit",
        str(prompt_limit),
        "--cities",
        ",".join(cities),
        "--sample-size",
        str(sample_size),
        "--require-ready-collectors",
        "--require-p0a-readiness",
        "--require-no-collection-failures",
        "--preflight-output-path",
        output_path,
    ]
    if persist:
        command.append("--persist")
    if persist_analysis:
        command.append("--persist-analysis")
    return command


def _command_step(
    *,
    step_id: str,
    title: str,
    command: list[str],
    env: dict[str, str] | None = None,
    output_paths: tuple[str, ...] = (),
    stop_on_failure: bool = True,
    planned_runs: int | None = None,
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
        "stop_on_failure": stop_on_failure,
        "notes": notes,
    }
    if planned_runs is not None:
        step["planned_runs"] = planned_runs
    return step


def _planned_runs(prompt_limit: int, cities: tuple[str, ...], sample_size: int) -> int:
    return prompt_limit * len(cities) * sample_size * PLATFORM_COUNT


def build_au_p0a_runbook(
    *,
    artifact_dir: str = DEFAULT_ARTIFACT_DIR,
    small_prompt_limit: int = 5,
    full_prompt_limit: int = 100,
    sample_size: int = 3,
    small_cities: tuple[str, ...] = DEFAULT_SMALL_CITIES,
    full_cities: tuple[str, ...] = DEFAULT_CITIES,
    persist: bool = True,
    persist_analysis: bool = True,
    generated_at: str | None = None,
) -> dict[str, Any]:
    artifact_root = artifact_dir.rstrip("/")
    preflight_path = f"{artifact_root}/api-preflight-latest.json"
    preflight_manifest_path = f"{artifact_root}/api-preflight-manifest-latest.json"
    small_batch_path = f"{artifact_root}/au-p0a-small-batch.json"
    small_manifest_path = f"{artifact_root}/au-p0a-small-batch-manifest.json"
    full_batch_path = f"{artifact_root}/au-p0a-full-batch.json"
    full_manifest_path = f"{artifact_root}/au-p0a-full-batch-manifest.json"
    python_env = {"PYTHONPATH": "packages/geno_core:apps/api"}
    preflight_env = {"GENO_API_PREFLIGHT_OUTPUT_PATH": preflight_path}
    manifest_env = {
        "GENO_API_PREFLIGHT_OUTPUT_PATH": preflight_path,
        "GENO_API_PREFLIGHT_MANIFEST_PATH": preflight_manifest_path,
    }
    small_planned_runs = _planned_runs(small_prompt_limit, small_cities, sample_size)
    full_planned_runs = _planned_runs(full_prompt_limit, full_cities, sample_size)
    runbook: dict[str, Any] = {
        "runbook_version": RUNBOOK_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "scope": {
            "market": "AU",
            "phase": "P0a Stable Evidence Chain",
            "platforms": ("perplexity.sonar.api", "openai.web_search.api"),
            "sample_size": sample_size,
            "small_batch": {
                "prompt_limit": small_prompt_limit,
                "cities": small_cities,
                "planned_runs": small_planned_runs,
            },
            "full_batch": {
                "prompt_limit": full_prompt_limit,
                "cities": full_cities,
                "planned_runs": full_planned_runs,
            },
        },
        "required_env": (
            "PERPLEXITY_API_KEY",
            "OPENAI_API_KEY",
            "DATABASE_URL",
        ),
        "recommended_env": (
            "OBJECT_STORE_ENDPOINT",
            "OBJECT_STORE_BUCKET",
            "OBJECT_STORE_ACCESS_KEY",
            "OBJECT_STORE_SECRET_KEY",
        ),
        "artifact_paths": {
            "preflight_json": preflight_path,
            "preflight_manifest": preflight_manifest_path,
            "small_batch_json": small_batch_path,
            "small_batch_manifest": small_manifest_path,
            "full_batch_json": full_batch_path,
            "full_batch_manifest": full_manifest_path,
        },
        "gates": {
            "audit_gate": "make verify-api-preflight must pass for each generated JSON payload.",
            "design_partner_gate": "scripts/verify_preflight_payload.py --require-design-partner-ready must pass before moving from preflight to small batch and before moving from small batch to full batch.",
            "manifest_gate": "scripts/build_preflight_manifest.py --require-design-partner-ready must pass for small/full batch manifests before treating the evidence package as ready.",
        },
        "steps": (
            {
                "id": "prepare_environment",
                "title": "Prepare provider keys, database, and optional object storage",
                "type": "manual",
                "required_env": ("PERPLEXITY_API_KEY", "OPENAI_API_KEY", "DATABASE_URL"),
                "recommended_env": ("OBJECT_STORE_ENDPOINT", "OBJECT_STORE_BUCKET", "OBJECT_STORE_ACCESS_KEY", "OBJECT_STORE_SECRET_KEY"),
                "stop_on_failure": True,
                "notes": (
                    "Do not start real AU batches until provider keys and DATABASE_URL are present.",
                    "Object storage is recommended so API snapshots and report artifacts become durable s3:// evidence assets.",
                ),
            },
            _command_step(
                step_id="preflight_collect",
                title="Run 1 prompt x Sydney x k=3 x 2-platform provider preflight",
                command=["make", "api-preflight"],
                env=preflight_env,
                output_paths=(preflight_path,),
                planned_runs=_planned_runs(1, ("Sydney",), sample_size),
            ),
            _command_step(
                step_id="preflight_verify_audit",
                title="Verify preflight payload hash and structure",
                command=["make", "verify-api-preflight"],
                env=preflight_env,
                output_paths=(preflight_path,),
            ),
            _command_step(
                step_id="preflight_manifest_audit",
                title="Build preflight evidence manifest",
                command=["make", "preflight-manifest"],
                env=manifest_env,
                output_paths=(preflight_manifest_path,),
            ),
            _command_step(
                step_id="preflight_design_partner_gate",
                title="Stop unless preflight is design-partner ready",
                command=[
                    "python3",
                    "scripts/verify_preflight_payload.py",
                    preflight_path,
                    "--require-design-partner-ready",
                ],
                env=python_env,
                output_paths=(preflight_path,),
            ),
            _command_step(
                step_id="small_batch_collect",
                title="Run small AU smoke batch before full design-partner run",
                command=_worker_command(
                    prompt_limit=small_prompt_limit,
                    cities=small_cities,
                    sample_size=sample_size,
                    output_path=small_batch_path,
                    persist=persist,
                    persist_analysis=persist_analysis,
                ),
                env=python_env,
                output_paths=(small_batch_path,),
                planned_runs=small_planned_runs,
            ),
            _command_step(
                step_id="small_batch_manifest_gate",
                title="Verify and manifest the small AU batch",
                command=[
                    "python3",
                    "scripts/build_preflight_manifest.py",
                    small_batch_path,
                    "--manifest-path",
                    small_manifest_path,
                    "--require-design-partner-ready",
                ],
                env=python_env,
                output_paths=(small_manifest_path,),
            ),
            _command_step(
                step_id="full_batch_collect",
                title="Run full AU P0a batch after small batch passes",
                command=_worker_command(
                    prompt_limit=full_prompt_limit,
                    cities=full_cities,
                    sample_size=sample_size,
                    output_path=full_batch_path,
                    persist=persist,
                    persist_analysis=persist_analysis,
                ),
                env=python_env,
                output_paths=(full_batch_path,),
                planned_runs=full_planned_runs,
            ),
            _command_step(
                step_id="full_batch_manifest_gate",
                title="Verify and manifest the full AU P0a evidence package",
                command=[
                    "python3",
                    "scripts/build_preflight_manifest.py",
                    full_batch_path,
                    "--manifest-path",
                    full_manifest_path,
                    "--require-design-partner-ready",
                ],
                env=python_env,
                output_paths=(full_manifest_path,),
            ),
        ),
    }
    runbook["runbook_payload_hash"] = compute_runbook_payload_hash(runbook)
    return runbook


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a command runbook for the AU P0a real provider batch")
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GENO_AU_P0A_RUNBOOK_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the generated runbook JSON.",
    )
    parser.add_argument(
        "--artifact-dir",
        default=os.environ.get("GENO_AU_P0A_ARTIFACT_DIR", DEFAULT_ARTIFACT_DIR),
        help="Directory for generated runtime preflight and batch evidence JSON files.",
    )
    parser.add_argument("--small-prompt-limit", type=int, default=int(os.environ.get("GENO_AU_P0A_SMALL_PROMPT_LIMIT", "5")))
    parser.add_argument("--full-prompt-limit", type=int, default=int(os.environ.get("GENO_AU_P0A_FULL_PROMPT_LIMIT", "100")))
    parser.add_argument("--sample-size", type=int, default=int(os.environ.get("GENO_AU_P0A_SAMPLE_SIZE", "3")))
    parser.add_argument("--small-cities", default=os.environ.get("GENO_AU_P0A_SMALL_CITIES", ",".join(DEFAULT_SMALL_CITIES)))
    parser.add_argument("--cities", default=os.environ.get("GENO_AU_P0A_CITIES", ",".join(DEFAULT_CITIES)))
    parser.add_argument("--no-persist", action="store_true", help="Omit --persist from small/full batch commands.")
    parser.add_argument("--no-persist-analysis", action="store_true", help="Omit --persist-analysis from small/full batch commands.")
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runbook = build_au_p0a_runbook(
        artifact_dir=args.artifact_dir,
        small_prompt_limit=args.small_prompt_limit,
        full_prompt_limit=args.full_prompt_limit,
        sample_size=args.sample_size,
        small_cities=_csv_tuple(args.small_cities),
        full_cities=_csv_tuple(args.cities),
        persist=not args.no_persist,
        persist_analysis=not args.no_persist_analysis,
        generated_at=args.generated_at,
    )
    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(runbook, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(runbook, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
