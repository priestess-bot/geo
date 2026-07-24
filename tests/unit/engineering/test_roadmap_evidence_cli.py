from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from geo_core.engineering.evidence_manifest import (
    EvidenceManifestError,
    RoadmapEvidenceManifest,
)
from scripts.roadmap_evidence_manifest import export_schema, verify_manifest


def _manifest() -> RoadmapEvidenceManifest:
    return RoadmapEvidenceManifest(
        schema_version="roadmap-evidence-v1",
        roadmap_id="GEO-next-phase-six-month-roadmap-2026-07-21",
        stage="M0",
        environment_fingerprint="unit-test:python-3.12",
        generated_at=datetime(2026, 7, 23, tzinfo=UTC),
        git_commit="1" * 40,
        included_workstreams=("A", "C", "D"),
        excluded_workstreams=("B",),
        checks=(),
    ).with_hash()


def _json_default(value: object) -> object:
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    enum_value = getattr(value, "value", None)
    if enum_value is not None:
        return enum_value
    raise TypeError(type(value).__name__)


def test_cli_contract_exports_schema_and_verifies_hashed_manifest(tmp_path: Path) -> None:
    schema_path = tmp_path / "schema.json"
    manifest_path = tmp_path / "manifest.json"
    export_schema(schema_path)
    manifest_path.write_text(
        json.dumps(asdict(_manifest()), default=_json_default), encoding="utf-8"
    )

    result = verify_manifest(manifest_path)

    assert json.loads(schema_path.read_text(encoding="utf-8"))["title"] == (
        "RoadmapEvidenceManifest"
    )
    assert result["accepted_check_count"] == 0
    assert result["acceptance_ready"] is False
    assert result["excluded_workstreams"] == ["B"]


def test_checked_in_schema_matches_the_runtime_contract(tmp_path: Path) -> None:
    generated = tmp_path / "schema.json"
    export_schema(generated)
    checked_in = (
        Path(__file__).resolve().parents[3]
        / "contracts"
        / "roadmap"
        / "roadmap-evidence-manifest-v1.schema.json"
    )

    assert generated.read_bytes() == checked_in.read_bytes()


def test_manifest_rejects_unknown_nested_fields(tmp_path: Path) -> None:
    payload = asdict(_manifest())
    payload["checks"] = [{"claimed_accepted": True}]
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(payload, default=_json_default), encoding="utf-8"
    )

    with pytest.raises(EvidenceManifestError, match="unknown fields.*checks"):
        verify_manifest(manifest_path)


def test_cli_contract_rejects_tampered_manifest(tmp_path: Path) -> None:
    payload = asdict(_manifest())
    payload["stage"] = "M2"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(payload, default=_json_default), encoding="utf-8")

    with pytest.raises(EvidenceManifestError, match="manifest hash"):
        verify_manifest(manifest_path)
