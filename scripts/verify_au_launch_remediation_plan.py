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

from scripts.build_au_launch_remediation_plan import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    PLAN_VERSION,
    compute_remediation_plan_hash,
)


REQUIRED_FIELDS = (
    "remediation_plan_version",
    "generated_at",
    "status",
    "remediation_plan_ready",
    "next_work_item_id",
    "output_path",
    "launch_status",
    "launch_status_source",
    "launch_status_verifier",
    "summary",
    "work_items",
    "blocker_remediations",
    "remediation_plan_hash",
)


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def verify_au_launch_remediation_plan(
    plan: Any,
    *,
    path: Path | None = None,
    require_ready: bool = False,
) -> dict[str, Any]:
    if not isinstance(plan, dict):
        return {
            "status": "fail",
            "errors": ["remediation_plan_not_json_object"],
            "hash_valid": False,
            "remediation_plan_ready": False,
        }

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in plan:
            errors.append(f"field_missing:{field}")
    if plan.get("remediation_plan_version") != PLAN_VERSION:
        errors.append("remediation_plan_version_invalid")

    expected_hash = plan.get("remediation_plan_hash")
    computed_hash = compute_remediation_plan_hash(plan)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("remediation_plan_hash_mismatch")

    launch_status = _as_dict(plan.get("launch_status"))
    launch_verifier = _as_dict(plan.get("launch_status_verifier"))
    summary = _as_dict(plan.get("summary"))
    work_items = [_as_dict(item) for item in _as_list(plan.get("work_items"))]
    remediations = [_as_dict(item) for item in _as_list(plan.get("blocker_remediations"))]
    blockers = sorted(str(item) for item in _as_list(launch_status.get("remaining_blockers")))

    if launch_verifier.get("status") != "pass":
        errors.append("launch_status_verifier_not_pass")
    if launch_verifier.get("hash_valid") is not True:
        errors.append("launch_status_hash_not_valid")

    remediation_blockers = sorted(str(item.get("blocker", "")) for item in remediations)
    if remediation_blockers != blockers:
        errors.append("blocker_remediation_coverage_mismatch")
    if len(remediation_blockers) != len(set(remediation_blockers)):
        errors.append("duplicate_blocker_remediation")

    work_item_ids = [str(item.get("id", "")) for item in work_items]
    if len(work_item_ids) != len(set(work_item_ids)):
        errors.append("duplicate_work_item_id")
    commands_by_work_item = {
        str(item.get("id", "")): [str(command.get("shell", "")) for command in _as_list(item.get("commands"))]
        for item in work_items
    }
    for work_item in work_items:
        work_item_id = str(work_item.get("id", ""))
        if not work_item_id:
            errors.append("work_item_id_missing")
            continue
        for field in (
            "stage",
            "title",
            "status",
            "external_dependency",
            "dependency_class",
            "commands",
            "verification_commands",
            "evidence_outputs",
            "clears_blockers",
            "blocker_count",
            "acceptance",
        ):
            if field not in work_item:
                errors.append(f"work_item_field_missing:{work_item_id}:{field}")
        if not _as_list(work_item.get("commands")):
            errors.append(f"work_item_commands_missing:{work_item_id}")
        if not _as_list(work_item.get("verification_commands")):
            errors.append(f"work_item_verification_commands_missing:{work_item_id}")
        if int(work_item.get("blocker_count") or 0) != len(_as_list(work_item.get("clears_blockers"))):
            errors.append(f"work_item_blocker_count_mismatch:{work_item_id}")

    p0a_environment_commands = commands_by_work_item.get("p0a_environment", [])
    if p0a_environment_commands and "make au-p0a-env-bootstrap" not in p0a_environment_commands:
        errors.append("work_item_command_missing:p0a_environment:env_bootstrap")
    if p0a_environment_commands and "make verify-au-p0a-env-bootstrap" not in p0a_environment_commands:
        errors.append("work_item_command_missing:p0a_environment:verify_env_bootstrap")
    p0b_google_environment_commands = commands_by_work_item.get("p0b_google_playwright_env", [])
    if p0b_google_environment_commands and "make au-p0b-google-env-bootstrap" not in p0b_google_environment_commands:
        errors.append("work_item_command_missing:p0b_google_playwright_env:env_bootstrap")
    if p0b_google_environment_commands and "make verify-au-p0b-google-env-bootstrap" not in p0b_google_environment_commands:
        errors.append("work_item_command_missing:p0b_google_playwright_env:verify_env_bootstrap")

    for remediation in remediations:
        blocker = str(remediation.get("blocker", ""))
        work_item_id = str(remediation.get("work_item_id", ""))
        if remediation.get("mapped") is not True:
            errors.append(f"blocker_unmapped:{blocker}")
        if work_item_id not in work_item_ids:
            errors.append(f"remediation_work_item_missing:{blocker}:{work_item_id}")
        if not remediation.get("next_command"):
            errors.append(f"remediation_next_command_missing:{blocker}")
        if not _as_list(remediation.get("verification_commands")):
            errors.append(f"remediation_verification_commands_missing:{blocker}")

    unmapped = sorted(str(item) for item in _as_list(summary.get("unmapped_blockers")))
    expected_unmapped = sorted(str(item.get("blocker", "")) for item in remediations if item.get("mapped") is not True)
    if unmapped != expected_unmapped:
        errors.append("summary_unmapped_blockers_mismatch")
    covered = len(blockers) - len(unmapped)
    if summary.get("blocker_count") != len(blockers):
        errors.append("summary_blocker_count_mismatch")
    if summary.get("covered_blocker_count") != covered:
        errors.append("summary_covered_blocker_count_mismatch")
    if summary.get("unmapped_blocker_count") != len(unmapped):
        errors.append("summary_unmapped_blocker_count_mismatch")
    if summary.get("work_item_count") != len(work_items):
        errors.append("summary_work_item_count_mismatch")
    external_blocker_count = sum(1 for item in remediations if item.get("external_dependency") is True)
    if summary.get("external_dependency_blocker_count") != external_blocker_count:
        errors.append("summary_external_dependency_blocker_count_mismatch")
    runnable_now = sorted(str(item.get("id")) for item in work_items if item.get("status") == "runnable_now")
    if sorted(str(item) for item in _as_list(summary.get("runnable_now_work_items"))) != runnable_now:
        errors.append("summary_runnable_now_work_items_mismatch")
    if summary.get("runnable_now_work_item_count") != len(runnable_now):
        errors.append("summary_runnable_now_work_item_count_mismatch")

    expected_ready = not unmapped and launch_verifier.get("status") == "pass" and launch_verifier.get("hash_valid") is True
    if plan.get("remediation_plan_ready") is not expected_ready:
        errors.append("remediation_plan_ready_mismatch")
    expected_status = "pass" if expected_ready else "fail"
    if plan.get("status") != expected_status:
        errors.append("status_mismatch")
    expected_next = str(work_items[0].get("id")) if work_items else "none"
    if plan.get("next_work_item_id") != expected_next:
        errors.append("next_work_item_id_mismatch")
    if require_ready and not expected_ready:
        errors.append("remediation_plan_not_ready")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "remediation_plan_version": plan.get("remediation_plan_version", ""),
        "remediation_plan_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_remediation_plan_hash": computed_hash,
        "hash_valid": hash_valid,
        "remediation_plan_ready": expected_ready,
        "next_work_item_id": expected_next,
        "blocker_count": len(blockers),
        "work_item_count": len(work_items),
        "unmapped_blocker_count": len(unmapped),
        "external_dependency_blocker_count": external_blocker_count,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU launch remediation plan JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GEO_AU_LAUNCH_REMEDIATION_PLAN_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU launch remediation plan JSON.",
    )
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Fail unless every launch blocker is mapped to a remediation work item.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = Path(args.path)
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": ["remediation_plan_file_missing"],
            "hash_valid": False,
            "remediation_plan_ready": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"remediation_plan_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "remediation_plan_ready": False,
        }
    else:
        result = verify_au_launch_remediation_plan(plan, path=path, require_ready=args.require_ready)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
