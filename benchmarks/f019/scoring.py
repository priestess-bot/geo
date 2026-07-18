"""Deterministic quality gates and quality-first candidate selection."""

from __future__ import annotations

import re
from dataclasses import asdict
from decimal import Decimal
from math import inf
from typing import Any, Iterable, Mapping, Sequence

from .contracts import CandidateArtifacts, CandidateRun, REPORT_SCHEMA_VERSION
from .dataset import BenchmarkDataset, apply_delta


QUALITY_WEIGHTS = {
    "entity_precision": 0.25,
    "relation_precision": 0.25,
    "question_groundedness": 0.20,
    "question_coverage": 0.20,
    "question_uniqueness": 0.10,
}


def _normal(value: str) -> str:
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", value.casefold())


def _precision_recall(predicted: set[tuple[Any, ...]], gold: set[tuple[Any, ...]]) -> tuple[float, float]:
    true_positive = len(predicted & gold)
    precision = true_positive / len(predicted) if predicted else 0.0
    recall = true_positive / len(gold) if gold else 0.0
    return precision, recall


def _f1(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def _semantic_duplicate_rate(texts: Sequence[str]) -> float:
    if not texts:
        return 1.0
    seen: list[set[str]] = []
    duplicates = 0
    for text in texts:
        normalized = _normal(text)
        grams = _character_ngrams(normalized)
        if any(_jaccard(grams, previous) >= 0.90 for previous in seen):
            duplicates += 1
        else:
            seen.append(grams)
    return duplicates / len(texts)


def _character_ngrams(value: str) -> set[str]:
    if len(value) < 3:
        return {value}
    return {value[index : index + 3] for index in range(len(value) - 2)}


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def _approval_bypass_count(artifacts: CandidateArtifacts) -> int:
    controlled: Iterable[Any] = (
        *artifacts.facts,
        *artifacts.entities,
        *artifacts.relations,
        *artifacts.questions,
    )
    return sum(
        item.control.workflow_status != "candidate" or not item.control.requires_human_approval
        for item in controlled
    )


def _project_leakage_count(
    artifacts: CandidateArtifacts, document_projects: Mapping[str, str]
) -> int:
    fact_projects = {item.candidate_id: item.project_id for item in artifacts.facts}
    violations = 0
    for fact in artifacts.facts:
        violations += document_projects.get(fact.source_document_id) != fact.project_id
    for entity in artifacts.entities:
        violations += any(
            document_projects.get(document_id) != entity.project_id
            for document_id in entity.source_document_ids
        )
    for relation in artifacts.relations:
        violations += document_projects.get(relation.source_document_id) != relation.project_id
    for question in artifacts.questions:
        violations += any(
            document_projects.get(document_id) != question.project_id
            for document_id in question.source_document_ids
        )
        violations += any(
            fact_projects.get(fact_id) != question.project_id for fact_id in question.source_fact_ids
        )
    for simulation in artifacts.simulations:
        violations += any(
            fact_projects.get(fact_id) != simulation.project_id
            for fact_id in simulation.source_fact_ids
        )
    return violations


def _incremental_audit(
    base: CandidateArtifacts,
    delta: CandidateArtifacts,
    dataset: BenchmarkDataset,
) -> dict[str, int]:
    active_documents = {
        item.document_id: item.project_id
        for item in apply_delta(dataset.documents, dataset.delta_operations)
    }
    changed_documents = {
        item.document_id
        for item in dataset.delta_operations
        if item.operation in {"update", "delete"}
    }

    fact_keys = [
        (item.project_id, _normal(item.text), item.source_document_id) for item in delta.facts
    ]
    relation_keys = [
        (
            item.project_id,
            _normal(item.subject),
            item.predicate,
            _normal(item.object),
            item.source_document_id,
        )
        for item in delta.relations
    ]
    duplicate_count = (len(fact_keys) - len(set(fact_keys))) + (
        len(relation_keys) - len(set(relation_keys))
    )

    referenced_documents: list[tuple[str, str]] = []
    referenced_documents.extend((item.source_document_id, item.project_id) for item in delta.facts)
    referenced_documents.extend((item.source_document_id, item.project_id) for item in delta.relations)
    for entity in delta.entities:
        referenced_documents.extend(
            (document_id, entity.project_id) for document_id in entity.source_document_ids
        )
    for question in delta.questions:
        referenced_documents.extend(
            (document_id, question.project_id) for document_id in question.source_document_ids
        )
    orphan_count = sum(
        active_documents.get(document_id) != project_id
        for document_id, project_id in referenced_documents
    )

    stable_base_facts = {
        (item.project_id, _normal(item.text), item.source_document_id)
        for item in base.facts
        if item.source_document_id not in changed_documents
    }
    stable_delta_facts = set(fact_keys)
    stable_base_relations = {
        (
            item.project_id,
            _normal(item.subject),
            item.predicate,
            _normal(item.object),
            item.source_document_id,
        )
        for item in base.relations
        if item.source_document_id not in changed_documents
    }
    stable_delta_relations = set(relation_keys)
    regression_count = len(stable_base_facts - stable_delta_facts) + len(
        stable_base_relations - stable_delta_relations
    )
    return {
        "duplicate_count": duplicate_count,
        "orphan_count": orphan_count,
        "regression_count": regression_count,
    }


def score_candidate(run: CandidateRun, dataset: BenchmarkDataset) -> dict[str, Any]:
    if not run.available or run.base is None or run.delta is None or run.usage is None:
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "candidate": _candidate_summary(run),
            "status": "unavailable",
            "selection_status": "not_selectable_unavailable",
            "metrics": None,
            "gates": None,
            "quality_score": None,
            "usage": None,
        }

    artifacts = run.base
    gold = dataset.gold
    gold_fact_ids = {
        (item["project_id"], _normal(item["text"]), item["source_document_id"]): item[
            "gold_id"
        ]
        for item in gold["facts"]
    }
    gold_facts = set(gold_fact_ids)
    predicted_facts = {
        (item.project_id, _normal(item.text), item.source_document_id)
        for item in artifacts.facts
    }
    fact_precision, fact_recall = _precision_recall(predicted_facts, gold_facts)

    gold_entities = {
        (item["project_id"], item["entity_type"], _normal(item["name"]))
        for item in gold["entities"]
    }
    predicted_entities = {
        (item.project_id, item.entity_type, _normal(item.name)) for item in artifacts.entities
    }
    entity_precision, entity_recall = _precision_recall(predicted_entities, gold_entities)

    gold_relations = {
        (
            item["project_id"],
            _normal(item["subject"]),
            item["predicate"],
            _normal(item["object"]),
        )
        for item in gold["relations"]
    }
    predicted_relations = {
        (
            item.project_id,
            _normal(item.subject),
            item.predicate,
            _normal(item.object),
        )
        for item in artifacts.relations
    }
    relation_precision, relation_recall = _precision_recall(predicted_relations, gold_relations)

    traceable = sum(
        bool(item.source_document_id and item.source_locator) for item in artifacts.facts
    )
    fact_traceability = traceable / len(artifacts.facts) if artifacts.facts else 0.0
    candidate_fact_gold_ids = {
        item.candidate_id: gold_fact_ids[
            (item.project_id, _normal(item.text), item.source_document_id)
        ]
        for item in artifacts.facts
        if (item.project_id, _normal(item.text), item.source_document_id) in gold_fact_ids
    }
    dimension_support = {
        (item["project_id"], item["dimension_key"]): set(item["supporting_fact_gold_ids"])
        for item in gold["questions"]
    }
    grounded_questions = []
    for question in artifacts.questions:
        mapped_support = {
            candidate_fact_gold_ids[fact_id]
            for fact_id in question.source_fact_ids
            if fact_id in candidate_fact_gold_ids
        }
        expected_support = dimension_support.get(
            (question.project_id, question.dimension_key), set()
        )
        if (
            question.source_fact_ids
            and len(mapped_support) == len(question.source_fact_ids)
            and mapped_support <= expected_support
        ):
            grounded_questions.append(question)
    unsupported_question_rate = (
        round(
            (len(artifacts.questions) - len(grounded_questions))
            / len(artifacts.questions),
            12,
        )
        if artifacts.questions
        else 1.0
    )
    gold_dimensions = {
        (item["project_id"], item["dimension_key"]) for item in gold["questions"]
    }
    covered_dimensions = {
        (item.project_id, item.dimension_key) for item in grounded_questions
    } & gold_dimensions
    question_coverage = (
        round(len(covered_dimensions) / len(gold_dimensions), 12) if gold_dimensions else 0.0
    )
    duplicate_rate = round(
        _semantic_duplicate_rate([item.text for item in artifacts.questions]), 12
    )

    document_projects = {item.document_id: item.project_id for item in dataset.documents}
    project_leakage_count = _project_leakage_count(artifacts, document_projects)
    approval_bypass_count = _approval_bypass_count(artifacts)
    test_only_publication_count = sum(
        not item.test_only or item.publication_eligible for item in artifacts.simulations
    )
    incremental = _incremental_audit(artifacts, run.delta, dataset)

    metrics = {
        "fact_precision_diagnostic": fact_precision,
        "fact_recall_diagnostic": fact_recall,
        "formal_fact_source_traceability": fact_traceability,
        "entity_precision": entity_precision,
        "entity_recall_diagnostic": entity_recall,
        "entity_f1_diagnostic": _f1(entity_precision, entity_recall),
        "relation_precision": relation_precision,
        "relation_recall_diagnostic": relation_recall,
        "relation_f1_diagnostic": _f1(relation_precision, relation_recall),
        "unsupported_question_rate": unsupported_question_rate,
        "question_groundedness": round(1 - unsupported_question_rate, 12),
        "semantic_duplicate_question_rate": duplicate_rate,
        "evidence_backed_dimension_coverage": question_coverage,
        "project_leakage_count": project_leakage_count,
        "approval_bypass_count": approval_bypass_count,
        "test_only_publication_count": test_only_publication_count,
        **incremental,
    }
    thresholds = dataset.manifest["quality_gate"]
    gates = {
        "entity_precision": entity_precision >= thresholds["entity_precision_min"],
        "relation_precision": relation_precision >= thresholds["relation_precision_min"],
        "formal_fact_source_traceability": fact_traceability
        == thresholds["formal_fact_source_traceability"],
        "unsupported_question_rate": unsupported_question_rate
        <= thresholds["unsupported_question_rate_max"],
        "semantic_duplicate_question_rate": duplicate_rate
        <= thresholds["semantic_duplicate_question_rate_max"],
        "evidence_backed_dimension_coverage": question_coverage
        >= thresholds["evidence_backed_dimension_coverage_min"],
        "project_leakage": project_leakage_count == 0,
        "approval_bypass": approval_bypass_count == 0,
        "test_only_publication": test_only_publication_count == 0,
        "incremental_duplicate": incremental["duplicate_count"] == 0,
        "incremental_orphan": incremental["orphan_count"] == 0,
        "incremental_regression": incremental["regression_count"] == 0,
    }
    quality_score = round(
        entity_precision * QUALITY_WEIGHTS["entity_precision"]
        + relation_precision * QUALITY_WEIGHTS["relation_precision"]
        + (1 - unsupported_question_rate) * QUALITY_WEIGHTS["question_groundedness"]
        + question_coverage * QUALITY_WEIGHTS["question_coverage"]
        + (1 - duplicate_rate) * QUALITY_WEIGHTS["question_uniqueness"],
        12,
    )
    passed = all(gates.values())
    selection_status = (
        "eligible_candidate_passed"
        if passed and run.eligible_for_selection
        else "harness_reference_only"
        if passed
        else "hard_gate_failed"
    )
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "candidate": _candidate_summary(run),
        "status": "passed" if passed else "failed",
        "selection_status": selection_status,
        "metrics": metrics,
        "gates": gates,
        "quality_score": quality_score,
        "quality_formula": QUALITY_WEIGHTS,
        "usage": asdict(run.usage),
        "cost_time_policy": "record_only_no_hard_cap",
    }


def select_candidate(reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    eligible = [
        report
        for report in reports
        if report.get("status") == "passed"
        and report["candidate"].get("eligible_for_selection") is True
    ]
    if not eligible:
        return {"selected_candidate_id": None, "reason": "no_eligible_candidate_passed"}
    best_quality = max(Decimal(str(item["quality_score"])) for item in eligible)
    close = [
        item
        for item in eligible
        if best_quality - Decimal(str(item["quality_score"])) < Decimal("0.02")
    ]
    if len(close) == 1:
        selected = close[0]
        reason = "quality_margin_at_least_2pp"
    else:
        selected = min(
            close,
            key=lambda item: (
                float(item.get("usage", {}).get("estimated_cost_usd", inf)),
                float(item.get("usage", {}).get("wall_clock_ms", inf)),
                0 if item["candidate"].get("adapter_kind") == "llamaindex" else 1,
                -float(item["quality_score"]),
                item["candidate"]["candidate_id"],
            ),
        )
        reason = "quality_within_2pp_then_cost_time_then_llamaindex"
    return {
        "selected_candidate_id": selected["candidate"]["candidate_id"],
        "reason": reason,
        "quality_score": selected["quality_score"],
        "estimated_cost_usd": selected["usage"]["estimated_cost_usd"],
        "wall_clock_ms": selected["usage"]["wall_clock_ms"],
    }


def _candidate_summary(run: CandidateRun) -> dict[str, Any]:
    return {
        "candidate_id": run.candidate_id,
        "adapter_kind": run.adapter_kind,
        "framework_version": run.framework_version,
        "eligible_for_selection": run.eligible_for_selection,
        "available": run.available,
        "unavailable_reason": run.unavailable_reason,
    }
