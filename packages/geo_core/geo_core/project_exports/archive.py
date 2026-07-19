"""Deterministic ZIP packaging for project export bundles."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import zipfile

from geo_core.project_exports.bundle import ProjectExportBundle


@dataclass(frozen=True)
class ProjectExportArchive:
    content: bytes
    content_hash: str
    byte_count: int
    file_count: int


def archive_project_export(bundle: ProjectExportBundle) -> ProjectExportArchive:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_STORED) as archive:
        for item in sorted(bundle.files, key=lambda value: value.path):
            info = zipfile.ZipInfo(item.path, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, item.content)
    content = buffer.getvalue()
    return ProjectExportArchive(
        content=content,
        content_hash=hashlib.sha256(content).hexdigest(),
        byte_count=len(content),
        file_count=len(bundle.files),
    )
