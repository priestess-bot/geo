#!/usr/bin/env python3
"""Build and verify the exact non-B roadmap acceptance register."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "contracts/roadmap/non-b-acceptance-classification-v1.json"
DEFAULT_OUTPUT = (
    ROOT / "docs/engineering/execution-packs/pack-08-acceptance-register.json"
)
CHECKBOX = re.compile(r"^\s*- \[([ xX])\]\s+`([^`]+)`")
TEMPLATE_PREFIXES = ("DOR-", "DOD-")
EVIDENCE_SCHEMA = "non-b-acceptance-register-v2"


class AcceptanceRegisterError(ValueError):
    """Raised when the roadmap and classification contract diverge."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AcceptanceRegisterError(f"cannot read JSON contract: {path}") from exc
    if not isinstance(value, dict):
        raise AcceptanceRegisterError(f"JSON contract must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _roadmap_rows(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        match = CHECKBOX.match(line)
        if match is None:
            continue
        rows.append(
            {
                "check_id": match.group(2),
                "roadmap_line": line_number,
                "roadmap_checked": match.group(1).lower() == "x",
            }
        )
    check_ids = [str(row["check_id"]) for row in rows]
    if len(check_ids) != len(set(check_ids)):
        duplicates = sorted(
            check_id for check_id in set(check_ids) if check_ids.count(check_id) > 1
        )
        raise AcceptanceRegisterError(f"roadmap checklist IDs are duplicated: {duplicates}")
    return rows


def _validate_policy(policy: dict[str, Any], rows: list[dict[str, object]]) -> None:
    expected = policy.get("expected_counts")
    if not isinstance(expected, dict):
        raise AcceptanceRegisterError("classification expected_counts is required")
    ids = {str(row["check_id"]) for row in rows}
    templates = {check_id for check_id in ids if check_id.startswith(TEMPLATE_PREFIXES)}
    implementation = {check_id for check_id in ids if check_id.startswith("IMPL-")}
    acceptance = ids - templates - implementation
    excluded = _string_set(policy, "excluded_b_ids")
    mixed = _string_set(policy, "mixed_atomic_ids")
    blocked_impl = _string_set(policy, "blocked_non_b_impl_ids")
    if excluded & mixed:
        raise AcceptanceRegisterError("excluded and mixed ID sets must be disjoint")
    for label, values in (
        ("excluded", excluded),
        ("mixed", mixed),
        ("blocked implementation", blocked_impl),
    ):
        unknown = sorted(values - ids)
        if unknown:
            raise AcceptanceRegisterError(f"{label} IDs are absent from roadmap: {unknown}")
    if blocked_impl & excluded:
        raise AcceptanceRegisterError("blocked non-B implementation IDs cannot be excluded B")
    observed = {
        "all": len(ids),
        "templates": len(templates),
        "acceptance": len(acceptance),
        "implementation_ledger": len(implementation),
        "roadmap_checked": sum(bool(row["roadmap_checked"]) for row in rows),
        "excluded_b": len(excluded),
        "mixed_atomic": len(mixed),
        "included_non_b": len(ids - templates - excluded),
    }
    if observed != expected:
        raise AcceptanceRegisterError(
            f"classification counts drifted: expected={expected}, observed={observed}"
        )


def _string_set(policy: dict[str, Any], key: str) -> set[str]:
    value = policy.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise AcceptanceRegisterError(f"classification {key} must be a string array")
    if len(value) != len(set(value)):
        raise AcceptanceRegisterError(f"classification {key} cannot contain duplicates")
    return set(value)


def _evidence_for(policy: dict[str, Any], check_id: str) -> list[dict[str, str]]:
    paths: list[str] = []
    groups = policy.get("evidence_groups")
    if not isinstance(groups, list):
        raise AcceptanceRegisterError("classification evidence_groups is required")
    for group in groups:
        if not isinstance(group, dict):
            raise AcceptanceRegisterError("evidence group must be an object")
        prefixes = group.get("prefixes")
        group_paths = group.get("paths")
        if (
            not isinstance(prefixes, list)
            or not isinstance(group_paths, list)
            or any(not isinstance(item, str) for item in [*prefixes, *group_paths])
        ):
            raise AcceptanceRegisterError("evidence group prefixes/paths must be strings")
        if check_id.startswith(tuple(prefixes)):
            paths.extend(group_paths)
    if not paths:
        paths = [str(policy["roadmap"])]
    references: list[dict[str, str]] = []
    for relative in dict.fromkeys(paths):
        path = ROOT / relative
        if not path.is_file():
            raise AcceptanceRegisterError(f"evidence path is not readable: {relative}")
        references.append({"path": relative, "sha256": _sha256(path)})
    return references


def _source_identity(*, output: Path) -> dict[str, str]:
    try:
        relative_output = output.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        relative_output = None
    try:
        inventory = subprocess.check_output(
            [
                "git",
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
                "--",
                ".",
            ],
            cwd=ROOT,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise AcceptanceRegisterError("git source identity is unavailable") from exc
    digest = hashlib.sha256()
    file_count = 0
    for raw_path in sorted(item for item in inventory.split(b"\0") if item):
        relative = raw_path.decode("utf-8")
        if relative_output is not None and relative == relative_output:
            continue
        path = ROOT / relative
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(b"symlink\0")
            digest.update(path.readlink().as_posix().encode("utf-8"))
        elif path.is_file():
            digest.update(b"file\0")
            digest.update(path.read_bytes())
        else:
            digest.update(b"other\0")
        digest.update(b"\0")
        file_count += 1
    return {
        "identity_method": "repository-content-v2",
        "file_count": str(file_count),
        "tree_fingerprint": digest.hexdigest(),
    }


def build_register(
    *, policy_path: Path, output: Path, generated_at: str | None = None
) -> dict[str, Any]:
    policy = _read_json(policy_path)
    roadmap_path = ROOT / str(policy.get("roadmap", ""))
    if not roadmap_path.is_file():
        raise AcceptanceRegisterError("classification roadmap path is invalid")
    rows = _roadmap_rows(roadmap_path)
    _validate_policy(policy, rows)
    excluded = _string_set(policy, "excluded_b_ids")
    mixed = _string_set(policy, "mixed_atomic_ids")
    blocked_impl = _string_set(policy, "blocked_non_b_impl_ids")
    checks: list[dict[str, object]] = []
    for source_row in rows:
        check_id = str(source_row["check_id"])
        checked = bool(source_row["roadmap_checked"])
        if check_id.startswith(TEMPLATE_PREFIXES):
            kind = "template"
            scope = "TEMPLATE"
            local_status = "TEMPLATE"
            acceptance_status = "TEMPLATE"
            remaining = "Instantiate this clause per work package; do not accept it recursively."
        elif check_id.startswith("IMPL-"):
            kind = "implementation_ledger"
            if check_id in excluded:
                scope = "EXCLUDED_B_FOR_CURRENT_ITERATION"
                local_status = "EXCLUDED"
                acceptance_status = "EXCLUDED_B_FOR_CURRENT_ITERATION"
                remaining = "Implement and accept under the independent Board B plan."
            else:
                scope = "INCLUDED_NON_B"
                local_status = "LOCAL_COMPLETE"
                acceptance_status = (
                    "BLOCKED_EXTERNAL" if check_id in blocked_impl else "READY_FOR_REVIEW"
                )
                remaining = (
                    "Real live/production identity evidence and independent verification are required."
                    if check_id in blocked_impl
                    else "Independent verifier must review the current source-bound evidence."
                )
        else:
            kind = "acceptance"
            if check_id in excluded:
                scope = "EXCLUDED_B_FOR_CURRENT_ITERATION"
                local_status = "EXCLUDED"
                acceptance_status = "EXCLUDED_B_FOR_CURRENT_ITERATION"
                remaining = "Implement and accept under the independent Board B plan."
            else:
                scope = "MIXED_ATOMIC" if check_id in mixed else "INCLUDED_NON_B"
                local_status = "LOCAL_COMPLETE"
                acceptance_status = "BLOCKED_EXTERNAL"
                remaining = (
                    "The non-B sub-scope is locally complete; the atomic ID still needs its "
                    "excluded-B dependency, applicable live evidence and independent signature."
                    if check_id in mixed
                    else "Applicable live/human evidence and an independent verifier are still required."
                )
        checks.append(
            {
                **source_row,
                "id_kind": kind,
                "scope_disposition": scope,
                "local_controllable_status": local_status,
                "acceptance_status": acceptance_status,
                "evidence_refs": _evidence_for(policy, check_id),
                "remaining_requirement": remaining,
                "fixture_is_not_live": True,
                "roadmap_checkbox_is_not_derived": checked,
            }
        )
    summary = {
        "all": len(checks),
        "templates": sum(item["id_kind"] == "template" for item in checks),
        "excluded_b": sum(
            item["scope_disposition"] == "EXCLUDED_B_FOR_CURRENT_ITERATION"
            for item in checks
        ),
        "mixed_atomic": sum(item["scope_disposition"] == "MIXED_ATOMIC" for item in checks),
        "included_non_b": sum(
            item["scope_disposition"] in {"INCLUDED_NON_B", "MIXED_ATOMIC"}
            for item in checks
        ),
        "local_gap": sum(
            item["local_controllable_status"] == "LOCAL_GAP" for item in checks
        ),
        "ready_for_review": sum(
            item["acceptance_status"] == "READY_FOR_REVIEW" for item in checks
        ),
        "blocked_external": sum(
            item["acceptance_status"] == "BLOCKED_EXTERNAL" for item in checks
        ),
    }
    register: dict[str, Any] = {
        "schema_version": EVIDENCE_SCHEMA,
        "generated_at": generated_at
        or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "roadmap": str(policy["roadmap"]),
        "roadmap_sha256": _sha256(roadmap_path),
        "classification": policy_path.resolve().relative_to(ROOT).as_posix(),
        "classification_sha256": _sha256(policy_path),
        "source_identity": _source_identity(output=output),
        "summary": summary,
        "checks": checks,
    }
    register["register_hash"] = _canonical_hash(register)
    return register


def export_register(*, policy_path: Path, output: Path) -> dict[str, Any]:
    register = build_register(policy_path=policy_path, output=output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(register, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return register


def verify_register(*, policy_path: Path, register_path: Path) -> dict[str, object]:
    stored = _read_json(register_path)
    stored_hash = stored.get("register_hash")
    without_hash = dict(stored)
    without_hash.pop("register_hash", None)
    if not isinstance(stored_hash, str) or stored_hash != _canonical_hash(without_hash):
        raise AcceptanceRegisterError("acceptance register canonical hash is invalid")
    generated_at = stored.get("generated_at")
    if not isinstance(generated_at, str):
        raise AcceptanceRegisterError("acceptance register generated_at is invalid")
    expected = build_register(
        policy_path=policy_path,
        output=register_path,
        generated_at=generated_at,
    )
    if stored != expected:
        raise AcceptanceRegisterError(
            "acceptance register is stale for the roadmap, evidence or source tree"
        )
    return {
        "register_hash": stored_hash,
        "check_count": len(stored["checks"]),
        "local_gap_count": stored["summary"]["local_gap"],
        "blocked_external_count": stored["summary"]["blocked_external"],
        "excluded_b_count": stored["summary"]["excluded_b"],
        "source_identity": stored["source_identity"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("output", type=Path, nargs="?", default=DEFAULT_OUTPUT)
    verify = commands.add_parser("verify")
    verify.add_argument("register", type=Path, nargs="?", default=DEFAULT_OUTPUT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        if arguments.command == "export":
            result = export_register(
                policy_path=arguments.policy.resolve(), output=arguments.output.resolve()
            )
            summary = result["summary"]
            print(json.dumps({"register_hash": result["register_hash"], **summary}, sort_keys=True))
        else:
            result = verify_register(
                policy_path=arguments.policy.resolve(),
                register_path=arguments.register.resolve(),
            )
            print(json.dumps(result, sort_keys=True))
    except AcceptanceRegisterError as exc:
        raise SystemExit(str(exc)) from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
