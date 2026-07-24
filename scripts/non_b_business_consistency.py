"""Validate deterministic per-scope PostgreSQL consistency manifests."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import re

from scripts.backup_envelope import BackupSecurityError


SCHEMA_VERSION = "geo-non-b-business-consistency-v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9]{4}_[a-z0-9_]+$")
_RELATION = re.compile(
    r"^(?:prompt_programs|(?:prompt_program|model_gateway|synthetic_lab|sampling|"
    r"workflow_c|recommendation)_[a-z0-9_]+)$"
)
_SCOPE = re.compile(r"^(?:__global__|[0-9a-f]{8}-[0-9a-f-]{27})$")
_REQUIRED_RELATIONS = frozenset(
    {
        "model_gateway_call_attempts",
        "model_gateway_job_admissions",
        "model_gateway_runtime_manifests",
        "model_gateway_runtime_options",
        "model_gateway_terminal_events",
        "prompt_program_bindings",
        "prompt_program_releases",
        "prompt_programs",
        "synthetic_lab_aggregate_versions",
        "synthetic_lab_artifact_governance_decisions",
        "synthetic_lab_execution_results",
        "synthetic_lab_execution_tasks",
        "synthetic_lab_manual_import_manifests",
        "synthetic_lab_terminal_results",
    }
)


def validate_business_consistency_manifest(
    value: object, *, expected_revision: str | None = None
) -> dict[str, object]:
    root = _mapping(value, "business consistency manifest")
    if set(root) != {
        "invariant_violations",
        "migration_revision",
        "schema_version",
        "tables",
    } or root["schema_version"] != SCHEMA_VERSION:
        raise BackupSecurityError("business consistency manifest structure is invalid")
    revision = root["migration_revision"]
    if (
        not isinstance(revision, str)
        or _REVISION.fullmatch(revision) is None
        or (expected_revision is not None and revision != expected_revision)
    ):
        raise BackupSecurityError("business consistency migration revision is invalid")
    tables = _mapping(root["tables"], "business consistency tables")
    if not _REQUIRED_RELATIONS <= set(tables):
        raise BackupSecurityError("business consistency required relation coverage is incomplete")
    normalized_tables: dict[str, object] = {}
    for relation, raw_summary in sorted(tables.items()):
        if not isinstance(relation, str) or _RELATION.fullmatch(relation) is None:
            raise BackupSecurityError("business consistency relation identity is invalid")
        normalized_tables[relation] = _table_summary(raw_summary)
    violations = _mapping(
        root["invariant_violations"], "business consistency invariant violations"
    )
    normalized_violations: dict[str, int] = {}
    for name, count in sorted(violations.items()):
        if (
            not isinstance(name, str)
            or re.fullmatch(r"[a-z][a-z0-9_]{2,127}", name) is None
        ):
            raise BackupSecurityError("business consistency invariant identity is invalid")
        normalized_violations[name] = _nonnegative(count)
    if any(normalized_violations.values()):
        raise BackupSecurityError("business consistency invariant violations are nonzero")
    return {
        "invariant_violations": normalized_violations,
        "migration_revision": revision,
        "schema_version": SCHEMA_VERSION,
        "tables": normalized_tables,
    }


def parse_business_consistency_json(
    raw: str, *, expected_revision: str | None = None
) -> dict[str, object]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        raise BackupSecurityError("business consistency JSON is invalid") from None
    return validate_business_consistency_manifest(
        value, expected_revision=expected_revision
    )


def _table_summary(value: object) -> dict[str, object]:
    summary = _mapping(value, "business consistency table summary")
    if set(summary) != {"aggregate_sha256", "scopes", "total_count"}:
        raise BackupSecurityError("business consistency table summary is invalid")
    total = _nonnegative(summary["total_count"])
    digest = summary["aggregate_sha256"]
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise BackupSecurityError("business consistency table digest is invalid")
    scopes = _mapping(summary["scopes"], "business consistency scopes")
    normalized_scopes: dict[str, object] = {}
    calculated_total = 0
    aggregate_parts: list[str] = []
    for scope, raw_scope in sorted(scopes.items()):
        if not isinstance(scope, str) or _SCOPE.fullmatch(scope) is None:
            raise BackupSecurityError("business consistency scope identity is invalid")
        scope_summary = _mapping(raw_scope, "business consistency scope summary")
        if set(scope_summary) != {"row_count", "rows_sha256"}:
            raise BackupSecurityError("business consistency scope summary is invalid")
        count = _nonnegative(scope_summary["row_count"])
        rows_hash = scope_summary["rows_sha256"]
        if not isinstance(rows_hash, str) or _SHA256.fullmatch(rows_hash) is None:
            raise BackupSecurityError("business consistency scope digest is invalid")
        calculated_total += count
        aggregate_parts.append(f"{scope}:{count}:{rows_hash}")
        normalized_scopes[scope] = {"row_count": count, "rows_sha256": rows_hash}
    expected_digest = hashlib.sha256("\n".join(aggregate_parts).encode("ascii")).hexdigest()
    if calculated_total != total or digest != expected_digest:
        raise BackupSecurityError("business consistency table rollup is inconsistent")
    return {
        "aggregate_sha256": digest,
        "scopes": normalized_scopes,
        "total_count": total,
    }


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise BackupSecurityError(f"{label} is invalid")
    return value


def _nonnegative(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise BackupSecurityError("business consistency count is invalid")
    return value


__all__ = [
    "parse_business_consistency_json",
    "SCHEMA_VERSION",
    "validate_business_consistency_manifest",
]
