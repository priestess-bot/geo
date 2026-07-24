from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.backup_envelope import BackupSecurityError
from scripts.non_b_business_consistency import validate_business_consistency_manifest


ROOT = Path(__file__).resolve().parents[3]
REQUIRED = {
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
EMPTY_HASH = hashlib.sha256(b"").hexdigest()


def test_manifest_validates_every_required_relation_and_scope_rollup() -> None:
    value = _manifest()
    value["tables"]["prompt_programs"] = _summary(
        {"10000000-0000-4000-8000-000000000001": (2, "1" * 64)}
    )

    result = validate_business_consistency_manifest(
        value, expected_revision="0030_synthetic_lab"
    )

    assert result["tables"]["prompt_programs"]["total_count"] == 2


def test_manifest_rejects_missing_table_bad_rollup_and_nonzero_invariant() -> None:
    missing = _manifest()
    del missing["tables"]["prompt_programs"]
    with pytest.raises(BackupSecurityError, match="coverage"):
        validate_business_consistency_manifest(missing)

    inconsistent = _manifest()
    inconsistent["tables"]["prompt_programs"]["total_count"] = 1
    with pytest.raises(BackupSecurityError, match="rollup"):
        validate_business_consistency_manifest(inconsistent)

    violated = _manifest()
    violated["invariant_violations"] = {"approved_latest_lineage": 1}
    with pytest.raises(BackupSecurityError, match="nonzero"):
        validate_business_consistency_manifest(violated)


def test_sql_discovers_all_non_b_families_and_hashes_rows_before_aggregation() -> None:
    sql = (ROOT / "scripts" / "non_b_business_consistency.sql").read_text(
        encoding="utf-8"
    )

    assert "table_name = 'prompt_programs'" in sql
    for family in (
        "model_gateway",
        "synthetic_lab",
        "sampling",
        "workflow_c",
        "recommendation",
    ):
        assert f"table_name LIKE '{family}\\_%'" in sql
    assert "to_jsonb(source_row)::text" in sql
    assert "GROUP BY project_id" in sql
    assert "ORDER BY scope.scope_id COLLATE \"C\"" in sql
    assert "geo-non-b-business-consistency-v1" in sql


def _manifest() -> dict[str, object]:
    return {
        "invariant_violations": {},
        "migration_revision": "0030_synthetic_lab",
        "schema_version": "geo-non-b-business-consistency-v1",
        "tables": {name: _summary({}) for name in REQUIRED},
    }


def _summary(scopes: dict[str, tuple[int, str]]) -> dict[str, object]:
    parts = [f"{scope}:{count}:{digest}" for scope, (count, digest) in sorted(scopes.items())]
    return {
        "aggregate_sha256": hashlib.sha256("\n".join(parts).encode("ascii")).hexdigest(),
        "scopes": {
            scope: {"row_count": count, "rows_sha256": digest}
            for scope, (count, digest) in scopes.items()
        },
        "total_count": sum(count for count, _digest in scopes.values()),
    }
