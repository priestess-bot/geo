"""Fail-closed runtime validation for a version-controlled RAG selection."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


class RagSelectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class RagSelection:
    candidate_id: str
    adapter_release: str
    dataset_version: str
    benchmark_report_hash: str


def load_rag_selection(path: Path) -> RagSelection:
    manifest = _mapping(_read_json(path), "selection manifest")
    if manifest.get("schema_version") != "f019-selection-manifest-v1":
        raise RagSelectionError("unsupported F-019 selection manifest")
    if manifest.get("status") != "selected":
        raise RagSelectionError("no RAG adapter has passed the F-019 selection gate")
    selected = _mapping(manifest.get("selected"), "selected candidate")
    report_descriptor = _mapping(selected.get("report"), "selected report")
    report_path = (path.parent / _required_text(report_descriptor, "path")).resolve()
    expected_hash = _required_hash(report_descriptor, "sha256")
    if not report_path.is_file() or _file_hash(report_path) != expected_hash:
        raise RagSelectionError("selected benchmark report is missing or has changed")
    report = _mapping(_read_json(report_path), "selected benchmark report")
    candidate = _mapping(report.get("candidate"), "selected report candidate")
    gates = _mapping(report.get("gates"), "selected report gates")
    if (
        report.get("status") != "passed"
        or report.get("selection_status") != "eligible_candidate_passed"
        or candidate.get("eligible_for_selection") is not True
        or not gates
        or not all(value is True for value in gates.values())
    ):
        raise RagSelectionError("selected benchmark report does not pass every hard gate")
    candidate_id = _required_text(selected, "candidate_id")
    if candidate.get("candidate_id") != candidate_id:
        raise RagSelectionError("selection candidate does not match its benchmark report")
    dataset = _mapping(report.get("dataset"), "selected report dataset")
    dataset_version = _required_text(manifest, "dataset_version")
    if dataset.get("dataset_version") != dataset_version:
        raise RagSelectionError("selection and report dataset versions differ")
    return RagSelection(
        candidate_id=candidate_id,
        adapter_release=_required_text(selected, "adapter_release"),
        dataset_version=dataset_version,
        benchmark_report_hash=expected_hash,
    )


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RagSelectionError(f"unable to read F-019 selection artifact: {path.name}") from exc


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RagSelectionError(f"{label} must be a JSON object")
    return value


def _required_text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise RagSelectionError(f"selection field {key} is required")
    return item


def _required_hash(value: Mapping[str, Any], key: str) -> str:
    item = _required_text(value, key)
    if len(item) != 64 or any(char not in "0123456789abcdef" for char in item):
        raise RagSelectionError(f"selection field {key} must be lowercase SHA-256")
    return item


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
