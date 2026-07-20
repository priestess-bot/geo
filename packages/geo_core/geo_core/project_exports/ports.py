"""Adapter boundaries for the later DB/job/object-store implementation of F027."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from geo_core.project_exports.bundle import ProjectExportBundle
from geo_core.project_exports.contracts import (
    AdminProjectExportInput,
    CustomerLatestApprovedProjectExportInput,
    ProjectExportScope,
)


class ProjectExportSource(Protocol):
    """Load only public, scope-checked rows inside the caller's DB/RLS transaction."""

    def load_admin(self, scope: ProjectExportScope) -> AdminProjectExportInput: ...

    def load_customer_latest_approved(
        self, scope: ProjectExportScope
    ) -> CustomerLatestApprovedProjectExportInput:
        """Load one approved result per F023 partition.

        The adapter partitions by Campaign, Protocol, window, source-stratum hash,
        and query-cluster key, then orders by approved_at, computed_at, and report
        UUID descending. RLS and customer membership remain active in that query.
        """
        ...


@dataclass(frozen=True)
class StoredProjectExport:
    artifact_uri: str
    manifest_hash: str


class ProjectExportBundleSink(Protocol):
    """Persist a completed bundle after a future worker has rendered it."""

    def store(self, bundle: ProjectExportBundle) -> StoredProjectExport: ...
