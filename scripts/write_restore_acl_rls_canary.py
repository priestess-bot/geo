#!/usr/bin/env python3
"""Validate and write the non-owner PostgreSQL restore ACL/RLS canary."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.backup_envelope import (  # noqa: E402
    BackupSecurityError,
    atomic_write,
    canonical_json,
)


SCHEMA_VERSION = "geo-restore-acl-rls-canary-v1"
EXPECTED_ROLES = {
    "geo_restore_canary_app": False,
    "geo_restore_canary_worker": True,
    "geo_restore_canary_readonly": False,
}


def write_canary(*, project_id: str, evidence: Path, output: Path) -> dict[str, object]:
    try:
        canonical_project_id = str(UUID(project_id))
    except (TypeError, ValueError, AttributeError):
        raise BackupSecurityError("restore ACL/RLS project identifier is invalid") from None

    records = _parse_records(evidence.read_text(encoding="ascii"))
    if set(records) != set(EXPECTED_ROLES):
        raise BackupSecurityError("restore ACL/RLS role evidence is incomplete")

    normalized: dict[str, dict[str, bool]] = {}
    for role, expects_worker_dispatch in EXPECTED_ROLES.items():
        record = records[role]
        expected = {
            "can_login": False,
            "can_create_role": False,
            "is_superuser": False,
            "bypass_rls": False,
            "inherits_roles": False,
            "member_of_expected_group": True,
            "scoped_project_visible": True,
            "empty_scope_hidden": True,
            "worker_outbox_execute": expects_worker_dispatch,
        }
        if record != expected:
            raise BackupSecurityError("restore ACL/RLS canary assertion failed")
        normalized[role] = record

    receipt: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "project_id": canonical_project_id,
        "roles": normalized,
        "role_grants_restored": True,
        "rls_scoped_visibility_verified": True,
        "unscoped_visibility_denied": True,
        "worker_dispatch_privilege_isolated": True,
    }
    atomic_write(output, canonical_json(receipt) + b"\n")
    return receipt


def validate_canary(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {
        "project_id",
        "role_grants_restored",
        "rls_scoped_visibility_verified",
        "roles",
        "schema_version",
        "unscoped_visibility_denied",
        "worker_dispatch_privilege_isolated",
    }:
        raise BackupSecurityError("restore ACL/RLS receipt is invalid")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise BackupSecurityError("restore ACL/RLS receipt is invalid")
    try:
        canonical_project_id = str(UUID(value["project_id"]))
    except (KeyError, TypeError, ValueError, AttributeError):
        raise BackupSecurityError("restore ACL/RLS receipt is invalid") from None
    if canonical_project_id != value["project_id"]:
        raise BackupSecurityError("restore ACL/RLS receipt is invalid")
    roles = value.get("roles")
    if not isinstance(roles, dict) or set(roles) != set(EXPECTED_ROLES):
        raise BackupSecurityError("restore ACL/RLS receipt is invalid")
    for role, expected_dispatch in EXPECTED_ROLES.items():
        record = roles[role]
        if not isinstance(record, dict) or record != {
            "can_login": False,
            "can_create_role": False,
            "is_superuser": False,
            "bypass_rls": False,
            "inherits_roles": False,
            "member_of_expected_group": True,
            "scoped_project_visible": True,
            "empty_scope_hidden": True,
            "worker_outbox_execute": expected_dispatch,
        }:
            raise BackupSecurityError("restore ACL/RLS receipt is invalid")
    for key in (
        "role_grants_restored",
        "rls_scoped_visibility_verified",
        "unscoped_visibility_denied",
        "worker_dispatch_privilege_isolated",
    ):
        if value.get(key) is not True:
            raise BackupSecurityError("restore ACL/RLS receipt is invalid")
    return value


def _parse_records(raw: str) -> dict[str, dict[str, bool]]:
    records: dict[str, dict[str, bool]] = {}
    keys = (
        "can_login",
        "can_create_role",
        "is_superuser",
        "bypass_rls",
        "inherits_roles",
        "member_of_expected_group",
        "scoped_project_visible",
        "empty_scope_hidden",
        "worker_outbox_execute",
    )
    for line in raw.splitlines():
        fields = line.split("|")
        if len(fields) != len(keys) + 1 or not fields[0]:
            raise BackupSecurityError("restore ACL/RLS canary evidence is invalid")
        role = fields[0]
        if role in records:
            raise BackupSecurityError("restore ACL/RLS canary evidence is invalid")
        values: dict[str, bool] = {}
        for key, value in zip(keys, fields[1:], strict=True):
            if value not in {"t", "f"}:
                raise BackupSecurityError("restore ACL/RLS canary evidence is invalid")
            values[key] = value == "t"
        records[role] = values
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write a verified non-owner PostgreSQL restore ACL/RLS canary receipt."
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        write_canary(project_id=args.project_id, evidence=args.evidence, output=args.output)
    except (BackupSecurityError, OSError):
        print("restore ACL/RLS canary error: verification evidence is invalid", file=sys.stderr)
        return 2
    print(f"restore ACL/RLS canary written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
