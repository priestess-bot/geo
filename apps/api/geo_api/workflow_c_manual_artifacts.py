"""Server-owned artifact lineage for governed manual sampling evidence."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from threading import RLock
from typing import Protocol
from uuid import UUID

from geo_core.sampling import SamplingRuleViolation
from geo_core.sampling.manual_artifact_governance import (
    StrictManualArtifactGovernance,
    wipe_bytearray,
)
from geo_core.sampling.manual_artifact_storage import (
    WorkflowCManualArtifactReceipt as ManualArtifactReceipt,
)


class ManualArtifactWriter(Protocol):
    def write(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        task_id: UUID,
        artifact_manifest_id: UUID,
        capture_session_id: UUID,
        evidence_kind: str,
        content_type: str,
        content: bytearray,
        governance_policy_key: str,
        pre_redacted_attestation: bool,
        activate: bool = True,
    ) -> ManualArtifactReceipt: ...

    def cleanup_staged(self, *, project_id: UUID, artifact_manifest_id: UUID) -> None: ...


class InMemoryManualArtifactWriter:
    """Test-only writer that still forbids raw or unredacted persistence."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._objects: dict[str, bytes] = {}
        self._governance = StrictManualArtifactGovernance()

    def write(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        task_id: UUID,
        artifact_manifest_id: UUID,
        capture_session_id: UUID,
        evidence_kind: str,
        content_type: str,
        content: bytearray,
        governance_policy_key: str,
        pre_redacted_attestation: bool,
        activate: bool = True,
    ) -> ManualArtifactReceipt:
        governed = None
        try:
            governed = self._governance.govern(
                evidence_kind=evidence_kind,
                content_type=content_type,
                content=content,
                governance_policy_key=governance_policy_key,
                pre_redacted_attestation=pre_redacted_attestation,
            )
            manifest = _canonical_json(
                {
                    "schema_version": "workflow-c-manual-evidence-test-manifest-v2",
                    "project_id": str(project_id),
                    "run_id": str(run_id),
                    "task_id": str(task_id),
                    "artifact_id": str(artifact_manifest_id),
                    "capture_session_id": str(capture_session_id),
                    "evidence_kind": evidence_kind,
                    "source_content_type": governed.source_content_type,
                    "persisted_content_type": governed.persisted_content_type,
                    "source_content_hash": governed.source_content_hash,
                    "persisted_content_hash": governed.persisted_content_hash,
                    "governance_policy_hash": governed.governance_policy_hash,
                    "redactor_version_hash": governed.redactor_version_hash,
                    "scanner_version_hash": governed.scanner_version_hash,
                    "pii_finding_count": governed.pii_finding_count,
                    "secret_finding_count": governed.secret_finding_count,
                    "redaction_assurance": governed.redaction_assurance,
                    "classification": governed.classification,
                    "audience": governed.audience,
                    "export_allowed": governed.export_allowed,
                    "raw_retained": governed.raw_retained,
                }
            )
            manifest_hash = hashlib.sha256(manifest).hexdigest()
            prefix = f"{project_id}/workflow-c/manual/{artifact_manifest_id}"
            values = {
                f"{prefix}/redacted": bytes(governed.payload),
                f"{prefix}/manifest.json": manifest,
            }
            with self._lock:
                for key, value in values.items():
                    existing = self._objects.get(key)
                    if existing is not None and existing != value:
                        raise SamplingRuleViolation(
                            "manual evidence artifact identity conflict"
                        )
                    self._objects[key] = value
            return ManualArtifactReceipt(
                artifact_manifest_id=artifact_manifest_id,
                artifact_manifest_hash=manifest_hash,
                artifact_content_hash=governed.persisted_content_hash,
                governance_policy_hash=governed.governance_policy_hash,
                capture_session_id=capture_session_id,
            )
        finally:
            wipe_bytearray(content)
            if governed is not None:
                wipe_bytearray(governed.payload)

    def cleanup_staged(self, *, project_id: UUID, artifact_manifest_id: UUID) -> None:
        # In-memory artifacts are test-only and have no independently accessible
        # staged state to clean up.
        return None

    def objects_for_test(self) -> dict[str, bytes]:
        with self._lock:
            return dict(self._objects)


class UnavailableManualArtifactWriter:
    """Production default: imports remain closed until restricted storage is mounted."""

    def write(self, **_values: object) -> ManualArtifactReceipt:
        raise SamplingRuleViolation(
            "manual evidence requires a restricted encrypted artifact governor"
        )

    def cleanup_staged(self, **_values: object) -> None:
        return None


def decode_manual_artifact(value: str) -> bytearray:
    try:
        return bytearray(base64.b64decode(value, validate=True))
    except (ValueError, binascii.Error) as error:
        raise SamplingRuleViolation(
            "manual evidence content is not valid base64"
        ) from error


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


__all__ = [
    "InMemoryManualArtifactWriter",
    "ManualArtifactReceipt",
    "ManualArtifactWriter",
    "UnavailableManualArtifactWriter",
    "decode_manual_artifact",
]
