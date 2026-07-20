"""Composition root for governed monitoring."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

from geo_core.monitoring.application import MonitoringApplication
from geo_core.monitoring.artifact_evidence import S3RawArtifactVerifier
from geo_core.object_store_config import build_object_store
from geo_core.monitoring.source_contract import CaptureMethod, RawEvidence


def build_monitoring_application() -> MonitoringApplication | None:
    database_url = _secret("GEO_DATABASE_URL")
    if not database_url:
        return None
    from geo_core.monitoring.postgres import PsycopgMonitoringUnitOfWorkFactory

    return MonitoringApplication(
        PsycopgMonitoringUnitOfWorkFactory(database_url),
        artifact_verifier=LazyRawArtifactVerifier(),
    )


class LazyRawArtifactVerifier:
    def verify(
        self,
        *,
        project_id: UUID,
        capture_method: CaptureMethod,
        evidence: RawEvidence,
    ) -> RawEvidence:
        return S3RawArtifactVerifier(build_object_store()).verify(
            project_id=project_id,
            capture_method=capture_method,
            evidence=evidence,
        )


def _secret(name: str) -> str:
    direct = os.getenv(name, "").strip()
    file_name = os.getenv(f"{name}_FILE", "").strip()
    if direct and file_name:
        raise ValueError(f"{name} and {name}_FILE cannot both be configured")
    if file_name:
        return Path(file_name).read_text(encoding="utf-8").strip()
    return direct
