from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_au_external_dependency_handoff import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    HANDOFF_VERSION,
    compute_external_dependency_handoff_hash,
)


REQUIRED_FIELDS = (
    "external_dependency_handoff_version",
    "generated_at",
    "status",
    "external_dependency_handoff_ready",
    "ready_for_customer_report_handoff",
    "output_path",
    "next_dependency_item_id",
    "summary",
    "source_paths",
    "source_loaders",
    "source_verifiers",
    "source_artifacts",
    "dependency_groups",
    "work_items",
    "local_followup_items",
    "operator_sequence",
    "next_dependency_item",
    "blocker_remediations",
    "redaction_policy",
    "current_boundary",
    "external_dependency_handoff_hash",
)

EXPECTED_GROUP_IDS = (
    "p0a_provider_credentials",
    "p0a_real_batches",
    "p0b_google_environment",
    "p0b_google_manual_backfill",
    "p0b_google_phase_execution",
)
FORBIDDEN_EXACT_FIELDS = {
    "value",
    "raw_value",
    "database_url",
    "selector_value",
    "answer_text",
    "citation_urls",
    "screenshot_url",
    "html_snapshot_url",
}


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _strings(value: object) -> list[str]:
    return [str(item) for item in _as_list(value)]


def _find_forbidden_fields(value: object, *, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in FORBIDDEN_EXACT_FIELDS:
                findings.append(child_path)
            findings.extend(_find_forbidden_fields(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_find_forbidden_fields(child, path=f"{path}[{index}]"))
    return findings


def _group_by_id(handoff: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(_as_dict(group).get("id") or ""): _as_dict(group) for group in _as_list(handoff.get("dependency_groups"))}


def _work_item_ids(handoff: dict[str, Any]) -> list[str]:
    return [str(_as_dict(item).get("id") or "") for item in _as_list(handoff.get("work_items"))]


def _validate_work_items(handoff: dict[str, Any], errors: list[str]) -> None:
    work_items = [_as_dict(item) for item in _as_list(handoff.get("work_items"))]
    ids = [str(item.get("id") or "") for item in work_items]
    if len(ids) != len(set(ids)):
        errors.append("duplicate_work_item_id")
    for item in work_items:
        item_id = str(item.get("id") or "")
        if not item_id:
            errors.append("work_item_id_missing")
        for field in (
            "stage",
            "title",
            "status",
            "external_dependency",
            "dependency_class",
            "required_inputs",
            "blocker_count",
            "clears_blockers",
            "commands",
            "verification_commands",
            "evidence_outputs",
            "acceptance",
        ):
            if field not in item:
                errors.append(f"work_item_field_missing:{item_id}:{field}")
        if item.get("external_dependency") is not True:
            errors.append(f"work_item_not_external_dependency:{item_id}")
        if not _as_list(item.get("commands")):
            errors.append(f"work_item_commands_missing:{item_id}")
        if not _as_list(item.get("verification_commands")):
            errors.append(f"work_item_verification_commands_missing:{item_id}")
        if int(item.get("blocker_count") or 0) != len(_as_list(item.get("clears_blockers"))):
            errors.append(f"work_item_blocker_count_mismatch:{item_id}")


def _validate_group_common(group: dict[str, Any], *, errors: list[str]) -> None:
    group_id = str(group.get("id") or "")
    for field in ("stage", "title", "status", "external_dependency", "dependency_class", "ready", "work_item_ids"):
        if field not in group:
            errors.append(f"dependency_group_field_missing:{group_id}:{field}")
    if group.get("external_dependency") is not True:
        errors.append(f"dependency_group_not_external:{group_id}")
    if not isinstance(group.get("ready"), bool):
        errors.append(f"dependency_group_ready_invalid:{group_id}")


def _validate_groups(handoff: dict[str, Any], errors: list[str]) -> None:
    groups = _group_by_id(handoff)
    observed_ids = tuple(group_id for group_id in groups if group_id)
    if observed_ids != EXPECTED_GROUP_IDS:
        errors.append("dependency_group_order_mismatch")
    work_item_ids = set(_work_item_ids(handoff))
    for group_id in EXPECTED_GROUP_IDS:
        group = groups.get(group_id, {})
        if not group:
            errors.append(f"dependency_group_missing:{group_id}")
            continue
        _validate_group_common(group, errors=errors)
        for work_item_id in _strings(group.get("work_item_ids")):
            if work_item_id not in work_item_ids:
                errors.append(f"dependency_group_work_item_missing:{group_id}:{work_item_id}")

    p0a_credentials = groups.get("p0a_provider_credentials", {})
    p0a_missing = _strings(p0a_credentials.get("missing_required"))
    if p0a_credentials.get("missing_required_count") != len(p0a_missing):
        errors.append("p0a_provider_credentials_missing_required_count_mismatch")
    if p0a_credentials.get("target_env_file") != ".env.au-p0a":
        errors.append("p0a_provider_credentials_target_env_file_invalid")
    credential_names = {str(_as_dict(item).get("name") or "") for item in _as_list(p0a_credentials.get("credential_items"))}
    for required in {"DATABASE_URL", "OPENAI_API_KEY", "PERPLEXITY_API_KEY"}:
        if required not in credential_names:
            errors.append(f"p0a_provider_credentials_required_item_missing:{required}")
    p0a_redaction = _as_dict(p0a_credentials.get("redaction_policy"))
    if p0a_redaction.get("raw_secret_values_allowed") is not False:
        errors.append("p0a_provider_credentials_raw_secret_policy_invalid")
    if p0a_redaction.get("credential_items_redacted") is not True:
        errors.append("p0a_provider_credentials_item_redaction_invalid")

    p0a_batches = groups.get("p0a_real_batches", {})
    if tuple(_strings(p0a_batches.get("phase_order"))) != ("preflight", "small_batch", "full_batch"):
        errors.append("p0a_real_batches_phase_order_invalid")
    if p0a_batches.get("phase_count") != len(_as_list(p0a_batches.get("phases"))):
        errors.append("p0a_real_batches_phase_count_mismatch")
    ready_phase_count = sum(1 for phase in _as_list(p0a_batches.get("phases")) if _as_dict(phase).get("ready") is True)
    if p0a_batches.get("ready_phase_count") != ready_phase_count:
        errors.append("p0a_real_batches_ready_phase_count_mismatch")
    if p0a_batches.get("blocked_phase_count") != int(p0a_batches.get("phase_count") or 0) - ready_phase_count:
        errors.append("p0a_real_batches_blocked_phase_count_mismatch")
    if int(p0a_batches.get("total_planned_runs") or 0) <= 0:
        errors.append("p0a_real_batches_total_planned_runs_invalid")

    p0b_environment = groups.get("p0b_google_environment", {})
    p0b_missing = _strings(p0b_environment.get("missing_required"))
    if p0b_environment.get("missing_required_count") != len(p0b_missing):
        errors.append("p0b_google_environment_missing_required_count_mismatch")
    if not p0b_environment.get("target_env_file"):
        errors.append("p0b_google_environment_target_env_file_missing")
    p0b_env_redaction = _as_dict(p0b_environment.get("redaction_policy"))
    if p0b_env_redaction.get("raw_secret_values_allowed") is not False:
        errors.append("p0b_google_environment_raw_secret_policy_invalid")

    p0b_manual = groups.get("p0b_google_manual_backfill", {})
    missing_reasons = _strings(p0b_manual.get("missing_reasons"))
    if p0b_manual.get("missing_reason_count") != len(missing_reasons):
        errors.append("p0b_google_manual_backfill_missing_reason_count_mismatch")
    if p0b_manual.get("expected_record_count") != 120:
        errors.append("p0b_google_manual_backfill_expected_record_count_invalid")
    if p0b_manual.get("expected_prompt_city_count") != 60:
        errors.append("p0b_google_manual_backfill_expected_prompt_city_count_invalid")
    if p0b_manual.get("expected_sample_size") != 2:
        errors.append("p0b_google_manual_backfill_expected_sample_size_invalid")
    manual_redaction = _as_dict(p0b_manual.get("redaction_policy"))
    if manual_redaction.get("raw_answer_values_allowed") is not False:
        errors.append("p0b_google_manual_backfill_raw_answer_policy_invalid")
    if manual_redaction.get("raw_citation_values_allowed") is not False:
        errors.append("p0b_google_manual_backfill_raw_citation_policy_invalid")
    if manual_redaction.get("raw_asset_urls_allowed") is not False:
        errors.append("p0b_google_manual_backfill_raw_asset_policy_invalid")

    p0b_phase = groups.get("p0b_google_phase_execution", {})
    expected_phase_order = ("environment", "browser_smoke", "manual_backfill", "health_check", "full_spike", "main_scoring")
    if tuple(_strings(p0b_phase.get("phase_order"))) != expected_phase_order:
        errors.append("p0b_google_phase_execution_phase_order_invalid")
    if p0b_phase.get("phase_count") != len(_as_list(p0b_phase.get("phases"))):
        errors.append("p0b_google_phase_execution_phase_count_mismatch")
    p0b_ready_count = sum(1 for phase in _as_list(p0b_phase.get("phases")) if _as_dict(phase).get("ready") is True)
    if p0b_phase.get("ready_phase_count") != p0b_ready_count:
        errors.append("p0b_google_phase_execution_ready_phase_count_mismatch")
    if p0b_phase.get("blocked_phase_count") != int(p0b_phase.get("phase_count") or 0) - p0b_ready_count:
        errors.append("p0b_google_phase_execution_blocked_phase_count_mismatch")
    if int(p0b_phase.get("full_spike_planned_runs") or 0) <= 0:
        errors.append("p0b_google_phase_execution_full_spike_planned_runs_invalid")
    if p0b_phase.get("manual_expected_record_count") != p0b_manual.get("expected_record_count"):
        errors.append("p0b_google_phase_manual_expected_record_count_mismatch")


def verify_au_external_dependency_handoff(
    handoff: Any,
    *,
    path: Path | None = None,
    require_ready: bool = False,
) -> dict[str, Any]:
    if not isinstance(handoff, dict):
        return {
            "status": "fail",
            "errors": ["external_dependency_handoff_not_json_object"],
            "hash_valid": False,
            "external_dependency_handoff_ready": False,
        }

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in handoff:
            errors.append(f"field_missing:{field}")
    if handoff.get("external_dependency_handoff_version") != HANDOFF_VERSION:
        errors.append("external_dependency_handoff_version_invalid")
    for forbidden_path in _find_forbidden_fields(handoff):
        errors.append(f"forbidden_raw_field:{forbidden_path}")

    expected_hash = handoff.get("external_dependency_handoff_hash")
    computed_hash = compute_external_dependency_handoff_hash(handoff)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("external_dependency_handoff_hash_mismatch")

    summary = _as_dict(handoff.get("summary"))
    work_items = [_as_dict(item) for item in _as_list(handoff.get("work_items"))]
    groups = _group_by_id(handoff)
    blockers = [_as_dict(item) for item in _as_list(handoff.get("blocker_remediations"))]
    source_verifiers = _as_dict(handoff.get("source_verifiers"))
    redaction_policy = _as_dict(handoff.get("redaction_policy"))
    next_dependency_item = _as_dict(handoff.get("next_dependency_item"))

    for name, verifier in source_verifiers.items():
        verifier_payload = _as_dict(verifier)
        if verifier_payload.get("status") != "pass":
            errors.append(f"source_verifier_not_pass:{name}")
        if verifier_payload.get("hash_valid") is not True:
            errors.append(f"source_verifier_hash_not_valid:{name}")

    expected_structural_ready = all(
        _as_dict(verifier).get("status") == "pass" and _as_dict(verifier).get("hash_valid") is True
        for verifier in source_verifiers.values()
    ) and int(summary.get("unmapped_blocker_count") or 0) == 0
    if summary.get("structural_ready") is not expected_structural_ready:
        errors.append("summary_structural_ready_mismatch")

    _validate_work_items(handoff, errors)
    _validate_groups(handoff, errors)

    external_blocker_count = sum(1 for item in blockers if item.get("external_dependency") is True)
    external_work_items = [item for item in work_items if item.get("external_dependency") is True]
    local_followup_items = [_as_dict(item) for item in _as_list(handoff.get("local_followup_items"))]
    runnable_now = sorted(str(item.get("id") or "") for item in work_items if item.get("status") == "runnable_now")
    requires_external_input = sum(1 for item in work_items if item.get("status") == "requires_external_input")
    pending_after = sum(1 for item in work_items if str(item.get("status") or "").startswith("pending_after"))

    if summary.get("blocker_count") != len(blockers):
        errors.append("summary_blocker_count_mismatch")
    if summary.get("external_dependency_blocker_count") != external_blocker_count:
        errors.append("summary_external_dependency_blocker_count_mismatch")
    if summary.get("work_item_count") != len(external_work_items):
        errors.append("summary_work_item_count_mismatch")
    if summary.get("local_followup_work_item_count") != len(local_followup_items):
        errors.append("summary_local_followup_work_item_count_mismatch")
    if summary.get("dependency_group_count") != len(_as_list(handoff.get("dependency_groups"))):
        errors.append("summary_dependency_group_count_mismatch")
    if summary.get("requires_external_input_work_item_count") != requires_external_input:
        errors.append("summary_requires_external_input_work_item_count_mismatch")
    if summary.get("pending_after_external_input_work_item_count") != pending_after:
        errors.append("summary_pending_after_external_input_work_item_count_mismatch")
    if summary.get("runnable_now_work_item_count") != len(runnable_now):
        errors.append("summary_runnable_now_work_item_count_mismatch")
    if sorted(_strings(summary.get("runnable_now_work_items"))) != runnable_now:
        errors.append("summary_runnable_now_work_items_mismatch")

    expected_next = next_dependency_item.get("id") or "none"
    if handoff.get("next_dependency_item_id") != expected_next:
        errors.append("next_dependency_item_id_mismatch")
    if summary.get("next_dependency_item_id") != expected_next:
        errors.append("summary_next_dependency_item_id_mismatch")
    if expected_next != "none" and expected_next not in _work_item_ids(handoff):
        errors.append("next_dependency_item_not_in_work_items")
    if list(handoff.get("operator_sequence") or []) != _work_item_ids(handoff):
        errors.append("operator_sequence_mismatch")

    p0a_credentials = groups.get("p0a_provider_credentials", {})
    p0a_batches = groups.get("p0a_real_batches", {})
    p0b_environment = groups.get("p0b_google_environment", {})
    p0b_manual = groups.get("p0b_google_manual_backfill", {})
    p0b_phase = groups.get("p0b_google_phase_execution", {})
    expected_p0b_missing = int(p0b_environment.get("missing_required_count") or 0) + int(
        p0b_manual.get("missing_reason_count") or 0
    )
    if summary.get("p0a_required_secret_missing_count") != p0a_credentials.get("missing_required_count"):
        errors.append("summary_p0a_required_secret_missing_count_mismatch")
    if sorted(_strings(summary.get("p0a_required_secret_missing"))) != sorted(
        _strings(p0a_credentials.get("missing_required"))
    ):
        errors.append("summary_p0a_required_secret_missing_mismatch")
    if summary.get("p0a_real_batch_phase_next_phase") != p0a_batches.get("next_phase"):
        errors.append("summary_p0a_real_batch_phase_next_phase_mismatch")
    if summary.get("p0a_real_batch_blocked_phase_count") != p0a_batches.get("blocked_phase_count"):
        errors.append("summary_p0a_real_batch_blocked_phase_count_mismatch")
    if summary.get("p0a_real_batch_total_planned_runs") != p0a_batches.get("total_planned_runs"):
        errors.append("summary_p0a_real_batch_total_planned_runs_mismatch")
    if summary.get("p0b_google_required_input_missing_count") != expected_p0b_missing:
        errors.append("summary_p0b_google_required_input_missing_count_mismatch")
    if summary.get("p0b_google_environment_missing_required_count") != p0b_environment.get("missing_required_count"):
        errors.append("summary_p0b_google_environment_missing_required_count_mismatch")
    if summary.get("p0b_google_manual_backfill_missing_reason_count") != p0b_manual.get("missing_reason_count"):
        errors.append("summary_p0b_google_manual_backfill_missing_reason_count_mismatch")
    if summary.get("p0b_google_manual_backfill_record_count") != p0b_manual.get("record_count"):
        errors.append("summary_p0b_google_manual_backfill_record_count_mismatch")
    if summary.get("p0b_google_manual_backfill_expected_record_count") != p0b_manual.get("expected_record_count"):
        errors.append("summary_p0b_google_manual_backfill_expected_record_count_mismatch")
    if summary.get("p0b_google_phase_next_phase") != p0b_phase.get("next_phase"):
        errors.append("summary_p0b_google_phase_next_phase_mismatch")
    if summary.get("p0b_google_phase_blocked_phase_count") != p0b_phase.get("blocked_phase_count"):
        errors.append("summary_p0b_google_phase_blocked_phase_count_mismatch")
    if summary.get("p0b_google_full_spike_planned_runs") != p0b_phase.get("full_spike_planned_runs"):
        errors.append("summary_p0b_google_full_spike_planned_runs_mismatch")

    for field in (
        "raw_secret_values_allowed",
        "raw_database_url_allowed",
        "raw_selector_values_allowed",
        "raw_manual_answer_values_allowed",
        "raw_citation_values_allowed",
        "raw_asset_urls_allowed",
    ):
        if redaction_policy.get(field) is not False:
            errors.append(f"redaction_policy_invalid:{field}")
    if set(_strings(redaction_policy.get("forbidden_exact_fields"))) != FORBIDDEN_EXACT_FIELDS:
        errors.append("redaction_policy_forbidden_exact_fields_mismatch")

    all_groups_ready = all(_as_dict(group).get("ready") is True for group in _as_list(handoff.get("dependency_groups")))
    expected_ready = expected_structural_ready and external_blocker_count == 0 and all_groups_ready
    if handoff.get("external_dependency_handoff_ready") is not expected_ready:
        errors.append("external_dependency_handoff_ready_mismatch")
    if summary.get("external_dependency_handoff_ready") is not expected_ready:
        errors.append("summary_external_dependency_handoff_ready_mismatch")
    expected_posture = (
        "external_dependencies_cleared"
        if expected_ready
        else "blocked_external_dependencies"
        if expected_structural_ready and external_blocker_count > 0
        else "external_dependency_handoff_not_verified"
    )
    if summary.get("handoff_posture") != expected_posture:
        errors.append("summary_handoff_posture_mismatch")
    expected_status = "pass" if expected_structural_ready else "fail"
    if handoff.get("status") != expected_status:
        errors.append("status_mismatch")
    if require_ready and not expected_ready:
        errors.append("external_dependency_handoff_not_ready")

    structural_ready = expected_structural_ready and not errors
    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "external_dependency_handoff_version": handoff.get("external_dependency_handoff_version", ""),
        "external_dependency_handoff_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_external_dependency_handoff_hash": computed_hash,
        "hash_valid": hash_valid,
        "external_dependency_handoff_ready": expected_ready,
        "structural_ready": structural_ready,
        "handoff_posture": summary.get("handoff_posture", ""),
        "external_dependency_blocker_count": external_blocker_count,
        "work_item_count": len(external_work_items),
        "dependency_group_count": len(groups),
        "next_dependency_item_id": expected_next,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU external dependency handoff JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_EXTERNAL_DEPENDENCY_HANDOFF_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU external dependency handoff JSON.",
    )
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Fail unless every external dependency has been cleared.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = Path(args.path)
    try:
        handoff = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": ["external_dependency_handoff_file_missing"],
            "hash_valid": False,
            "external_dependency_handoff_ready": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"external_dependency_handoff_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "external_dependency_handoff_ready": False,
        }
    else:
        result = verify_au_external_dependency_handoff(handoff, path=path, require_ready=args.require_ready)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
