"""Command-line entry point for the isolated F-019 benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .dataset import MANIFEST_PATH, load_dataset
from .runner import adapter_by_name, run_candidate, write_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate", help="validate manifest, hashes, corpus and gold")
    run = subparsers.add_parser("run", help="execute one isolated adapter")
    run.add_argument(
        "--adapter",
        choices=("deterministic", "llamaindex", "graphrag"),
        required=True,
    )
    run.add_argument("--output", type=Path)
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

    report = run_candidate(adapter_by_name(arguments.adapter), manifest_path=arguments.manifest)
    if arguments.output:
        write_report(report, arguments.output)
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 3


if __name__ == "__main__":
    raise SystemExit(main())
