"""Build a fail-closed, hash-addressed selection manifest from candidate reports."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .scoring import select_candidate


SELECTION_SCHEMA_VERSION = "f019-selection-manifest-v1"
REQUIRED_CANDIDATES = (
    "deterministic",
    "project-native",
    "llamaindex",
    "graphrag",
)
ADAPTER_RELEASES = {
    "project-native-rag-v1": "project-native-rag-v1",
    "llamaindex-property-graph-v1": "llamaindex-property-graph-v1",
}
NATIVE_CANDIDATE_ID = "project-native-rag-v1"
LLAMAINDEX_CANDIDATE_ID = "llamaindex-property-graph-v1"


class SelectionManifestError(ValueError):
    pass


def build_selection_manifest(
    report_paths: Mapping[str, Path],
    *,
    selection_path: Path,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    if set(report_paths) != set(REQUIRED_CANDIDATES):
        raise SelectionManifestError("selection requires every frozen F-019 candidate report")
    reports = {name: _read_report(path) for name, path in report_paths.items()}
    dataset_versions = {
        str(_mapping(report.get("dataset"), "report dataset").get("dataset_version"))
        for report in reports.values()
    }
    manifest_hashes = {
        str(_mapping(report.get("dataset"), "report dataset").get("manifest_sha256"))
        for report in reports.values()
    }
    if len(dataset_versions) != 1 or "None" in dataset_versions:
        raise SelectionManifestError("candidate reports use different dataset versions")
    if len(manifest_hashes) != 1 or "None" in manifest_hashes:
        raise SelectionManifestError("candidate reports use different benchmark manifests")

    decision = select_candidate(tuple(reports.values()))
    selected_id = decision.get("selected_candidate_id")
    selected_report_name = next(
        (
            name
            for name, report in reports.items()
            if _mapping(report.get("candidate"), "report candidate").get("candidate_id")
            == selected_id
        ),
        None,
    )
    selected: dict[str, Any] | None = None
    status = "not_selected"
    if isinstance(selected_id, str) and selected_report_name is not None:
        candidate_report = reports[selected_report_name]
        gates = _mapping(candidate_report.get("gates"), "selected candidate gates")
        candidate = _mapping(candidate_report.get("candidate"), "selected candidate")
        if (
            candidate_report.get("status") != "passed"
            or candidate_report.get("selection_status") != "eligible_candidate_passed"
            or candidate.get("eligible_for_selection") is not True
            or not gates
            or not all(value is True for value in gates.values())
        ):
            raise SelectionManifestError(
                "selection algorithm returned a candidate with failed gates"
            )
        try:
            adapter_release = ADAPTER_RELEASES[selected_id]
        except KeyError as exc:
            raise SelectionManifestError(
                "selected candidate has no runtime adapter release"
            ) from exc
        selected = {
            "candidate_id": selected_id,
            "adapter_release": adapter_release,
            "reason": _selection_reason(selected_id, reports),
            "selection_algorithm_reason": decision["reason"],
            "quality_score": decision["quality_score"],
            "estimated_cost_usd": decision["estimated_cost_usd"],
            "wall_clock_ms": decision["wall_clock_ms"],
            "report": _descriptor(
                report_paths[selected_report_name], relative_to=selection_path.parent
            ),
        }
        status = "selected"

    llama = reports["llamaindex"]
    llama_candidate = _mapping(llama.get("candidate"), "LlamaIndex candidate")
    if status == "selected" and llama_candidate.get("available") is not True:
        # Missing integration is not quality evidence. A future hash-addressed technical
        # waiver may relax this, but dependency absence alone cannot select native.
        status = "not_selected"
        selected = None
    measurement_complete = all(
        _candidate_measurement_complete(reports[name]) for name in ("project-native", "llamaindex")
    )
    if status == "selected" and not measurement_complete:
        status = "not_selected"
        selected = None
    if llama_candidate.get("available") is not True:
        comparison_note = "llamaindex_unavailable_not_a_quality_failure"
    elif not measurement_complete:
        comparison_note = "candidate_usage_evidence_incomplete"
    else:
        comparison_note = "llamaindex_executed_and_scored"
    decision_basis = (
        _decision_basis(reports, selected_id)
        if status == "selected" and isinstance(selected_id, str)
        else None
    )
    qualified_fallbacks = (
        _qualified_fallbacks(
            reports,
            report_paths,
            selection_path=selection_path,
            selected_id=selected_id,
        )
        if status == "selected" and isinstance(selected_id, str)
        else []
    )
    return {
        "$schema": "schemas/selection.schema.json",
        "schema_version": SELECTION_SCHEMA_VERSION,
        "generated_at": (generated_at or datetime.now(UTC)).isoformat(),
        "status": status,
        "dataset_version": dataset_versions.pop(),
        "benchmark_manifest_sha256": manifest_hashes.pop(),
        "policy": {
            "quality_first": True,
            "cost_time_policy": "record_only_no_hard_cap",
            "quality_close_threshold": 0.02,
            "llamaindex_preferred_only_after_quality_cost_time_tie": True,
        },
        "comparison_note": comparison_note,
        "decision_basis": decision_basis,
        "qualified_fallbacks": qualified_fallbacks,
        "failed_or_dropped_evidence": _failed_or_dropped_evidence(reports),
        "candidates": [
            {
                "name": name,
                "candidate_id": _mapping(report.get("candidate"), "report candidate").get(
                    "candidate_id"
                ),
                "status": report.get("status"),
                "selection_status": report.get("selection_status"),
                "unavailable_reason": _mapping(report.get("candidate"), "report candidate").get(
                    "unavailable_reason"
                ),
                "quality_score": report.get("quality_score"),
                "all_hard_gates_passed": _all_hard_gates_passed(report),
                "disposition": _candidate_disposition(
                    name,
                    report,
                    selected_id=selected_id if status == "selected" else None,
                ),
                "validation_evidence": _validation_summary(report),
                "report": _descriptor(path, relative_to=selection_path.parent),
            }
            for name, path in ((name, report_paths[name]) for name in REQUIRED_CANDIDATES)
            for report in (reports[name],)
        ],
        "selected": selected,
    }


def _selection_reason(selected_id: str, reports: Mapping[str, Mapping[str, Any]]) -> str:
    llama = reports["llamaindex"]
    if selected_id == NATIVE_CANDIDATE_ID and _eligible_candidate_passed(llama):
        return (
            "project_owned_domain_boundary_and_business_source_of_truth_with_equal_quality"
        )
    return "quality_first_hard_gate_selection"


def _decision_basis(
    reports: Mapping[str, Mapping[str, Any]], selected_id: str
) -> dict[str, Any]:
    native = reports["project-native"]
    llama = reports["llamaindex"]
    resource_comparison = _resource_comparison(native, llama)
    return {
        "primary_reason_code": _selection_reason(selected_id, reports),
        "quality": {
            "project_native_score": native.get("quality_score"),
            "llamaindex_score": llama.get("quality_score"),
            "score_difference": _decimal_difference(
                native.get("quality_score"), llama.get("quality_score")
            ),
            "project_native_all_hard_gates_passed": _all_hard_gates_passed(native),
            "llamaindex_all_hard_gates_passed": _all_hard_gates_passed(llama),
        },
        "domain_boundary": {
            "stable_contract_owner": "geo_core.rag.contracts",
            "selected_runtime": "project_owned_adapter",
            "framework_adapter_policy": "optional_adapter_only",
            "framework_objects_cross_domain_or_stable_api": False,
        },
        "business_source_of_truth": {
            "owner": "project_knowledge_catalog_evidence_postgres",
            "framework_owned_business_state": False,
            "selection_changes_business_source_of_truth": False,
        },
        "integration_complexity": {
            "selected_path": "project_contracts_plus_project_model_gateway",
            "fallback_path": "optional_llamaindex_property_graph_adapter_plus_project_grounding",
            "assessment": "selected_path_has_fewer_runtime_layers_and_dependencies",
        },
        "recorded_resource_comparison": resource_comparison,
    }


def _resource_comparison(
    native: Mapping[str, Any], llama: Mapping[str, Any]
) -> dict[str, Any]:
    native_usage = _mapping(native.get("usage"), "Project Native usage")
    llama_usage = _mapping(llama.get("usage"), "LlamaIndex usage")
    native_total_tokens = _usage_int(native_usage, "input_tokens") + _usage_int(
        native_usage, "output_tokens"
    )
    llama_total_tokens = _usage_int(llama_usage, "input_tokens") + _usage_int(
        llama_usage, "output_tokens"
    )
    return {
        "policy": "record_only_no_hard_cap",
        "interpretation": "resource_measurements_are_audited_not_rejection_caps",
        "project_native": {
            "model_calls": _usage_int(native_usage, "model_calls"),
            "total_tokens": native_total_tokens,
            "estimated_cost_usd": native_usage.get("estimated_cost_usd"),
            "wall_clock_ms": _usage_int(native_usage, "wall_clock_ms"),
        },
        "llamaindex": {
            "model_calls": _usage_int(llama_usage, "model_calls"),
            "total_tokens": llama_total_tokens,
            "estimated_cost_usd": llama_usage.get("estimated_cost_usd"),
            "wall_clock_ms": _usage_int(llama_usage, "wall_clock_ms"),
        },
        "project_native_reduction_vs_llamaindex": {
            "model_calls": _difference(llama_usage, native_usage, "model_calls"),
            "total_tokens": llama_total_tokens - native_total_tokens,
            "estimated_cost_usd": _decimal_difference(
                llama_usage.get("estimated_cost_usd"),
                native_usage.get("estimated_cost_usd"),
            ),
            "wall_clock_ms": _difference(llama_usage, native_usage, "wall_clock_ms"),
            "model_calls_percent": _reduction_percent(
                _usage_int(native_usage, "model_calls"),
                _usage_int(llama_usage, "model_calls"),
            ),
            "total_tokens_percent": _reduction_percent(
                native_total_tokens, llama_total_tokens
            ),
            "estimated_cost_percent": _reduction_percent(
                native_usage.get("estimated_cost_usd"),
                llama_usage.get("estimated_cost_usd"),
            ),
            "wall_clock_percent": _reduction_percent(
                _usage_int(native_usage, "wall_clock_ms"),
                _usage_int(llama_usage, "wall_clock_ms"),
            ),
        },
    }


def _qualified_fallbacks(
    reports: Mapping[str, Mapping[str, Any]],
    report_paths: Mapping[str, Path],
    *,
    selection_path: Path,
    selected_id: str,
) -> list[dict[str, Any]]:
    fallbacks: list[dict[str, Any]] = []
    for name in ("project-native", "llamaindex"):
        report = reports[name]
        candidate_id = _mapping(report.get("candidate"), "report candidate").get(
            "candidate_id"
        )
        if candidate_id == selected_id or not _eligible_candidate_passed(report):
            continue
        if not isinstance(candidate_id, str) or candidate_id not in ADAPTER_RELEASES:
            continue
        fallbacks.append(
            {
                "candidate_id": candidate_id,
                "adapter_release": ADAPTER_RELEASES[candidate_id],
                "status": "qualified_fallback",
                "reason": "passed_same_frozen_quality_and_safety_gates",
                "activation_requires": "new_hash_addressed_reselection_manifest",
                "report": _descriptor(
                    report_paths[name], relative_to=selection_path.parent
                ),
            }
        )
    return fallbacks


def _failed_or_dropped_evidence(
    reports: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    failed = [
        name
        for name, report in reports.items()
        if report.get("status") == "failed"
    ]
    unavailable = [
        {
            "name": name,
            "candidate_id": _mapping(report.get("candidate"), "report candidate").get(
                "candidate_id"
            ),
            "reason": _mapping(report.get("candidate"), "report candidate").get(
                "unavailable_reason"
            ),
        }
        for name, report in reports.items()
        if report.get("status") == "unavailable"
    ]
    return {
        "hard_gate_failed_candidates": failed,
        "unavailable_candidates": unavailable,
        "formal_candidate_validation": {
            name: _validation_summary(reports[name])
            for name in ("project-native", "llamaindex")
        },
    }


def _eligible_candidate_passed(report: Mapping[str, Any]) -> bool:
    candidate = _mapping(report.get("candidate"), "report candidate")
    return (
        report.get("status") == "passed"
        and report.get("selection_status") == "eligible_candidate_passed"
        and candidate.get("eligible_for_selection") is True
        and _all_hard_gates_passed(report) is True
    )


def _all_hard_gates_passed(report: Mapping[str, Any]) -> bool | None:
    gates = report.get("gates")
    if not isinstance(gates, Mapping) or not gates:
        return None
    return all(value is True for value in gates.values())


def _candidate_disposition(
    name: str, report: Mapping[str, Any], *, selected_id: object
) -> str:
    candidate_id = _mapping(report.get("candidate"), "report candidate").get(
        "candidate_id"
    )
    if candidate_id == selected_id:
        return "selected"
    if _eligible_candidate_passed(report):
        return "qualified_fallback"
    if report.get("selection_status") == "harness_reference_only":
        return "harness_reference_only"
    if report.get("status") == "unavailable":
        return "unavailable_not_evaluated"
    return "not_selected_failed_gate"


def _validation_summary(report: Mapping[str, Any]) -> dict[str, Any] | None:
    validation = report.get("validation_evidence")
    if not isinstance(validation, Mapping):
        return None
    return {
        "dropped_candidate_count": validation.get("dropped_candidate_count"),
        "failure_stage": validation.get("failure_stage"),
    }


def _usage_int(usage: Mapping[str, Any], key: str) -> int:
    value = usage.get(key)
    if not isinstance(value, int):
        raise SelectionManifestError(f"candidate usage {key} must be an integer")
    return value


def _difference(
    left: Mapping[str, Any], right: Mapping[str, Any], key: str
) -> int:
    return _usage_int(left, key) - _usage_int(right, key)


def _decimal_difference(left: object, right: object) -> float:
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        raise SelectionManifestError("candidate comparison values must be numeric")
    return float(Decimal(str(left)) - Decimal(str(right)))


def _reduction_percent(selected_value: object, fallback_value: object) -> float:
    if not isinstance(selected_value, (int, float)) or not isinstance(
        fallback_value, (int, float)
    ):
        raise SelectionManifestError("candidate resource values must be numeric")
    denominator = Decimal(str(fallback_value))
    if denominator == 0:
        raise SelectionManifestError("candidate resource comparison denominator is zero")
    value = (
        (denominator - Decimal(str(selected_value))) / denominator * Decimal("100")
    )
    return float(value.quantize(Decimal("0.0001")))


def write_selection_manifest(manifest: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_report(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SelectionManifestError(f"unable to read candidate report: {path.name}") from exc
    return dict(_mapping(value, "candidate report"))


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SelectionManifestError(f"{label} must be a JSON object")
    return value


def _candidate_measurement_complete(report: Mapping[str, Any]) -> bool:
    candidate = _mapping(report.get("candidate"), "report candidate")
    if candidate.get("available") is not True:
        return True
    evidence = report.get("usage_evidence")
    return isinstance(evidence, Mapping) and evidence.get("measurement_complete") is True


def _descriptor(path: Path, *, relative_to: Path) -> dict[str, str]:
    if not path.is_file():
        raise SelectionManifestError(f"selection artifact does not exist: {path.name}")
    return {
        "path": os.path.relpath(path.resolve(), relative_to.resolve()),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
