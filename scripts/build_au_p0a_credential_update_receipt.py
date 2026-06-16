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

from scripts.build_au_p0a_credential_clearance import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_CREDENTIAL_CLEARANCE_PATH,
    build_au_p0a_credential_clearance,
)
from scripts.build_au_p0a_credential_fulfillment import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_CREDENTIAL_FULFILLMENT_PATH,
    build_au_p0a_credential_fulfillment,
)
from scripts.build_au_p0a_credential_request_packet import (  # noqa: E402
    DEFAULT_OUTPUT_PATH as DEFAULT_CREDENTIAL_REQUEST_PATH,
    build_au_p0a_credential_request_packet,
)
from scripts.build_au_p0a_env_report import DEFAULT_OUTPUT_PATH as DEFAULT_ENV_REPORT_PATH  # noqa: E402
from scripts.verify_au_p0a_credential_clearance import verify_au_p0a_credential_clearance  # noqa: E402
from scripts.verify_au_p0a_credential_fulfillment import verify_au_p0a_credential_fulfillment  # noqa: E402
from scripts.verify_au_p0a_credential_request_packet import verify_au_p0a_credential_request_packet  # noqa: E402
from scripts.verify_au_p0a_env_report import verify_au_p0a_env_report  # noqa: E402


RECEIPT_VERSION = "au_p0a_credential_update_receipt_v1"
DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-p0a-credential-update-receipt-latest.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compute_p0a_credential_update_receipt_hash(payload: dict[str, Any]) -> str:
    payload_for_hash = dict(payload)
    payload_for_hash.pop("p0a_credential_update_receipt_hash", None)
    return hashlib.sha256(_stable_bytes(payload_for_hash)).hexdigest()


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _strings(value: object) -> list[str]:
    return [str(item) for item in _as_list(value)]


def _surface_ids(value: object) -> list[str]:
    ids: list[str] = []
    for item in _as_list(value):
        if isinstance(item, dict):
            surface_id = str(item.get("id") or "").strip()
        else:
            surface_id = str(item).strip()
        if surface_id:
            ids.append(surface_id)
    return ids


def _load_json(path: Path) -> tuple[dict[str, Any] | None, dict[str, Any]]:
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
    if not isinstance(payload, dict):
        return None, {"path": str(path), "exists": True, "source": "invalid_file", "errors": ["not_json_object"]}
    return payload, {
        "path": str(path),
        "exists": True,
        "source": "existing_file",
        "file_sha256": _file_sha256(path),
        "errors": [],
    }


def _load_or_build_request(path: Path, *, generated_at: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if payload is not None:
        return payload, source
    return build_au_p0a_credential_request_packet(output_path=path, generated_at=generated_at), {
        **source,
        "source": "generated_in_memory",
    }


def _load_or_build_fulfillment(
    path: Path,
    *,
    credential_request_path: Path,
    env_report_path: Path,
    credential_request: dict[str, Any],
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if payload is not None:
        return payload, source
    return build_au_p0a_credential_fulfillment(
        credential_request_path=credential_request_path,
        env_report_path=env_report_path,
        credential_request=credential_request,
        output_path=path,
        generated_at=generated_at,
    ), {
        **source,
        "source": "generated_in_memory",
    }


def _load_or_build_clearance(
    path: Path,
    *,
    credential_request_path: Path,
    env_report_path: Path,
    credential_fulfillment_path: Path,
    credential_request: dict[str, Any],
    credential_fulfillment: dict[str, Any],
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    if payload is not None:
        return payload, source
    return build_au_p0a_credential_clearance(
        credential_request_path=credential_request_path,
        env_report_path=env_report_path,
        credential_fulfillment_path=credential_fulfillment_path,
        credential_request=credential_request,
        credential_fulfillment=credential_fulfillment,
        output_path=path,
        generated_at=generated_at,
    ), {
        **source,
        "source": "generated_in_memory",
    }


def _load_env_report(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _load_json(path)
    return payload or {}, source


def _required_records(
    credential_request: dict[str, Any],
    credential_fulfillment: dict[str, Any],
    env_report: dict[str, Any],
) -> list[dict[str, Any]]:
    request_items = {
        str(item.get("name") or ""): _as_dict(item)
        for item in [_as_dict(value) for value in _as_list(credential_request.get("requested_credentials"))]
        if str(item.get("name") or "")
    }
    fulfillment_items = {
        str(item.get("name") or ""): _as_dict(item)
        for item in [_as_dict(value) for value in _as_list(credential_fulfillment.get("credential_fulfillment_items"))]
        if str(item.get("name") or "")
    }
    env_items = {
        str(item.get("name") or ""): _as_dict(item)
        for item in [_as_dict(value) for value in _as_list(env_report.get("required"))]
        if str(item.get("name") or "")
    }
    names = sorted(set(request_items) | set(fulfillment_items) | set(env_items))
    records: list[dict[str, Any]] = []
    for name in names:
        request = request_items.get(name, {})
        fulfillment = fulfillment_items.get(name, {})
        env_item = env_items.get(name, {})
        records.append(
            {
                "name": name,
                "required": request.get("required") is True or fulfillment.get("required") is True,
                "owner_hint": str(request.get("owner_hint") or fulfillment.get("owner_hint") or "unknown"),
                "target_env_file": str(
                    request.get("target_env_file")
                    or _as_dict(credential_request.get("summary")).get("target_env_file")
                    or ".env.au-p0a"
                ),
                "source": str(env_item.get("source") or fulfillment.get("environment_source") or "missing"),
                "present": env_item.get("present") is True or fulfillment.get("environment_present") is True,
                "fulfilled": fulfillment.get("fulfilled") is True,
                "value_length": int(env_item.get("value_length") or fulfillment.get("value_length") or 0),
                "sha256_prefix": str(env_item.get("sha256_prefix") or fulfillment.get("sha256_prefix") or ""),
                "secret_redacted": env_item.get("secret_redacted") is True
                and fulfillment.get("secret_redacted", True) is True,
                "raw_value_recorded": False,
                "blocking_reasons": _strings(fulfillment.get("blocking_reasons")),
                "post_update_checks": _strings(request.get("post_update_checks")),
            }
        )
    return records


def _owner_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        owner = str(record.get("owner_hint") or "unknown")
        counts[owner] = counts.get(owner, 0) + 1
    return dict(sorted(counts.items()))


def _credential_update_action_plan(
    *,
    records: list[dict[str, Any]],
    contract: dict[str, Any],
    post_update_commands: list[str],
    update_receipt_complete: bool,
) -> dict[str, Any]:
    missing_records = [
        record for record in records if record.get("required") is True and record.get("present") is not True
    ]
    action_items: list[dict[str, Any]] = []
    allowed_surfaces = _surface_ids(contract.get("allowed_update_surfaces"))
    if not allowed_surfaces:
        allowed_surfaces = ["gitignored_env_file", "process_environment"]
    for index, record in enumerate(missing_records, start=1):
        action_items.append(
            {
                "order": index,
                "credential_name": str(record.get("name") or ""),
                "owner_hint": str(record.get("owner_hint") or "unknown"),
                "target_env_file": str(record.get("target_env_file") or contract.get("target_env_file") or ""),
                "allowed_update_surface_ids": allowed_surfaces,
                "accepted_injection_methods": [
                    "process_environment",
                    "GENO_AU_P0A_ENV_FILE",
                    str(record.get("target_env_file") or contract.get("target_env_file") or ".env.au-p0a"),
                ],
                "next_command_after_update": "make au-p0a-env",
                "strict_gate_command": (
                    "PYTHONPATH=packages/geno_core:apps/api python3 "
                    "scripts/verify_au_p0a_credential_update_receipt.py "
                    "${GENO_AU_P0A_CREDENTIAL_UPDATE_RECEIPT_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-credential-update-receipt-latest.json} "
                    "--require-complete"
                ),
                "blocking_reasons": _strings(record.get("blocking_reasons")),
                "raw_secret_values_allowed": False,
                "secret_redacted": True,
            }
        )
    return {
        "version": "au_p0a_credential_update_action_plan_v1",
        "ready": True,
        "complete": update_receipt_complete,
        "action_required": not update_receipt_complete,
        "action_item_count": len(action_items),
        "action_items": action_items,
        "owner_counts": _owner_counts(action_items),
        "target_env_file": str(contract.get("target_env_file") or ""),
        "next_command": "make au-external-dependency-clearance" if update_receipt_complete else "make au-p0a-env",
        "post_update_validation_sequence": post_update_commands,
        "post_update_validation_command_count": len(post_update_commands),
        "strict_gate_command": (
            "PYTHONPATH=packages/geno_core:apps/api python3 "
            "scripts/verify_au_p0a_credential_update_receipt.py "
            "${GENO_AU_P0A_CREDENTIAL_UPDATE_RECEIPT_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-credential-update-receipt-latest.json} "
            "--require-complete"
        ),
        "redaction_policy": {
            "raw_secret_values_allowed": False,
            "secret_redacted": True,
            "source_payloads_embedded": False,
            "hash_path_status_only": True,
        },
    }


def build_au_p0a_credential_update_receipt(
    *,
    credential_request_path: Path = Path(DEFAULT_CREDENTIAL_REQUEST_PATH),
    env_report_path: Path = Path(DEFAULT_ENV_REPORT_PATH),
    credential_fulfillment_path: Path = Path(DEFAULT_CREDENTIAL_FULFILLMENT_PATH),
    credential_clearance_path: Path = Path(DEFAULT_CREDENTIAL_CLEARANCE_PATH),
    credential_request: dict[str, Any] | None = None,
    env_report: dict[str, Any] | None = None,
    credential_fulfillment: dict[str, Any] | None = None,
    credential_clearance: dict[str, Any] | None = None,
    output_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if credential_request is None:
        credential_request, request_source = _load_or_build_request(credential_request_path, generated_at=generated_at)
    else:
        request_source = {"path": str(credential_request_path), "exists": True, "source": "provided_payload", "errors": []}
    if env_report is None:
        env_report, env_source = _load_env_report(env_report_path)
    else:
        env_source = {"path": str(env_report_path), "exists": True, "source": "provided_payload", "errors": []}
    if credential_fulfillment is None:
        credential_fulfillment, fulfillment_source = _load_or_build_fulfillment(
            credential_fulfillment_path,
            credential_request_path=credential_request_path,
            env_report_path=env_report_path,
            credential_request=credential_request,
            generated_at=generated_at,
        )
    else:
        fulfillment_source = {
            "path": str(credential_fulfillment_path),
            "exists": True,
            "source": "provided_payload",
            "errors": [],
        }
    if credential_clearance is None:
        credential_clearance, clearance_source = _load_or_build_clearance(
            credential_clearance_path,
            credential_request_path=credential_request_path,
            env_report_path=env_report_path,
            credential_fulfillment_path=credential_fulfillment_path,
            credential_request=credential_request,
            credential_fulfillment=credential_fulfillment,
            generated_at=generated_at,
        )
    else:
        clearance_source = {
            "path": str(credential_clearance_path),
            "exists": True,
            "source": "provided_payload",
            "errors": [],
        }

    request_verifier = verify_au_p0a_credential_request_packet(credential_request, path=credential_request_path)
    env_verifier = verify_au_p0a_env_report(env_report, path=env_report_path)
    fulfillment_verifier = verify_au_p0a_credential_fulfillment(
        credential_fulfillment,
        path=credential_fulfillment_path if fulfillment_source.get("source") == "existing_file" else None,
    )
    clearance_verifier = verify_au_p0a_credential_clearance(
        credential_clearance,
        path=credential_clearance_path if clearance_source.get("source") == "existing_file" else None,
    )
    contract = _as_dict(credential_clearance.get("credential_update_contract"))
    env_file = _as_dict(env_report.get("env_file"))
    hygiene = _as_dict(env_file.get("hygiene"))
    records = _required_records(credential_request, credential_fulfillment, env_report)
    required_records = [record for record in records if record.get("required") is True]
    present_required = [record for record in required_records if record.get("present") is True]
    missing_required = [str(record.get("name") or "") for record in required_records if record.get("present") is not True]
    update_receipt_complete = (
        request_verifier.get("status") == "pass"
        and env_verifier.get("status") == "pass"
        and fulfillment_verifier.get("status") == "pass"
        and clearance_verifier.get("status") == "pass"
        and not missing_required
        and credential_fulfillment.get("credentials_fulfilled") is True
        and credential_clearance.get("credential_clearance_ready") is True
        and hygiene.get("hygiene_ready") is True
    )
    post_update_commands = _strings(contract.get("post_update_commands")) or _strings(
        credential_clearance.get("post_update_validation_sequence")
    )
    action_plan = _credential_update_action_plan(
        records=records,
        contract=contract,
        post_update_commands=post_update_commands,
        update_receipt_complete=update_receipt_complete,
    )
    payload: dict[str, Any] = {
        "p0a_credential_update_receipt_version": RECEIPT_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "status": "pass",
        "credential_update_receipt_ready": True,
        "credential_update_receipt_complete": update_receipt_complete,
        "credentials_fulfilled": credential_fulfillment.get("credentials_fulfilled") is True,
        "credential_clearance_ready": credential_clearance.get("credential_clearance_ready") is True,
        "output_path": str(output_path) if output_path else "",
        "credential_update_contract": {
            "version": str(contract.get("version") or ""),
            "target_env_file": str(contract.get("target_env_file") or ""),
            "required_missing_key_count_at_contract_time": int(contract.get("required_missing_key_count") or 0),
            "required_missing_keys_at_contract_time": _strings(contract.get("required_missing_keys")),
            "raw_values_allowed_in_artifacts": contract.get("raw_values_allowed_in_artifacts") is True,
            "allowed_update_surface_ids": [
                str(item.get("id") or "")
                for item in [_as_dict(value) for value in _as_list(contract.get("allowed_update_surfaces"))]
                if str(item.get("id") or "")
            ],
        },
        "source_artifacts": {
            "credential_request": {
                "path": str(credential_request_path),
                "source": request_source,
                "hash_field": "p0a_credential_request_packet_hash",
                "hash": str(credential_request.get("p0a_credential_request_packet_hash") or ""),
            },
            "env_report": {
                "path": str(env_report_path),
                "source": env_source,
                "hash_field": "environment_report_hash",
                "hash": str(env_report.get("environment_report_hash") or ""),
            },
            "credential_fulfillment": {
                "path": str(credential_fulfillment_path),
                "source": fulfillment_source,
                "hash_field": "p0a_credential_fulfillment_hash",
                "hash": str(credential_fulfillment.get("p0a_credential_fulfillment_hash") or ""),
            },
            "credential_clearance": {
                "path": str(credential_clearance_path),
                "source": clearance_source,
                "hash_field": "p0a_credential_clearance_hash",
                "hash": str(credential_clearance.get("p0a_credential_clearance_hash") or ""),
            },
        },
        "verifiers": {
            "credential_request": request_verifier,
            "env_report": env_verifier,
            "credential_fulfillment": fulfillment_verifier,
            "credential_clearance": clearance_verifier,
        },
        "env_file_hygiene": {
            "path": str(env_file.get("path") or hygiene.get("path") or ""),
            "exists": env_file.get("exists") is True,
            "entry_count": int(env_file.get("entry_count") or hygiene.get("entry_count") or 0),
            "git_ignored": hygiene.get("git_ignored"),
            "git_tracked": hygiene.get("git_tracked"),
            "file_mode": str(hygiene.get("file_mode") or ""),
            "permission_safe": hygiene.get("permission_safe") is True,
            "hygiene_ready": hygiene.get("hygiene_ready") is True,
            "errors": _strings(hygiene.get("errors")),
            "warnings": _strings(hygiene.get("warnings")),
            "secret_redacted": True,
        },
        "required_credential_records": records,
        "credential_update_action_plan": action_plan,
        "summary": {
            "credential_update_receipt_ready": True,
            "required_count": len(required_records),
            "present_required_count": len(present_required),
            "missing_required_count": len(missing_required),
            "missing_required": sorted(missing_required),
            "credential_update_action_plan_ready": action_plan["ready"],
            "credential_update_action_required": action_plan["action_required"],
            "credential_update_action_item_count": action_plan["action_item_count"],
            "credential_update_action_owner_counts": action_plan["owner_counts"],
            "credential_update_post_update_validation_command_count": action_plan[
                "post_update_validation_command_count"
            ],
            "env_file_hygiene_ready": hygiene.get("hygiene_ready") is True,
            "credentials_fulfilled": credential_fulfillment.get("credentials_fulfilled") is True,
            "credential_clearance_ready": credential_clearance.get("credential_clearance_ready") is True,
            "credential_update_receipt_complete": update_receipt_complete,
            "next_command": "make au-external-dependency-clearance"
            if update_receipt_complete
            else "make au-p0a-env",
            "raw_secret_values_allowed": False,
        },
        "post_update_validation_sequence": post_update_commands,
        "strict_gate_commands": [
            "make verify-au-p0a-credential-update-receipt",
            "PYTHONPATH=packages/geno_core:apps/api python3 "
            "scripts/verify_au_p0a_credential_update_receipt.py "
            "${GENO_AU_P0A_CREDENTIAL_UPDATE_RECEIPT_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-credential-update-receipt-latest.json} "
            "--require-complete",
        ],
        "runtime_endpoints": {
            "p0a_credential_update_receipt": "GET /v1/p0a-credential-update-receipt/au",
            "p0a_credential_clearance": "GET /v1/p0a-credential-clearance/au",
            "p0a_credential_fulfillment": "GET /v1/p0a-credential-fulfillment/au",
        },
        "redaction_policy": {
            "raw_secret_values_allowed": False,
            "recorded_fields": ["present", "source", "value_length", "sha256_prefix", "secret_redacted"],
            "forbidden_exact_secret_field_count": 5,
            "secret_redacted": True,
        },
    }
    payload["p0a_credential_update_receipt_hash"] = compute_p0a_credential_update_receipt_hash(payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an AU P0a credential update receipt JSON")
    parser.add_argument(
        "--credential-request-path",
        default=os.environ.get("GENO_AU_P0A_CREDENTIAL_REQUEST_OUTPUT_PATH", DEFAULT_CREDENTIAL_REQUEST_PATH),
        help="Path to the AU P0a credential request packet JSON.",
    )
    parser.add_argument(
        "--env-report-path",
        default=os.environ.get("GENO_AU_P0A_ENV_OUTPUT_PATH", DEFAULT_ENV_REPORT_PATH),
        help="Path to the AU P0a environment report JSON.",
    )
    parser.add_argument(
        "--credential-fulfillment-path",
        default=os.environ.get(
            "GENO_AU_P0A_CREDENTIAL_FULFILLMENT_OUTPUT_PATH",
            DEFAULT_CREDENTIAL_FULFILLMENT_PATH,
        ),
        help="Path to the AU P0a credential fulfillment JSON.",
    )
    parser.add_argument(
        "--credential-clearance-path",
        default=os.environ.get("GENO_AU_P0A_CREDENTIAL_CLEARANCE_OUTPUT_PATH", DEFAULT_CREDENTIAL_CLEARANCE_PATH),
        help="Path to the AU P0a credential clearance JSON.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GENO_AU_P0A_CREDENTIAL_UPDATE_RECEIPT_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU P0a credential update receipt JSON.",
    )
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    payload = build_au_p0a_credential_update_receipt(
        credential_request_path=Path(args.credential_request_path),
        env_report_path=Path(args.env_report_path),
        credential_fulfillment_path=Path(args.credential_fulfillment_path),
        credential_clearance_path=Path(args.credential_clearance_path),
        output_path=output_path,
        generated_at=args.generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if payload["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
