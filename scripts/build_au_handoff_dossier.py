from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_au_launch_remediation_plan import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_REMEDIATION_PLAN_PATH,
    build_au_launch_remediation_plan,
)
from scripts.build_au_launch_status import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_LAUNCH_STATUS_PATH,
    build_au_launch_status,
)
from scripts.build_au_p0a_environment_checklist import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0A_ENVIRONMENT_CHECKLIST_PATH,
    build_au_p0a_environment_checklist,
)
from scripts.build_au_p0a_execution_checklist import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0A_EXECUTION_CHECKLIST_PATH,
    build_au_p0a_execution_checklist,
)
from scripts.build_au_p0b_google_execution_checklist import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0B_GOOGLE_EXECUTION_CHECKLIST_PATH,
    build_au_p0b_google_execution_checklist,
)
from scripts.verify_au_launch_remediation_plan import verify_au_launch_remediation_plan  # noqa: E402
from scripts.verify_au_launch_status import verify_au_launch_status  # noqa: E402


DOSSIER_VERSION = "au_handoff_dossier_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-handoff-dossier-latest.json"
DEFAULT_MARKDOWN_OUTPUT_PATH = "docs/runtime_preflight/au-handoff-dossier-latest.md"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_handoff_dossier_hash(dossier: dict[str, Any]) -> str:
    payload = dict(dossier)
    payload.pop("handoff_dossier_hash", None)
    return hashlib.sha256(_stable_bytes(payload)).hexdigest()


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_text(content: str) -> str:
    return _sha256_bytes(content.encode("utf-8"))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _load_or_build_launch_status(path: Path, *, generated_at: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        report = build_au_launch_status(output_path=path, generated_at=generated_at)
        return report, {"path": str(path), "exists": False, "source": "generated_in_memory", "errors": ["file_missing"]}
    except json.JSONDecodeError as exc:
        report = build_au_launch_status(output_path=path, generated_at=generated_at)
        return report, {
            "path": str(path),
            "exists": True,
            "source": "generated_in_memory",
            "errors": [f"json_invalid:{exc.msg}"],
        }
    if isinstance(payload, dict):
        return payload, {"path": str(path), "exists": True, "source": "existing_file"}
    report = build_au_launch_status(output_path=path, generated_at=generated_at)
    return report, {"path": str(path), "exists": True, "source": "generated_in_memory", "errors": ["not_json_object"]}


def _load_or_build_remediation_plan(
    path: Path,
    *,
    launch_status: dict[str, Any],
    launch_status_path: Path,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        plan = build_au_launch_remediation_plan(
            launch_status=launch_status,
            launch_status_path=launch_status_path,
            output_path=path,
            generated_at=generated_at,
        )
        return plan, {"path": str(path), "exists": False, "source": "generated_in_memory", "errors": ["file_missing"]}
    except json.JSONDecodeError as exc:
        plan = build_au_launch_remediation_plan(
            launch_status=launch_status,
            launch_status_path=launch_status_path,
            output_path=path,
            generated_at=generated_at,
        )
        return plan, {
            "path": str(path),
            "exists": True,
            "source": "generated_in_memory",
            "errors": [f"json_invalid:{exc.msg}"],
        }
    if not isinstance(payload, dict):
        plan = build_au_launch_remediation_plan(
            launch_status=launch_status,
            launch_status_path=launch_status_path,
            output_path=path,
            generated_at=generated_at,
        )
        return plan, {"path": str(path), "exists": True, "source": "generated_in_memory", "errors": ["not_json_object"]}

    embedded = _as_dict(payload.get("launch_status"))
    if embedded.get("launch_status_hash") != launch_status.get("launch_status_hash"):
        plan = build_au_launch_remediation_plan(
            launch_status=launch_status,
            launch_status_path=launch_status_path,
            output_path=path,
            generated_at=generated_at,
        )
        return plan, {
            "path": str(path),
            "exists": True,
            "source": "generated_in_memory_due_to_launch_status_hash_mismatch",
            "errors": ["launch_status_hash_mismatch"],
        }
    return payload, {"path": str(path), "exists": True, "source": "existing_file"}


def _load_or_build_p0a_environment_checklist(
    path: Path,
    *,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        checklist = build_au_p0a_environment_checklist(output_path=path, generated_at=generated_at)
        return checklist, {"path": str(path), "exists": False, "source": "generated_in_memory", "errors": ["file_missing"]}
    except json.JSONDecodeError as exc:
        checklist = build_au_p0a_environment_checklist(output_path=path, generated_at=generated_at)
        return checklist, {
            "path": str(path),
            "exists": True,
            "source": "generated_in_memory",
            "errors": [f"json_invalid:{exc.msg}"],
        }
    if isinstance(payload, dict):
        return payload, {"path": str(path), "exists": True, "source": "existing_file"}
    checklist = build_au_p0a_environment_checklist(output_path=path, generated_at=generated_at)
    return checklist, {"path": str(path), "exists": True, "source": "generated_in_memory", "errors": ["not_json_object"]}


def _load_or_build_p0a_execution_checklist(
    path: Path,
    *,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        checklist = build_au_p0a_execution_checklist(output_path=path, generated_at=generated_at)
        return checklist, {"path": str(path), "exists": False, "source": "generated_in_memory", "errors": ["file_missing"]}
    except json.JSONDecodeError as exc:
        checklist = build_au_p0a_execution_checklist(output_path=path, generated_at=generated_at)
        return checklist, {
            "path": str(path),
            "exists": True,
            "source": "generated_in_memory",
            "errors": [f"json_invalid:{exc.msg}"],
        }
    if isinstance(payload, dict):
        return payload, {"path": str(path), "exists": True, "source": "existing_file"}
    checklist = build_au_p0a_execution_checklist(output_path=path, generated_at=generated_at)
    return checklist, {"path": str(path), "exists": True, "source": "generated_in_memory", "errors": ["not_json_object"]}


def _load_or_build_p0b_google_execution_checklist(
    path: Path,
    *,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        checklist = build_au_p0b_google_execution_checklist(output_path=path, generated_at=generated_at)
        return checklist, {"path": str(path), "exists": False, "source": "generated_in_memory", "errors": ["file_missing"]}
    except json.JSONDecodeError as exc:
        checklist = build_au_p0b_google_execution_checklist(output_path=path, generated_at=generated_at)
        return checklist, {
            "path": str(path),
            "exists": True,
            "source": "generated_in_memory",
            "errors": [f"json_invalid:{exc.msg}"],
        }
    if isinstance(payload, dict):
        return payload, {"path": str(path), "exists": True, "source": "existing_file"}
    checklist = build_au_p0b_google_execution_checklist(output_path=path, generated_at=generated_at)
    return checklist, {"path": str(path), "exists": True, "source": "generated_in_memory", "errors": ["not_json_object"]}


def _p0a_environment_checklist_summary(checklist: dict[str, Any]) -> dict[str, Any]:
    summary = _as_dict(checklist.get("summary"))
    env_file_hygiene = _as_dict(checklist.get("env_file_hygiene"))
    env_file_hygiene_errors = [str(value) for value in _as_list(env_file_hygiene.get("errors"))]
    env_file_hygiene_warnings = [str(value) for value in _as_list(env_file_hygiene.get("warnings"))]
    return {
        "path": str(_as_dict(checklist.get("paths")).get("output", "")),
        "environment_checklist_version": checklist.get("environment_checklist_version", ""),
        "status": checklist.get("status", ""),
        "environment_checklist_ready": checklist.get("environment_checklist_ready") is True,
        "next_action": checklist.get("next_action", ""),
        "environment_checklist_hash": checklist.get("environment_checklist_hash", ""),
        "required_count": summary.get("required_count", 0),
        "required_present_count": summary.get("required_present_count", 0),
        "missing_required_count": summary.get("missing_required_count", 0),
        "missing_required": [str(value) for value in _as_list(summary.get("missing_required"))],
        "recommended_count": summary.get("recommended_count", 0),
        "missing_recommended_count": summary.get("missing_recommended_count", 0),
        "missing_recommended": [str(value) for value in _as_list(summary.get("missing_recommended"))],
        "runbook_verifier_status": summary.get("runbook_verifier_status", ""),
        "environment_verifier_status": summary.get("environment_verifier_status", ""),
        "environment_report_ready": summary.get("environment_report_ready") is True,
        "env_file_hygiene_ready": summary.get("env_file_hygiene_ready") is True,
        "env_file_hygiene_error_count": summary.get("env_file_hygiene_error_count", len(env_file_hygiene_errors)),
        "env_file_hygiene_warning_count": summary.get(
            "env_file_hygiene_warning_count",
            len(env_file_hygiene_warnings),
        ),
        "env_file_hygiene_errors": env_file_hygiene_errors,
        "env_file_hygiene_warnings": env_file_hygiene_warnings,
        "env_file_hygiene_path": str(env_file_hygiene.get("path") or ""),
        "env_file_hygiene_file_mode": str(env_file_hygiene.get("file_mode") or ""),
        "env_file_hygiene_git_safe": env_file_hygiene.get("git_safe") is True,
        "env_file_hygiene_permission_safe": env_file_hygiene.get("permission_safe") is True,
        "env_file_hygiene_required": env_file_hygiene.get("hygiene_required") is True,
    }


def _p0a_execution_checklist_summary(checklist: dict[str, Any]) -> dict[str, Any]:
    summary = _as_dict(checklist.get("summary"))
    credential_handoff = _as_dict(checklist.get("credential_handoff"))
    redaction_policy = _as_dict(credential_handoff.get("redaction_policy"))
    return {
        "path": str(_as_dict(checklist.get("paths")).get("output", "")),
        "execution_checklist_version": checklist.get("execution_checklist_version", ""),
        "status": checklist.get("status", ""),
        "p0a_execution_checklist_ready": checklist.get("p0a_execution_checklist_ready") is True,
        "ready_for_design_partner": checklist.get("ready_for_design_partner") is True,
        "next_action": checklist.get("next_action", ""),
        "p0a_execution_checklist_hash": checklist.get("p0a_execution_checklist_hash", ""),
        "small_batch_planned_runs": summary.get("small_batch_planned_runs"),
        "full_batch_planned_runs": summary.get("full_batch_planned_runs"),
        "step_count": summary.get("step_count", 0),
        "artifact_count": summary.get("artifact_count", 0),
        "missing_artifact_count": summary.get("missing_artifact_count", 0),
        "missing_artifacts": [str(value) for value in _as_list(summary.get("missing_artifacts"))],
        "failed_artifact_count": summary.get("failed_artifact_count", 0),
        "failed_artifacts": [str(value) for value in _as_list(summary.get("failed_artifacts"))],
        "remaining_blocker_count": summary.get("remaining_blocker_count", 0),
        "remaining_blockers": [str(value) for value in _as_list(summary.get("remaining_blockers"))],
        "completion_percent": summary.get("completion_percent", 0.0),
        "design_ready_artifact_percent": summary.get("design_ready_artifact_percent", 0.0),
        "runbook_verifier_status": summary.get("runbook_verifier_status", ""),
        "environment_verifier_status": summary.get("environment_verifier_status", ""),
        "runbook_execution_verifier_status": summary.get("runbook_execution_verifier_status", ""),
        "package_verifier_status": summary.get("package_verifier_status", ""),
        "status_verifier_status": summary.get("status_verifier_status", ""),
        "credential_handoff_ready": credential_handoff.get("ready") is True,
        "credential_handoff_missing_required_count": credential_handoff.get("missing_required_count", 0),
        "credential_handoff_missing_required": [
            str(value) for value in _as_list(credential_handoff.get("missing_required"))
        ],
        "credential_handoff_target_env_file": str(credential_handoff.get("target_env_file") or ""),
        "credential_handoff_setup_command_count": len(_as_list(credential_handoff.get("setup_commands"))),
        "credential_handoff_verification_command_count": len(_as_list(credential_handoff.get("verification_commands"))),
        "credential_handoff_secret_redacted": redaction_policy.get("raw_secret_values_allowed") is False
        and redaction_policy.get("forbidden_exact_secret_fields_redacted") is True,
    }


def _p0b_google_execution_checklist_summary(checklist: dict[str, Any]) -> dict[str, Any]:
    summary = _as_dict(checklist.get("summary"))
    env_file_hygiene = _as_dict(checklist.get("env_file_hygiene"))
    environment_handoff = _as_dict(checklist.get("environment_handoff"))
    redaction_policy = _as_dict(environment_handoff.get("redaction_policy"))
    env_file_hygiene_errors = [str(value) for value in _as_list(env_file_hygiene.get("errors"))]
    env_file_hygiene_warnings = [str(value) for value in _as_list(env_file_hygiene.get("warnings"))]
    return {
        "path": str(_as_dict(checklist.get("paths")).get("output", "")),
        "execution_checklist_version": checklist.get("execution_checklist_version", ""),
        "status": checklist.get("status", ""),
        "google_execution_checklist_ready": checklist.get("google_execution_checklist_ready") is True,
        "google_main_scoring_allowed": checklist.get("google_main_scoring_allowed") is True,
        "limited_coverage": checklist.get("limited_coverage") is True,
        "next_action": checklist.get("next_action", ""),
        "google_execution_checklist_hash": checklist.get("google_execution_checklist_hash", ""),
        "planned_runs": summary.get("planned_runs"),
        "step_count": summary.get("step_count", 0),
        "missing_required_environment_count": summary.get("missing_required_environment_count", 0),
        "missing_required_environment": [str(value) for value in _as_list(summary.get("missing_required_environment"))],
        "missing_full_run_required_environment_count": summary.get("missing_full_run_required_environment_count", 0),
        "missing_full_run_required_environment": [
            str(value) for value in _as_list(summary.get("missing_full_run_required_environment"))
        ],
        "missing_selector_group_count": summary.get("missing_selector_group_count", 0),
        "missing_selector_groups": [str(value) for value in _as_list(summary.get("missing_selector_groups"))],
        "missing_dependency_count": summary.get("missing_dependency_count", 0),
        "missing_dependencies": [str(value) for value in _as_list(summary.get("missing_dependencies"))],
        "file_gate_issue_count": summary.get("file_gate_issue_count", 0),
        "file_gate_issues": [str(value) for value in _as_list(summary.get("file_gate_issues"))],
        "env_file_hygiene_ready": summary.get("env_file_hygiene_ready") is True,
        "env_file_hygiene_error_count": summary.get("env_file_hygiene_error_count", len(env_file_hygiene_errors)),
        "env_file_hygiene_warning_count": summary.get(
            "env_file_hygiene_warning_count",
            len(env_file_hygiene_warnings),
        ),
        "env_file_hygiene_errors": env_file_hygiene_errors,
        "env_file_hygiene_warnings": env_file_hygiene_warnings,
        "env_file_hygiene_path": str(env_file_hygiene.get("path") or ""),
        "env_file_hygiene_file_mode": str(env_file_hygiene.get("file_mode") or ""),
        "env_file_hygiene_git_safe": env_file_hygiene.get("git_safe") is True,
        "env_file_hygiene_permission_safe": env_file_hygiene.get("permission_safe") is True,
        "env_file_hygiene_required": env_file_hygiene.get("hygiene_required") is True,
        "environment_handoff_ready": environment_handoff.get("ready") is True,
        "environment_handoff_missing_required_count": environment_handoff.get("missing_required_count", 0),
        "environment_handoff_missing_required": [
            str(value) for value in _as_list(environment_handoff.get("missing_required"))
        ],
        "environment_handoff_target_env_file": str(environment_handoff.get("target_env_file") or ""),
        "environment_handoff_setup_command_count": len(_as_list(environment_handoff.get("setup_commands"))),
        "environment_handoff_verification_command_count": len(_as_list(environment_handoff.get("verification_commands"))),
        "environment_handoff_secret_redacted": redaction_policy.get("raw_secret_values_allowed") is False
        and redaction_policy.get("forbidden_exact_secret_fields_redacted") is True,
        "remaining_blocker_count": summary.get("remaining_blocker_count", 0),
        "remaining_blockers": [str(value) for value in _as_list(summary.get("remaining_blockers"))],
        "runbook_verifier_status": summary.get("runbook_verifier_status", ""),
        "playwright_env_verifier_status": summary.get("playwright_env_verifier_status", ""),
        "status_verifier_status": summary.get("status_verifier_status", ""),
        "package_verifier_status": summary.get("package_verifier_status", ""),
    }


def _source_file_entry(name: str, path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"name": name, "path": "", "exists": False}
    path_text = str(path)
    entry: dict[str, Any] = {"name": name, "path": path_text, "exists": bool(path_text) and path.exists()}
    if path_text and path.is_file():
        entry["size_bytes"] = path.stat().st_size
        entry["file_sha256"] = _file_sha256(path)
    return entry


def _optional_input_path(inputs: dict[str, Any], key: str) -> Path | None:
    value = str(inputs.get(key) or "")
    return Path(value) if value else None


def _stage_summaries(launch_status: dict[str, Any]) -> list[dict[str, Any]]:
    p0a = _as_dict(launch_status.get("p0a_design_partner"))
    p0b = _as_dict(launch_status.get("p0b_google"))
    p0c = _as_dict(launch_status.get("p0c_customer_report"))
    return [
        {
            "id": "p0a_design_partner",
            "label": "P0a Design Partner Data",
            "status": p0a.get("status", ""),
            "ready": p0a.get("ready_for_design_partner") is True,
            "next_action": p0a.get("next_action", ""),
            "remaining_blocker_count": len(_as_list(p0a.get("remaining_blockers"))),
            "hash_valid": p0a.get("hash_valid") is True,
            "completion": _as_dict(p0a.get("completion")),
        },
        {
            "id": "p0b_google",
            "label": "P0b Google Spike",
            "status": p0b.get("status", ""),
            "ready": p0b.get("google_main_scoring_allowed") is True,
            "next_action": p0b.get("next_action", ""),
            "remaining_blocker_count": len(_as_list(p0b.get("remaining_blockers"))),
            "status_hash_valid": p0b.get("status_hash_valid") is True,
            "package_hash_valid": p0b.get("package_hash_valid") is True,
            "limited_coverage": p0b.get("limited_coverage") is True,
        },
        {
            "id": "p0c_customer_report",
            "label": "P0c Customer Report Contract",
            "status": p0c.get("status", ""),
            "ready": p0c.get("p0c_report_contract_ready") is True,
            "next_action": p0c.get("next_action", ""),
            "remaining_blocker_count": len(_as_list(p0c.get("remaining_blockers"))),
            "hash_valid": p0c.get("hash_valid") is True,
            "artifact_count": p0c.get("artifact_count", 0),
            "google_coverage": p0c.get("google_coverage", ""),
        },
    ]


def _work_item_summaries(remediation_plan: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in _as_list(remediation_plan.get("work_items")):
        work_item = _as_dict(item)
        items.append(
            {
                "id": work_item.get("id", ""),
                "stage": work_item.get("stage", ""),
                "title": work_item.get("title", ""),
                "status": work_item.get("status", ""),
                "external_dependency": work_item.get("external_dependency") is True,
                "dependency_class": work_item.get("dependency_class", ""),
                "blocker_count": int(work_item.get("blocker_count") or 0),
                "commands": [str(_as_dict(command).get("shell", "")) for command in _as_list(work_item.get("commands"))],
                "verification_commands": [
                    str(_as_dict(command).get("shell", "")) for command in _as_list(work_item.get("verification_commands"))
                ],
                "evidence_outputs": [str(value) for value in _as_list(work_item.get("evidence_outputs"))],
            }
        )
    return items


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


def _handoff_posture(*, dossier_ready: bool, customer_ready: bool, external_blockers: int) -> str:
    if not dossier_ready:
        return "dossier_not_ready"
    if customer_ready:
        return "ready_for_customer_report_handoff"
    if external_blockers > 0:
        return "blocked_external_dependencies"
    return "blocked_internal_followup"


def render_au_handoff_markdown(dossier: dict[str, Any]) -> str:
    summary = _as_dict(dossier.get("summary"))
    launch_status = _as_dict(dossier.get("launch_status"))
    remediation_plan = _as_dict(dossier.get("remediation_plan"))
    p0a_environment_checklist = _as_dict(dossier.get("p0a_environment_checklist"))
    p0a_execution_checklist = _as_dict(dossier.get("p0a_execution_checklist"))
    p0b_google_execution_checklist = _as_dict(dossier.get("p0b_google_execution_checklist"))
    runtime_endpoints = _as_dict(dossier.get("runtime_endpoints"))
    next_work_item = _as_dict(dossier.get("next_work_item"))
    lines = [
        "# AU 客户交付总包",
        "",
        f"- 生成时间：{dossier.get('generated_at', '')}",
        f"- Dossier 状态：{dossier.get('status', '')}",
        f"- 客户报告交付准入：{'ready' if summary.get('ready_for_customer_report_handoff') else 'blocked'}",
        f"- 当前姿态：{summary.get('handoff_posture', '')}",
        f"- 下一步：{summary.get('next_action', '')}",
        f"- 下一 work item：{summary.get('next_work_item_id', '')}",
        f"- Launch status hash：{launch_status.get('launch_status_hash', '')}",
        f"- Remediation plan hash：{remediation_plan.get('remediation_plan_hash', '')}",
        f"- P0a environment checklist hash：{p0a_environment_checklist.get('environment_checklist_hash', '')}",
        f"- P0a execution checklist hash：{p0a_execution_checklist.get('p0a_execution_checklist_hash', '')}",
        f"- P0b Google execution checklist hash：{p0b_google_execution_checklist.get('google_execution_checklist_hash', '')}",
        "",
        "## 阶段门禁",
        "",
        "| 阶段 | 状态 | Ready | 下一步 | Blockers |",
        "| --- | --- | --- | --- | ---: |",
    ]
    for stage in _as_list(dossier.get("stage_summaries")):
        item = _as_dict(stage)
        lines.append(
            "| {label} | {status} | {ready} | {next_action} | {count} |".format(
                label=item.get("label", ""),
                status=item.get("status", ""),
                ready="yes" if item.get("ready") else "no",
                next_action=item.get("next_action", ""),
                count=item.get("remaining_blocker_count", 0),
            )
        )
    lines.extend(
        [
            "",
            "## Blocker 覆盖",
            "",
            f"- 总 blocker 数：{summary.get('remaining_blocker_count', 0)}",
            f"- 已映射 blocker 数：{summary.get('covered_blocker_count', 0)}",
            f"- 未映射 blocker 数：{summary.get('unmapped_blocker_count', 0)}",
            f"- 外部依赖 blocker 数：{summary.get('external_dependency_blocker_count', 0)}",
            f"- Work item 数：{summary.get('work_item_count', 0)}",
            "",
            "## 下一 Work Item",
            "",
            f"- ID：{next_work_item.get('id', 'none')}",
            f"- 阶段：{next_work_item.get('stage', '')}",
            f"- 标题：{next_work_item.get('title', '')}",
            f"- 依赖类型：{next_work_item.get('dependency_class', '')}",
            f"- 覆盖 blocker 数：{next_work_item.get('blocker_count', 0)}",
            "",
            "### 执行命令",
            "",
        ]
    )
    commands = [str(command) for command in _as_list(next_work_item.get("commands")) if str(command)]
    lines.extend([f"- `{command}`" for command in commands] or ["- 无"])
    lines.extend(["", "### 验证命令", ""])
    verification_commands = [
        str(command) for command in _as_list(next_work_item.get("verification_commands")) if str(command)
    ]
    lines.extend([f"- `{command}`" for command in verification_commands] or ["- 无"])
    lines.extend(
        [
            "",
            "## P0a 环境清单",
            "",
            f"- 状态：{p0a_environment_checklist.get('status', '')}",
            f"- Ready：{'yes' if p0a_environment_checklist.get('environment_checklist_ready') else 'no'}",
            f"- 下一步：{p0a_environment_checklist.get('next_action', '')}",
            f"- 必填变量：{p0a_environment_checklist.get('required_present_count', 0)}/{p0a_environment_checklist.get('required_count', 0)}",
            f"- 缺失必填：{', '.join(str(value) for value in _as_list(p0a_environment_checklist.get('missing_required'))) or '无'}",
            f"- 缺失推荐：{', '.join(str(value) for value in _as_list(p0a_environment_checklist.get('missing_recommended'))) or '无'}",
            f"- Env-file hygiene：{'ready' if p0a_environment_checklist.get('env_file_hygiene_ready') else 'blocked'}"
            f"（errors: {p0a_environment_checklist.get('env_file_hygiene_error_count', 0)}, "
            f"warnings: {p0a_environment_checklist.get('env_file_hygiene_warning_count', 0)}）",
            f"- Env-file hygiene path：{p0a_environment_checklist.get('env_file_hygiene_path') or 'none'}",
            f"- Runbook verifier：{p0a_environment_checklist.get('runbook_verifier_status', '')}",
            f"- Environment verifier：{p0a_environment_checklist.get('environment_verifier_status', '')}",
            "",
            "## P0a 执行清单",
            "",
            f"- 状态：{p0a_execution_checklist.get('status', '')}",
            f"- Ready：{'yes' if p0a_execution_checklist.get('p0a_execution_checklist_ready') else 'no'}",
            f"- Design partner ready：{'yes' if p0a_execution_checklist.get('ready_for_design_partner') else 'no'}",
            f"- 下一步：{p0a_execution_checklist.get('next_action', '')}",
            f"- Small batch planned runs：{p0a_execution_checklist.get('small_batch_planned_runs', '')}",
            f"- Full batch planned runs：{p0a_execution_checklist.get('full_batch_planned_runs', '')}",
            f"- 缺失 artifact：{', '.join(str(value) for value in _as_list(p0a_execution_checklist.get('missing_artifacts'))) or '无'}",
            f"- Remaining blockers：{p0a_execution_checklist.get('remaining_blocker_count', 0)}",
            f"- Credential handoff：{'ready' if p0a_execution_checklist.get('credential_handoff_ready') else 'blocked'}"
            f"（missing: {p0a_execution_checklist.get('credential_handoff_missing_required_count', 0)}, "
            f"redacted: {'yes' if p0a_execution_checklist.get('credential_handoff_secret_redacted') else 'no'}）",
            f"- Credential missing：{', '.join(str(value) for value in _as_list(p0a_execution_checklist.get('credential_handoff_missing_required'))) or '无'}",
            f"- Credential target env file：{p0a_execution_checklist.get('credential_handoff_target_env_file') or 'none'}",
            f"- Status verifier：{p0a_execution_checklist.get('status_verifier_status', '')}",
            "",
            "## P0b Google 执行清单",
            "",
            f"- 状态：{p0b_google_execution_checklist.get('status', '')}",
            f"- Ready：{'yes' if p0b_google_execution_checklist.get('google_execution_checklist_ready') else 'no'}",
            f"- Google 主评分准入：{'yes' if p0b_google_execution_checklist.get('google_main_scoring_allowed') else 'no'}",
            f"- 下一步：{p0b_google_execution_checklist.get('next_action', '')}",
            f"- Planned runs：{p0b_google_execution_checklist.get('planned_runs', '')}",
            f"- 缺失 smoke env：{', '.join(str(value) for value in _as_list(p0b_google_execution_checklist.get('missing_required_environment'))) or '无'}",
            f"- 缺失 full-run env：{', '.join(str(value) for value in _as_list(p0b_google_execution_checklist.get('missing_full_run_required_environment'))) or '无'}",
            f"- 缺失 selector group：{', '.join(str(value) for value in _as_list(p0b_google_execution_checklist.get('missing_selector_groups'))) or '无'}",
            f"- Env-file hygiene：{'ready' if p0b_google_execution_checklist.get('env_file_hygiene_ready') else 'blocked'}"
            f"（errors: {p0b_google_execution_checklist.get('env_file_hygiene_error_count', 0)}, "
            f"warnings: {p0b_google_execution_checklist.get('env_file_hygiene_warning_count', 0)}）",
            f"- Env-file hygiene path：{p0b_google_execution_checklist.get('env_file_hygiene_path') or 'none'}",
            f"- Environment handoff：{'ready' if p0b_google_execution_checklist.get('environment_handoff_ready') else 'blocked'}"
            f"（missing: {p0b_google_execution_checklist.get('environment_handoff_missing_required_count', 0)}, "
            f"redacted: {'yes' if p0b_google_execution_checklist.get('environment_handoff_secret_redacted') else 'no'}）",
            f"- Environment handoff missing：{', '.join(str(value) for value in _as_list(p0b_google_execution_checklist.get('environment_handoff_missing_required'))) or '无'}",
            f"- Environment handoff target env file：{p0b_google_execution_checklist.get('environment_handoff_target_env_file') or 'none'}",
            f"- Remaining blockers：{p0b_google_execution_checklist.get('remaining_blocker_count', 0)}",
            f"- Status verifier：{p0b_google_execution_checklist.get('status_verifier_status', '')}",
            f"- Package verifier：{p0b_google_execution_checklist.get('package_verifier_status', '')}",
        ]
    )
    lines.extend(
        [
            "",
            "## Runtime 复盘入口",
            "",
            f"- 项目生命周期：`{runtime_endpoints.get('project_lifecycle_events', '')}`",
            f"- 项目生命周期 CSV：`{runtime_endpoints.get('project_lifecycle_events_export', '')}`",
            f"- 项目审计轨道：`{runtime_endpoints.get('runtime_audit_events', '')}`",
            f"- 项目审计 CSV：`{runtime_endpoints.get('runtime_audit_events_export', '')}`",
        ]
    )
    lines.extend(["", "## 证据来源", "", "| 名称 | 存在 | sha256 | 路径 |", "| --- | --- | --- | --- |"])
    for source in _as_list(dossier.get("evidence_sources")):
        item = _as_dict(source)
        lines.append(
            "| {name} | {exists} | {sha} | `{path}` |".format(
                name=item.get("name", ""),
                exists="yes" if item.get("exists") else "no",
                sha=item.get("file_sha256", ""),
                path=item.get("path", ""),
            )
        )
    lines.extend(
        [
            "",
            "## 当前边界",
            "",
            "- 本总包证明当前 AU launch 状态、清障计划和本地证据索引可复算。",
            "- 本总包不代表真实 P0a provider 批次、P0b Google 240-run 或生产发布门禁已经完成。",
            "- 真实客户报告交付硬门禁仍以 `scripts/verify_au_launch_status.py --require-ready` 为准。",
            "",
        ]
    )
    return "\n".join(lines)


def build_au_handoff_dossier(
    *,
    launch_status_path: Path = Path(DEFAULT_LAUNCH_STATUS_PATH),
    remediation_plan_path: Path = Path(DEFAULT_REMEDIATION_PLAN_PATH),
    p0a_environment_checklist_path: Path = Path(DEFAULT_P0A_ENVIRONMENT_CHECKLIST_PATH),
    p0a_execution_checklist_path: Path = Path(DEFAULT_P0A_EXECUTION_CHECKLIST_PATH),
    p0b_google_execution_checklist_path: Path = Path(DEFAULT_P0B_GOOGLE_EXECUTION_CHECKLIST_PATH),
    launch_status: dict[str, Any] | None = None,
    remediation_plan: dict[str, Any] | None = None,
    p0a_environment_checklist: dict[str, Any] | None = None,
    p0a_execution_checklist: dict[str, Any] | None = None,
    p0b_google_execution_checklist: dict[str, Any] | None = None,
    output_path: Path | None = None,
    markdown_output_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if launch_status is None:
        launch_status, launch_source = _load_or_build_launch_status(launch_status_path, generated_at=generated_at)
    else:
        launch_source = {"path": str(launch_status_path), "exists": True, "source": "provided_payload"}
    if remediation_plan is None:
        remediation_plan, remediation_source = _load_or_build_remediation_plan(
            remediation_plan_path,
            launch_status=launch_status,
            launch_status_path=launch_status_path,
            generated_at=generated_at,
        )
    else:
        remediation_source = {"path": str(remediation_plan_path), "exists": True, "source": "provided_payload"}
    if p0a_environment_checklist is None:
        p0a_environment_checklist, checklist_source = _load_or_build_p0a_environment_checklist(
            p0a_environment_checklist_path,
            generated_at=generated_at,
        )
    else:
        checklist_source = {"path": str(p0a_environment_checklist_path), "exists": True, "source": "provided_payload"}
    if p0a_execution_checklist is None:
        p0a_execution_checklist, p0a_execution_checklist_source = _load_or_build_p0a_execution_checklist(
            p0a_execution_checklist_path,
            generated_at=generated_at,
        )
    else:
        p0a_execution_checklist_source = {
            "path": str(p0a_execution_checklist_path),
            "exists": True,
            "source": "provided_payload",
        }
    if p0b_google_execution_checklist is None:
        p0b_google_execution_checklist, p0b_google_checklist_source = _load_or_build_p0b_google_execution_checklist(
            p0b_google_execution_checklist_path,
            generated_at=generated_at,
        )
    else:
        p0b_google_checklist_source = {
            "path": str(p0b_google_execution_checklist_path),
            "exists": True,
            "source": "provided_payload",
        }
    launch_verification = verify_au_launch_status(launch_status, path=launch_status_path)
    remediation_verification = verify_au_launch_remediation_plan(remediation_plan, path=remediation_plan_path)
    checklist_summary = _p0a_environment_checklist_summary(p0a_environment_checklist)
    p0a_execution_checklist_summary = _p0a_execution_checklist_summary(p0a_execution_checklist)
    p0b_google_checklist_summary = _p0b_google_execution_checklist_summary(p0b_google_execution_checklist)
    remediation_summary = _as_dict(remediation_plan.get("summary"))
    remaining_blockers = [str(item) for item in _as_list(launch_status.get("remaining_blockers"))]
    work_items = _work_item_summaries(remediation_plan)
    next_work_item_id = str(remediation_plan.get("next_work_item_id") or "none")
    next_work_item = next((item for item in work_items if item.get("id") == next_work_item_id), {"id": "none"})
    handoff_dossier_ready = (
        launch_verification.get("status") == "pass"
        and launch_verification.get("hash_valid") is True
        and remediation_verification.get("status") == "pass"
        and remediation_verification.get("hash_valid") is True
        and remediation_summary.get("unmapped_blocker_count") == 0
    )
    customer_ready = launch_status.get("ready_for_customer_report_handoff") is True
    external_blocker_count = int(remediation_summary.get("external_dependency_blocker_count") or 0)
    inputs = _as_dict(launch_status.get("inputs"))
    evidence_sources = [
        _source_file_entry("launch_status", launch_status_path),
        _source_file_entry("remediation_plan", remediation_plan_path),
        _source_file_entry("p0a_environment_checklist", p0a_environment_checklist_path),
        _source_file_entry("p0a_execution_checklist", p0a_execution_checklist_path),
        _source_file_entry("p0b_google_execution_checklist", p0b_google_execution_checklist_path),
        _source_file_entry("p0a_status", _optional_input_path(inputs, "p0a_status_path")),
        _source_file_entry("p0b_google_status", _optional_input_path(inputs, "p0b_google_status_path")),
        _source_file_entry("p0b_google_package", _optional_input_path(inputs, "p0b_google_package_path")),
        _source_file_entry("p0c_report_package", _optional_input_path(inputs, "p0c_report_package_path")),
    ]
    dossier: dict[str, Any] = {
        "handoff_dossier_version": DOSSIER_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if handoff_dossier_ready else "fail",
        "handoff_dossier_ready": handoff_dossier_ready,
        "ready_for_customer_report_handoff": customer_ready,
        "output_path": str(output_path) if output_path else "",
        "markdown_output_path": str(markdown_output_path) if markdown_output_path else "",
        "summary": {
            "handoff_posture": _handoff_posture(
                dossier_ready=handoff_dossier_ready,
                customer_ready=customer_ready,
                external_blockers=external_blocker_count,
            ),
            "ready_for_customer_report_handoff": customer_ready,
            "next_action": launch_status.get("next_action", ""),
            "next_work_item_id": next_work_item_id,
            "remaining_blocker_count": len(remaining_blockers),
            "blocker_stage_counts": _blocker_stage_counts(remaining_blockers),
            "covered_blocker_count": remediation_summary.get("covered_blocker_count", 0),
            "unmapped_blocker_count": remediation_summary.get("unmapped_blocker_count", 0),
            "work_item_count": remediation_summary.get("work_item_count", 0),
            "external_dependency_blocker_count": external_blocker_count,
            "runnable_now_work_item_count": remediation_summary.get("runnable_now_work_item_count", 0),
            "p0a_environment_checklist_ready": checklist_summary.get("environment_checklist_ready") is True,
            "p0a_missing_required_environment_count": checklist_summary.get("missing_required_count", 0),
            "p0a_env_file_hygiene_ready": checklist_summary.get("env_file_hygiene_ready") is True,
            "p0a_env_file_hygiene_error_count": checklist_summary.get("env_file_hygiene_error_count", 0),
            "p0a_env_file_hygiene_warning_count": checklist_summary.get("env_file_hygiene_warning_count", 0),
            "p0a_execution_checklist_ready": p0a_execution_checklist_summary.get("p0a_execution_checklist_ready")
            is True,
            "p0a_execution_remaining_blocker_count": p0a_execution_checklist_summary.get("remaining_blocker_count", 0),
            "p0a_credential_handoff_ready": p0a_execution_checklist_summary.get("credential_handoff_ready") is True,
            "p0a_credential_handoff_missing_required_count": p0a_execution_checklist_summary.get(
                "credential_handoff_missing_required_count",
                0,
            ),
            "p0a_credential_handoff_secret_redacted": p0a_execution_checklist_summary.get(
                "credential_handoff_secret_redacted",
            )
            is True,
            "p0b_google_execution_checklist_ready": p0b_google_checklist_summary.get(
                "google_execution_checklist_ready"
            )
            is True,
            "p0b_google_remaining_blocker_count": p0b_google_checklist_summary.get("remaining_blocker_count", 0),
            "p0b_google_env_file_hygiene_ready": p0b_google_checklist_summary.get("env_file_hygiene_ready")
            is True,
            "p0b_google_env_file_hygiene_error_count": p0b_google_checklist_summary.get(
                "env_file_hygiene_error_count",
                0,
            ),
            "p0b_google_env_file_hygiene_warning_count": p0b_google_checklist_summary.get(
                "env_file_hygiene_warning_count",
                0,
            ),
            "p0b_google_environment_handoff_ready": p0b_google_checklist_summary.get("environment_handoff_ready")
            is True,
            "p0b_google_environment_handoff_missing_required_count": p0b_google_checklist_summary.get(
                "environment_handoff_missing_required_count",
                0,
            ),
            "p0b_google_environment_handoff_secret_redacted": p0b_google_checklist_summary.get(
                "environment_handoff_secret_redacted",
            )
            is True,
        },
        "runtime_endpoints": {
            "launch_status": "GET /v1/launch-status/au",
            "launch_remediation_plan": "GET /v1/launch-remediation-plan/au",
            "p0a_environment_checklist": "GET /v1/p0a-environment-checklist/au",
            "p0a_execution_checklist": "GET /v1/p0a-execution-checklist/au",
            "p0b_google_execution_checklist": "GET /v1/p0b-google-execution-checklist/au",
            "au_retest_scheduler_plan": "GET /v1/au-retest-scheduler-plan",
            "au_retest_execution_status": "GET /v1/au-retest-execution-status",
            "project_lifecycle_events": "GET /v1/projects/runtime/lifecycle-events?project_id={project_id}",
            "project_lifecycle_events_export": "GET /v1/projects/runtime/lifecycle-events/export.csv?project_id={project_id}",
            "runtime_audit_events": "GET /v1/audit-events/runtime?project_id={project_id}",
            "runtime_audit_events_export": "GET /v1/audit-events/runtime/export.csv?project_id={project_id}",
        },
        "launch_status": {
            "path": str(launch_status_path),
            "status": launch_status.get("status", ""),
            "ready_for_customer_report_handoff": customer_ready,
            "next_action": launch_status.get("next_action", ""),
            "launch_status_hash": launch_status.get("launch_status_hash", ""),
            "remaining_blockers": remaining_blockers,
        },
        "launch_status_source": launch_source,
        "launch_status_verifier": launch_verification,
        "remediation_plan": {
            "path": str(remediation_plan_path),
            "status": remediation_plan.get("status", ""),
            "remediation_plan_ready": remediation_plan.get("remediation_plan_ready") is True,
            "next_work_item_id": next_work_item_id,
            "remediation_plan_hash": remediation_plan.get("remediation_plan_hash", ""),
            "summary": remediation_summary,
        },
        "remediation_plan_source": remediation_source,
        "remediation_plan_verifier": remediation_verification,
        "p0a_environment_checklist": checklist_summary,
        "p0a_environment_checklist_source": checklist_source,
        "p0a_execution_checklist": p0a_execution_checklist_summary,
        "p0a_execution_checklist_source": p0a_execution_checklist_source,
        "p0b_google_execution_checklist": p0b_google_checklist_summary,
        "p0b_google_execution_checklist_source": p0b_google_checklist_source,
        "stage_summaries": _stage_summaries(launch_status),
        "work_items": work_items,
        "next_work_item": next_work_item,
        "blocker_remediations": _as_list(remediation_plan.get("blocker_remediations")),
        "evidence_sources": evidence_sources,
    }
    markdown = render_au_handoff_markdown(dossier)
    dossier["markdown_report"] = {
        "path": str(markdown_output_path) if markdown_output_path else "",
        "size_bytes": len(markdown.encode("utf-8")),
        "content_sha256": _sha256_text(markdown),
        "media_type": "text/markdown; charset=utf-8",
    }
    dossier["handoff_dossier_hash"] = compute_handoff_dossier_hash(dossier)
    return dossier


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU customer handoff dossier JSON and Markdown")
    parser.add_argument(
        "--launch-status-path",
        default=os.environ.get("GENO_AU_LAUNCH_STATUS_OUTPUT_PATH", DEFAULT_LAUNCH_STATUS_PATH),
        help="Path to the AU launch status JSON.",
    )
    parser.add_argument(
        "--remediation-plan-path",
        default=os.environ.get("GENO_AU_LAUNCH_REMEDIATION_PLAN_OUTPUT_PATH", DEFAULT_REMEDIATION_PLAN_PATH),
        help="Path to the AU launch remediation plan JSON.",
    )
    parser.add_argument(
        "--p0a-environment-checklist-path",
        default=os.environ.get("GENO_AU_P0A_ENVIRONMENT_CHECKLIST_OUTPUT_PATH", DEFAULT_P0A_ENVIRONMENT_CHECKLIST_PATH),
        help="Path to the AU P0a environment checklist JSON.",
    )
    parser.add_argument(
        "--p0a-execution-checklist-path",
        default=os.environ.get("GENO_AU_P0A_EXECUTION_CHECKLIST_OUTPUT_PATH", DEFAULT_P0A_EXECUTION_CHECKLIST_PATH),
        help="Path to the AU P0a execution checklist JSON.",
    )
    parser.add_argument(
        "--p0b-google-execution-checklist-path",
        default=os.environ.get(
            "GENO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH",
            DEFAULT_P0B_GOOGLE_EXECUTION_CHECKLIST_PATH,
        ),
        help="Path to the AU P0b Google execution checklist JSON.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GENO_AU_HANDOFF_DOSSIER_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU handoff dossier JSON.",
    )
    parser.add_argument(
        "--markdown-output-path",
        default=os.environ.get("GENO_AU_HANDOFF_DOSSIER_MARKDOWN_PATH", DEFAULT_MARKDOWN_OUTPUT_PATH),
        help="Path to write the human-readable AU handoff dossier Markdown.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    markdown_path = Path(args.markdown_output_path)
    dossier = build_au_handoff_dossier(
        launch_status_path=Path(args.launch_status_path),
        remediation_plan_path=Path(args.remediation_plan_path),
        p0a_environment_checklist_path=Path(args.p0a_environment_checklist_path),
        p0a_execution_checklist_path=Path(args.p0a_execution_checklist_path),
        p0b_google_execution_checklist_path=Path(args.p0b_google_execution_checklist_path),
        output_path=output_path,
        markdown_output_path=markdown_path,
        generated_at=args.generated_at,
    )
    markdown = render_au_handoff_markdown(dossier)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(dossier, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    markdown_path.write_text(markdown, encoding="utf-8")
    print(json.dumps(dossier, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if dossier["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
