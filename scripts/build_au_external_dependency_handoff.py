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
from scripts.verify_au_p0a_environment_checklist import verify_au_p0a_environment_checklist  # noqa: E402
from scripts.verify_au_p0a_execution_checklist import verify_au_p0a_execution_checklist  # noqa: E402
from scripts.verify_au_p0b_google_execution_checklist import verify_au_p0b_google_execution_checklist  # noqa: E402


HANDOFF_VERSION = "au_external_dependency_handoff_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-external-dependency-handoff-latest.json"


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


def _p0a_provider_credentials_group(
    p0a_environment_checklist: dict[str, Any],
    p0a_execution_checklist: dict[str, Any],
    work_items: list[dict[str, Any]],
) -> dict[str, Any]:
    credential_handoff = _as_dict(p0a_execution_checklist.get("credential_handoff"))
    env_summary = _as_dict(p0a_environment_checklist.get("summary"))
    redaction = _as_dict(credential_handoff.get("redaction_policy"))
    ready = credential_handoff.get("ready") is True
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
        "verification_commands": _commands(credential_handoff.get("verification_commands")),
        "evidence_outputs": _strings(credential_handoff.get("evidence_outputs")),
        "credential_items": _as_list(credential_handoff.get("credential_items")),
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
        "redaction_policy": _as_dict(phase_handoff.get("redaction_policy")),
    }


def _p0b_google_environment_group(p0b_google_execution_checklist: dict[str, Any], work_items: list[dict[str, Any]]) -> dict[str, Any]:
    environment_handoff = _as_dict(p0b_google_execution_checklist.get("environment_handoff"))
    redaction = _as_dict(environment_handoff.get("redaction_policy"))
    ready = environment_handoff.get("ready") is True
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
        "verification_commands": _commands(environment_handoff.get("verification_commands")),
        "evidence_outputs": _strings(environment_handoff.get("evidence_outputs")),
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
) -> dict[str, Any]:
    manual_handoff = _as_dict(p0b_google_execution_checklist.get("manual_backfill_handoff"))
    redaction = _as_dict(manual_handoff.get("redaction_policy"))
    ready = manual_handoff.get("ready") is True
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
        "verification_path": str(manual_handoff.get("verification_path") or ""),
        "expected_record_count": int(manual_handoff.get("expected_record_count") or 0),
        "record_count": int(manual_handoff.get("record_count") or 0),
        "expected_prompt_city_count": int(manual_handoff.get("expected_prompt_city_count") or 0),
        "covered_prompt_city_count": int(manual_handoff.get("covered_prompt_city_count") or 0),
        "expected_sample_size": int(manual_handoff.get("expected_sample_size") or 0),
        "prompt_count": int(manual_handoff.get("prompt_count") or 0),
        "geo_cities": _strings(manual_handoff.get("geo_cities")),
        "file_sha256": str(manual_handoff.get("file_sha256") or ""),
        "verification_hash": str(manual_handoff.get("verification_hash") or ""),
        "required_fields": _strings(manual_handoff.get("required_fields")),
        "operator_requirements": _strings(manual_handoff.get("operator_requirements")),
        "setup_commands": _commands(manual_handoff.get("setup_commands")),
        "verification_commands": _commands(manual_handoff.get("verification_commands")),
        "evidence_outputs": _strings(manual_handoff.get("evidence_outputs")),
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
    launch_status: dict[str, Any] | None = None,
    remediation_plan: dict[str, Any] | None = None,
    p0a_environment_checklist: dict[str, Any] | None = None,
    p0a_execution_checklist: dict[str, Any] | None = None,
    p0b_google_execution_checklist: dict[str, Any] | None = None,
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
    source_verifiers = {
        "launch_status": _verifier_summary(launch_verifier),
        "remediation_plan": _verifier_summary(remediation_verifier),
        "p0a_environment_checklist": _verifier_summary(p0a_environment_verifier),
        "p0a_execution_checklist": _verifier_summary(p0a_execution_verifier),
        "p0b_google_execution_checklist": _verifier_summary(p0b_google_verifier),
    }
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
        _p0b_google_manual_backfill_group(p0b_google_execution_checklist, work_items),
        _p0b_google_phase_execution_group(p0b_google_execution_checklist, work_items),
    ]
    external_ready = (
        structural_ready
        and external_dependency_blocker_count == 0
        and all(group.get("ready") is True for group in dependency_groups)
    )
    requires_external_input_count = sum(1 for item in work_items if item.get("status") == "requires_external_input")
    pending_after_count = sum(1 for item in work_items if str(item.get("status") or "").startswith("pending_after"))
    runnable_now = [str(item.get("id")) for item in work_items if item.get("status") == "runnable_now"]
    p0a_credentials = _as_dict(p0a_execution_checklist.get("credential_handoff"))
    p0a_phase = _as_dict(p0a_execution_checklist.get("real_batch_phase_handoff"))
    p0a_summary = _as_dict(p0a_execution_checklist.get("summary"))
    p0b_environment = _as_dict(p0b_google_execution_checklist.get("environment_handoff"))
    p0b_manual = _as_dict(p0b_google_execution_checklist.get("manual_backfill_handoff"))
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
            "external_dependency_blocker_count": external_dependency_blocker_count,
            "requires_external_input_work_item_count": requires_external_input_count,
            "pending_after_external_input_work_item_count": pending_after_count,
            "runnable_now_work_item_count": len(runnable_now),
            "runnable_now_work_items": runnable_now,
            "next_dependency_item_id": str(next_dependency_item.get("id") or "none"),
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
        },
        "source_loaders": {
            "launch_status": launch_source,
            "remediation_plan": remediation_source,
            "p0a_environment_checklist": p0a_environment_source,
            "p0a_execution_checklist": p0a_execution_source,
            "p0b_google_execution_checklist": p0b_google_source,
        },
        "source_verifiers": source_verifiers,
        "source_artifacts": [
            _source_file_entry("launch_status", launch_status_path),
            _source_file_entry("remediation_plan", remediation_plan_path),
            _source_file_entry("p0a_environment_checklist", p0a_environment_checklist_path),
            _source_file_entry("p0a_execution_checklist", p0a_execution_checklist_path),
            _source_file_entry("p0b_google_execution_checklist", p0b_google_execution_checklist_path),
        ],
        "dependency_groups": dependency_groups,
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
        default=os.environ.get("GENO_AU_EXTERNAL_DEPENDENCY_HANDOFF_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
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
        output_path=output_path,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(handoff, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(handoff, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if handoff["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
