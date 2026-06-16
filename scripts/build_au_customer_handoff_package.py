from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_au_customer_handoff_clearance import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_CUSTOMER_HANDOFF_CLEARANCE_PATH,
)
from scripts.build_au_customer_handoff_readiness import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_CUSTOMER_HANDOFF_READINESS_PATH,
)
from scripts.build_au_delivery_progress import DEFAULT_OUTPUT_PATH as DEFAULT_DELIVERY_PROGRESS_PATH  # noqa: E402
from scripts.build_au_external_dependency_handoff import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_EXTERNAL_DEPENDENCY_HANDOFF_PATH,
)
from scripts.build_au_handoff_dossier import DEFAULT_OUTPUT_PATH as DEFAULT_HANDOFF_DOSSIER_PATH  # noqa: E402
from scripts.build_au_next_work_item_packet import DEFAULT_OUTPUT_PATH as DEFAULT_NEXT_WORK_ITEM_PATH  # noqa: E402
from scripts.build_au_p0a_credential_clearance import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0A_CREDENTIAL_CLEARANCE_PATH,
)
from scripts.build_au_p0a_credential_update_receipt import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0A_CREDENTIAL_UPDATE_RECEIPT_PATH,
)
from scripts.build_au_p0a_evidence_package import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0A_EVIDENCE_PACKAGE_PATH,
)
from scripts.build_au_p0a_real_batch_clearance import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0A_REAL_BATCH_CLEARANCE_PATH,
)
from scripts.build_au_p0b_google_environment_clearance import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0B_GOOGLE_ENVIRONMENT_CLEARANCE_PATH,
)
from scripts.build_au_p0b_google_evidence_package import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0B_GOOGLE_EVIDENCE_PACKAGE_PATH,
)
from scripts.build_au_p0b_google_manual_backfill_clearance import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0B_GOOGLE_MANUAL_BACKFILL_CLEARANCE_PATH,
)
from scripts.build_au_p0b_google_phase_execution_clearance import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_P0B_GOOGLE_PHASE_EXECUTION_CLEARANCE_PATH,
)
from scripts.build_au_p0c_report_package import DEFAULT_OUTPUT_PATH as DEFAULT_P0C_REPORT_PACKAGE_PATH  # noqa: E402
from scripts.run_au_external_dependency_clearance import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_EXTERNAL_DEPENDENCY_CLEARANCE_PATH,
)
from scripts.verify_au_customer_handoff_clearance import verify_au_customer_handoff_clearance  # noqa: E402
from scripts.verify_au_customer_handoff_readiness import verify_au_customer_handoff_readiness  # noqa: E402
from scripts.verify_au_delivery_progress import verify_au_delivery_progress  # noqa: E402
from scripts.verify_au_external_dependency_clearance import verify_au_external_dependency_clearance  # noqa: E402
from scripts.verify_au_external_dependency_handoff import verify_au_external_dependency_handoff  # noqa: E402
from scripts.verify_au_handoff_dossier import verify_au_handoff_dossier  # noqa: E402
from scripts.verify_au_next_work_item_packet import verify_au_next_work_item_packet  # noqa: E402
from scripts.verify_au_p0a_credential_clearance import verify_au_p0a_credential_clearance  # noqa: E402
from scripts.verify_au_p0a_credential_update_receipt import verify_au_p0a_credential_update_receipt  # noqa: E402
from scripts.verify_au_p0a_evidence_package import verify_au_p0a_evidence_package  # noqa: E402
from scripts.verify_au_p0a_real_batch_clearance import verify_au_p0a_real_batch_clearance  # noqa: E402
from scripts.verify_au_p0b_google_environment_clearance import (  # noqa: E402
    verify_au_p0b_google_environment_clearance,
)
from scripts.verify_au_p0b_google_evidence_package import verify_au_p0b_google_evidence_package  # noqa: E402
from scripts.verify_au_p0b_google_manual_backfill_clearance import (  # noqa: E402
    verify_au_p0b_google_manual_backfill_clearance,
)
from scripts.verify_au_p0b_google_phase_execution_clearance import (  # noqa: E402
    verify_au_p0b_google_phase_execution_clearance,
)
from scripts.verify_au_p0c_report_package import verify_au_p0c_report_package  # noqa: E402
from scripts.au_trial_handoff import (  # noqa: E402
    TRIAL_SUMMARY_FIELDS,
    build_trial_handoff_audit,
    compact_trial_handoff_summary,
)


PACKAGE_VERSION = "au_customer_handoff_package_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-customer-handoff-package-latest.json"
DEFAULT_MARKDOWN_OUTPUT_PATH = "docs/runtime_preflight/au-customer-handoff-package-latest.md"
CURRENT_CLEARANCE_SUMMARY_FIELDS = (
    "current_clearance_request_artifact_id",
    "current_clearance_request_artifact_hash",
    "current_clearance_completion_contract_ready",
    "current_clearance_completion_contract_version",
    "current_clearance_credential_update_receipt_required",
    "current_clearance_credential_update_receipt_endpoint",
    "current_clearance_credential_update_receipt_strict_gate",
    "current_clearance_post_update_validation_command_count",
    "current_clearance_completion_contract_missing_required_count",
    "current_clearance_completion_contract_raw_secret_values_allowed",
)
DEFAULT_HANDOFF_DOSSIER_MARKDOWN_PATH = "docs/runtime_preflight/au-handoff-dossier-latest.md"

JSON_SOURCE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "name": "handoff_dossier",
        "stage": "handoff",
        "path_attr": "handoff_dossier_path",
        "default_path": DEFAULT_HANDOFF_DOSSIER_PATH,
        "hash_field": "handoff_dossier_hash",
        "verifier": verify_au_handoff_dossier,
        "required_for_customer_handoff": True,
        "customer_visible": True,
    },
    {
        "name": "customer_handoff_readiness",
        "stage": "handoff",
        "path_attr": "customer_handoff_readiness_path",
        "default_path": DEFAULT_CUSTOMER_HANDOFF_READINESS_PATH,
        "hash_field": "customer_handoff_readiness_hash",
        "verifier": verify_au_customer_handoff_readiness,
        "required_for_customer_handoff": True,
        "customer_visible": False,
    },
    {
        "name": "next_work_item",
        "stage": "handoff",
        "path_attr": "next_work_item_path",
        "default_path": DEFAULT_NEXT_WORK_ITEM_PATH,
        "hash_field": "next_work_item_packet_hash",
        "verifier": verify_au_next_work_item_packet,
        "required_for_customer_handoff": True,
        "customer_visible": False,
    },
    {
        "name": "delivery_progress",
        "stage": "handoff",
        "path_attr": "delivery_progress_path",
        "default_path": DEFAULT_DELIVERY_PROGRESS_PATH,
        "hash_field": "delivery_progress_hash",
        "verifier": verify_au_delivery_progress,
        "required_for_customer_handoff": True,
        "customer_visible": False,
    },
    {
        "name": "customer_handoff_clearance",
        "stage": "handoff",
        "path_attr": "customer_handoff_clearance_path",
        "default_path": DEFAULT_CUSTOMER_HANDOFF_CLEARANCE_PATH,
        "hash_field": "customer_handoff_clearance_hash",
        "verifier": verify_au_customer_handoff_clearance,
        "required_for_customer_handoff": True,
        "customer_visible": False,
    },
    {
        "name": "external_dependency_handoff",
        "stage": "external_dependency",
        "path_attr": "external_dependency_handoff_path",
        "default_path": DEFAULT_EXTERNAL_DEPENDENCY_HANDOFF_PATH,
        "hash_field": "external_dependency_handoff_hash",
        "verifier": verify_au_external_dependency_handoff,
        "required_for_customer_handoff": True,
        "customer_visible": False,
    },
    {
        "name": "external_dependency_clearance",
        "stage": "external_dependency",
        "path_attr": "external_dependency_clearance_path",
        "default_path": DEFAULT_EXTERNAL_DEPENDENCY_CLEARANCE_PATH,
        "hash_field": "clearance_execution_hash",
        "verifier": verify_au_external_dependency_clearance,
        "required_for_customer_handoff": True,
        "customer_visible": False,
    },
    {
        "name": "p0a_credential_clearance",
        "stage": "p0a",
        "path_attr": "p0a_credential_clearance_path",
        "default_path": DEFAULT_P0A_CREDENTIAL_CLEARANCE_PATH,
        "hash_field": "p0a_credential_clearance_hash",
        "verifier": verify_au_p0a_credential_clearance,
        "required_for_customer_handoff": True,
        "customer_visible": False,
    },
    {
        "name": "p0a_credential_update_receipt",
        "stage": "p0a",
        "path_attr": "p0a_credential_update_receipt_path",
        "default_path": DEFAULT_P0A_CREDENTIAL_UPDATE_RECEIPT_PATH,
        "hash_field": "p0a_credential_update_receipt_hash",
        "verifier": verify_au_p0a_credential_update_receipt,
        "required_for_customer_handoff": True,
        "customer_visible": False,
    },
    {
        "name": "p0a_real_batch_clearance",
        "stage": "p0a",
        "path_attr": "p0a_real_batch_clearance_path",
        "default_path": DEFAULT_P0A_REAL_BATCH_CLEARANCE_PATH,
        "hash_field": "p0a_real_batch_clearance_hash",
        "verifier": verify_au_p0a_real_batch_clearance,
        "required_for_customer_handoff": True,
        "customer_visible": False,
    },
    {
        "name": "p0b_google_environment_clearance",
        "stage": "p0b_google",
        "path_attr": "p0b_google_environment_clearance_path",
        "default_path": DEFAULT_P0B_GOOGLE_ENVIRONMENT_CLEARANCE_PATH,
        "hash_field": "p0b_google_environment_clearance_hash",
        "verifier": verify_au_p0b_google_environment_clearance,
        "required_for_customer_handoff": True,
        "customer_visible": False,
    },
    {
        "name": "p0b_google_manual_backfill_clearance",
        "stage": "p0b_google",
        "path_attr": "p0b_google_manual_backfill_clearance_path",
        "default_path": DEFAULT_P0B_GOOGLE_MANUAL_BACKFILL_CLEARANCE_PATH,
        "hash_field": "p0b_google_manual_backfill_clearance_hash",
        "verifier": verify_au_p0b_google_manual_backfill_clearance,
        "required_for_customer_handoff": True,
        "customer_visible": False,
    },
    {
        "name": "p0b_google_phase_execution_clearance",
        "stage": "p0b_google",
        "path_attr": "p0b_google_phase_execution_clearance_path",
        "default_path": DEFAULT_P0B_GOOGLE_PHASE_EXECUTION_CLEARANCE_PATH,
        "hash_field": "p0b_google_phase_execution_clearance_hash",
        "verifier": verify_au_p0b_google_phase_execution_clearance,
        "required_for_customer_handoff": True,
        "customer_visible": False,
    },
    {
        "name": "p0a_evidence_package",
        "stage": "p0a",
        "path_attr": "p0a_evidence_package_path",
        "default_path": DEFAULT_P0A_EVIDENCE_PACKAGE_PATH,
        "hash_field": "package_payload_hash",
        "verifier": verify_au_p0a_evidence_package,
        "required_for_customer_handoff": True,
        "customer_visible": False,
    },
    {
        "name": "p0b_google_evidence_package",
        "stage": "p0b_google",
        "path_attr": "p0b_google_evidence_package_path",
        "default_path": DEFAULT_P0B_GOOGLE_EVIDENCE_PACKAGE_PATH,
        "hash_field": "package_payload_hash",
        "verifier": verify_au_p0b_google_evidence_package,
        "required_for_customer_handoff": True,
        "customer_visible": False,
    },
    {
        "name": "p0c_report_package",
        "stage": "p0c",
        "path_attr": "p0c_report_package_path",
        "default_path": DEFAULT_P0C_REPORT_PACKAGE_PATH,
        "hash_field": "package_payload_hash",
        "verifier": verify_au_p0c_report_package,
        "required_for_customer_handoff": True,
        "customer_visible": True,
    },
)

MARKDOWN_SOURCE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "name": "handoff_dossier_markdown",
        "stage": "handoff",
        "path_attr": "handoff_dossier_markdown_path",
        "default_path": DEFAULT_HANDOFF_DOSSIER_MARKDOWN_PATH,
        "required_for_customer_handoff": True,
        "customer_visible": True,
    },
)

CUSTOMER_VISIBLE_ARTIFACTS = ("handoff_dossier", "handoff_dossier_markdown", "p0c_report_package")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_customer_handoff_package_hash(package: dict[str, Any]) -> str:
    payload = dict(package)
    payload.pop("customer_handoff_package_hash", None)
    return hashlib.sha256(_stable_bytes(payload)).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _short(value: object) -> str:
    text = str(value or "")
    return text[:12] if text else "none"


def _markdown_cell(value: object) -> str:
    text = str(value if value is not None else "")
    return text.replace("|", "\\|").replace("\n", " ")


def _render_customer_handoff_manifest_markdown(package: dict[str, Any]) -> str:
    summary = _as_dict(package.get("summary"))
    source_artifacts = {
        str(name): _as_dict(artifact)
        for name, artifact in _as_dict(package.get("source_artifacts")).items()
    }
    customer_visible = [
        artifact
        for artifact in source_artifacts.values()
        if artifact.get("customer_visible") is True
    ]
    lines = [
        "# AU Customer Handoff Package Manifest",
        "",
        "This manifest is generated from the hash-only customer handoff package index.",
        "It records paths, statuses and hashes only; raw answers, citation URLs, assets, secrets and provider payloads are not embedded.",
        "",
        "## Status",
        "",
        f"- Generated at: `{package.get('generated_at', '')}`",
        f"- Package manifest: `{'ready' if package.get('customer_handoff_package_manifest_ready') else 'blocked'}`",
        f"- Customer delivery: `{'ready' if package.get('customer_handoff_package_ready') else 'blocked'}`",
        f"- Report export handoff: `{'ready' if package.get('ready_for_report_export_handoff') else 'blocked'}`",
        f"- Engineering progress: `{summary.get('engineering_progress_percent', 0)}%`",
        f"- Customer readiness: `{summary.get('customer_report_handoff_readiness_percent', 0)}%`",
        f"- Trial customer handoff: `{'ready' if package.get('ready_for_trial_customer_handoff') else 'blocked'}`",
        f"- Trial readiness: `{summary.get('trial_customer_handoff_readiness_percent', 0)}%`",
        f"- Trial Google coverage: `{summary.get('trial_google_coverage_mode') or 'none'}`",
        f"- Trial full batch: `{summary.get('trial_full_batch_status') or 'none'}`",
        f"- Structural auditability: `{summary.get('structural_auditability_percent', 0)}%`",
        f"- Missing customer gates: `{summary.get('missing_required_count', 0)}`",
        f"- Next command: `{summary.get('next_command') or 'none'}`",
        f"- Current clearance request: `{summary.get('current_clearance_request_artifact_id') or 'none'}`",
        f"- Current clearance request hash: `{_short(summary.get('current_clearance_request_artifact_hash'))}`",
        f"- Current completion contract: `{'ready' if summary.get('current_clearance_completion_contract_ready') else 'blocked'}`",
        f"- Current completion contract version: `{summary.get('current_clearance_completion_contract_version') or 'none'}`",
        f"- Current credential receipt endpoint: `{summary.get('current_clearance_credential_update_receipt_endpoint') or 'none'}`",
        f"- Current receipt strict gate: `{summary.get('current_clearance_credential_update_receipt_strict_gate') or 'none'}`",
        "",
        "## Customer-Visible Artifacts",
        "",
        "| Name | Path | Status | Hash |",
        "| --- | --- | --- | --- |",
    ]
    for artifact in sorted(customer_visible, key=lambda item: str(item.get("name") or "")):
        lines.append(
            "| "
            f"{_markdown_cell(artifact.get('name'))} | "
            f"{_markdown_cell(artifact.get('path'))} | "
            f"{_markdown_cell(artifact.get('verifier_status'))} | "
            f"{_short(artifact.get('hash'))} |"
        )

    lines.extend(
        [
            "",
            "## Source Artifact Index",
            "",
            "| Name | Stage | Type | Status | Hash Field | Hash | Required | Customer Visible |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for artifact in sorted(source_artifacts.values(), key=lambda item: str(item.get("name") or "")):
        lines.append(
            "| "
            f"{_markdown_cell(artifact.get('name'))} | "
            f"{_markdown_cell(artifact.get('stage'))} | "
            f"{_markdown_cell(artifact.get('artifact_type'))} | "
            f"{_markdown_cell(artifact.get('verifier_status'))} | "
            f"{_markdown_cell(artifact.get('hash_field'))} | "
            f"{_short(artifact.get('hash'))} | "
            f"{'yes' if artifact.get('required_for_customer_handoff') else 'no'} | "
            f"{'yes' if artifact.get('customer_visible') else 'no'} |"
        )

    hard_gates = _strings(package.get("hard_gate_commands"))
    lines.extend(
        [
            "",
            "## Hard Gates",
            "",
        ]
    )
    for command in hard_gates:
        lines.append(f"- `{command}`")

    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- This Markdown manifest is a readable index over the JSON package.",
            "- The JSON package remains the source of truth for machine verification.",
            "- Strict customer delivery still requires `scripts/verify_au_customer_handoff_package.py --require-ready`.",
            "",
        ]
    )
    return "\n".join(lines)


def _markdown_manifest_entry(
    *,
    markdown_text: str,
    markdown_output_path: Path | None,
    written: bool,
) -> dict[str, Any]:
    digest = _sha256_text(markdown_text)
    encoded = markdown_text.encode("utf-8")
    current_file_exists = bool(markdown_output_path and markdown_output_path.is_file())
    return {
        "artifact_type": "markdown",
        "path": str(markdown_output_path) if markdown_output_path else "",
        "exists": written or current_file_exists,
        "hash_field": "file_sha256",
        "hash": digest,
        "file_sha256": digest,
        "size_bytes": len(encoded),
        "customer_visible": True,
        "raw_secret_values_allowed": False,
        "raw_answer_values_allowed": False,
        "raw_citation_values_allowed": False,
        "raw_asset_urls_allowed": False,
        "raw_provider_response_allowed": False,
        "source_payloads_embedded": False,
        "hash_path_status_only": True,
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, ["file_missing"]
    except json.JSONDecodeError as exc:
        return None, [f"json_invalid:{exc.msg}"]
    if not isinstance(payload, dict):
        return None, ["not_json_object"]
    return payload, []


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _strings(value: object) -> list[str]:
    return [str(item) for item in _as_list(value)]


def _unique_strings(values: list[str]) -> list[str]:
    observed: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in observed:
            observed.add(value)
            result.append(value)
    return result


def _verifier_summary(
    verifier: dict[str, Any],
    *,
    hash_field: str,
    ready_fields: tuple[str, ...],
) -> dict[str, Any]:
    ready_values = {field: verifier.get(field) for field in ready_fields if field in verifier}
    result = {
        "status": str(verifier.get("status") or ""),
        "hash_valid": verifier.get("hash_valid") is True,
        "hash_field": hash_field,
        "hash": str(verifier.get(hash_field) or verifier.get("package_payload_hash") or ""),
        "errors": _strings(verifier.get("errors")),
        "ready_fields": ready_values,
    }
    for field in CURRENT_CLEARANCE_SUMMARY_FIELDS:
        if field in verifier:
            result[field] = verifier.get(field)
    for field in TRIAL_SUMMARY_FIELDS:
        if field in verifier:
            result[field] = verifier.get(field)
    return result


def _json_artifact_entry(
    spec: dict[str, Any],
    *,
    path: Path,
    ready_fields: tuple[str, ...],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    hash_field = str(spec["hash_field"])
    payload, load_errors = _load_json(path)
    if payload is None:
        verifier: dict[str, Any] = {
            "status": "fail",
            "hash_valid": False,
            "errors": load_errors,
        }
        payload_hash = ""
    else:
        verifier_fn: Callable[..., dict[str, Any]] = spec["verifier"]
        verifier = verifier_fn(payload, path=path)
        payload_hash = str(payload.get(hash_field) or "")
    file_sha256 = _file_sha256(path) if path.is_file() else ""
    verifier_hash = str(verifier.get(hash_field) or verifier.get("package_payload_hash") or "")
    entry = {
        "name": spec["name"],
        "stage": spec["stage"],
        "artifact_type": "json",
        "path": str(path),
        "exists": path.is_file(),
        "required": spec.get("required_for_customer_handoff") is True,
        "required_for_customer_handoff": spec.get("required_for_customer_handoff") is True,
        "customer_visible": spec.get("customer_visible") is True,
        "hash_field": hash_field,
        "hash": payload_hash,
        "verifier_hash": verifier_hash,
        "hash_valid": verifier.get("hash_valid") is True,
        "verifier_status": str(verifier.get("status") or "fail"),
        "file_sha256": file_sha256,
        "size_bytes": path.stat().st_size if path.is_file() else 0,
        "errors": load_errors + _strings(verifier.get("errors")),
    }
    verifier_compact = _verifier_summary(verifier, hash_field=hash_field, ready_fields=ready_fields)
    return entry, verifier_compact, payload or {}


def _markdown_artifact_entry(spec: dict[str, Any], *, path: Path) -> dict[str, Any]:
    errors: list[str] = []
    if not path.is_file():
        errors.append("file_missing")
    elif path.stat().st_size <= 0:
        errors.append("file_empty")
    return {
        "name": spec["name"],
        "stage": spec["stage"],
        "artifact_type": "markdown",
        "path": str(path),
        "exists": path.is_file(),
        "required": spec.get("required_for_customer_handoff") is True,
        "required_for_customer_handoff": spec.get("required_for_customer_handoff") is True,
        "customer_visible": spec.get("customer_visible") is True,
        "hash_field": "file_sha256",
        "hash": _file_sha256(path) if path.is_file() else "",
        "verifier_hash": _file_sha256(path) if path.is_file() else "",
        "hash_valid": path.is_file() and path.stat().st_size > 0,
        "verifier_status": "pass" if not errors else "fail",
        "file_sha256": _file_sha256(path) if path.is_file() else "",
        "size_bytes": path.stat().st_size if path.is_file() else 0,
        "errors": errors,
    }


def _ready_fields_for(name: str) -> tuple[str, ...]:
    return {
        "handoff_dossier": ("handoff_dossier_ready", "ready_for_customer_report_handoff"),
        "customer_handoff_readiness": ("customer_handoff_readiness_ready", "ready_for_customer_report_handoff"),
        "next_work_item": ("next_work_item_packet_ready",),
        "delivery_progress": ("delivery_progress_ready", "ready_for_customer_report_handoff"),
        "customer_handoff_clearance": (
            "customer_handoff_clearance_packet_ready",
            "customer_handoff_clearance_ready",
            "ready_for_report_export_handoff",
        ),
        "external_dependency_handoff": ("external_dependency_handoff_ready",),
        "external_dependency_clearance": ("handoff_ready",),
        "p0a_credential_clearance": ("credential_clearance_ready", "credentials_fulfilled"),
        "p0a_credential_update_receipt": ("credential_update_receipt_ready", "credential_update_receipt_complete"),
        "p0a_real_batch_clearance": ("real_batch_clearance_ready", "real_batches_fulfilled"),
        "p0b_google_environment_clearance": ("environment_clearance_ready", "environment_fulfilled"),
        "p0b_google_manual_backfill_clearance": ("manual_backfill_clearance_ready", "manual_backfill_fulfilled"),
        "p0b_google_phase_execution_clearance": ("phase_execution_clearance_ready", "phase_execution_fulfilled"),
        "p0a_evidence_package": ("package_ready", "p0a_package_ready"),
        "p0b_google_evidence_package": ("package_ready", "google_evidence_package_ready"),
        "p0c_report_package": ("p0c_report_contract_ready",),
    }.get(name, ())


def _customer_package_manifest_ready(source_artifacts: dict[str, dict[str, Any]]) -> bool:
    return all(
        artifact.get("exists") is True
        and artifact.get("hash_valid") is True
        and artifact.get("verifier_status") == "pass"
        for artifact in source_artifacts.values()
        if artifact.get("required_for_customer_handoff") is True
    )


def _trial_handoff_audit_from_sources(
    *,
    source_artifacts: dict[str, dict[str, Any]],
    source_payloads: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    handoff_dossier = _as_dict(source_payloads.get("handoff_dossier"))
    return build_trial_handoff_audit(
        launch_status=_as_dict(handoff_dossier.get("launch_status")),
        p0a_credential_update_receipt=_as_dict(source_payloads.get("p0a_credential_update_receipt")),
        p0a_credential_clearance=_as_dict(source_payloads.get("p0a_credential_clearance")),
        p0a_real_batch_clearance=_as_dict(source_payloads.get("p0a_real_batch_clearance")),
        p0b_google_environment_clearance=_as_dict(source_payloads.get("p0b_google_environment_clearance")),
        p0b_google_manual_backfill_clearance=_as_dict(source_payloads.get("p0b_google_manual_backfill_clearance")),
        p0b_google_phase_execution_clearance=_as_dict(source_payloads.get("p0b_google_phase_execution_clearance")),
        p0c_report_package=_as_dict(source_payloads.get("p0c_report_package")),
        handoff_dossier=handoff_dossier,
        customer_handoff_package_manifest_ready=_customer_package_manifest_ready(source_artifacts),
    )


def _summary(
    *,
    source_artifacts: dict[str, dict[str, Any]],
    source_payloads: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    customer_handoff_clearance = _as_dict(source_payloads.get("customer_handoff_clearance"))
    delivery_progress = _as_dict(source_payloads.get("delivery_progress"))
    p0c_report_package = _as_dict(source_payloads.get("p0c_report_package"))
    clearance_summary = _as_dict(customer_handoff_clearance.get("summary"))
    delivery_summary = _as_dict(delivery_progress.get("summary"))
    blocked_sources = sorted(
        name
        for name, artifact in source_artifacts.items()
        if artifact.get("required_for_customer_handoff") is True
        and not (
            artifact.get("exists") is True
            and artifact.get("hash_valid") is True
            and artifact.get("verifier_status") == "pass"
        )
    )
    ready_sources = sorted(
        name
        for name, artifact in source_artifacts.items()
        if artifact.get("required_for_customer_handoff") is True
        and artifact.get("exists") is True
        and artifact.get("hash_valid") is True
        and artifact.get("verifier_status") == "pass"
    )
    customer_visible = sorted(
        name for name, artifact in source_artifacts.items() if artifact.get("customer_visible") is True
    )
    blocking_reasons = sorted(
        dict.fromkeys(
            f"{name}:{error}"
            for name, artifact in source_artifacts.items()
            for error in _strings(artifact.get("errors"))
            if error
        )
    )
    required_source_count = len(
        [artifact for artifact in source_artifacts.values() if artifact.get("required_for_customer_handoff") is True]
    )
    manifest_ready = len(blocked_sources) == 0
    ready_for_report_export_handoff = customer_handoff_clearance.get("ready_for_report_export_handoff") is True
    p0c_report_contract_ready = p0c_report_package.get("p0c_report_contract_ready") is True
    trial_handoff_audit = _trial_handoff_audit_from_sources(
        source_artifacts=source_artifacts,
        source_payloads=source_payloads,
    )
    trial_summary = compact_trial_handoff_summary(trial_handoff_audit)
    return {
        "source_artifact_count": len(source_artifacts),
        "required_source_artifact_count": required_source_count,
        "ready_source_artifact_count": len(ready_sources),
        "blocked_source_artifact_count": len(blocked_sources),
        "ready_source_artifacts": ready_sources,
        "blocked_source_artifacts": blocked_sources,
        "blocking_reason_count": len(blocking_reasons),
        "blocking_reasons": blocking_reasons,
        "customer_visible_artifacts": customer_visible,
        "customer_handoff_package_manifest_ready": manifest_ready,
        "customer_handoff_clearance_ready": customer_handoff_clearance.get("customer_handoff_clearance_ready") is True,
        "ready_for_report_export_handoff": ready_for_report_export_handoff,
        "p0c_report_contract_ready": p0c_report_contract_ready,
        "customer_handoff_package_ready": manifest_ready and ready_for_report_export_handoff and p0c_report_contract_ready,
        "engineering_progress_percent": delivery_summary.get(
            "engineering_progress_percent",
            clearance_summary.get("engineering_progress_percent", 0.0),
        ),
        "customer_report_handoff_readiness_percent": delivery_summary.get(
            "customer_report_handoff_readiness_percent",
            clearance_summary.get("customer_report_handoff_readiness_percent", 0.0),
        ),
        "structural_auditability_percent": delivery_summary.get(
            "structural_auditability_percent",
            clearance_summary.get("structural_auditability_percent", 0.0),
        ),
        **trial_summary,
        "missing_required_count": clearance_summary.get("missing_required_count", 0),
        "missing_required": clearance_summary.get("missing_required", []),
        "blocked_customer_gate_ids": clearance_summary.get("blocked_customer_gate_ids", []),
        "blocked_progress_gate_ids": delivery_summary.get("blocked_progress_gate_ids", []),
        "next_action": (
            "ready_for_customer_delivery_export"
            if manifest_ready and ready_for_report_export_handoff and p0c_report_contract_ready
            else "clear_customer_handoff_prerequisites_first"
        ),
        "next_command": clearance_summary.get("next_command") or delivery_summary.get("next_command") or "make au-p0a-env",
        "current_clearance_request_artifact_id": str(
            clearance_summary.get(
                "current_clearance_request_artifact_id",
                delivery_summary.get("current_clearance_request_artifact_id", ""),
            )
            or ""
        ),
        "current_clearance_request_artifact_hash": str(
            clearance_summary.get(
                "current_clearance_request_artifact_hash",
                delivery_summary.get("current_clearance_request_artifact_hash", ""),
            )
            or ""
        ),
        "current_clearance_completion_contract_ready": clearance_summary.get(
            "current_clearance_completion_contract_ready",
            delivery_summary.get("current_clearance_completion_contract_ready"),
        )
        is True,
        "current_clearance_completion_contract_version": str(
            clearance_summary.get(
                "current_clearance_completion_contract_version",
                delivery_summary.get("current_clearance_completion_contract_version", ""),
            )
            or ""
        ),
        "current_clearance_credential_update_receipt_required": clearance_summary.get(
            "current_clearance_credential_update_receipt_required",
            delivery_summary.get("current_clearance_credential_update_receipt_required"),
        )
        is True,
        "current_clearance_credential_update_receipt_endpoint": str(
            clearance_summary.get(
                "current_clearance_credential_update_receipt_endpoint",
                delivery_summary.get("current_clearance_credential_update_receipt_endpoint", ""),
            )
            or ""
        ),
        "current_clearance_credential_update_receipt_strict_gate": str(
            clearance_summary.get(
                "current_clearance_credential_update_receipt_strict_gate",
                delivery_summary.get("current_clearance_credential_update_receipt_strict_gate", ""),
            )
            or ""
        ),
        "current_clearance_post_update_validation_command_count": clearance_summary.get(
            "current_clearance_post_update_validation_command_count",
            delivery_summary.get("current_clearance_post_update_validation_command_count", 0),
        ),
        "current_clearance_completion_contract_missing_required_count": clearance_summary.get(
            "current_clearance_completion_contract_missing_required_count",
            delivery_summary.get("current_clearance_completion_contract_missing_required_count", 0),
        ),
        "current_clearance_completion_contract_raw_secret_values_allowed": clearance_summary.get(
            "current_clearance_completion_contract_raw_secret_values_allowed",
            delivery_summary.get("current_clearance_completion_contract_raw_secret_values_allowed"),
        )
        is True,
        "handoff_dossier_hash": source_artifacts["handoff_dossier"]["hash"],
        "customer_handoff_readiness_hash": source_artifacts["customer_handoff_readiness"]["hash"],
        "next_work_item_packet_hash": source_artifacts["next_work_item"]["hash"],
        "delivery_progress_hash": source_artifacts["delivery_progress"]["hash"],
        "customer_handoff_clearance_hash": source_artifacts["customer_handoff_clearance"]["hash"],
        "external_dependency_handoff_hash": source_artifacts["external_dependency_handoff"]["hash"],
        "clearance_execution_hash": source_artifacts["external_dependency_clearance"]["hash"],
        "p0a_credential_clearance_hash": source_artifacts["p0a_credential_clearance"]["hash"],
        "p0a_credential_update_receipt_hash": source_artifacts["p0a_credential_update_receipt"]["hash"],
        "p0a_real_batch_clearance_hash": source_artifacts["p0a_real_batch_clearance"]["hash"],
        "p0b_google_environment_clearance_hash": source_artifacts["p0b_google_environment_clearance"]["hash"],
        "p0b_google_manual_backfill_clearance_hash": source_artifacts[
            "p0b_google_manual_backfill_clearance"
        ]["hash"],
        "p0b_google_phase_execution_clearance_hash": source_artifacts[
            "p0b_google_phase_execution_clearance"
        ]["hash"],
        "p0a_evidence_package_hash": source_artifacts["p0a_evidence_package"]["hash"],
        "p0b_google_evidence_package_hash": source_artifacts["p0b_google_evidence_package"]["hash"],
        "p0c_report_package_hash": source_artifacts["p0c_report_package"]["hash"],
        "handoff_dossier_markdown_sha256": source_artifacts["handoff_dossier_markdown"]["hash"],
        "raw_secret_values_allowed": False,
        "raw_answer_values_allowed": False,
        "raw_citation_values_allowed": False,
        "raw_asset_urls_allowed": False,
        "raw_provider_response_allowed": False,
    }


def _operator_steps() -> list[dict[str, Any]]:
    return [
        {
            "order": 1,
            "id": "refresh_customer_handoff_sources",
            "command": "make au-handoff-dossier au-customer-handoff-readiness",
            "purpose": "refresh_base_handoff_evidence_before_next_work_item_indexing",
            "external_call_risk": "none",
        },
        {
            "order": 2,
            "id": "refresh_next_work_item",
            "command": "make au-next-work-item verify-au-next-work-item",
            "purpose": "refresh_next_work_item_packet_before_customer_handoff_index",
            "external_call_risk": "none",
        },
        {
            "order": 3,
            "id": "refresh_delivery_progress_and_clearance",
            "command": (
                "make au-delivery-progress verify-au-delivery-progress "
                "au-customer-handoff-clearance verify-au-customer-handoff-clearance"
            ),
            "purpose": "refresh_delivery_progress_and_clearance_after_next_work_item",
            "external_call_risk": "none",
        },
        {
            "order": 4,
            "id": "refresh_p0a_credential_update_receipt",
            "command": "make au-p0a-credential-update-receipt verify-au-p0a-credential-update-receipt",
            "purpose": "refresh_p0a_credential_receipt_before_customer_handoff_index",
            "external_call_risk": "none",
        },
        {
            "order": 5,
            "id": "refresh_p0_evidence_packages",
            "command": "make au-p0a-package au-p0b-google-package au-p0c-report-package",
            "purpose": "refresh_package_hashes_before_customer_handoff_index",
            "external_call_risk": "fixture_or_local_only_unless_provider_env_is_enabled",
        },
        {
            "order": 6,
            "id": "build_customer_handoff_package",
            "command": "make au-customer-handoff-package",
            "purpose": "write_hash_index_over_customer_handoff_sources",
            "external_call_risk": "none",
        },
        {
            "order": 7,
            "id": "verify_customer_handoff_package",
            "command": "make verify-au-customer-handoff-package",
            "purpose": "prove_manifest_hashes_and_source_files_are_current",
            "external_call_risk": "none",
        },
        {
            "order": 8,
            "id": "run_customer_ready_strict_gate",
            "command": (
                "PYTHONPATH=packages/geno_core:apps/api python3 "
                "scripts/verify_au_customer_handoff_package.py "
                "${GENO_AU_CUSTOMER_HANDOFF_PACKAGE_OUTPUT_PATH:-docs/runtime_preflight/au-customer-handoff-package-latest.json} "
                "--require-ready"
            ),
            "purpose": "fail_until_customer_handoff_clearance_and_p0c_report_package_are_ready",
            "external_call_risk": "none",
        },
    ]


def _post_update_validation_sequence() -> list[str]:
    return [
        "make au-handoff-dossier",
        "make verify-au-handoff-dossier",
        "make au-customer-handoff-readiness",
        "make verify-au-customer-handoff-readiness",
        "make au-next-work-item",
        "make verify-au-next-work-item",
        "make au-delivery-progress",
        "make verify-au-delivery-progress",
        "make au-customer-handoff-clearance",
        "make verify-au-customer-handoff-clearance",
        "make au-p0a-credential-update-receipt",
        "make verify-au-p0a-credential-update-receipt",
        "make au-p0a-package",
        "make verify-au-p0a-package",
        "make au-p0b-google-package",
        "make verify-au-p0b-google-package",
        "make au-p0c-report-package",
        "make verify-au-p0c-report-package",
        "make au-customer-handoff-package",
        "make verify-au-customer-handoff-package",
        "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_customer_handoff_clearance.py "
        "${GENO_AU_CUSTOMER_HANDOFF_CLEARANCE_OUTPUT_PATH:-docs/runtime_preflight/au-customer-handoff-clearance-latest.json} "
        "--require-cleared",
        "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_credential_update_receipt.py "
        "${GENO_AU_P0A_CREDENTIAL_UPDATE_RECEIPT_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-credential-update-receipt-latest.json} "
        "--require-complete",
        "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_customer_handoff_package.py "
        "${GENO_AU_CUSTOMER_HANDOFF_PACKAGE_OUTPUT_PATH:-docs/runtime_preflight/au-customer-handoff-package-latest.json} "
        "--require-ready",
    ]


def build_au_customer_handoff_package(
    *,
    handoff_dossier_path: Path = Path(DEFAULT_HANDOFF_DOSSIER_PATH),
    handoff_dossier_markdown_path: Path = Path(DEFAULT_HANDOFF_DOSSIER_MARKDOWN_PATH),
    customer_handoff_readiness_path: Path = Path(DEFAULT_CUSTOMER_HANDOFF_READINESS_PATH),
    next_work_item_path: Path = Path(DEFAULT_NEXT_WORK_ITEM_PATH),
    delivery_progress_path: Path = Path(DEFAULT_DELIVERY_PROGRESS_PATH),
    customer_handoff_clearance_path: Path = Path(DEFAULT_CUSTOMER_HANDOFF_CLEARANCE_PATH),
    external_dependency_handoff_path: Path = Path(DEFAULT_EXTERNAL_DEPENDENCY_HANDOFF_PATH),
    external_dependency_clearance_path: Path = Path(DEFAULT_EXTERNAL_DEPENDENCY_CLEARANCE_PATH),
    p0a_credential_clearance_path: Path = Path(DEFAULT_P0A_CREDENTIAL_CLEARANCE_PATH),
    p0a_credential_update_receipt_path: Path = Path(DEFAULT_P0A_CREDENTIAL_UPDATE_RECEIPT_PATH),
    p0a_real_batch_clearance_path: Path = Path(DEFAULT_P0A_REAL_BATCH_CLEARANCE_PATH),
    p0b_google_environment_clearance_path: Path = Path(DEFAULT_P0B_GOOGLE_ENVIRONMENT_CLEARANCE_PATH),
    p0b_google_manual_backfill_clearance_path: Path = Path(DEFAULT_P0B_GOOGLE_MANUAL_BACKFILL_CLEARANCE_PATH),
    p0b_google_phase_execution_clearance_path: Path = Path(DEFAULT_P0B_GOOGLE_PHASE_EXECUTION_CLEARANCE_PATH),
    p0a_evidence_package_path: Path = Path(DEFAULT_P0A_EVIDENCE_PACKAGE_PATH),
    p0b_google_evidence_package_path: Path = Path(DEFAULT_P0B_GOOGLE_EVIDENCE_PACKAGE_PATH),
    p0c_report_package_path: Path = Path(DEFAULT_P0C_REPORT_PACKAGE_PATH),
    output_path: Path | None = None,
    markdown_output_path: Path | None = Path(DEFAULT_MARKDOWN_OUTPUT_PATH),
    generated_at: str | None = None,
) -> dict[str, Any]:
    path_values = {
        "handoff_dossier_path": handoff_dossier_path,
        "handoff_dossier_markdown_path": handoff_dossier_markdown_path,
        "customer_handoff_readiness_path": customer_handoff_readiness_path,
        "next_work_item_path": next_work_item_path,
        "delivery_progress_path": delivery_progress_path,
        "customer_handoff_clearance_path": customer_handoff_clearance_path,
        "external_dependency_handoff_path": external_dependency_handoff_path,
        "external_dependency_clearance_path": external_dependency_clearance_path,
        "p0a_credential_clearance_path": p0a_credential_clearance_path,
        "p0a_credential_update_receipt_path": p0a_credential_update_receipt_path,
        "p0a_real_batch_clearance_path": p0a_real_batch_clearance_path,
        "p0b_google_environment_clearance_path": p0b_google_environment_clearance_path,
        "p0b_google_manual_backfill_clearance_path": p0b_google_manual_backfill_clearance_path,
        "p0b_google_phase_execution_clearance_path": p0b_google_phase_execution_clearance_path,
        "p0a_evidence_package_path": p0a_evidence_package_path,
        "p0b_google_evidence_package_path": p0b_google_evidence_package_path,
        "p0c_report_package_path": p0c_report_package_path,
    }
    source_artifacts: dict[str, dict[str, Any]] = {}
    verifiers: dict[str, dict[str, Any]] = {}
    source_payloads: dict[str, dict[str, Any]] = {}
    for spec in JSON_SOURCE_SPECS:
        name = str(spec["name"])
        entry, verifier_compact, payload = _json_artifact_entry(
            spec,
            path=Path(path_values[str(spec["path_attr"])]),
            ready_fields=_ready_fields_for(name),
        )
        source_artifacts[name] = entry
        verifiers[name] = verifier_compact
        source_payloads[name] = payload
    for spec in MARKDOWN_SOURCE_SPECS:
        name = str(spec["name"])
        source_artifacts[name] = _markdown_artifact_entry(spec, path=Path(path_values[str(spec["path_attr"])]))

    summary = _summary(
        source_artifacts=source_artifacts,
        source_payloads=source_payloads,
    )
    trial_handoff_audit = _trial_handoff_audit_from_sources(
        source_artifacts=source_artifacts,
        source_payloads=source_payloads,
    )
    package_ready = summary["customer_handoff_package_ready"] is True
    validation_sequence = _post_update_validation_sequence()
    package: dict[str, Any] = {
        "customer_handoff_package_version": PACKAGE_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass" if summary["customer_handoff_package_manifest_ready"] else "fail",
        "customer_handoff_package_manifest_ready": summary["customer_handoff_package_manifest_ready"],
        "customer_handoff_package_ready": package_ready,
        "ready_for_report_export_handoff": summary["ready_for_report_export_handoff"],
        "ready_for_customer_delivery": package_ready,
        "ready_for_trial_customer_handoff": summary["ready_for_trial_customer_handoff"],
        "next_action": summary["next_action"],
        "remaining_blockers": summary["blocking_reasons"] if not summary["customer_handoff_package_manifest_ready"] else [],
        "output_path": str(output_path) if output_path else "",
        "source_artifacts": source_artifacts,
        "verifiers": verifiers,
        "summary": summary,
        "trial_handoff_audit": trial_handoff_audit,
        "handoff_index": [
            {
                "name": artifact["name"],
                "stage": artifact["stage"],
                "artifact_type": artifact["artifact_type"],
                "path": artifact["path"],
                "hash_field": artifact["hash_field"],
                "hash": artifact["hash"],
                "file_sha256": artifact["file_sha256"],
                "customer_visible": artifact["customer_visible"],
                "required_for_customer_handoff": artifact["required_for_customer_handoff"],
                "status": artifact["verifier_status"],
            }
            for artifact in source_artifacts.values()
        ],
        "runtime_endpoints": {
            "customer_handoff_package": "GET /v1/customer-handoff-package/au",
            "customer_handoff_clearance": "GET /v1/customer-handoff-clearance/au",
            "handoff_dossier": "GET /v1/handoff-dossier/au",
            "customer_handoff_readiness": "GET /v1/customer-handoff-readiness/au",
            "next_work_item": "GET /v1/next-work-item/au",
            "delivery_progress": "GET /v1/delivery-progress/au",
            "external_dependency_handoff": "GET /v1/external-dependency-handoff/au",
            "external_dependency_clearance": "GET /v1/external-dependency-clearance/au",
            "p0a_credential_clearance": "GET /v1/p0a-credential-clearance/au",
            "p0a_credential_update_receipt": "GET /v1/p0a-credential-update-receipt/au",
            "p0a_real_batch_clearance": "GET /v1/p0a-real-batch-clearance/au",
            "p0b_google_environment_clearance": "GET /v1/p0b-google-environment-clearance/au",
            "p0b_google_manual_backfill_clearance": "GET /v1/p0b-google-manual-backfill-clearance/au",
            "p0b_google_phase_execution_clearance": "GET /v1/p0b-google-phase-execution-clearance/au",
        },
        "operator_steps": _operator_steps(),
        "post_update_validation_sequence": validation_sequence,
        "hard_gate_commands": _unique_strings(
            [
                "make au-customer-handoff-package",
                "make verify-au-customer-handoff-package",
                *validation_sequence,
            ]
        ),
        "redaction_policy": {
            "raw_secret_values_allowed": False,
            "raw_answer_values_allowed": False,
            "raw_citation_values_allowed": False,
            "raw_asset_urls_allowed": False,
            "raw_provider_response_allowed": False,
            "source_payloads_embedded": False,
            "hash_path_status_only": True,
            "customer_visible_artifacts": list(CUSTOMER_VISIBLE_ARTIFACTS),
        },
    }
    manifest_markdown = _render_customer_handoff_manifest_markdown(package)
    package["customer_handoff_package_markdown"] = _markdown_manifest_entry(
        markdown_text=manifest_markdown,
        markdown_output_path=markdown_output_path,
        written=False,
    )
    package["customer_handoff_package_hash"] = compute_customer_handoff_package_hash(package)
    return package


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU customer handoff package index JSON")
    parser.add_argument(
        "--handoff-dossier-path",
        default=os.environ.get("GENO_AU_HANDOFF_DOSSIER_OUTPUT_PATH", DEFAULT_HANDOFF_DOSSIER_PATH),
        help="Path to the AU handoff dossier JSON.",
    )
    parser.add_argument(
        "--handoff-dossier-markdown-path",
        default=os.environ.get("GENO_AU_HANDOFF_DOSSIER_MARKDOWN_PATH", DEFAULT_HANDOFF_DOSSIER_MARKDOWN_PATH),
        help="Path to the AU handoff dossier Markdown.",
    )
    parser.add_argument(
        "--customer-handoff-readiness-path",
        default=os.environ.get("GENO_AU_CUSTOMER_HANDOFF_READINESS_OUTPUT_PATH", DEFAULT_CUSTOMER_HANDOFF_READINESS_PATH),
        help="Path to the AU customer handoff readiness JSON.",
    )
    parser.add_argument(
        "--next-work-item-path",
        default=os.environ.get("GENO_AU_NEXT_WORK_ITEM_OUTPUT_PATH", DEFAULT_NEXT_WORK_ITEM_PATH),
        help="Path to the AU next work item packet JSON.",
    )
    parser.add_argument(
        "--delivery-progress-path",
        default=os.environ.get("GENO_AU_DELIVERY_PROGRESS_OUTPUT_PATH", DEFAULT_DELIVERY_PROGRESS_PATH),
        help="Path to the AU delivery progress JSON.",
    )
    parser.add_argument(
        "--customer-handoff-clearance-path",
        default=os.environ.get("GENO_AU_CUSTOMER_HANDOFF_CLEARANCE_OUTPUT_PATH", DEFAULT_CUSTOMER_HANDOFF_CLEARANCE_PATH),
        help="Path to the AU customer handoff clearance JSON.",
    )
    parser.add_argument(
        "--external-dependency-handoff-path",
        default=os.environ.get("GENO_AU_EXTERNAL_DEPENDENCY_HANDOFF_OUTPUT_PATH", DEFAULT_EXTERNAL_DEPENDENCY_HANDOFF_PATH),
        help="Path to the AU external dependency handoff JSON.",
    )
    parser.add_argument(
        "--external-dependency-clearance-path",
        default=os.environ.get(
            "GENO_AU_EXTERNAL_DEPENDENCY_CLEARANCE_OUTPUT_PATH",
            DEFAULT_EXTERNAL_DEPENDENCY_CLEARANCE_PATH,
        ),
        help="Path to the AU external dependency clearance JSON.",
    )
    parser.add_argument(
        "--p0a-credential-clearance-path",
        default=os.environ.get("GENO_AU_P0A_CREDENTIAL_CLEARANCE_OUTPUT_PATH", DEFAULT_P0A_CREDENTIAL_CLEARANCE_PATH),
        help="Path to the AU P0a credential clearance JSON.",
    )
    parser.add_argument(
        "--p0a-credential-update-receipt-path",
        default=os.environ.get(
            "GENO_AU_P0A_CREDENTIAL_UPDATE_RECEIPT_OUTPUT_PATH",
            DEFAULT_P0A_CREDENTIAL_UPDATE_RECEIPT_PATH,
        ),
        help="Path to the AU P0a credential update receipt JSON.",
    )
    parser.add_argument(
        "--p0a-real-batch-clearance-path",
        default=os.environ.get("GENO_AU_P0A_REAL_BATCH_CLEARANCE_OUTPUT_PATH", DEFAULT_P0A_REAL_BATCH_CLEARANCE_PATH),
        help="Path to the AU P0a real batch clearance JSON.",
    )
    parser.add_argument(
        "--p0b-google-environment-clearance-path",
        default=os.environ.get(
            "GENO_AU_P0B_GOOGLE_ENVIRONMENT_CLEARANCE_OUTPUT_PATH",
            DEFAULT_P0B_GOOGLE_ENVIRONMENT_CLEARANCE_PATH,
        ),
        help="Path to the AU P0b Google environment clearance JSON.",
    )
    parser.add_argument(
        "--p0b-google-manual-backfill-clearance-path",
        default=os.environ.get(
            "GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_CLEARANCE_OUTPUT_PATH",
            DEFAULT_P0B_GOOGLE_MANUAL_BACKFILL_CLEARANCE_PATH,
        ),
        help="Path to the AU P0b Google manual backfill clearance JSON.",
    )
    parser.add_argument(
        "--p0b-google-phase-execution-clearance-path",
        default=os.environ.get(
            "GENO_AU_P0B_GOOGLE_PHASE_EXECUTION_CLEARANCE_OUTPUT_PATH",
            DEFAULT_P0B_GOOGLE_PHASE_EXECUTION_CLEARANCE_PATH,
        ),
        help="Path to the AU P0b Google phase execution clearance JSON.",
    )
    parser.add_argument(
        "--p0a-evidence-package-path",
        default=os.environ.get("GENO_AU_P0A_EVIDENCE_PACKAGE_OUTPUT_PATH", DEFAULT_P0A_EVIDENCE_PACKAGE_PATH),
        help="Path to the AU P0a evidence package JSON.",
    )
    parser.add_argument(
        "--p0b-google-evidence-package-path",
        default=os.environ.get("GENO_AU_P0B_GOOGLE_PACKAGE_OUTPUT_PATH", DEFAULT_P0B_GOOGLE_EVIDENCE_PACKAGE_PATH),
        help="Path to the AU P0b Google evidence package JSON.",
    )
    parser.add_argument(
        "--p0c-report-package-path",
        default=os.environ.get("GENO_AU_P0C_REPORT_PACKAGE_OUTPUT_PATH", DEFAULT_P0C_REPORT_PACKAGE_PATH),
        help="Path to the AU P0c report package JSON.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GENO_AU_CUSTOMER_HANDOFF_PACKAGE_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU customer handoff package index JSON.",
    )
    parser.add_argument(
        "--markdown-output-path",
        default=os.environ.get("GENO_AU_CUSTOMER_HANDOFF_PACKAGE_MARKDOWN_PATH", DEFAULT_MARKDOWN_OUTPUT_PATH),
        help="Path to write the human-readable AU customer handoff package Markdown manifest.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    markdown_output_path = Path(args.markdown_output_path)
    package = build_au_customer_handoff_package(
        handoff_dossier_path=Path(args.handoff_dossier_path),
        handoff_dossier_markdown_path=Path(args.handoff_dossier_markdown_path),
        customer_handoff_readiness_path=Path(args.customer_handoff_readiness_path),
        next_work_item_path=Path(args.next_work_item_path),
        delivery_progress_path=Path(args.delivery_progress_path),
        customer_handoff_clearance_path=Path(args.customer_handoff_clearance_path),
        external_dependency_handoff_path=Path(args.external_dependency_handoff_path),
        external_dependency_clearance_path=Path(args.external_dependency_clearance_path),
        p0a_credential_clearance_path=Path(args.p0a_credential_clearance_path),
        p0a_credential_update_receipt_path=Path(args.p0a_credential_update_receipt_path),
        p0a_real_batch_clearance_path=Path(args.p0a_real_batch_clearance_path),
        p0b_google_environment_clearance_path=Path(args.p0b_google_environment_clearance_path),
        p0b_google_manual_backfill_clearance_path=Path(args.p0b_google_manual_backfill_clearance_path),
        p0b_google_phase_execution_clearance_path=Path(args.p0b_google_phase_execution_clearance_path),
        p0a_evidence_package_path=Path(args.p0a_evidence_package_path),
        p0b_google_evidence_package_path=Path(args.p0b_google_evidence_package_path),
        p0c_report_package_path=Path(args.p0c_report_package_path),
        output_path=output_path,
        markdown_output_path=markdown_output_path,
    )
    manifest_markdown = _render_customer_handoff_manifest_markdown(package)
    package["customer_handoff_package_markdown"] = _markdown_manifest_entry(
        markdown_text=manifest_markdown,
        markdown_output_path=markdown_output_path,
        written=True,
    )
    package["customer_handoff_package_hash"] = compute_customer_handoff_package_hash(package)
    markdown_output_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_output_path.write_text(manifest_markdown, encoding="utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(package, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(package, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
