"""Deterministic artifact packaging tests for F027."""

from __future__ import annotations

from datetime import UTC, datetime
import io
import zipfile
from uuid import uuid4

from geo_core.project_exports.archive import archive_project_export
from geo_core.project_exports.bundle import (
    ExportFile,
    ProjectExportBundle,
    ProjectExportManifest,
)


def test_f027_unit_01_zip_is_deterministic_and_contains_sorted_bundle_files() -> None:
    manifest = ProjectExportManifest(
        audience="admin",
        project_id=uuid4(),
        campaign_id=None,
        generated_at=datetime(2026, 7, 19, tzinfo=UTC),
        files=(),
    )
    first = ProjectExportBundle(
        manifest,
        (
            ExportFile("z.csv", "text/csv", b"z\r\n"),
            ExportFile("a.json", "application/json", b"{}"),
        ),
    )
    second = ProjectExportBundle(manifest, tuple(reversed(first.files)))

    left = archive_project_export(first)
    right = archive_project_export(second)

    assert left == right
    with zipfile.ZipFile(io.BytesIO(left.content)) as archive:
        assert archive.namelist() == ["a.json", "z.csv"]
        assert archive.read("a.json") == b"{}"
        assert all(item.date_time == (1980, 1, 1, 0, 0, 0) for item in archive.infolist())
