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

from scripts.build_au_p0b_google_execution_checklist import (  # noqa: E402
    CHECKLIST_VERSION,
    DEFAULT_MANUAL_BACKFILL_TEMPLATE_MANIFEST_PATH,
    DEFAULT_MANUAL_BACKFILL_TEMPLATE_PATH,
    DEFAULT_OUTPUT_PATH,
    compute_google_execution_checklist_hash,
)


REQUIRED_FIELDS = (
    "execution_checklist_version",
    "generated_at",
    "status",
    "google_execution_checklist_ready",
    "google_main_scoring_allowed",
    "limited_coverage",
    "next_action",
    "paths",
    "summary",
    "runbook_source",
    "runbook_verifier",
    "playwright_environment_source",
    "playwright_environment",
    "playwright_environment_verifier",
    "env_file_hygiene",
    "status_report_source",
    "status_report",
    "status_report_verifier",
    "package_source",
    "evidence_package",
    "evidence_package_verifier",
    "required_environment",
    "full_run_required_environment",
    "selector_groups",
    "file_checks",
    "dependency_checks",
    "environment_handoff",
    "manual_backfill_handoff",
    "setup_commands",
    "execution_commands",
    "verification_commands",
    "work_items",
    "evidence_outputs",
    "current_boundary",
    "google_execution_checklist_hash",
)


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _find_forbidden_secret_fields(value: object, *, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in {"value", "raw_value"}:
                findings.append(child_path)
            findings.extend(_find_forbidden_secret_fields(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_find_forbidden_secret_fields(child, path=f"{path}[{index}]"))
    return findings


def _command_ids(commands: list[object]) -> set[str]:
    return {str(_as_dict(item).get("id", "")) for item in commands}


def _validate_env_tasks(label: str, tasks: list[object], errors: list[str]) -> tuple[int, list[str]]:
    missing: list[str] = []
    for item in tasks:
        task = _as_dict(item)
        name = task.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"{label}_task_name_missing")
            continue
        for field in (
            "gate",
            "required",
            "present",
            "source",
            "value_length",
            "sha256_prefix",
            "secret_redacted",
            "action",
            "accepted_sources",
        ):
            if field not in task:
                errors.append(f"{label}_task_field_missing:{name}:{field}")
        if task.get("secret_redacted") is not True:
            errors.append(f"{label}_task_secret_redaction_missing:{name}")
        if task.get("source") not in {"process", "env_file", "missing"}:
            errors.append(f"{label}_task_source_invalid:{name}")
        if task.get("present") is True:
            if not isinstance(task.get("value_length"), int) or task.get("value_length") <= 0:
                errors.append(f"{label}_task_value_length_invalid:{name}")
            if not isinstance(task.get("sha256_prefix"), str) or len(task.get("sha256_prefix")) != 12:
                errors.append(f"{label}_task_sha256_prefix_invalid:{name}")
            if task.get("truthy") is False:
                missing.append(name)
        elif task.get("present") is False:
            missing.append(name)
            if task.get("value_length") not in {0, None}:
                errors.append(f"{label}_task_missing_value_length_invalid:{name}")
            if task.get("sha256_prefix") not in {"", None}:
                errors.append(f"{label}_task_missing_sha256_prefix_invalid:{name}")
        else:
            errors.append(f"{label}_task_present_invalid:{name}")
    return len(tasks), sorted(missing)


def _validate_selector_tasks(tasks: list[object], errors: list[str]) -> tuple[int, list[str]]:
    missing: list[str] = []
    for item in tasks:
        task = _as_dict(item)
        group = task.get("group")
        if not isinstance(group, str) or not group:
            errors.append("selector_group_name_missing")
            continue
        for field in (
            "candidate_names",
            "present",
            "selected_name",
            "source",
            "value_length",
            "sha256_prefix",
            "secret_redacted",
            "action",
        ):
            if field not in task:
                errors.append(f"selector_group_field_missing:{group}:{field}")
        if task.get("secret_redacted") is not True:
            errors.append(f"selector_group_secret_redaction_missing:{group}")
        if task.get("present") is True:
            if not task.get("selected_name"):
                errors.append(f"selector_group_selected_name_missing:{group}")
            if not isinstance(task.get("value_length"), int) or task.get("value_length") <= 0:
                errors.append(f"selector_group_value_length_invalid:{group}")
            if not isinstance(task.get("sha256_prefix"), str) or len(task.get("sha256_prefix")) != 12:
                errors.append(f"selector_group_sha256_prefix_invalid:{group}")
        elif task.get("present") is False:
            missing.append(group)
        else:
            errors.append(f"selector_group_present_invalid:{group}")
    return len(tasks), sorted(missing)


def _validate_dependency_tasks(tasks: list[object], errors: list[str]) -> list[str]:
    missing: list[str] = []
    for item in tasks:
        task = _as_dict(item)
        name = task.get("name")
        if not isinstance(name, str) or not name:
            errors.append("dependency_name_missing")
            continue
        if task.get("secret_redacted") is not True:
            errors.append(f"dependency_secret_redaction_missing:{name}")
        if task.get("present") is True:
            continue
        if task.get("present") is False:
            missing.append(name)
        else:
            errors.append(f"dependency_present_invalid:{name}")
    return sorted(missing)


def _validate_env_file_hygiene(hygiene: dict[str, Any], errors: list[str]) -> tuple[bool, list[str], list[str]]:
    required_fields = (
        "path",
        "exists",
        "loaded",
        "entry_count",
        "inside_workspace",
        "relative_path",
        "git_safe",
        "file_mode",
        "permission_safe",
        "hygiene_required",
        "hygiene_ready",
        "errors",
        "warnings",
        "verifier_ready",
        "verifier_errors",
        "secret_redacted",
    )
    for field in required_fields:
        if field not in hygiene:
            errors.append(f"env_file_hygiene_field_missing:{field}")
    if hygiene.get("secret_redacted") is not True:
        errors.append("env_file_hygiene_secret_redaction_missing")
    if "value" in hygiene or "raw_value" in hygiene:
        errors.append("env_file_hygiene_raw_value_leaked")
    if hygiene.get("hygiene_ready") is not True and hygiene.get("hygiene_ready") is not False:
        errors.append("env_file_hygiene_ready_invalid")
    if hygiene.get("hygiene_required") is not True and hygiene.get("hygiene_required") is not False:
        errors.append("env_file_hygiene_required_invalid")
    hygiene_errors = [str(item) for item in _as_list(hygiene.get("errors"))]
    hygiene_warnings = [str(item) for item in _as_list(hygiene.get("warnings"))]
    if sorted(str(item) for item in _as_list(hygiene.get("verifier_errors"))) != sorted(hygiene_errors):
        errors.append("env_file_hygiene_verifier_errors_mismatch")
    if hygiene.get("verifier_ready") is not (hygiene.get("hygiene_ready") is True):
        errors.append("env_file_hygiene_verifier_ready_mismatch")
    return hygiene.get("hygiene_ready") is True, hygiene_errors, hygiene_warnings


def _file_gate_issues(tasks: list[object]) -> list[str]:
    issues: list[str] = []
    for item in tasks:
        task = _as_dict(item)
        name = str(task.get("name", ""))
        expected_type = str(task.get("expected_type", ""))
        present = task.get("present") is True
        if name == "MANUAL_BACKFILL_PATH" and (not present or task.get("is_file") is not True):
            issues.append(f"{name}:file_missing")
        elif present and expected_type == "file" and task.get("is_file") is not True:
            issues.append(f"{name}:file_missing")
        elif present and expected_type == "directory" and task.get("is_dir") is not True:
            issues.append(f"{name}:directory_missing")
    return sorted(issues)


def _environment_handoff_missing(
    *,
    missing_required: list[str],
    missing_full_required: list[str],
    missing_selectors: list[str],
    missing_dependencies: list[str],
    file_issues: list[str],
    env_file_hygiene_ready: bool,
    env_file_hygiene_errors: list[str],
) -> list[str]:
    missing = [
        *[f"smoke_env:{name}" for name in missing_required],
        *[f"full_run_env:{name}" for name in missing_full_required],
        *[f"selector_group:{name}" for name in missing_selectors],
        *[f"dependency:{name}" for name in missing_dependencies],
    ]
    for issue in file_issues:
        if issue == "MANUAL_BACKFILL_PATH:file_missing" and "MANUAL_BACKFILL_PATH" in missing_full_required:
            continue
        missing.append(f"file_gate:{issue}")
    if not env_file_hygiene_ready:
        missing.extend([f"env_file_hygiene:{error}" for error in env_file_hygiene_errors] or ["env_file_hygiene:not_ready"])
    return sorted(missing)


def _validate_handoff_environment_items(tasks: list[object], errors: list[str]) -> tuple[int, list[str]]:
    missing: list[str] = []
    for item in tasks:
        task = _as_dict(item)
        name = task.get("name")
        if not isinstance(name, str) or not name:
            errors.append("environment_handoff_item_name_missing")
            continue
        for field in (
            "gate",
            "required",
            "present",
            "source",
            "owner_hint",
            "accepted_injection_methods",
            "env_file_key",
            "value_length",
            "sha256_prefix",
            "secret_redacted",
            "post_update_checks",
        ):
            if field not in task:
                errors.append(f"environment_handoff_item_field_missing:{name}:{field}")
        if task.get("secret_redacted") is not True:
            errors.append(f"environment_handoff_item_secret_redaction_missing:{name}")
        if task.get("env_file_key") != name:
            errors.append(f"environment_handoff_item_env_key_mismatch:{name}")
        accepted_methods = {str(value) for value in _as_list(task.get("accepted_injection_methods"))}
        if not {"process_environment", "GENO_AU_P0B_GOOGLE_ENV_FILE", ".env.au-p0b-google"}.issubset(
            accepted_methods
        ):
            errors.append(f"environment_handoff_item_injection_methods_incomplete:{name}")
        present = task.get("present")
        truthy = task.get("truthy")
        if present is True:
            if not isinstance(task.get("value_length"), int) or task.get("value_length") <= 0:
                errors.append(f"environment_handoff_item_value_length_invalid:{name}")
            if not isinstance(task.get("sha256_prefix"), str) or len(task.get("sha256_prefix")) != 12:
                errors.append(f"environment_handoff_item_sha256_prefix_invalid:{name}")
            if truthy is False:
                missing.append(name)
        elif present is False:
            missing.append(name)
        else:
            errors.append(f"environment_handoff_item_present_invalid:{name}")
    return len(tasks), sorted(missing)


def _validate_handoff_selector_items(tasks: list[object], errors: list[str]) -> tuple[int, list[str]]:
    missing: list[str] = []
    for item in tasks:
        task = _as_dict(item)
        group = task.get("group")
        if not isinstance(group, str) or not group:
            errors.append("environment_handoff_selector_group_missing")
            continue
        for field in (
            "candidate_names",
            "present",
            "selected_name",
            "source",
            "owner_hint",
            "accepted_injection_methods",
            "value_length",
            "sha256_prefix",
            "secret_redacted",
            "post_update_checks",
        ):
            if field not in task:
                errors.append(f"environment_handoff_selector_field_missing:{group}:{field}")
        if task.get("secret_redacted") is not True:
            errors.append(f"environment_handoff_selector_secret_redaction_missing:{group}")
        accepted_methods = {str(value) for value in _as_list(task.get("accepted_injection_methods"))}
        if not {"process_environment", "GENO_AU_P0B_GOOGLE_ENV_FILE", ".env.au-p0b-google"}.issubset(
            accepted_methods
        ):
            errors.append(f"environment_handoff_selector_injection_methods_incomplete:{group}")
        present = task.get("present")
        if present is True:
            if not task.get("selected_name"):
                errors.append(f"environment_handoff_selector_selected_name_missing:{group}")
            if not isinstance(task.get("value_length"), int) or task.get("value_length") <= 0:
                errors.append(f"environment_handoff_selector_value_length_invalid:{group}")
            if not isinstance(task.get("sha256_prefix"), str) or len(task.get("sha256_prefix")) != 12:
                errors.append(f"environment_handoff_selector_sha256_prefix_invalid:{group}")
        elif present is False:
            missing.append(group)
        else:
            errors.append(f"environment_handoff_selector_present_invalid:{group}")
    return len(tasks), sorted(missing)


def _validate_handoff_file_items(tasks: list[object], errors: list[str]) -> tuple[int, list[str]]:
    issues: list[str] = []
    for item in tasks:
        task = _as_dict(item)
        name = task.get("name")
        if not isinstance(name, str) or not name:
            errors.append("environment_handoff_file_name_missing")
            continue
        for field in (
            "expected_type",
            "present",
            "exists",
            "is_file",
            "is_dir",
            "source",
            "owner_hint",
            "accepted_injection_methods",
            "value_length",
            "sha256_prefix",
            "secret_redacted",
            "post_update_checks",
        ):
            if field not in task:
                errors.append(f"environment_handoff_file_field_missing:{name}:{field}")
        if task.get("secret_redacted") is not True:
            errors.append(f"environment_handoff_file_secret_redaction_missing:{name}")
        expected_type = str(task.get("expected_type", ""))
        present = task.get("present") is True
        if name == "MANUAL_BACKFILL_PATH" and (not present or task.get("is_file") is not True):
            issues.append(f"{name}:file_missing")
        elif present and expected_type == "file" and task.get("is_file") is not True:
            issues.append(f"{name}:file_missing")
        elif present and expected_type == "directory" and task.get("is_dir") is not True:
            issues.append(f"{name}:directory_missing")
    return len(tasks), sorted(issues)


def _validate_handoff_dependency_items(tasks: list[object], errors: list[str]) -> tuple[int, list[str]]:
    missing: list[str] = []
    for item in tasks:
        task = _as_dict(item)
        name = task.get("name")
        if not isinstance(name, str) or not name:
            errors.append("environment_handoff_dependency_name_missing")
            continue
        if task.get("secret_redacted") is not True:
            errors.append(f"environment_handoff_dependency_secret_redaction_missing:{name}")
        if task.get("present") is False:
            missing.append(name)
        elif task.get("present") is not True:
            errors.append(f"environment_handoff_dependency_present_invalid:{name}")
    return len(tasks), sorted(missing)


def _validate_environment_handoff(
    handoff: dict[str, Any],
    *,
    missing_required: list[str],
    missing_full_required: list[str],
    missing_selectors: list[str],
    missing_dependencies: list[str],
    file_issues: list[str],
    env_file_hygiene_ready: bool,
    env_file_hygiene_errors: list[str],
    errors: list[str],
) -> list[str]:
    if handoff.get("version") != "au_p0b_google_environment_handoff_v1":
        errors.append("environment_handoff_version_invalid")
    for field in (
        "ready",
        "missing_required_count",
        "missing_required",
        "target_env_file",
        "setup_commands",
        "environment_items",
        "selector_items",
        "file_items",
        "dependency_items",
        "verification_commands",
        "evidence_outputs",
        "redaction_policy",
    ):
        if field not in handoff:
            errors.append(f"environment_handoff_field_missing:{field}")
    _validate_handoff_environment_items(_as_list(handoff.get("environment_items")), errors)
    _validate_handoff_selector_items(_as_list(handoff.get("selector_items")), errors)
    _validate_handoff_file_items(_as_list(handoff.get("file_items")), errors)
    _validate_handoff_dependency_items(_as_list(handoff.get("dependency_items")), errors)
    expected_missing = _environment_handoff_missing(
        missing_required=missing_required,
        missing_full_required=missing_full_required,
        missing_selectors=missing_selectors,
        missing_dependencies=missing_dependencies,
        file_issues=file_issues,
        env_file_hygiene_ready=env_file_hygiene_ready,
        env_file_hygiene_errors=env_file_hygiene_errors,
    )
    observed_missing = sorted(str(item) for item in _as_list(handoff.get("missing_required")))
    if observed_missing != expected_missing:
        errors.append("environment_handoff_missing_required_mismatch")
    if handoff.get("missing_required_count") != len(observed_missing):
        errors.append("environment_handoff_missing_required_count_mismatch")
    if handoff.get("ready") is not (not observed_missing):
        errors.append("environment_handoff_ready_mismatch")
    setup_commands = [str(item) for item in _as_list(handoff.get("setup_commands"))]
    for command in {
        "make verify-au-p0b-google-env-template",
        "cp .env.au-p0b-google.example .env.au-p0b-google",
        "chmod 600 .env.au-p0b-google",
    }:
        if command not in setup_commands:
            errors.append(f"environment_handoff_setup_command_missing:{command}")
    verification_commands = [str(item) for item in _as_list(handoff.get("verification_commands"))]
    for command in {
        "make au-p0b-google-playwright-env",
        "make verify-au-p0b-google-playwright-env",
        "make verify-au-p0b-google-manual-backfill",
        "make au-p0b-google-execution-checklist",
        "make verify-au-p0b-google-execution-checklist",
    }:
        if command not in verification_commands:
            errors.append(f"environment_handoff_verification_command_missing:{command}")
    redaction_policy = _as_dict(handoff.get("redaction_policy"))
    if redaction_policy.get("raw_secret_values_allowed") is not False:
        errors.append("environment_handoff_raw_secret_policy_invalid")
    if redaction_policy.get("forbidden_exact_secret_field_count") != 2:
        errors.append("environment_handoff_forbidden_field_count_invalid")
    if redaction_policy.get("forbidden_exact_secret_fields_redacted") is not True:
        errors.append("environment_handoff_forbidden_field_redaction_missing")
    if len(_as_list(handoff.get("evidence_outputs"))) < 3:
        errors.append("environment_handoff_evidence_outputs_incomplete")
    return observed_missing


def _validate_manual_backfill_handoff(
    handoff: dict[str, Any],
    *,
    remaining_blockers: list[str],
    errors: list[str],
) -> list[str]:
    if handoff.get("version") != "au_p0b_google_manual_backfill_handoff_v1":
        errors.append("manual_backfill_handoff_version_invalid")
    for field in (
        "ready",
        "status",
        "hash_valid",
        "manual_backfill_ready",
        "missing_reason_count",
        "missing_reasons",
        "manual_jsonl_env_var",
        "target_jsonl_path",
        "manual_jsonl_path_redacted",
        "template_path",
        "template_manifest_path",
        "verification_path",
        "expected_record_count",
        "record_count",
        "expected_prompt_city_count",
        "covered_prompt_city_count",
        "expected_sample_size",
        "prompt_count",
        "geo_cities",
        "file_sha256",
        "verification_hash",
        "required_fields",
        "operator_requirements",
        "setup_commands",
        "verification_commands",
        "evidence_outputs",
        "redaction_policy",
    ):
        if field not in handoff:
            errors.append(f"manual_backfill_handoff_field_missing:{field}")

    status = str(handoff.get("status") or "")
    if status not in {"pass", "fail"}:
        errors.append("manual_backfill_handoff_status_invalid")
    observed_missing = sorted(str(item) for item in _as_list(handoff.get("missing_reasons")))
    if handoff.get("missing_reason_count") != len(observed_missing):
        errors.append("manual_backfill_handoff_missing_reason_count_mismatch")
    expected_ready = (
        status == "pass"
        and handoff.get("hash_valid") is True
        and handoff.get("manual_backfill_ready") is True
        and not observed_missing
    )
    if handoff.get("ready") is not expected_ready:
        errors.append("manual_backfill_handoff_ready_mismatch")

    manual_blockers = sorted(str(blocker) for blocker in remaining_blockers if str(blocker).startswith("manual_backfill:"))
    if manual_blockers and not any(reason.startswith("manual_backfill:") for reason in observed_missing):
        errors.append("manual_backfill_handoff_missing_reasons_do_not_cover_manual_blocker")
    if not manual_blockers and status == "pass" and observed_missing:
        errors.append("manual_backfill_handoff_missing_reasons_unexpected")

    expected_record_count = handoff.get("expected_record_count")
    record_count = handoff.get("record_count")
    expected_prompt_city_count = handoff.get("expected_prompt_city_count")
    covered_prompt_city_count = handoff.get("covered_prompt_city_count")
    expected_sample_size = handoff.get("expected_sample_size")
    prompt_count = handoff.get("prompt_count")
    geo_cities = [str(value) for value in _as_list(handoff.get("geo_cities"))]
    for label, value in (
        ("expected_record_count", expected_record_count),
        ("record_count", record_count),
        ("expected_prompt_city_count", expected_prompt_city_count),
        ("covered_prompt_city_count", covered_prompt_city_count),
        ("expected_sample_size", expected_sample_size),
        ("prompt_count", prompt_count),
    ):
        if not isinstance(value, int) or value < 0:
            errors.append(f"manual_backfill_handoff_{label}_invalid")
    if isinstance(expected_record_count, int) and expected_record_count <= 0:
        errors.append("manual_backfill_handoff_expected_record_count_empty")
    if (
        isinstance(expected_record_count, int)
        and isinstance(expected_prompt_city_count, int)
        and isinstance(expected_sample_size, int)
        and expected_record_count != expected_prompt_city_count * expected_sample_size
    ):
        errors.append("manual_backfill_handoff_expected_record_count_mismatch")
    if (
        isinstance(prompt_count, int)
        and isinstance(expected_prompt_city_count, int)
        and expected_prompt_city_count != prompt_count * len(geo_cities)
    ):
        errors.append("manual_backfill_handoff_prompt_city_count_mismatch")
    if isinstance(record_count, int) and isinstance(expected_record_count, int) and record_count > expected_record_count:
        errors.append("manual_backfill_handoff_record_count_exceeds_expected")
    if (
        isinstance(covered_prompt_city_count, int)
        and isinstance(expected_prompt_city_count, int)
        and covered_prompt_city_count > expected_prompt_city_count
    ):
        errors.append("manual_backfill_handoff_covered_prompt_city_count_exceeds_expected")
    if handoff.get("ready") is True:
        if record_count != expected_record_count:
            errors.append("manual_backfill_handoff_ready_record_count_mismatch")
        if covered_prompt_city_count != expected_prompt_city_count:
            errors.append("manual_backfill_handoff_ready_prompt_city_coverage_mismatch")
        if not handoff.get("file_sha256") or not handoff.get("verification_hash"):
            errors.append("manual_backfill_handoff_ready_hashes_missing")

    if handoff.get("manual_jsonl_env_var") != "MANUAL_BACKFILL_PATH":
        errors.append("manual_backfill_handoff_env_var_invalid")
    if handoff.get("manual_jsonl_path_redacted") is not True:
        errors.append("manual_backfill_handoff_manual_path_redaction_missing")
    if handoff.get("template_path") != DEFAULT_MANUAL_BACKFILL_TEMPLATE_PATH:
        errors.append("manual_backfill_handoff_template_path_invalid")
    if handoff.get("template_manifest_path") != DEFAULT_MANUAL_BACKFILL_TEMPLATE_MANIFEST_PATH:
        errors.append("manual_backfill_handoff_template_manifest_path_invalid")

    required_fields = {str(value) for value in _as_list(handoff.get("required_fields"))}
    for required in {"answer_text", "citation_urls", "screenshot_url or html_snapshot_url"}:
        if required not in required_fields:
            errors.append(f"manual_backfill_handoff_required_field_missing:{required}")
    operator_requirements = {str(value) for value in _as_list(handoff.get("operator_requirements"))}
    for requirement in {
        "fill_answer_text_for_each_record",
        "include_at_least_one_citation_url_for_each_record",
        "include_screenshot_url_or_html_snapshot_url_for_each_record",
        "preserve_prompt_city_sample_index_and_sample_size",
    }:
        if requirement not in operator_requirements:
            errors.append(f"manual_backfill_handoff_operator_requirement_missing:{requirement}")
    setup_commands = [str(value) for value in _as_list(handoff.get("setup_commands"))]
    if "make au-p0b-google-manual-template" not in setup_commands:
        errors.append("manual_backfill_handoff_setup_command_missing:make au-p0b-google-manual-template")
    verification_commands = [str(value) for value in _as_list(handoff.get("verification_commands"))]
    for command in {
        "make verify-au-p0b-google-manual-backfill",
        "make au-p0b-google-status",
        "make verify-au-p0b-google-status",
        "make au-p0b-google-package",
        "make verify-au-p0b-google-package",
        "make au-p0b-google-execution-checklist",
        "make verify-au-p0b-google-execution-checklist",
    }:
        if command not in verification_commands:
            errors.append(f"manual_backfill_handoff_verification_command_missing:{command}")
    evidence_outputs = {str(value) for value in _as_list(handoff.get("evidence_outputs"))}
    for output in {
        DEFAULT_MANUAL_BACKFILL_TEMPLATE_PATH,
        DEFAULT_MANUAL_BACKFILL_TEMPLATE_MANIFEST_PATH,
        str(handoff.get("verification_path") or ""),
    }:
        if output not in evidence_outputs:
            errors.append(f"manual_backfill_handoff_evidence_output_missing:{output}")
    redaction_policy = _as_dict(handoff.get("redaction_policy"))
    if redaction_policy.get("raw_answer_values_allowed") is not False:
        errors.append("manual_backfill_handoff_raw_answer_policy_invalid")
    if redaction_policy.get("raw_citation_values_allowed") is not False:
        errors.append("manual_backfill_handoff_raw_citation_policy_invalid")
    if redaction_policy.get("raw_asset_urls_allowed") is not False:
        errors.append("manual_backfill_handoff_raw_asset_policy_invalid")
    if redaction_policy.get("manual_jsonl_path_redacted") is not True:
        errors.append("manual_backfill_handoff_redaction_policy_path_invalid")
    return observed_missing


def _expected_next_action(
    *,
    runbook_ok: bool,
    env_ok: bool,
    ready_for_smoke: bool,
    env_next_action: str,
    remaining_blockers: list[str],
    google_allowed: bool,
) -> str:
    if not runbook_ok:
        return "run_make_au_p0b_google_runbook"
    if not env_ok or not ready_for_smoke:
        return env_next_action or "populate_google_playwright_smoke_environment"
    if any(blocker.startswith("playwright_smoke:") for blocker in remaining_blockers):
        return "run_google_playwright_smoke"
    if any(blocker.startswith("manual_backfill:") for blocker in remaining_blockers):
        return "run_verify_google_manual_backfill"
    if any(blocker.startswith("health:") or blocker.startswith("health_manifest:") for blocker in remaining_blockers):
        return "run_au_p0b_google_spike_health"
    if any(blocker.startswith("spike:") or blocker.startswith("spike_manifest:") for blocker in remaining_blockers):
        return "run_au_p0b_google_spike"
    if not google_allowed:
        return "run_au_p0b_google_status"
    return "allow_google_into_main_scoring_denominator"


def verify_au_p0b_google_execution_checklist(
    checklist: Any,
    *,
    path: Path | None = None,
    require_google_main_scoring_ready: bool = False,
) -> dict[str, Any]:
    if not isinstance(checklist, dict):
        return {
            "status": "fail",
            "errors": ["execution_checklist_not_json_object"],
            "hash_valid": False,
            "google_execution_checklist_ready": False,
        }

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in checklist:
            errors.append(f"field_missing:{field}")
    if checklist.get("execution_checklist_version") != CHECKLIST_VERSION:
        errors.append("execution_checklist_version_invalid")
    for forbidden_path in _find_forbidden_secret_fields(checklist):
        errors.append(f"forbidden_secret_field:{forbidden_path}")

    expected_hash = checklist.get("google_execution_checklist_hash")
    computed_hash = compute_google_execution_checklist_hash(checklist)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("google_execution_checklist_hash_mismatch")

    summary = _as_dict(checklist.get("summary"))
    runbook_verifier = _as_dict(checklist.get("runbook_verifier"))
    env_summary = _as_dict(checklist.get("playwright_environment"))
    env_verifier = _as_dict(checklist.get("playwright_environment_verifier"))
    env_file_hygiene = _as_dict(checklist.get("env_file_hygiene"))
    status_verifier = _as_dict(checklist.get("status_report_verifier"))
    package = _as_dict(checklist.get("evidence_package"))
    package_verifier = _as_dict(checklist.get("evidence_package_verifier"))
    environment_handoff = _as_dict(checklist.get("environment_handoff"))
    manual_backfill_handoff = _as_dict(checklist.get("manual_backfill_handoff"))
    required_count, missing_required = _validate_env_tasks(
        "required_environment",
        _as_list(checklist.get("required_environment")),
        errors,
    )
    full_required_count, missing_full_required = _validate_env_tasks(
        "full_run_required_environment",
        _as_list(checklist.get("full_run_required_environment")),
        errors,
    )
    selector_count, missing_selectors = _validate_selector_tasks(_as_list(checklist.get("selector_groups")), errors)
    missing_dependencies = _validate_dependency_tasks(_as_list(checklist.get("dependency_checks")), errors)
    env_file_hygiene_ready, env_file_hygiene_errors, env_file_hygiene_warnings = _validate_env_file_hygiene(
        env_file_hygiene,
        errors,
    )
    file_issues = _file_gate_issues(_as_list(checklist.get("file_checks")))
    environment_handoff_missing = _validate_environment_handoff(
        environment_handoff,
        missing_required=missing_required,
        missing_full_required=missing_full_required,
        missing_selectors=missing_selectors,
        missing_dependencies=missing_dependencies,
        file_issues=file_issues,
        env_file_hygiene_ready=env_file_hygiene_ready,
        env_file_hygiene_errors=env_file_hygiene_errors,
        errors=errors,
    )
    remaining_blockers = [str(item) for item in _as_list(package.get("remaining_blockers"))]
    if not remaining_blockers:
        remaining_blockers = [str(item) for item in _as_list(summary.get("remaining_blockers"))]
    manual_backfill_handoff_missing = _validate_manual_backfill_handoff(
        manual_backfill_handoff,
        remaining_blockers=remaining_blockers,
        errors=errors,
    )

    if summary.get("required_environment_count") != required_count:
        errors.append("summary_required_environment_count_mismatch")
    if sorted(str(item) for item in _as_list(summary.get("missing_required_environment"))) != missing_required:
        errors.append("summary_missing_required_environment_mismatch")
    if summary.get("missing_required_environment_count") != len(missing_required):
        errors.append("summary_missing_required_environment_count_mismatch")
    if summary.get("full_run_required_environment_count") != full_required_count:
        errors.append("summary_full_run_required_environment_count_mismatch")
    if sorted(str(item) for item in _as_list(summary.get("missing_full_run_required_environment"))) != missing_full_required:
        errors.append("summary_missing_full_run_required_environment_mismatch")
    if summary.get("missing_full_run_required_environment_count") != len(missing_full_required):
        errors.append("summary_missing_full_run_required_environment_count_mismatch")
    if summary.get("selector_group_count") != selector_count:
        errors.append("summary_selector_group_count_mismatch")
    if sorted(str(item) for item in _as_list(summary.get("missing_selector_groups"))) != missing_selectors:
        errors.append("summary_missing_selector_groups_mismatch")
    if summary.get("missing_selector_group_count") != len(missing_selectors):
        errors.append("summary_missing_selector_group_count_mismatch")
    if sorted(str(item) for item in _as_list(summary.get("missing_dependencies"))) != missing_dependencies:
        errors.append("summary_missing_dependencies_mismatch")
    if summary.get("missing_dependency_count") != len(missing_dependencies):
        errors.append("summary_missing_dependency_count_mismatch")
    if sorted(str(item) for item in _as_list(summary.get("file_gate_issues"))) != file_issues:
        errors.append("summary_file_gate_issues_mismatch")
    if summary.get("file_gate_issue_count") != len(file_issues):
        errors.append("summary_file_gate_issue_count_mismatch")
    if summary.get("env_file_hygiene_ready") is not env_file_hygiene_ready:
        errors.append("summary_env_file_hygiene_ready_mismatch")
    if summary.get("env_file_hygiene_error_count") != len(env_file_hygiene_errors):
        errors.append("summary_env_file_hygiene_error_count_mismatch")
    if summary.get("env_file_hygiene_warning_count") != len(env_file_hygiene_warnings):
        errors.append("summary_env_file_hygiene_warning_count_mismatch")
    if summary.get("environment_handoff_ready") is not (not environment_handoff_missing):
        errors.append("summary_environment_handoff_ready_mismatch")
    if sorted(str(item) for item in _as_list(summary.get("environment_handoff_missing_required"))) != sorted(
        environment_handoff_missing
    ):
        errors.append("summary_environment_handoff_missing_required_mismatch")
    if summary.get("environment_handoff_missing_required_count") != len(environment_handoff_missing):
        errors.append("summary_environment_handoff_missing_required_count_mismatch")
    handoff_redaction = _as_dict(environment_handoff.get("redaction_policy"))
    handoff_redacted = (
        handoff_redaction.get("raw_secret_values_allowed") is False
        and handoff_redaction.get("forbidden_exact_secret_fields_redacted") is True
    )
    if summary.get("environment_handoff_secret_redacted") is not handoff_redacted:
        errors.append("summary_environment_handoff_secret_redacted_mismatch")
    if summary.get("manual_backfill_handoff_ready") is not (manual_backfill_handoff.get("ready") is True):
        errors.append("summary_manual_backfill_handoff_ready_mismatch")
    if summary.get("manual_backfill_handoff_status") != manual_backfill_handoff.get("status"):
        errors.append("summary_manual_backfill_handoff_status_mismatch")
    if summary.get("manual_backfill_handoff_expected_record_count") != manual_backfill_handoff.get(
        "expected_record_count"
    ):
        errors.append("summary_manual_backfill_handoff_expected_record_count_mismatch")
    if summary.get("manual_backfill_handoff_record_count") != manual_backfill_handoff.get("record_count"):
        errors.append("summary_manual_backfill_handoff_record_count_mismatch")
    if summary.get("manual_backfill_handoff_expected_prompt_city_count") != manual_backfill_handoff.get(
        "expected_prompt_city_count"
    ):
        errors.append("summary_manual_backfill_handoff_expected_prompt_city_count_mismatch")
    if summary.get("manual_backfill_handoff_covered_prompt_city_count") != manual_backfill_handoff.get(
        "covered_prompt_city_count"
    ):
        errors.append("summary_manual_backfill_handoff_covered_prompt_city_count_mismatch")
    if summary.get("manual_backfill_handoff_missing_reason_count") != len(manual_backfill_handoff_missing):
        errors.append("summary_manual_backfill_handoff_missing_reason_count_mismatch")
    if sorted(str(item) for item in _as_list(summary.get("manual_backfill_handoff_missing_reasons"))) != sorted(
        manual_backfill_handoff_missing
    ):
        errors.append("summary_manual_backfill_handoff_missing_reasons_mismatch")
    if summary.get("manual_backfill_handoff_template_path") != manual_backfill_handoff.get("template_path"):
        errors.append("summary_manual_backfill_handoff_template_path_mismatch")
    if summary.get("manual_backfill_handoff_verification_path") != manual_backfill_handoff.get("verification_path"):
        errors.append("summary_manual_backfill_handoff_verification_path_mismatch")
    manual_redaction = _as_dict(manual_backfill_handoff.get("redaction_policy"))
    manual_content_redacted = (
        manual_redaction.get("raw_answer_values_allowed") is False
        and manual_redaction.get("raw_citation_values_allowed") is False
        and manual_redaction.get("raw_asset_urls_allowed") is False
    )
    if summary.get("manual_backfill_handoff_content_redacted") is not manual_content_redacted:
        errors.append("summary_manual_backfill_handoff_content_redacted_mismatch")
    if sorted(str(item) for item in _as_list(summary.get("remaining_blockers"))) != sorted(remaining_blockers):
        errors.append("summary_remaining_blockers_mismatch")
    if summary.get("remaining_blocker_count") != len(remaining_blockers):
        errors.append("summary_remaining_blocker_count_mismatch")

    runbook_ok = runbook_verifier.get("status") == "pass" and runbook_verifier.get("hash_valid") is True
    env_ok = env_verifier.get("status") == "pass" and env_verifier.get("hash_valid") is True
    status_ok = status_verifier.get("status") == "pass" and status_verifier.get("hash_valid") is True
    package_ok = package_verifier.get("status") == "pass" and package_verifier.get("hash_valid") is True
    google_allowed = package.get("google_main_scoring_allowed") is True
    expected_ready = runbook_ok and env_ok and status_ok and package_ok and google_allowed and not remaining_blockers
    if checklist.get("google_execution_checklist_ready") is not expected_ready:
        errors.append("google_execution_checklist_ready_mismatch")
    if checklist.get("google_main_scoring_allowed") is not google_allowed:
        errors.append("google_main_scoring_allowed_mismatch")
    if checklist.get("limited_coverage") is not (not google_allowed):
        errors.append("limited_coverage_mismatch")
    if checklist.get("status") != ("pass" if expected_ready else "fail"):
        errors.append("status_mismatch")
    expected_next = _expected_next_action(
        runbook_ok=runbook_ok,
        env_ok=env_ok,
        ready_for_smoke=env_summary.get("ready_for_playwright_smoke") is True,
        env_next_action=str(env_summary.get("next_action") or ""),
        remaining_blockers=remaining_blockers,
        google_allowed=google_allowed,
    )
    if checklist.get("next_action") != expected_next:
        errors.append("next_action_mismatch")
    if require_google_main_scoring_ready and not expected_ready:
        errors.append("google_execution_not_ready")

    setup_ids = _command_ids(_as_list(checklist.get("setup_commands")))
    execution_ids = _command_ids(_as_list(checklist.get("execution_commands")))
    verification_ids = _command_ids(_as_list(checklist.get("verification_commands")))
    for command_id in {
        "verify_env_template",
        "copy_env_template",
        "build_runbook",
        "dry_run_runbook",
        "secure_env_file_permissions",
        "build_playwright_env",
        "build_execution_checklist",
    }:
        if command_id not in setup_ids:
            errors.append(f"setup_command_missing:{command_id}")
    for command_id in {
        "verify_playwright_env",
        "run_smoke",
        "verify_smoke_strict",
        "build_manual_template",
        "verify_manual_backfill",
        "run_health",
        "manifest_health",
        "run_full_spike",
        "manifest_full_spike",
        "refresh_status",
        "refresh_package",
    }:
        if command_id not in execution_ids:
            errors.append(f"execution_command_missing:{command_id}")
    for command_id in {"hard_playwright_env_gate", "hard_status_gate", "hard_package_gate"}:
        if command_id not in verification_ids:
            errors.append(f"verification_command_missing:{command_id}")
    if len(_as_list(checklist.get("evidence_outputs"))) < 10:
        errors.append("evidence_outputs_incomplete")
    if len(_as_list(checklist.get("work_items"))) < 5:
        errors.append("work_items_incomplete")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "execution_checklist_version": checklist.get("execution_checklist_version", ""),
        "google_execution_checklist_hash": expected_hash if isinstance(expected_hash, str) else "",
        "computed_google_execution_checklist_hash": computed_hash,
        "hash_valid": hash_valid,
        "google_execution_checklist_ready": expected_ready,
        "google_main_scoring_allowed": google_allowed,
        "limited_coverage": checklist.get("limited_coverage") is True,
        "next_action": expected_next,
        "missing_required_environment": missing_required,
        "missing_full_run_required_environment": missing_full_required,
        "missing_selector_groups": missing_selectors,
        "missing_dependencies": missing_dependencies,
        "file_gate_issues": file_issues,
        "remaining_blocker_count": len(remaining_blockers),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AU P0b Google execution checklist JSON")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to the AU P0b Google execution checklist JSON.",
    )
    parser.add_argument(
        "--require-google-main-scoring-ready",
        action="store_true",
        help="Fail unless the checklist proves Google can enter the main scoring denominator.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = Path(args.path)
    try:
        checklist = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": ["execution_checklist_file_missing"],
            "hash_valid": False,
            "google_execution_checklist_ready": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "path": str(path),
            "errors": [f"execution_checklist_json_invalid:{exc.msg}"],
            "hash_valid": False,
            "google_execution_checklist_ready": False,
        }
    else:
        result = verify_au_p0b_google_execution_checklist(
            checklist,
            path=path,
            require_google_main_scoring_ready=args.require_google_main_scoring_ready,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
