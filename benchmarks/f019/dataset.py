"""Load and validate the versioned, fully offline F-019 fixture dataset."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .contracts import DeltaOperation, Document


ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "manifest.json"


class DatasetValidationError(ValueError):
    """The checked-in benchmark fixture is incomplete or internally inconsistent."""


@dataclass(frozen=True)
class BenchmarkDataset:
    manifest: dict[str, Any]
    documents: tuple[Document, ...]
    delta_operations: tuple[DeltaOperation, ...]
    gold: dict[str, Any]


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _document(raw: Mapping[str, Any]) -> Document:
    return Document(
        document_id=str(raw["document_id"]),
        project_id=str(raw["project_id"]),
        source_format=raw["source_format"],
        category=raw["category"],
        title=str(raw["title"]),
        source_uri=str(raw["source_uri"]),
        license_id=str(raw["license_id"]),
        valid_from=str(raw["valid_from"]),
        content=str(raw["content"]),
        question_contexts=tuple(raw.get("question_contexts", ())),
        conflict_group=raw.get("conflict_group"),
    )


def _delta(raw: Mapping[str, Any]) -> DeltaOperation:
    replacement = raw.get("document")
    return DeltaOperation(
        operation_id=str(raw["operation_id"]),
        operation=raw["operation"],
        project_id=str(raw["project_id"]),
        document_id=str(raw["document_id"]),
        document=_document(replacement) if replacement else None,
    )


def load_dataset(manifest_path: Path = MANIFEST_PATH) -> BenchmarkDataset:
    manifest = _read_json(manifest_path)
    base = manifest_path.parent
    corpus = _read_json(base / manifest["files"]["corpus"]["path"])
    delta = _read_json(base / manifest["files"]["delta"]["path"])
    gold = _read_json(base / manifest["files"]["gold"]["path"])
    dataset = BenchmarkDataset(
        manifest=manifest,
        documents=tuple(_document(item) for item in corpus["documents"]),
        delta_operations=tuple(_delta(item) for item in delta["operations"]),
        gold=gold,
    )
    validate_dataset(dataset, base)
    return dataset


def validate_dataset(dataset: BenchmarkDataset, base: Path = ROOT) -> None:
    manifest = dataset.manifest
    if manifest.get("schema_version") != "f019-benchmark-manifest-v1":
        raise DatasetValidationError("unsupported manifest schema_version")
    if not manifest.get("dataset_version"):
        raise DatasetValidationError("dataset_version is required")

    for label, descriptor in manifest.get("files", {}).items():
        path = base / descriptor["path"]
        if not path.is_file():
            raise DatasetValidationError(f"manifest file missing: {label}")
        if _sha256(path) != descriptor["sha256"]:
            raise DatasetValidationError(f"manifest sha256 mismatch: {label}")

    documents = dataset.documents
    if len(documents) < 20:
        raise DatasetValidationError("corpus must contain at least 20 documents")
    _assert_unique((item.document_id for item in documents), "document_id")
    if {item.source_format for item in documents} != {"html", "pdf", "docx", "text"}:
        raise DatasetValidationError("corpus must cover html/pdf/docx/text")
    if {item.category for item in documents} != {"product", "competitor", "market"}:
        raise DatasetValidationError("corpus must cover product/competitor/market")

    projects = set(manifest["project_boundary"]["project_ids"])
    if {item.project_id for item in documents} != projects:
        raise DatasetValidationError("document projects do not match manifest boundary")
    licenses = {item["license_id"] for item in manifest["licenses"]}
    if any(item.license_id not in licenses for item in documents):
        raise DatasetValidationError("document references undeclared license")

    required_gold = {"facts": 50, "entities": 30, "relations": 30, "questions": 40}
    for name, minimum in required_gold.items():
        values = dataset.gold.get(name, [])
        if len(values) < minimum:
            raise DatasetValidationError(f"gold {name} must contain at least {minimum} items")
        _assert_unique((str(item["gold_id"]) for item in values), f"gold {name} id")
        if any(item["project_id"] not in projects for item in values):
            raise DatasetValidationError(f"gold {name} crosses the declared project boundary")

    fact_projects = {item["gold_id"]: item["project_id"] for item in dataset.gold["facts"]}
    for question in dataset.gold["questions"]:
        support_ids = question.get("supporting_fact_gold_ids", [])
        if not support_ids:
            raise DatasetValidationError(
                f"gold question has no supporting fact: {question['gold_id']}"
            )
        if any(fact_projects.get(fact_id) != question["project_id"] for fact_id in support_ids):
            raise DatasetValidationError(
                f"gold question support crosses project boundary: {question['gold_id']}"
            )

    document_keys = {(item.project_id, item.document_id) for item in documents}
    for operation in dataset.delta_operations:
        key = (operation.project_id, operation.document_id)
        if operation.operation in {"reimport", "update", "delete"} and key not in document_keys:
            raise DatasetValidationError(
                f"delta targets missing document: {operation.operation_id}"
            )
        if operation.operation in {"add", "update"} and operation.document is None:
            raise DatasetValidationError(f"delta replacement is required: {operation.operation_id}")
        if operation.document and operation.document.project_id != operation.project_id:
            raise DatasetValidationError(f"delta project mismatch: {operation.operation_id}")


def apply_delta(
    documents: Sequence[Document], operations: Sequence[DeltaOperation]
) -> tuple[Document, ...]:
    state = {(item.project_id, item.document_id): item for item in documents}
    for operation in operations:
        key = (operation.project_id, operation.document_id)
        if operation.operation == "reimport":
            state[key] = state[key]
        elif operation.operation == "delete":
            state.pop(key)
        elif operation.operation in {"add", "update"}:
            if operation.document is None:
                raise DatasetValidationError(f"missing delta document: {operation.operation_id}")
            state[key] = operation.document
    return tuple(state[key] for key in sorted(state))


def _assert_unique(values: Iterable[str], label: str) -> None:
    materialized = list(values)
    if len(materialized) != len(set(materialized)):
        raise DatasetValidationError(f"duplicate {label}")
