"""Stored result projection for encrypted manual-import previews."""

from __future__ import annotations

from dataclasses import dataclass

from geo_core.synthetic_lab.manual_import_artifacts import ManualImportArtifactRef
from geo_core.synthetic_lab.manual_import_preview import ManualImportPreview


@dataclass(frozen=True, kw_only=True)
class StoredManualImportPreview:
    preview: ManualImportPreview
    artifact: ManualImportArtifactRef
    status: str
    version: int
    row_count: int
    selectable_count: int
    blocked_count: int
    replayed: bool = False


StoredManualImportPreview.__module__ = "geo_core.synthetic_lab.postgres_manual_import"


__all__ = ["StoredManualImportPreview"]
