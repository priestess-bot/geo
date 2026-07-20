from __future__ import annotations

import hashlib
from pathlib import Path

from benchmarks.f019.dataset import MANIFEST_PATH, apply_delta, load_dataset


def test_manifest_hashes_and_minimum_gold_are_valid() -> None:
    dataset = load_dataset()

    assert dataset.manifest["schema_version"] == "f019-benchmark-manifest-v1"
    assert dataset.manifest["dataset_version"] == "2026.07.19.1"
    assert len(dataset.documents) == 20
    assert len(dataset.gold["facts"]) == 60
    assert len(dataset.gold["entities"]) == 53
    assert len(dataset.gold["relations"]) == 40
    assert len(dataset.gold["questions"]) == 40

    for descriptor in dataset.manifest["files"].values():
        path = MANIFEST_PATH.parent / descriptor["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == descriptor["sha256"]


def test_corpus_covers_required_formats_categories_and_geo_phenomena() -> None:
    dataset = load_dataset()
    manifest_coverage = set(dataset.manifest["coverage"]["phenomena"])

    assert {item.source_format for item in dataset.documents} == {
        "html",
        "pdf",
        "docx",
        "text",
    }
    assert {item.category for item in dataset.documents} == {
        "product",
        "competitor",
        "market",
    }
    assert {item.project_id for item in dataset.documents} == {
        "project-aurora",
        "project-boreal",
    }
    assert {item.conflict_group for item in dataset.documents if item.conflict_group} == {
        "aurora-a1-warranty",
        "boreal-hub-price",
    }
    assert {"facts", "entities", "relations", "conflicts", "time", "noise"} <= (
        manifest_coverage
    )
    assert sum("噪声" in item.content for item in dataset.documents) >= 8


def test_delta_covers_reimport_update_delete_and_add_without_crossing_projects() -> None:
    dataset = load_dataset()
    active = apply_delta(dataset.documents, dataset.delta_operations)

    assert {item.operation for item in dataset.delta_operations} == {
        "reimport",
        "update",
        "delete",
        "add",
    }
    assert len(active) == 20
    assert "boreal-competitor-010" not in {item.document_id for item in active}
    assert "aurora-market-011" in {item.document_id for item in active}
    assert all(
        operation.document is None or operation.document.project_id == operation.project_id
        for operation in dataset.delta_operations
    )


def test_manifest_declares_official_gate_and_no_cost_or_time_cap() -> None:
    gate = load_dataset().manifest["quality_gate"]
    policy = load_dataset().manifest["selection_policy"]

    assert gate["entity_precision_min"] == 0.85
    assert gate["relation_precision_min"] == 0.80
    assert gate["formal_fact_source_traceability"] == 1.0
    assert gate["unsupported_question_rate_max"] == 0.05
    assert gate["semantic_duplicate_question_rate_max"] == 0.10
    assert gate["evidence_backed_dimension_coverage_min"] == 0.90
    assert policy["quality_close_threshold"] == 0.02
    assert policy["cost_time_policy"] == "record_only_no_hard_cap"
    assert "cost_max" not in policy
    assert "wall_clock_max" not in policy


def test_schemas_are_versioned_files() -> None:
    schema_directory = Path(__file__).parents[3] / "benchmarks" / "f019" / "schemas"

    assert (schema_directory / "candidate-output.schema.json").is_file()
    assert (schema_directory / "report.schema.json").is_file()
    assert (schema_directory / "manifest.schema.json").is_file()


def test_project_owned_contract_does_not_import_framework_types() -> None:
    contract_path = (
        Path(__file__).parents[3] / "benchmarks" / "f019" / "contracts.py"
    )
    source = contract_path.read_text(encoding="utf-8")

    assert "llama_index" not in source
    assert "graphrag" not in source
