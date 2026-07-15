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
from scripts.build_au_p0b_google_manual_backfill_fulfillment import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0B_GOOGLE_MANUAL_BACKFILL_FULFILLMENT_PATH,
)
from scripts.verify_au_launch_remediation_plan import verify_au_launch_remediation_plan  # noqa: E402
from scripts.verify_au_launch_status import verify_au_launch_status  # noqa: E402
from scripts.verify_au_p0a_environment_checklist import verify_au_p0a_environment_checklist  # noqa: E402
from scripts.verify_au_p0a_execution_checklist import verify_au_p0a_execution_checklist  # noqa: E402
from scripts.verify_au_p0b_google_execution_checklist import verify_au_p0b_google_execution_checklist  # noqa: E402
from scripts.verify_au_p0b_google_manual_backfill_fulfillment import (  # noqa: E402
    verify_au_p0b_google_manual_backfill_fulfillment,
)


HANDOFF_VERSION = "au_external_dependency_handoff_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-external-dependency-handoff-latest.json"
CLEARANCE_SEQUENCE_VERSION = "au_external_dependency_clearance_sequence_v1"
CLEARANCE_STEP_ORDER = (
    "p0a_provider_credentials",
    "p0a_real_batches",
    "p0b_google_environment",
    "p0b_google_manual_backfill",
    "p0b_google_phase_execution",
    "customer_report_handoff_gate",
)
P0A_PROVIDER_CREDENTIAL_BOOTSTRAPPED_COMMAND_PRIORITY = (
    "make au-p0a-env",
    "make verify-au-p0a-env",
    "make au-p0a-environment-checklist",
    "make verify-au-p0a-environment-checklist",
    "make au-p0a-readiness",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )


def compute_external_dependency_handoff_hash(handoff: dict[str, Any]) -> str:
    payload = dict(handoff)
    payload.pop("external_dependency_handoff_hash", None)
    return hashlib.sha256(_stable_bytes(payload)).hexdigest()


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


def _strings(value: object) -> list[str]:
    return [str(item) for item in _as_list(value)]


def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _first_present(primary: dict[str, Any], secondary: dict[str, Any], key: str) -> object:
    if key in primary and primary.get(key) is not None:
        return primary.get(key)
    return secondary.get(key)


def _commands(value: object) -> list[str]:
    commands: list[str] = []
    for item in _as_list(value):
        if isinstance(item, str):
            commands.append(item)
        else:
            shell = str(_as_dict(item).get("shell") or "")
            if shell:
                commands.append(shell)
    return commands


def _unique_strings(values: list[str]) -> list[str]:
    observed: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in observed:
            observed.add(value)
            result.append(value)
    return result


def _load_json(path: Path) -> tuple[Any | None, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, {"path": str(path), "exists": False, "source": "missing_file", "errors": ["file_missing"]}
    except json.JSONDecodeError as exc:
        return None, {
            "path": str(path),
            "exists": True,
            "source": "invalid_file",
            "errors": [f"json_invalid:{exc.msg}"],
        }
    return payload, {"path": str(path), "exists": True, "source": "existing_file", "errors": []}


def _source_file_entry(name: str, path: Path) -> dict[str, Any]:
    entry: dict[str, Any] = {"name": name, "path": str(path), "exists": path.exists()}
    if path.is_file():
        entry["size_bytes"] = path.stat().st_size
        entry["file_sha256"] = _file_sha256(path)
    return entry


def _load_or_build_launch_status(path: Path, *, generated_at: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if isinstance(payload, dict):
        return payload, source
    return build_au_launch_status(output_path=path, generated_at=generated_at), {
        **source,
        "source": "generated_in_memory",
    }


def _load_or_build_remediation_plan(
    path: Path,
    *,
    launch_status: dict[str, Any],
    launch_status_path: Path,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if isinstance(payload, dict):
        embedded = _as_dict(payload.get("launch_status"))
        if embedded.get("launch_status_hash") == launch_status.get("launch_status_hash"):
            return payload, source
    plan = build_au_launch_remediation_plan(
        launch_status=launch_status,
        launch_status_path=launch_status_path,
        output_path=path,
        generated_at=generated_at,
    )
    return plan, {**source, "source": "generated_in_memory"}


def _load_or_build_p0a_environment_checklist(
    path: Path,
    *,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if isinstance(payload, dict):
        return payload, source
    return build_au_p0a_environment_checklist(output_path=path, generated_at=generated_at), {
        **source,
        "source": "generated_in_memory",
    }


def _load_or_build_p0a_execution_checklist(
    path: Path,
    *,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if isinstance(payload, dict):
        return payload, source
    return build_au_p0a_execution_checklist(output_path=path, generated_at=generated_at), {
        **source,
        "source": "generated_in_memory",
    }


def _load_or_build_p0b_google_execution_checklist(
    path: Path,
    *,
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if isinstance(payload, dict):
        return payload, source
    return build_au_p0b_google_execution_checklist(output_path=path, generated_at=generated_at), {
        **source,
        "source": "generated_in_memory",
    }


def _load_optional_p0b_manual_backfill_fulfillment(
    path: Path | None,
    payload: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if payload is not None:
        return payload, {"path": str(path or ""), "exists": True, "source": "provided_payload", "errors": []}
    if path is None:
        return None, {"path": "", "exists": False, "source": "not_configured", "errors": []}
    loaded, source = _load_json(path)
    if isinstance(loaded, dict):
        return loaded, source
    return None, source


def _verifier_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": result.get("status", ""),
        "hash_valid": result.get("hash_valid") is True,
        "ready": any(
            result.get(field) is True
            for field in (
                "launch_status_ready",
                "remediation_plan_ready",
                "environment_checklist_ready",
                "p0a_execution_checklist_ready",
                "google_execution_checklist_ready",
                "manual_backfill_fulfillment_ready",
            )
        ),
        "errors": _strings(result.get("errors")),
    }


def _work_item_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("id") or ""),
        "stage": str(item.get("stage") or ""),
        "title": str(item.get("title") or ""),
        "status": str(item.get("status") or ""),
        "external_dependency": item.get("external_dependency") is True,
        "dependency_class": str(item.get("dependency_class") or ""),
        "required_inputs": _strings(item.get("required_inputs")),
        "blocker_count": int(item.get("blocker_count") or 0),
        "clears_blockers": _strings(item.get("clears_blockers")),
        "commands": _commands(item.get("commands")),
        "verification_commands": _commands(item.get("verification_commands")),
        "evidence_outputs": _strings(item.get("evidence_outputs")),
        "acceptance": str(item.get("acceptance") or ""),
    }


def _matching_work_item_ids(work_items: list[dict[str, Any]], candidates: list[str]) -> list[str]:
    available = {str(item.get("id") or "") for item in work_items}
    return [item for item in candidates if item in available]


def _work_items_by_id(work_items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("id") or ""): item for item in work_items}


def _work_item_field_values(
    work_items: list[dict[str, Any]],
    work_item_ids: list[str],
    field: str,
) -> list[str]:
    by_id = _work_items_by_id(work_items)
    values: list[str] = []
    for work_item_id in work_item_ids:
        values.extend(_strings(_as_dict(by_id.get(work_item_id)).get(field)))
    return _unique_strings(values)


def _first_unready_phase(group: dict[str, Any]) -> dict[str, Any]:
    next_phase = str(group.get("next_phase") or "")
    phases = [_as_dict(item) for item in _as_list(group.get("phases"))]
    for phase in phases:
        if phase.get("id") == next_phase:
            return phase
    for phase in phases:
        if phase.get("ready") is not True:
            return phase
    return {}


def _planned_runs_for_group(group: dict[str, Any]) -> int:
    for field in ("total_planned_runs", "full_spike_planned_runs", "expected_record_count"):
        planned = int(group.get(field) or 0)
        if planned > 0:
            return planned
    phase = _first_unready_phase(group)
    return int(phase.get("planned_runs") or 0)


def _blocking_reasons_for_group(group: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    reasons.extend(f"missing_required:{value}" for value in _strings(group.get("missing_required")))
    reasons.extend(_strings(group.get("missing_reasons")))
    phase = _first_unready_phase(group)
    reasons.extend(_strings(phase.get("blocking_reasons")))
    if group.get("ready") is not True and not reasons:
        reasons.append(f"{group.get('id', 'dependency_group')}:not_ready")
    return _unique_strings(reasons)


def _commands_for_group(group: dict[str, Any], work_items: list[dict[str, Any]]) -> list[str]:
    phase = _first_unready_phase(group)
    work_item_ids = _strings(group.get("work_item_ids"))
    commands = _unique_strings(
        _commands(phase.get("commands"))
        + _strings(group.get("setup_commands"))
        + _work_item_field_values(work_items, work_item_ids, "commands")
    )
    if (
        group.get("id") == "p0a_provider_credentials"
        and group.get("env_file_hygiene_exists") is True
        and group.get("env_file_hygiene_ready") is True
    ):
        return _unique_strings(list(P0A_PROVIDER_CREDENTIAL_BOOTSTRAPPED_COMMAND_PRIORITY) + commands)
    return commands


def _with_group_execution_fields(group: dict[str, Any], work_items: list[dict[str, Any]]) -> dict[str, Any]:
    commands = _commands_for_group(group, work_items)
    blocking_reasons = [] if group.get("ready") is True else _blocking_reasons_for_group(group)
    return {
        **group,
        "commands": commands,
        "next_command": "" if group.get("ready") is True or not commands else commands[0],
        "blocking_reasons": blocking_reasons,
    }


def _clearance_step_from_group(
    group: dict[str, Any],
    *,
    order: int,
    prerequisite_step_ids: list[str],
    prior_ready_by_id: dict[str, bool],
    work_items: list[dict[str, Any]],
) -> dict[str, Any]:
    group_id = str(group.get("id") or "")
    work_item_ids = _strings(group.get("work_item_ids"))
    phase = _first_unready_phase(group)
    prerequisite_ready = all(prior_ready_by_id.get(step_id) is True for step_id in prerequisite_step_ids)
    ready = group.get("ready") is True
    commands = _commands_for_group(group, work_items)
    verification_commands = _unique_strings(
        _strings(group.get("verification_commands"))
        + _work_item_field_values(work_items, work_item_ids, "verification_commands")
    )
    evidence_outputs = _unique_strings(
        _strings(group.get("evidence_outputs"))
        + _work_item_field_values(work_items, work_item_ids, "evidence_outputs")
    )
    blocked_by = _blocking_reasons_for_group(group)
    if not prerequisite_ready:
        blocked_by = _unique_strings(
            [f"prerequisite_step_not_ready:{step_id}" for step_id in prerequisite_step_ids if prior_ready_by_id.get(step_id) is not True]
            + blocked_by
        )
    if ready:
        status = "ready"
    elif not prerequisite_ready:
        status = "blocked_waiting_on_prerequisite"
    else:
        status = str(group.get("status") or "blocked")
    return {
        "id": group_id,
        "order": order,
        "stage": str(group.get("stage") or ""),
        "title": str(group.get("title") or group_id),
        "type": "dependency_group",
        "group_id": group_id,
        "work_item_ids": work_item_ids,
        "dependency_class": str(group.get("dependency_class") or ""),
        "status": status,
        "ready": ready,
        "can_start": prerequisite_ready and not ready,
        "external_input_required": str(group.get("status") or "") == "requires_external_input"
        or bool(_strings(group.get("missing_required")))
        or bool(_strings(group.get("missing_reasons"))),
        "prerequisite_step_ids": prerequisite_step_ids,
        "current_phase": str(phase.get("id") or group.get("next_phase") or "none"),
        "planned_runs": _planned_runs_for_group(group),
        "commands": commands,
        "verification_commands": verification_commands,
        "evidence_outputs": evidence_outputs,
        "blocked_by": [] if ready else blocked_by,
        "acceptance": "ready=true and all verification commands pass with redacted evidence artifacts present",
    }


def _build_clearance_sequence(
    dependency_groups: list[dict[str, Any]],
    work_items: list[dict[str, Any]],
    *,
    external_ready: bool,
    customer_ready: bool,
) -> dict[str, Any]:
    groups = {str(group.get("id") or ""): group for group in dependency_groups}
    prerequisites = {
        "p0a_provider_credentials": [],
        "p0a_real_batches": ["p0a_provider_credentials"],
        "p0b_google_environment": ["p0a_real_batches"],
        "p0b_google_manual_backfill": ["p0b_google_environment"],
        "p0b_google_phase_execution": ["p0b_google_manual_backfill"],
    }
    steps: list[dict[str, Any]] = []
    ready_by_id: dict[str, bool] = {}
    for index, step_id in enumerate(CLEARANCE_STEP_ORDER[:-1], start=1):
        step = _clearance_step_from_group(
            groups.get(step_id, {"id": step_id, "ready": False}),
            order=index,
            prerequisite_step_ids=prerequisites[step_id],
            prior_ready_by_id=ready_by_id,
            work_items=work_items,
        )
        steps.append(step)
        ready_by_id[step["id"]] = step["ready"] is True

    final_prerequisites = ["p0a_real_batches", "p0b_google_phase_execution"]
    final_prerequisite_ready = all(ready_by_id.get(step_id) is True for step_id in final_prerequisites)
    final_ready = external_ready and customer_ready
    final_blockers = [
        f"prerequisite_step_not_ready:{step_id}" for step_id in final_prerequisites if ready_by_id.get(step_id) is not True
    ]
    if not external_ready:
        final_blockers.append("external_dependency_handoff_not_ready")
    if not customer_ready:
        final_blockers.append("customer_report_handoff_not_ready")
    final_step = {
        "id": "customer_report_handoff_gate",
        "order": len(CLEARANCE_STEP_ORDER),
        "stage": "Launch",
        "title": "Customer report handoff hard gates",
        "type": "final_gate",
        "group_id": "",
        "work_item_ids": [],
        "dependency_class": "customer_report_handoff",
        "status": "ready" if final_ready else "blocked_waiting_on_prerequisite",
        "ready": final_ready,
        "can_start": final_prerequisite_ready and not final_ready,
        "external_input_required": False,
        "prerequisite_step_ids": final_prerequisites,
        "current_phase": "final_hard_gate",
        "planned_runs": 0,
        "commands": [
            "make au-launch-status",
            "make au-handoff-dossier",
            "make au-external-dependency-handoff",
        ],
        "verification_commands": [
            "make verify-au-launch-status",
            "make verify-au-handoff-dossier",
            "make verify-au-external-dependency-handoff",
            "PYTHONPATH=packages/geo_core:apps/api python3 scripts/verify_au_external_dependency_handoff.py ${GEO_AU_EXTERNAL_DEPENDENCY_HANDOFF_OUTPUT_PATH:-docs/runtime_preflight/au-external-dependency-handoff-latest.json} --require-ready",
            "PYTHONPATH=packages/geo_core:apps/api python3 scripts/verify_au_launch_status.py ${GEO_AU_LAUNCH_STATUS_OUTPUT_PATH:-docs/runtime_preflight/au-launch-status-latest.json} --require-ready",
        ],
        "evidence_outputs": [
            DEFAULT_OUTPUT_PATH,
            "docs/runtime_preflight/au-launch-status-latest.json",
            "docs/runtime_preflight/au-handoff-dossier-latest.json",
            "docs/runtime_preflight/au-handoff-dossier-latest.md",
        ],
        "blocked_by": [] if final_ready else _unique_strings(final_blockers),
        "acceptance": "all external dependency groups ready and customer report launch hard gates pass",
    }
    steps.append(final_step)

    current_step = next((step for step in steps if step.get("ready") is not True and step.get("can_start") is True), None)
    if current_step is None:
        current_step = next((step for step in steps if step.get("ready") is not True), {"id": "none", "commands": []})
    next_commands = _strings(_as_dict(current_step).get("commands"))
    return {
        "version": CLEARANCE_SEQUENCE_VERSION,
        "mode": "recommended_serial_clearance",
        "step_ids": [step["id"] for step in steps],
        "step_count": len(steps),
        "ready_step_count": sum(1 for step in steps if step.get("ready") is True),
        "blocked_step_count": sum(1 for step in steps if step.get("ready") is not True),
        "current_step_id": str(_as_dict(current_step).get("id") or "none"),
        "next_command": next_commands[0] if next_commands else "",
        "hard_gate_commands": _strings(final_step.get("verification_commands")),
        "steps": steps,
    }


def _p0a_provider_credentials_group(
    p0a_environment_checklist: dict[str, Any],
    p0a_execution_checklist: dict[str, Any],
    work_items: list[dict[str, Any]],
) -> dict[str, Any]:
    credential_handoff = _as_dict(p0a_execution_checklist.get("credential_handoff"))
    env_summary = _as_dict(p0a_environment_checklist.get("summary"))
    redaction = _as_dict(credential_handoff.get("redaction_policy"))
    ready = credential_handoff.get("ready") is True
    verification_commands = _unique_strings(
        _commands(credential_handoff.get("verification_commands"))
        + [
            "make au-p0a-credential-fulfillment",
            "make verify-au-p0a-credential-fulfillment",
            (
                "PYTHONPATH=packages/geo_core:apps/api python3 "
                "scripts/verify_au_p0a_credential_fulfillment.py "
                "${GEO_AU_P0A_CREDENTIAL_FULFILLMENT_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-credential-fulfillment-latest.json} "
                "--require-fulfilled"
            ),
            "make au-p0a-credential-clearance",
            "make verify-au-p0a-credential-clearance",
            (
                "PYTHONPATH=packages/geo_core:apps/api python3 "
                "scripts/verify_au_p0a_credential_clearance.py "
                "${GEO_AU_P0A_CREDENTIAL_CLEARANCE_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-credential-clearance-latest.json} "
                "--require-cleared"
            ),
            "make au-p0a-credential-update-receipt",
            "make verify-au-p0a-credential-update-receipt",
            (
                "PYTHONPATH=packages/geo_core:apps/api python3 "
                "scripts/verify_au_p0a_credential_update_receipt.py "
                "${GEO_AU_P0A_CREDENTIAL_UPDATE_RECEIPT_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-credential-update-receipt-latest.json} "
                "--require-complete"
            ),
        ]
    )
    evidence_outputs = _unique_strings(
        _strings(credential_handoff.get("evidence_outputs"))
        + [
            "docs/runtime_preflight/au-p0a-credential-fulfillment-latest.json",
            "docs/runtime_preflight/au-p0a-credential-clearance-latest.json",
            "docs/runtime_preflight/au-p0a-credential-update-receipt-latest.json",
        ]
    )
    return {
        "id": "p0a_provider_credentials",
        "stage": "P0a",
        "title": "P0a provider keys and runtime database",
        "status": "ready" if ready else "requires_external_input",
        "external_dependency": True,
        "dependency_class": "provider_keys_and_database",
        "ready": ready,
        "work_item_ids": _matching_work_item_ids(work_items, ["p0a_environment"]),
        "target_env_file": str(credential_handoff.get("target_env_file") or ""),
        "missing_required_count": int(credential_handoff.get("missing_required_count") or 0),
        "missing_required": _strings(credential_handoff.get("missing_required")),
        "setup_commands": _commands(credential_handoff.get("setup_commands")),
        "verification_commands": verification_commands,
        "evidence_outputs": evidence_outputs,
        "credential_items": _as_list(credential_handoff.get("credential_items")),
        "env_file_hygiene_path": str(_as_dict(p0a_environment_checklist.get("env_file_hygiene")).get("path") or ""),
        "env_file_hygiene_exists": _as_dict(p0a_environment_checklist.get("env_file_hygiene")).get("exists") is True,
        "env_file_hygiene_entry_count": int(
            _as_dict(p0a_environment_checklist.get("env_file_hygiene")).get("entry_count") or 0
        ),
        "env_file_hygiene_ready": env_summary.get("env_file_hygiene_ready") is True,
        "env_file_hygiene_error_count": int(env_summary.get("env_file_hygiene_error_count") or 0),
        "env_file_hygiene_warning_count": int(env_summary.get("env_file_hygiene_warning_count") or 0),
        "redaction_policy": {
            "raw_secret_values_allowed": redaction.get("raw_secret_values_allowed") is True,
            "forbidden_exact_secret_fields_redacted": redaction.get("forbidden_exact_secret_fields_redacted") is True,
            "credential_items_redacted": all(
                _as_dict(item).get("secret_redacted") is True
                for item in _as_list(credential_handoff.get("credential_items"))
            ),
        },
    }


def _p0a_real_batches_group(p0a_execution_checklist: dict[str, Any], work_items: list[dict[str, Any]]) -> dict[str, Any]:
    phase_handoff = _as_dict(p0a_execution_checklist.get("real_batch_phase_handoff"))
    ready = phase_handoff.get("ready") is True
    verification_commands = _unique_strings(
        [
            "make au-p0a-real-batch-fulfillment",
            "make verify-au-p0a-real-batch-fulfillment",
            (
                "PYTHONPATH=packages/geo_core:apps/api python3 "
                "scripts/verify_au_p0a_real_batch_fulfillment.py "
                "${GEO_AU_P0A_REAL_BATCH_FULFILLMENT_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-real-batch-fulfillment-latest.json} "
                "--require-fulfilled"
            ),
            "make au-p0a-status",
            "make verify-au-p0a-status",
            "make au-p0a-execution-checklist",
            "make verify-au-p0a-execution-checklist",
            (
                "PYTHONPATH=packages/geo_core:apps/api python3 "
                "scripts/verify_au_p0a_execution_checklist.py "
                "${GEO_AU_P0A_EXECUTION_CHECKLIST_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-execution-checklist-latest.json} "
                "--require-design-partner-ready"
            ),
        ]
    )
    evidence_outputs = _unique_strings(
        _strings(phase_handoff.get("evidence_outputs"))
        + [
            "docs/runtime_preflight/au-p0a-real-batch-fulfillment-latest.json",
            "docs/runtime_preflight/au-p0a-status-latest.json",
            "docs/runtime_preflight/au-p0a-execution-checklist-latest.json",
        ]
    )
    return {
        "id": "p0a_real_batches",
        "stage": "P0a",
        "title": "P0a provider preflight, small batch, and full batch",
        "status": "ready" if ready else "pending_after_external_input",
        "external_dependency": True,
        "dependency_class": "provider_api_execution",
        "ready": ready,
        "work_item_ids": _matching_work_item_ids(work_items, ["p0a_preflight", "p0a_small_batch", "p0a_full_batch"]),
        "next_phase": str(phase_handoff.get("next_phase") or ""),
        "phase_order": _strings(phase_handoff.get("phase_order")),
        "phase_count": int(phase_handoff.get("phase_count") or 0),
        "ready_phase_count": int(phase_handoff.get("ready_phase_count") or 0),
        "blocked_phase_count": int(phase_handoff.get("blocked_phase_count") or 0),
        "total_planned_runs": int(phase_handoff.get("total_planned_runs") or 0),
        "phases": _as_list(phase_handoff.get("phases")),
        "verification_commands": verification_commands,
        "evidence_outputs": evidence_outputs,
        "redaction_policy": _as_dict(phase_handoff.get("redaction_policy")),
    }


def _p0b_google_environment_group(p0b_google_execution_checklist: dict[str, Any], work_items: list[dict[str, Any]]) -> dict[str, Any]:
    environment_handoff = _as_dict(p0b_google_execution_checklist.get("environment_handoff"))
    redaction = _as_dict(environment_handoff.get("redaction_policy"))
    ready = environment_handoff.get("ready") is True
    verification_commands = _unique_strings(
        _commands(environment_handoff.get("verification_commands"))
        + [
            "make au-p0b-google-environment-fulfillment",
            "make verify-au-p0b-google-environment-fulfillment",
            (
                "PYTHONPATH=packages/geo_core:apps/api python3 "
                "scripts/verify_au_p0b_google_environment_fulfillment.py "
                "${GEO_AU_P0B_GOOGLE_ENVIRONMENT_FULFILLMENT_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-environment-fulfillment-latest.json} "
                "--require-fulfilled"
            ),
        ]
    )
    evidence_outputs = _unique_strings(
        _strings(environment_handoff.get("evidence_outputs"))
        + ["docs/runtime_preflight/au-p0b-google-environment-fulfillment-latest.json"]
    )
    return {
        "id": "p0b_google_environment",
        "stage": "P0b",
        "title": "Google Playwright selectors, session inputs, database, and manual path",
        "status": "ready" if ready else "requires_external_input",
        "external_dependency": True,
        "dependency_class": "google_ui_selectors_session_and_database",
        "ready": ready,
        "work_item_ids": _matching_work_item_ids(work_items, ["p0b_google_playwright_env"]),
        "target_env_file": str(environment_handoff.get("target_env_file") or ""),
        "missing_required_count": int(environment_handoff.get("missing_required_count") or 0),
        "missing_required": _strings(environment_handoff.get("missing_required")),
        "setup_commands": _commands(environment_handoff.get("setup_commands")),
        "verification_commands": verification_commands,
        "evidence_outputs": evidence_outputs,
        "environment_items": _as_list(environment_handoff.get("environment_items")),
        "selector_items": _as_list(environment_handoff.get("selector_items")),
        "file_items": _as_list(environment_handoff.get("file_items")),
        "dependency_items": _as_list(environment_handoff.get("dependency_items")),
        "redaction_policy": {
            "raw_secret_values_allowed": redaction.get("raw_secret_values_allowed") is True,
            "forbidden_exact_secret_fields_redacted": redaction.get("forbidden_exact_secret_fields_redacted") is True,
        },
    }


def _p0b_google_manual_backfill_group(
    p0b_google_execution_checklist: dict[str, Any],
    work_items: list[dict[str, Any]],
    *,
    manual_backfill_fulfillment: dict[str, Any] | None = None,
    manual_backfill_fulfillment_verifier: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manual_handoff = _as_dict(p0b_google_execution_checklist.get("manual_backfill_handoff"))
    fulfillment_summary = _as_dict(_as_dict(manual_backfill_fulfillment).get("summary"))
    redaction = _as_dict(manual_handoff.get("redaction_policy"))
    ready = manual_handoff.get("ready") is True
    fulfillment_hash = str(
        _as_dict(manual_backfill_fulfillment).get("p0b_google_manual_backfill_fulfillment_hash") or ""
    )
    fulfillment_available = bool(manual_backfill_fulfillment)
    fulfillment_verified = (
        _as_dict(manual_backfill_fulfillment_verifier).get("status") == "pass"
        and _as_dict(manual_backfill_fulfillment_verifier).get("hash_valid") is True
    )
    record_count = _int(_first_present(fulfillment_summary, manual_handoff, "record_count"))
    covered_prompt_city_count = _int(_first_present(fulfillment_summary, manual_handoff, "covered_prompt_city_count"))
    expected_record_count = _int(_first_present(fulfillment_summary, manual_handoff, "expected_record_count"))
    expected_prompt_city_count = _int(_first_present(fulfillment_summary, manual_handoff, "expected_prompt_city_count"))
    expected_sample_size = _int(_first_present(fulfillment_summary, manual_handoff, "expected_sample_size"))
    missing_required = _strings(fulfillment_summary.get("missing_required"))
    verification_commands = _unique_strings(
        _commands(manual_handoff.get("verification_commands"))
        + [
            "make au-p0b-google-manual-backfill-fulfillment",
            "make verify-au-p0b-google-manual-backfill-fulfillment",
            (
                "PYTHONPATH=packages/geo_core:apps/api python3 "
                "scripts/verify_au_p0b_google_manual_backfill_fulfillment.py "
                "${GEO_AU_P0B_GOOGLE_MANUAL_BACKFILL_FULFILLMENT_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-manual-backfill-fulfillment-latest.json} "
                "--require-fulfilled"
            ),
        ]
    )
    evidence_outputs = _unique_strings(
        _strings(manual_handoff.get("evidence_outputs"))
        + ["docs/runtime_preflight/au-p0b-google-manual-backfill-fulfillment-latest.json"]
    )
    return {
        "id": "p0b_google_manual_backfill",
        "stage": "P0b",
        "title": "Google AI Mode 120-row manual backfill JSONL",
        "status": "ready" if ready else "requires_external_input",
        "external_dependency": True,
        "dependency_class": "manual_google_ai_mode_sampling",
        "ready": ready,
        "work_item_ids": _matching_work_item_ids(work_items, ["p0b_google_manual_backfill"]),
        "missing_reason_count": int(manual_handoff.get("missing_reason_count") or 0),
        "missing_reasons": _strings(manual_handoff.get("missing_reasons")),
        "manual_jsonl_env_var": str(manual_handoff.get("manual_jsonl_env_var") or ""),
        "target_jsonl_path": str(manual_handoff.get("target_jsonl_path") or ""),
        "template_path": str(manual_handoff.get("template_path") or ""),
        "template_manifest_path": str(manual_handoff.get("template_manifest_path") or ""),
        "verification_path": str(fulfillment_summary.get("verification_path") or manual_handoff.get("verification_path") or ""),
        "expected_record_count": expected_record_count,
        "record_count": record_count,
        "expected_prompt_city_count": expected_prompt_city_count,
        "covered_prompt_city_count": covered_prompt_city_count,
        "expected_sample_size": expected_sample_size,
        "prompt_count": int(manual_handoff.get("prompt_count") or 0),
        "geo_cities": _strings(manual_handoff.get("geo_cities")),
        "file_sha256": str(
            _as_dict(_as_dict(manual_backfill_fulfillment).get("source_p0b_google_manual_backfill_verification")).get(
                "file_sha256"
            )
            or manual_handoff.get("file_sha256")
            or ""
        ),
        "verification_hash": str(
            _as_dict(_as_dict(manual_backfill_fulfillment).get("source_p0b_google_manual_backfill_verification")).get(
                "verification_hash"
            )
            or manual_handoff.get("verification_hash")
            or ""
        ),
        "fulfillment_available": fulfillment_available,
        "fulfillment_verified": fulfillment_verified,
        "manual_backfill_fulfilled": _as_dict(manual_backfill_fulfillment).get("manual_backfill_fulfilled") is True,
        "manual_backfill_fulfillment_hash": fulfillment_hash,
        "manual_backfill_fulfillment_missing_required_count": _int(
            fulfillment_summary.get("missing_required_count")
        ),
        "manual_backfill_fulfillment_missing_required": missing_required,
        "manual_backfill_verification_status": str(
            fulfillment_summary.get("manual_backfill_verification_status") or ""
        ),
        "required_fields": _strings(manual_handoff.get("required_fields")),
        "operator_requirements": _strings(manual_handoff.get("operator_requirements")),
        "setup_commands": _commands(manual_handoff.get("setup_commands")),
        "verification_commands": verification_commands,
        "evidence_outputs": evidence_outputs,
        "redaction_policy": {
            "raw_answer_values_allowed": redaction.get("raw_answer_values_allowed") is True,
            "raw_citation_values_allowed": redaction.get("raw_citation_values_allowed") is True,
            "raw_asset_urls_allowed": redaction.get("raw_asset_urls_allowed") is True,
            "manual_jsonl_path_redacted": redaction.get("manual_jsonl_path_redacted") is True,
        },
    }


def _p0b_google_phase_execution_group(
    p0b_google_execution_checklist: dict[str, Any],
    work_items: list[dict[str, Any]],
) -> dict[str, Any]:
    phase_handoff = _as_dict(p0b_google_execution_checklist.get("google_spike_phase_handoff"))
    ready = phase_handoff.get("ready") is True
    verification_commands = _unique_strings(
        _commands(phase_handoff.get("verification_commands"))
        + [
            "make au-p0b-google-phase-execution-fulfillment",
            "make verify-au-p0b-google-phase-execution-fulfillment",
            (
                "PYTHONPATH=packages/geo_core:apps/api python3 "
                "scripts/verify_au_p0b_google_phase_execution_fulfillment.py "
                "${GEO_AU_P0B_GOOGLE_PHASE_EXECUTION_FULFILLMENT_OUTPUT_PATH:-docs/runtime_preflight/au-p0b-google-phase-execution-fulfillment-latest.json} "
                "--require-fulfilled"
            ),
        ]
    )
    evidence_outputs = _unique_strings(
        _strings(phase_handoff.get("evidence_outputs"))
        + ["docs/runtime_preflight/au-p0b-google-phase-execution-fulfillment-latest.json"]
    )
    return {
        "id": "p0b_google_phase_execution",
        "stage": "P0b",
        "title": "Google browser/manual health, full spike, and main scoring phases",
        "status": "ready" if ready else "pending_after_external_input",
        "external_dependency": True,
        "dependency_class": "google_browser_manual_spike_execution",
        "ready": ready,
        "work_item_ids": _matching_work_item_ids(
            work_items,
            [
                "p0b_google_playwright_smoke",
                "p0b_google_spike_health",
                "p0b_google_full_spike",
            ],
        ),
        "next_phase": str(phase_handoff.get("next_phase") or ""),
        "phase_order": _strings(phase_handoff.get("phase_order")),
        "phase_count": int(phase_handoff.get("phase_count") or 0),
        "ready_phase_count": int(phase_handoff.get("ready_phase_count") or 0),
        "blocked_phase_count": int(phase_handoff.get("blocked_phase_count") or 0),
        "full_spike_planned_runs": int(phase_handoff.get("full_spike_planned_runs") or 0),
        "manual_expected_record_count": int(phase_handoff.get("manual_expected_record_count") or 0),
        "phases": _as_list(phase_handoff.get("phases")),
        "verification_commands": verification_commands,
        "evidence_outputs": evidence_outputs,
        "redaction_policy": _as_dict(phase_handoff.get("redaction_policy")),
    }


def _handoff_posture(*, structural_ready: bool, external_ready: bool, external_blockers: int) -> str:
    if not structural_ready:
        return "external_dependency_handoff_not_verified"
    if external_ready:
        return "external_dependencies_cleared"
    if external_blockers > 0:
        return "blocked_external_dependencies"
    return "blocked_followup"


def build_au_external_dependency_handoff(
    *,
    launch_status_path: Path = Path(DEFAULT_LAUNCH_STATUS_PATH),
    remediation_plan_path: Path = Path(DEFAULT_REMEDIATION_PLAN_PATH),
    p0a_environment_checklist_path: Path = Path(DEFAULT_P0A_ENVIRONMENT_CHECKLIST_PATH),
    p0a_execution_checklist_path: Path = Path(DEFAULT_P0A_EXECUTION_CHECKLIST_PATH),
    p0b_google_execution_checklist_path: Path = Path(DEFAULT_P0B_GOOGLE_EXECUTION_CHECKLIST_PATH),
    p0b_google_manual_backfill_fulfillment_path: Path | None = None,
    launch_status: dict[str, Any] | None = None,
    remediation_plan: dict[str, Any] | None = None,
    p0a_environment_checklist: dict[str, Any] | None = None,
    p0a_execution_checklist: dict[str, Any] | None = None,
    p0b_google_execution_checklist: dict[str, Any] | None = None,
    p0b_google_manual_backfill_fulfillment: dict[str, Any] | None = None,
    output_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if launch_status is None:
        launch_status, launch_source = _load_or_build_launch_status(launch_status_path, generated_at=generated_at)
    else:
        launch_source = {"path": str(launch_status_path), "exists": True, "source": "provided_payload", "errors": []}
    if remediation_plan is None:
        remediation_plan, remediation_source = _load_or_build_remediation_plan(
            remediation_plan_path,
            launch_status=launch_status,
            launch_status_path=launch_status_path,
            generated_at=generated_at,
        )
    else:
        remediation_source = {
            "path": str(remediation_plan_path),
            "exists": True,
            "source": "provided_payload",
            "errors": [],
        }
    if p0a_environment_checklist is None:
        p0a_environment_checklist, p0a_environment_source = _load_or_build_p0a_environment_checklist(
            p0a_environment_checklist_path,
            generated_at=generated_at,
        )
    else:
        p0a_environment_source = {
            "path": str(p0a_environment_checklist_path),
            "exists": True,
            "source": "provided_payload",
            "errors": [],
        }
    if p0a_execution_checklist is None:
        p0a_execution_checklist, p0a_execution_source = _load_or_build_p0a_execution_checklist(
            p0a_execution_checklist_path,
            generated_at=generated_at,
        )
    else:
        p0a_execution_source = {
            "path": str(p0a_execution_checklist_path),
            "exists": True,
            "source": "provided_payload",
            "errors": [],
        }
    if p0b_google_execution_checklist is None:
        p0b_google_execution_checklist, p0b_google_source = _load_or_build_p0b_google_execution_checklist(
            p0b_google_execution_checklist_path,
            generated_at=generated_at,
        )
    else:
        p0b_google_source = {
            "path": str(p0b_google_execution_checklist_path),
            "exists": True,
            "source": "provided_payload",
            "errors": [],
        }
    (
        p0b_google_manual_backfill_fulfillment,
        p0b_manual_fulfillment_source,
    ) = _load_optional_p0b_manual_backfill_fulfillment(
        p0b_google_manual_backfill_fulfillment_path,
        p0b_google_manual_backfill_fulfillment,
    )

    launch_verifier = verify_au_launch_status(launch_status, path=launch_status_path)
    remediation_verifier = verify_au_launch_remediation_plan(remediation_plan, path=remediation_plan_path)
    p0a_environment_verifier = verify_au_p0a_environment_checklist(
        p0a_environment_checklist,
        path=p0a_environment_checklist_path,
    )
    p0a_execution_verifier = verify_au_p0a_execution_checklist(
        p0a_execution_checklist,
        path=p0a_execution_checklist_path,
    )
    p0b_google_verifier = verify_au_p0b_google_execution_checklist(
        p0b_google_execution_checklist,
        path=p0b_google_execution_checklist_path,
    )
    p0b_manual_fulfillment_verifier = (
        verify_au_p0b_google_manual_backfill_fulfillment(
            p0b_google_manual_backfill_fulfillment,
            path=p0b_google_manual_backfill_fulfillment_path,
        )
        if p0b_google_manual_backfill_fulfillment is not None
        else {
            "status": "skip",
            "hash_valid": False,
            "manual_backfill_fulfillment_ready": False,
            "errors": _strings(p0b_manual_fulfillment_source.get("errors")),
        }
    )
    source_verifiers = {
        "launch_status": _verifier_summary(launch_verifier),
        "remediation_plan": _verifier_summary(remediation_verifier),
        "p0a_environment_checklist": _verifier_summary(p0a_environment_verifier),
        "p0a_execution_checklist": _verifier_summary(p0a_execution_verifier),
        "p0b_google_execution_checklist": _verifier_summary(p0b_google_verifier),
    }
    if p0b_google_manual_backfill_fulfillment is not None:
        source_verifiers["p0b_google_manual_backfill_fulfillment"] = _verifier_summary(
            p0b_manual_fulfillment_verifier
        )
    structural_ready = all(
        verifier.get("status") == "pass" and verifier.get("hash_valid") is True
        for verifier in source_verifiers.values()
    ) and int(_as_dict(remediation_plan.get("summary")).get("unmapped_blocker_count") or 0) == 0

    source_work_items = [_as_dict(item) for item in _as_list(remediation_plan.get("work_items"))]
    work_items = [_work_item_summary(item) for item in source_work_items if item.get("external_dependency") is True]
    local_followup_items = [
        _work_item_summary(item) for item in source_work_items if item.get("external_dependency") is not True
    ]
    blocker_remediations = [_as_dict(item) for item in _as_list(remediation_plan.get("blocker_remediations"))]
    remediation_summary = _as_dict(remediation_plan.get("summary"))
    external_dependency_blocker_count = sum(1 for item in blocker_remediations if item.get("external_dependency") is True)
    next_dependency_item = next(
        (item for item in work_items if item.get("id") == remediation_plan.get("next_work_item_id")),
        work_items[0] if work_items else {"id": "none"},
    )
    dependency_groups = [
        _p0a_provider_credentials_group(p0a_environment_checklist, p0a_execution_checklist, work_items),
        _p0a_real_batches_group(p0a_execution_checklist, work_items),
        _p0b_google_environment_group(p0b_google_execution_checklist, work_items),
        _p0b_google_manual_backfill_group(
            p0b_google_execution_checklist,
            work_items,
            manual_backfill_fulfillment=p0b_google_manual_backfill_fulfillment,
            manual_backfill_fulfillment_verifier=p0b_manual_fulfillment_verifier,
        ),
        _p0b_google_phase_execution_group(p0b_google_execution_checklist, work_items),
    ]
    dependency_groups = [_with_group_execution_fields(group, work_items) for group in dependency_groups]
    external_ready = (
        structural_ready
        and external_dependency_blocker_count == 0
        and all(group.get("ready") is True for group in dependency_groups)
    )
    clearance_sequence = _build_clearance_sequence(
        dependency_groups,
        work_items,
        external_ready=external_ready,
        customer_ready=launch_status.get("ready_for_customer_report_handoff") is True,
    )
    requires_external_input_count = sum(1 for item in work_items if item.get("status") == "requires_external_input")
    pending_after_count = sum(1 for item in work_items if str(item.get("status") or "").startswith("pending_after"))
    runnable_now = [str(item.get("id")) for item in work_items if item.get("status") == "runnable_now"]
    p0a_credentials = _as_dict(p0a_execution_checklist.get("credential_handoff"))
    p0a_phase = _as_dict(p0a_execution_checklist.get("real_batch_phase_handoff"))
    p0a_summary = _as_dict(p0a_execution_checklist.get("summary"))
    p0b_environment = _as_dict(p0b_google_execution_checklist.get("environment_handoff"))
    p0b_manual = _as_dict(next((group for group in dependency_groups if group.get("id") == "p0b_google_manual_backfill"), {}))
    p0b_phase = _as_dict(p0b_google_execution_checklist.get("google_spike_phase_handoff"))
    p0b_summary = _as_dict(p0b_google_execution_checklist.get("summary"))
    p0b_required_input_missing_count = int(p0b_environment.get("missing_required_count") or 0) + int(
        p0b_manual.get("missing_reason_count") or 0
    )

    handoff: dict[str, Any] = {
        "external_dependency_handoff_version": HANDOFF_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if structural_ready else "fail",
        "external_dependency_handoff_ready": external_ready,
        "ready_for_customer_report_handoff": launch_status.get("ready_for_customer_report_handoff") is True,
        "output_path": str(output_path) if output_path else "",
        "next_dependency_item_id": str(next_dependency_item.get("id") or "none"),
        "summary": {
            "handoff_posture": _handoff_posture(
                structural_ready=structural_ready,
                external_ready=external_ready,
                external_blockers=external_dependency_blocker_count,
            ),
            "structural_ready": structural_ready,
            "external_dependency_handoff_ready": external_ready,
            "ready_for_customer_report_handoff": launch_status.get("ready_for_customer_report_handoff") is True,
            "blocker_count": int(remediation_summary.get("blocker_count") or 0),
            "covered_blocker_count": int(remediation_summary.get("covered_blocker_count") or 0),
            "unmapped_blocker_count": int(remediation_summary.get("unmapped_blocker_count") or 0),
            "all_blockers_mapped": int(remediation_summary.get("unmapped_blocker_count") or 0) == 0,
            "source_work_item_count": int(remediation_summary.get("work_item_count") or 0),
            "work_item_count": len(work_items),
            "local_followup_work_item_count": len(local_followup_items),
            "dependency_group_count": len(dependency_groups),
            "clearance_step_count": int(clearance_sequence.get("step_count") or 0),
            "clearance_ready_step_count": int(clearance_sequence.get("ready_step_count") or 0),
            "clearance_blocked_step_count": int(clearance_sequence.get("blocked_step_count") or 0),
            "clearance_current_step_id": str(clearance_sequence.get("current_step_id") or "none"),
            "external_dependency_blocker_count": external_dependency_blocker_count,
            "requires_external_input_work_item_count": requires_external_input_count,
            "pending_after_external_input_work_item_count": pending_after_count,
            "runnable_now_work_item_count": len(runnable_now),
            "runnable_now_work_items": runnable_now,
            "next_dependency_item_id": str(next_dependency_item.get("id") or "none"),
            "next_command": str(clearance_sequence.get("next_command") or ""),
            "p0a_required_secret_missing_count": int(p0a_credentials.get("missing_required_count") or 0),
            "p0a_required_secret_missing": _strings(p0a_credentials.get("missing_required")),
            "p0a_execution_remaining_blocker_count": int(p0a_summary.get("remaining_blocker_count") or 0),
            "p0a_real_batch_phase_next_phase": str(p0a_phase.get("next_phase") or ""),
            "p0a_real_batch_blocked_phase_count": int(p0a_phase.get("blocked_phase_count") or 0),
            "p0a_real_batch_total_planned_runs": int(p0a_phase.get("total_planned_runs") or 0),
            "p0b_google_required_input_missing_count": p0b_required_input_missing_count,
            "p0b_google_environment_missing_required_count": int(p0b_environment.get("missing_required_count") or 0),
            "p0b_google_manual_backfill_missing_reason_count": int(p0b_manual.get("missing_reason_count") or 0),
            "p0b_google_manual_backfill_record_count": int(p0b_manual.get("record_count") or 0),
            "p0b_google_manual_backfill_expected_record_count": int(
                p0b_manual.get("expected_record_count") or 0
            ),
            "p0b_google_manual_backfill_covered_prompt_city_count": int(
                p0b_manual.get("covered_prompt_city_count") or 0
            ),
            "p0b_google_manual_backfill_expected_prompt_city_count": int(
                p0b_manual.get("expected_prompt_city_count") or 0
            ),
            "p0b_google_manual_backfill_fulfillment_available": p0b_manual.get("fulfillment_available") is True,
            "p0b_google_manual_backfill_fulfillment_verified": p0b_manual.get("fulfillment_verified") is True,
            "p0b_google_manual_backfill_fulfillment_hash": str(
                p0b_manual.get("manual_backfill_fulfillment_hash") or ""
            ),
            "p0b_google_manual_backfill_fulfillment_missing_required_count": int(
                p0b_manual.get("manual_backfill_fulfillment_missing_required_count") or 0
            ),
            "p0b_google_remaining_blocker_count": int(p0b_summary.get("remaining_blocker_count") or 0),
            "p0b_google_phase_next_phase": str(p0b_phase.get("next_phase") or ""),
            "p0b_google_phase_blocked_phase_count": int(p0b_phase.get("blocked_phase_count") or 0),
            "p0b_google_full_spike_planned_runs": int(p0b_phase.get("full_spike_planned_runs") or 0),
        },
        "source_paths": {
            "launch_status": str(launch_status_path),
            "remediation_plan": str(remediation_plan_path),
            "p0a_environment_checklist": str(p0a_environment_checklist_path),
            "p0a_execution_checklist": str(p0a_execution_checklist_path),
            "p0b_google_execution_checklist": str(p0b_google_execution_checklist_path),
            "p0b_google_manual_backfill_fulfillment": str(p0b_google_manual_backfill_fulfillment_path or ""),
        },
        "source_loaders": {
            "launch_status": launch_source,
            "remediation_plan": remediation_source,
            "p0a_environment_checklist": p0a_environment_source,
            "p0a_execution_checklist": p0a_execution_source,
            "p0b_google_execution_checklist": p0b_google_source,
            "p0b_google_manual_backfill_fulfillment": p0b_manual_fulfillment_source,
        },
        "source_verifiers": source_verifiers,
        "source_artifacts": [
            _source_file_entry("launch_status", launch_status_path),
            _source_file_entry("remediation_plan", remediation_plan_path),
            _source_file_entry("p0a_environment_checklist", p0a_environment_checklist_path),
            _source_file_entry("p0a_execution_checklist", p0a_execution_checklist_path),
            _source_file_entry("p0b_google_execution_checklist", p0b_google_execution_checklist_path),
            *(
                [_source_file_entry("p0b_google_manual_backfill_fulfillment", p0b_google_manual_backfill_fulfillment_path)]
                if p0b_google_manual_backfill_fulfillment_path is not None
                and p0b_google_manual_backfill_fulfillment_path.exists()
                else []
            ),
        ],
        "dependency_groups": dependency_groups,
        "clearance_sequence": clearance_sequence,
        "work_items": work_items,
        "local_followup_items": local_followup_items,
        "operator_sequence": [str(item.get("id")) for item in work_items],
        "next_dependency_item": next_dependency_item,
        "blocker_remediations": blocker_remediations,
        "redaction_policy": {
            "raw_secret_values_allowed": False,
            "raw_database_url_allowed": False,
            "raw_selector_values_allowed": False,
            "raw_manual_answer_values_allowed": False,
            "raw_citation_values_allowed": False,
            "raw_asset_urls_allowed": False,
            "forbidden_exact_fields": [
                "value",
                "raw_value",
                "database_url",
                "selector_value",
                "answer_text",
                "citation_urls",
                "screenshot_url",
                "html_snapshot_url",
            ],
            "recorded_fields": [
                "present",
                "source",
                "truthy",
                "value_length",
                "sha256_prefix",
                "exists",
                "is_file",
                "is_dir",
                "hash_valid",
                "ready",
                "counts",
                "file_sha256",
                "verification_hash",
            ],
        },
        "current_boundary": [
            "This handoff proves the current AU external dependency blockers are mapped to ordered work items and redacted evidence.",
            "It does not prove provider keys, runtime database connectivity, Google selectors, Google sessions, manual JSONL rows, or real provider/browser runs are complete.",
            "Use --require-ready on the verifier only after P0a/P0b external inputs and their hard gates are actually green.",
        ],
    }
    handoff["external_dependency_handoff_hash"] = compute_external_dependency_handoff_hash(handoff)
    return handoff


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU external dependency handoff JSON")
    parser.add_argument(
        "--launch-status-path",
        default=os.environ.get("GEO_AU_LAUNCH_STATUS_OUTPUT_PATH", DEFAULT_LAUNCH_STATUS_PATH),
        help="Path to the AU launch status JSON.",
    )
    parser.add_argument(
        "--remediation-plan-path",
        default=os.environ.get("GEO_AU_LAUNCH_REMEDIATION_PLAN_OUTPUT_PATH", DEFAULT_REMEDIATION_PLAN_PATH),
        help="Path to the AU launch remediation plan JSON.",
    )
    parser.add_argument(
        "--p0a-environment-checklist-path",
        default=os.environ.get("GEO_AU_P0A_ENVIRONMENT_CHECKLIST_OUTPUT_PATH", DEFAULT_P0A_ENVIRONMENT_CHECKLIST_PATH),
        help="Path to the AU P0a environment checklist JSON.",
    )
    parser.add_argument(
        "--p0a-execution-checklist-path",
        default=os.environ.get("GEO_AU_P0A_EXECUTION_CHECKLIST_OUTPUT_PATH", DEFAULT_P0A_EXECUTION_CHECKLIST_PATH),
        help="Path to the AU P0a execution checklist JSON.",
    )
    parser.add_argument(
        "--p0b-google-execution-checklist-path",
        default=os.environ.get(
            "GEO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH",
            DEFAULT_P0B_GOOGLE_EXECUTION_CHECKLIST_PATH,
        ),
        help="Path to the AU P0b Google execution checklist JSON.",
    )
    parser.add_argument(
        "--p0b-google-manual-backfill-fulfillment-path",
        default=os.environ.get(
            "GEO_AU_P0B_GOOGLE_MANUAL_BACKFILL_FULFILLMENT_OUTPUT_PATH",
            DEFAULT_P0B_GOOGLE_MANUAL_BACKFILL_FULFILLMENT_PATH,
        ),
        help="Optional path to the AU P0b Google manual backfill fulfillment JSON.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GEO_AU_EXTERNAL_DEPENDENCY_HANDOFF_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU external dependency handoff JSON.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    handoff = build_au_external_dependency_handoff(
        launch_status_path=Path(args.launch_status_path),
        remediation_plan_path=Path(args.remediation_plan_path),
        p0a_environment_checklist_path=Path(args.p0a_environment_checklist_path),
        p0a_execution_checklist_path=Path(args.p0a_execution_checklist_path),
        p0b_google_execution_checklist_path=Path(args.p0b_google_execution_checklist_path),
        p0b_google_manual_backfill_fulfillment_path=Path(args.p0b_google_manual_backfill_fulfillment_path),
        output_path=output_path,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(handoff, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(handoff, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if handoff["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
