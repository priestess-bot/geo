"""Offline benchmark runner and JSON report writer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .adapters import (
    DeterministicBaselineAdapter,
    graphrag_adapter,
    llamaindex_adapter,
    project_native_adapter,
)
from .contracts import BenchmarkAdapter
from .dataset import MANIFEST_PATH, load_dataset
from .scoring import score_candidate


def adapter_by_name(name: str, *, model=None) -> BenchmarkAdapter:
    if name == "deterministic":
        return DeterministicBaselineAdapter()
    if name == "project-native":
        return project_native_adapter(model)
    if name == "llamaindex":
        return llamaindex_adapter(model)
    if name == "graphrag":
        return graphrag_adapter()
    raise ValueError(f"unknown benchmark adapter: {name}")


def run_candidate(
    adapter: BenchmarkAdapter,
    *,
    manifest_path: Path = MANIFEST_PATH,
) -> dict[str, Any]:
    dataset = load_dataset(manifest_path)
    run = adapter.run(dataset.documents, dataset.delta_operations)
    score = score_candidate(run, dataset)
    report = {
        **score,
        "dataset": {
            "schema_version": dataset.manifest["schema_version"],
            "dataset_version": dataset.manifest["dataset_version"],
            "manifest_sha256": _sha256(manifest_path),
            "project_ids": dataset.manifest["project_boundary"]["project_ids"],
        },
        "raw_candidate_output": run.to_dict(),
    }
    evidence = getattr(adapter, "usage_evidence", None)
    if callable(evidence):
        report["usage_evidence"] = evidence()
    validation_evidence = getattr(adapter, "validation_evidence", None)
    if callable(validation_evidence):
        report["validation_evidence"] = validation_evidence()
    return report


def write_report(report: dict[str, Any], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()
