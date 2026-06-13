from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_au_handoff_dossier import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    DOSSIER_VERSION,
    compute_handoff_dossier_hash,
    render_au_handoff_markdown,
)


REQUIRED_FIELDS = (
    "handoff_dossier_version",
    "generated_at",
    "status",
    "handoff_dossier_ready",
    "ready_for_customer_report_handoff",
    "output_path",
    "markdown_output_path",
    "summary",
    "runtime_endpoints",
    "launch_status",
    "launch_status_source",
    "launch_status_verifier",
    "remediation_plan",
    "remediation_plan_source",
    "remediation_plan_verifier",
    "p0a_environment_checklist",
    "p0a_environment_checklist_source",
    "p0a_execution_checklist",
    "p0a_execution_checklist_source",
    "p0b_google_execution_checklist",
    "p0b_google_execution_checklist_source",
    "stage_summaries",
    "work_items",
    "next_work_item",
    "blocker_remediations",
    "evidence_sources",
    "markdown_report",
    "handoff_dossier_hash",
)


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _blocker_stage_counts(blockers: list[object]) -> dict[str, int]:
    counts = {"p0a": 0, "p0b_google": 0, "p0c": 0, "other": 0}
    for blocker in blockers:
        value = str(blocker)
        if value.startswith("p0a:"):
            counts["p0a"] += 1
        elif value.startswith("p0b_google:"):
            counts["p0b_google"] += 1
        elif value.startswith("p0c:"):
            counts["p0c"] += 1
        else:
            counts["other"] += 1
    return counts


def verify_au_handoff_dossier(
    dossier: Any,
    *,
    path: Path | None = None,
    require_customer_ready: bool = False,
) -> dict[str, Any]:
    if not isinstance(dossier, dict):
        return {
            "status": "fail",
            "errors": ["handoff_dossier_not_json_object"],
            "hash_valid": False,
            "handoff_dossier_ready": False,
            "ready_for_customer_report_handoff": False,
        }

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in dossier:
            errors.append(f"field_missing:{field}")
    if dossier.get("handoff_dossier_version") != DOSSIER_VERSION:
        errors.append("handoff_dossier_version_invalid")

    expected_hash = dossier.get("handoff_dossier_hash")
    computed_hash = compute_handoff_dossier_hash(dossier)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("handoff_dossier_hash_mismatch")

    launch = _as_dict(dossier.get("launch_status"))
    launch_verifier = _as_dict(dossier.get("launch_status_verifier"))
    remediation = _as_dict(dossier.get("remediation_plan"))
    remediation_verifier = _as_dict(dossier.get("remediation_plan_verifier"))
    p0a_environment_checklist = _as_dict(dossier.get("p0a_environment_checklist"))
    p0a_execution_checklist = _as_dict(dossier.get("p0a_execution_checklist"))
    p0b_google_execution_checklist = _as_dict(dossier.get("p0b_google_execution_checklist"))
    summary = _as_dict(dossier.get("summary"))
    endpoints = _as_dict(dossier.get("runtime_endpoints"))
    markdown_report = _as_dict(dossier.get("markdown_report"))
    blockers = _as_list(launch.get("remaining_blockers"))
    work_items = [_as_dict(item) for item in _as_list(dossier.get("work_items"))]
    next_work_item = _as_dict(dossier.get("next_work_item"))

    if launch_verifier.get("status") != "pass":
        errors.append("launch_status_verifier_not_pass")
    if launch_verifier.get("hash_valid") is not True:
        errors.append("launch_status_hash_not_valid")
    if remediation_verifier.get("status") != "pass":
        errors.append("remediation_plan_verifier_not_pass")
    if remediation_verifier.get("hash_valid") is not True:
        errors.append("remediation_plan_hash_not_valid")
    expected_ready = (
        launch_verifier.get("status") == "pass"
        and launch_verifier.get("hash_valid") is True
        and remediation_verifier.get("status") == "pass"
        and remediation_verifier.get("hash_valid") is True
        and summary.get("unmapped_blocker_count") == 0
    )
    if dossier.get("handoff_dossier_ready") is not expected_ready:
        errors.append("handoff_dossier_ready_mismatch")
    if dossier.get("status") != ("pass" if expected_ready else "fail"):
        errors.append("status_mismatch")

    customer_ready = launch.get("ready_for_customer_report_handoff") is True
    if dossier.get("ready_for_customer_report_handoff") is not customer_ready:
        errors.append("ready_for_customer_report_handoff_mismatch")
    if summary.get("ready_for_customer_report_handoff") is not customer_ready:
        errors.append("summary_ready_for_customer_report_handoff_mismatch")
    if require_customer_ready and not customer_ready:
        errors.append("customer_handoff_not_ready")

    if summary.get("remaining_blocker_count") != len(blockers):
        errors.append("summary_remaining_blocker_count_mismatch")
    if summary.get("blocker_stage_counts") != _blocker_stage_counts(blockers):
        errors.append("summary_blocker_stage_counts_mismatch")
    if summary.get("work_item_count") != len(work_items):
        errors.append("summary_work_item_count_mismatch")
    expected_covered_blocker_count = int(remediation_verifier.get("blocker_count") or 0) - int(
        remediation_verifier.get("unmapped_blocker_count") or 0
    )
    if summary.get("covered_blocker_count") != expected_covered_blocker_count:
        errors.append("summary_covered_blocker_count_mismatch")
    if summary.get("unmapped_blocker_count") != remediation_verifier.get("unmapped_blocker_count"):
        errors.append("summary_unmapped_blocker_count_mismatch")
    if summary.get("external_dependency_blocker_count") != remediation_verifier.get("external_dependency_blocker_count"):
        errors.append("summary_external_dependency_blocker_count_mismatch")
    if (
        summary.get("p0a_environment_checklist_ready")
        is not p0a_environment_checklist.get("environment_checklist_ready")
    ):
        errors.append("summary_p0a_environment_checklist_ready_mismatch")
    if summary.get("p0a_missing_required_environment_count") != p0a_environment_checklist.get(
        "missing_required_count"
    ):
        errors.append("summary_p0a_missing_required_environment_count_mismatch")
    if summary.get("p0a_env_file_hygiene_ready") is not p0a_environment_checklist.get("env_file_hygiene_ready"):
        errors.append("summary_p0a_env_file_hygiene_ready_mismatch")
    if summary.get("p0a_env_file_hygiene_error_count") != p0a_environment_checklist.get(
        "env_file_hygiene_error_count"
    ):
        errors.append("summary_p0a_env_file_hygiene_error_count_mismatch")
    if summary.get("p0a_env_file_hygiene_warning_count") != p0a_environment_checklist.get(
        "env_file_hygiene_warning_count"
    ):
        errors.append("summary_p0a_env_file_hygiene_warning_count_mismatch")
    if summary.get("p0a_execution_checklist_ready") is not p0a_execution_checklist.get(
        "p0a_execution_checklist_ready"
    ):
        errors.append("summary_p0a_execution_checklist_ready_mismatch")
    if summary.get("p0a_execution_remaining_blocker_count") != p0a_execution_checklist.get(
        "remaining_blocker_count"
    ):
        errors.append("summary_p0a_execution_remaining_blocker_count_mismatch")
    if summary.get("p0b_google_execution_checklist_ready") is not p0b_google_execution_checklist.get(
        "google_execution_checklist_ready"
    ):
        errors.append("summary_p0b_google_execution_checklist_ready_mismatch")
    if summary.get("p0b_google_remaining_blocker_count") != p0b_google_execution_checklist.get(
        "remaining_blocker_count"
    ):
        errors.append("summary_p0b_google_remaining_blocker_count_mismatch")
    if summary.get("p0b_google_env_file_hygiene_ready") is not p0b_google_execution_checklist.get(
        "env_file_hygiene_ready"
    ):
        errors.append("summary_p0b_google_env_file_hygiene_ready_mismatch")
    if summary.get("p0b_google_env_file_hygiene_error_count") != p0b_google_execution_checklist.get(
        "env_file_hygiene_error_count"
    ):
        errors.append("summary_p0b_google_env_file_hygiene_error_count_mismatch")
    if summary.get("p0b_google_env_file_hygiene_warning_count") != p0b_google_execution_checklist.get(
        "env_file_hygiene_warning_count"
    ):
        errors.append("summary_p0b_google_env_file_hygiene_warning_count_mismatch")
    if endpoints.get("au_retest_scheduler_plan") != "GET /v1/au-retest-scheduler-plan":
        errors.append("runtime_endpoint_au_retest_scheduler_plan_invalid")
    if endpoints.get("au_retest_execution_status") != "GET /v1/au-retest-execution-status":
        errors.append("runtime_endpoint_au_retest_execution_status_invalid")
    if endpoints.get("p0a_execution_checklist") != "GET /v1/p0a-execution-checklist/au":
        errors.append("runtime_endpoint_p0a_execution_checklist_invalid")
    if endpoints.get("project_lifecycle_events") != "GET /v1/projects/runtime/lifecycle-events?project_id={project_id}":
        errors.append("runtime_endpoint_project_lifecycle_events_invalid")
    if (
        endpoints.get("project_lifecycle_events_export")
        != "GET /v1/projects/runtime/lifecycle-events/export.csv?project_id={project_id}"
    ):
        errors.append("runtime_endpoint_project_lifecycle_events_export_invalid")
    if endpoints.get("runtime_audit_events") != "GET /v1/audit-events/runtime?project_id={project_id}":
        errors.append("runtime_endpoint_runtime_audit_events_invalid")
    if endpoints.get("runtime_audit_events_export") != "GET /v1/audit-events/runtime/export.csv?project_id={project_id}":
        errors.append("runtime_endpoint_runtime_audit_events_export_invalid")

    next_work_item_id = str(summary.get("next_work_item_id") or "")
    if next_work_item_id != remediation.get("next_work_item_id"):
        errors.append("summary_next_work_item_id_mismatch")
    if next_work_item_id != "none" and next_work_item.get("id") != next_work_item_id:
        errors.append("next_work_item_mismatch")
    if next_work_item_id == "none" and next_work_item.get("id") not in {"none", ""}:
        errors.append("next_work_item_none_mismatch")

    markdown = render_au_handoff_markdown(dossier)
    if markdown_report.get("content_sha256") != hashlib.sha256(markdown.encode("utf-8")).hexdigest():
        errors.append("markdown_content_sha256_mismatch")
    if markdown_report.get("size_bytes") != len(markdown.encode("utf-8")):
        errors.append("markdown_size_bytes_mismatch")

    for source in _as_list(dossier.get("evidence_sources")):
        item = _as_dict(source)
        if not item.get("name"):
            errors.append("evidence_source_name_missing")
        if "path" not in item:
            errors.append(f"evidence_source_path_missing:{item.get('name', '')}")
        if "exists" not in item:
            errors.append(f"evidence_source_exists_missing:{item.get('name', '')}")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "handoff_dossier_version": dossier.get("handoff_dossier_version", ""),
        "handoff_dossier_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_handoff_dossier_hash": computed_hash,
        "hash_valid": hash_valid,
        "handoff_dossier_ready": expected_ready,
        "ready_for_customer_report_handoff": customer_ready,
        "handoff_posture": summary.get("handoff_posture", ""),
        "remaining_blocker_count": len(blockers),
        "work_item_count": len(work_items),
        "next_work_item_id": next_work_item_id,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU customer handoff dossier JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_HANDOFF_DOSSIER_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU handoff dossier JSON.",
    )
    parser.add_argument(
        "--require-customer-ready",
        action="store_true",
        help="Fail unless the dossier proves customer report handoff is ready.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = Path(args.path)
    try:
        dossier = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": ["handoff_dossier_file_missing"],
            "hash_valid": False,
            "handoff_dossier_ready": False,
            "ready_for_customer_report_handoff": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"handoff_dossier_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "handoff_dossier_ready": False,
            "ready_for_customer_report_handoff": False,
        }
    else:
        result = verify_au_handoff_dossier(dossier, path=path, require_customer_ready=args.require_customer_ready)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
