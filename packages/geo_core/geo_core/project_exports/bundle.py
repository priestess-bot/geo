"""Deterministic in-memory JSON/CSV bundles for project-level audit data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
from uuid import UUID

from geo_core.project_exports.constants import (
    DATA_JSON_PATH,
    MANIFEST_PATH,
    METRIC_METHOD_VERSION,
    PROJECT_EXPORT_MANIFEST_SCHEMA_VERSION,
    PROJECT_EXPORT_SCHEMA_VERSION,
)
from geo_core.project_exports.contracts import ProjectExportInput, ProjectExportRuleViolation
from geo_core.project_exports.csv_serialization import csv_projections, render_csv
from geo_core.project_exports.schemas import CSV_SCHEMAS, ColumnSchema
from geo_core.project_exports.serialization import (
    canonical_json_bytes,
    json_projection,
    sort_export_data,
    time_text,
)


@dataclass(frozen=True)
class ExportFile:
    path: str
    media_type: str
    content: bytes


@dataclass(frozen=True)
class ExportFileDescriptor:
    path: str
    media_type: str
    schema_version: str
    row_count: int
    byte_count: int
    sha256: str
    columns: ColumnSchema

    def canonical_value(self) -> dict[str, object]:
        return {
            "path": self.path,
            "media_type": self.media_type,
            "schema_version": self.schema_version,
            "row_count": self.row_count,
            "byte_count": self.byte_count,
            "sha256": self.sha256,
            "columns": [
                {"name": name, "type": value_type} for name, value_type in self.columns
            ],
        }


@dataclass(frozen=True)
class ProjectExportManifest:
    audience: str
    project_id: UUID
    campaign_id: UUID | None
    generated_at: datetime
    files: tuple[ExportFileDescriptor, ...]

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema_version": PROJECT_EXPORT_MANIFEST_SCHEMA_VERSION,
            "export_schema_version": PROJECT_EXPORT_SCHEMA_VERSION,
            "audience": self.audience,
            "scope": {
                "project_id": str(self.project_id),
                "campaign_id": str(self.campaign_id) if self.campaign_id else None,
            },
            "generated_at": time_text(self.generated_at),
            "metric_method_version": METRIC_METHOD_VERSION,
            "files": [item.canonical_value() for item in self.files],
        }

    @property
    def canonical_hash(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self.canonical_payload())).hexdigest()

    def render(self) -> bytes:
        value = self.canonical_payload()
        value["manifest_hash"] = self.canonical_hash
        return canonical_json_bytes(value)


@dataclass(frozen=True)
class ProjectExportBundle:
    manifest: ProjectExportManifest
    files: tuple[ExportFile, ...]

    def file(self, path: str) -> bytes:
        for item in self.files:
            if item.path == path:
                return item.content
        raise KeyError(path)

    def as_mapping(self) -> dict[str, bytes]:
        return {item.path: item.content for item in self.files}


def build_project_export(
    source: ProjectExportInput, *, generated_at: datetime
) -> ProjectExportBundle:
    """Render a deterministic file set from a validated typed input."""
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ProjectExportRuleViolation("export generated_at must be timezone-aware")
    sorted_data = sort_export_data(source)
    json_value, json_row_count = json_projection(source, sorted_data)
    data_files: list[tuple[ExportFile, int, ColumnSchema]] = [
        (
            ExportFile(DATA_JSON_PATH, "application/json", canonical_json_bytes(json_value)),
            json_row_count,
            (),
        )
    ]
    rows_by_path = csv_projections(sorted_data)
    for path in sorted(CSV_SCHEMAS):
        rows = rows_by_path[path]
        data_files.append(
            (
                ExportFile(
                    path,
                    "text/csv; charset=utf-8",
                    render_csv(CSV_SCHEMAS[path], rows),
                ),
                len(rows),
                CSV_SCHEMAS[path],
            )
        )
    data_files.sort(key=lambda item: item[0].path)
    descriptors = tuple(
        ExportFileDescriptor(
            path=file.path,
            media_type=file.media_type,
            schema_version=PROJECT_EXPORT_SCHEMA_VERSION,
            row_count=row_count,
            byte_count=len(file.content),
            sha256=hashlib.sha256(file.content).hexdigest(),
            columns=columns,
        )
        for file, row_count, columns in data_files
    )
    manifest = ProjectExportManifest(
        audience=source.audience.value,
        project_id=source.scope.project_id,
        campaign_id=source.scope.campaign_id,
        generated_at=generated_at,
        files=descriptors,
    )
    files = tuple(item[0] for item in data_files) + (
        ExportFile(MANIFEST_PATH, "application/json", manifest.render()),
    )
    return ProjectExportBundle(manifest=manifest, files=files)


__all__ = [
    "CSV_SCHEMAS",
    "ExportFile",
    "ExportFileDescriptor",
    "ProjectExportBundle",
    "ProjectExportManifest",
    "build_project_export",
    "canonical_json_bytes",
]
