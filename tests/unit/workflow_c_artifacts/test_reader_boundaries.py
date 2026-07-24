from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from geo_core.sampling import SamplingRuleViolation
from geo_core.secrets import EnvelopeCipher, MasterKeyring
from geo_core.workflow_c_artifacts.reader import (
    PostgresWorkflowCManualArtifactReader,
    WorkflowCManualArtifactReadRequest,
)


NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
PROJECT_ID = UUID("cc200000-0000-0000-0000-000000000001")
ARTIFACT_ID = UUID("cc200000-0000-0000-0000-000000000002")


class _Cursor:
    def __init__(self, row) -> None:
        self._row = row

    def fetchone(self):
        return self._row


class _Connection:
    def __init__(self, row) -> None:
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, *_values):
        return None

    def execute(self, statement: str, _parameters=None):
        if "set_config" in statement:
            return _Cursor(None)
        return _Cursor(self.row)


class _Objects:
    def __init__(self) -> None:
        self.reads = 0

    def get_s3_uri(self, **_values):
        self.reads += 1
        raise AssertionError("tombstoned artifact must not reach object storage")


def test_tombstoned_artifact_is_rejected_before_any_object_read() -> None:
    row = {
        "status": "tombstoned",
        "dek_status": "destroyed",
        "expires_at": NOW + timedelta(days=1),
        "classification": "restricted_manual_evidence",
        "audience": "admin_only",
        "export_allowed": False,
        "raw_retained": False,
    }
    objects = _Objects()
    reader = PostgresWorkflowCManualArtifactReader(
        connect=lambda: _Connection(row),
        cipher=EnvelopeCipher(MasterKeyring(keys={1: b"W" * 32}, active_version=1)),
        object_store=objects,
        clock=lambda: NOW,
    )
    with pytest.raises(SamplingRuleViolation, match="not eligible"):
        reader.load(
            WorkflowCManualArtifactReadRequest(
                project_id=PROJECT_ID,
                artifact_id=ARTIFACT_ID,
                expected_manifest_hash="a" * 64,
                expected_content_hash="b" * 64,
            )
        )
    assert objects.reads == 0


def test_project_export_source_has_no_manual_artifact_reader() -> None:
    root = Path(__file__).resolve().parents[3]
    source = (
        root / "packages/geo_core/geo_core/project_exports/postgres_source.py"
    ).read_text(encoding="utf-8")
    assert "workflow_c_manual_artifacts" not in source
    assert "workflow_c_artifact_deks" not in source
    assert "restricted_manual_evidence" not in source
