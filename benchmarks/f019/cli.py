"""Command-line entry point for the isolated F-019 benchmark."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from typing import Sequence

from .dataset import MANIFEST_PATH, load_dataset
from .runner import adapter_by_name, run_candidate, write_report
from .provider import DeepSeekJsonInvoker
from .selection import (
    REQUIRED_CANDIDATES,
    build_selection_manifest,
    write_selection_manifest,
)
from geo_core.rag.selection import load_rag_selection


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate", help="validate manifest, hashes, corpus and gold")
    run = subparsers.add_parser("run", help="execute one isolated adapter")
    run.add_argument(
        "--adapter",
        choices=("deterministic", "project-native", "llamaindex", "graphrag"),
        required=True,
    )
    run.add_argument("--output", type=Path)
    run.add_argument("--deepseek-key-file", type=Path, default=_default_key_file())
    run.add_argument("--model", default="deepseek-v4-flash")
    suite = subparsers.add_parser(
        "suite", help="run every frozen candidate and build a fail-closed selection"
    )
    suite.add_argument("--output-dir", type=Path, required=True)
    suite.add_argument("--selection", type=Path, required=True)
    suite.add_argument("--deepseek-key-file", type=Path, default=_default_key_file())
    suite.add_argument("--model", default="deepseek-v4-flash")
    select = subparsers.add_parser(
        "select", help="build a selection from existing frozen candidate reports"
    )
    select.add_argument("--report-dir", type=Path, required=True)
    select.add_argument("--selection", type=Path, required=True)
    verify = subparsers.add_parser(
        "verify-selection", help="verify the selected report hash and every runtime gate"
    )
    verify.add_argument("--selection", type=Path, default=Path(__file__).parent / "selection.json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.command == "validate":
        dataset = load_dataset(arguments.manifest)
        print(
            json.dumps(
                {
                    "status": "valid",
                    "dataset_version": dataset.manifest["dataset_version"],
                    "document_count": len(dataset.documents),
                    "gold_counts": {
                        name: len(dataset.gold[name])
                        for name in ("facts", "entities", "relations", "questions")
                    },
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

    if arguments.command == "verify-selection":
        selected = load_rag_selection(arguments.selection)
        print(
            json.dumps(
                {
                    "status": "valid",
                    "candidate_id": selected.candidate_id,
                    "adapter_release": selected.adapter_release,
                    "dataset_version": selected.dataset_version,
                    "benchmark_report_hash": selected.benchmark_report_hash,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

    if arguments.command == "suite":
        reports: dict[str, Path] = {}
        for name in REQUIRED_CANDIDATES:
            destination = arguments.output_dir / f"{name}.json"
            print(f"running candidate={name}", flush=True)
            report = _run(
                name,
                manifest=arguments.manifest,
                key_file=arguments.deepseek_key_file,
                model=arguments.model,
            )
            write_report(report, destination)
            reports[name] = destination
            print(
                json.dumps(
                    {
                        "candidate": name,
                        "status": report["status"],
                        "selection_status": report["selection_status"],
                        "quality_score": report["quality_score"],
                        "usage": report.get("usage"),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                flush=True,
            )
        selection = build_selection_manifest(
            reports, selection_path=arguments.selection, generated_at=datetime.now(UTC)
        )
        write_selection_manifest(selection, arguments.selection)
        print(
            json.dumps(
                {
                    "status": selection["status"],
                    "selected": selection["selected"],
                    "selection_path": str(arguments.selection),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0 if selection["status"] == "selected" else 3

    if arguments.command == "select":
        reports = {name: arguments.report_dir / f"{name}.json" for name in REQUIRED_CANDIDATES}
        selection = build_selection_manifest(
            reports,
            selection_path=arguments.selection,
            generated_at=datetime.now(UTC),
        )
        write_selection_manifest(selection, arguments.selection)
        print(
            json.dumps(
                {
                    "status": selection["status"],
                    "selected": selection["selected"],
                    "selection_path": str(arguments.selection),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0 if selection["status"] == "selected" else 3

    report = _run(
        arguments.adapter,
        manifest=arguments.manifest,
        key_file=arguments.deepseek_key_file,
        model=arguments.model,
    )
    if arguments.output:
        write_report(report, arguments.output)
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 3


def _run(name: str, *, manifest: Path, key_file: Path | None, model: str):
    invoker = None
    if name in {"project-native", "llamaindex"} and key_file is not None:
        invoker = DeepSeekJsonInvoker(key_file=key_file, model=model)
    return run_candidate(adapter_by_name(name, model=invoker), manifest_path=manifest)


def _default_key_file() -> Path | None:
    value = os.getenv("GEO_DEEPSEEK_API_KEY_FILE", "").strip()
    return Path(value) if value else None


if __name__ == "__main__":
    raise SystemExit(main())
