"""Governed manual evidence control for the Workflow C memory adapter."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import hashlib
from threading import RLock
from uuid import UUID

from geo_api.workflow_c_manual_artifacts import (
    ManualArtifactWriter,
    UnavailableManualArtifactWriter,
    decode_manual_artifact,
)
from geo_api.workflow_c_sampling_contracts import (
    ReviewManualEvidenceRequest,
    SubmitManualEvidenceRequest,
)
from geo_api.workflow_c_sampling_ids import sampling_command_id
from geo_core.sampling import (
    CaptureMethod,
    InMemorySamplingStore,
    ManualCaptureDevice,
    ManualEvidenceImport,
    ManualEvidenceKind,
    ManualEvidenceStatus,
    SamplingApplication,
    SamplingConflict,
    SamplingNotFound,
    commit_manual_evidence,
    decide_manual_evidence,
)
from geo_core.sampling.lifecycle import AttemptEnqueueResult
from geo_core.sampling.manual_artifact_governance import wipe_bytearray


class WorkflowCManualEvidenceControl:
    def __init__(
        self,
        *,
        store: InMemorySamplingStore,
        application: SamplingApplication,
        clock: Callable[[], datetime],
        artifact_writer: ManualArtifactWriter | None = None,
        enqueue_attempt: Callable[..., AttemptEnqueueResult] | None = None,
    ) -> None:
        self._store = store
        self._application = application
        self._enqueue_attempt = enqueue_attempt or application.enqueue_attempt
        self._artifact_writer = artifact_writer or UnavailableManualArtifactWriter()
        self._clock = clock
        self._lock = RLock()
        self._imports: dict[tuple[UUID, UUID], ManualEvidenceImport] = {}
        self._commands: dict[
            tuple[UUID, UUID, str, str],
            tuple[tuple[object, ...], ManualEvidenceImport],
        ] = {}
        self._submissions: dict[
            tuple[UUID, UUID], tuple[tuple[object, ...], ManualEvidenceImport]
        ] = {}

    def submit(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        task_id: UUID,
        actor_id: str,
        idempotency_key: str,
        payload: SubmitManualEvidenceRequest,
    ) -> ManualEvidenceImport:
        task = self._store.task(
            project_id=project_id,
            run_id=run_id,
            task_id=task_id,
        )
        if task is None:
            raise SamplingNotFound("Sampling Task does not exist")
        if task.identity.capture_method is not CaptureMethod.MANUAL_UI:
            raise SamplingConflict("manual evidence requires a manual_ui Task")
        if task.version != payload.expected_task_version:
            raise SamplingConflict("Sampling Task optimistic version check failed")
        content = decode_manual_artifact(payload.content_base64.get_secret_value())
        content_hash = hashlib.sha256(content).hexdigest()
        signature = (
            run_id,
            task_id,
            actor_id,
            payload.expected_task_version,
            content_hash,
            payload.content_type,
            payload.governance_policy_option_key,
            payload.evidence_kind,
            payload.pre_redacted_attestation,
            payload.device,
            payload.locale,
            payload.captured_at,
        )
        import_id = sampling_command_id(project_id, "manual-evidence", idempotency_key)
        with self._lock:
            prior = self._submissions.get((project_id, import_id))
            if prior is not None:
                if prior[0] != signature:
                    raise SamplingConflict(
                        "manual evidence Idempotency-Key was reused with different input"
                    )
                return prior[1]
        attempt_id = sampling_command_id(project_id, "manual-attempt", idempotency_key)
        manifest_id = sampling_command_id(project_id, "manual-manifest", idempotency_key)
        capture_session_id = sampling_command_id(
            project_id, "manual-capture-session", idempotency_key
        )
        try:
            receipt = self._artifact_writer.write(
                project_id=project_id,
                run_id=run_id,
                task_id=task_id,
                artifact_manifest_id=manifest_id,
                capture_session_id=capture_session_id,
                evidence_kind=payload.evidence_kind,
                content_type=payload.content_type,
                content=content,
                governance_policy_key=payload.governance_policy_option_key,
                pre_redacted_attestation=payload.pre_redacted_attestation,
            )
        finally:
            wipe_bytearray(content)
        now = self._clock()
        item = ManualEvidenceImport(
            id=import_id,
            project_id=project_id,
            run_id=run_id,
            task_id=task_id,
            task_key=task.identity.task_key,
            attempt_id=attempt_id,
            expected_task_version=payload.expected_task_version,
            artifact_manifest_id=receipt.artifact_manifest_id,
            artifact_manifest_hash=receipt.artifact_manifest_hash,
            artifact_content_hash=receipt.artifact_content_hash,
            governance_policy_hash=receipt.governance_policy_hash,
            capture_session_id=receipt.capture_session_id,
            evidence_kind=ManualEvidenceKind(payload.evidence_kind),
            device=ManualCaptureDevice(payload.device),
            locale=payload.locale,
            captured_at=payload.captured_at,
            submitted_by=actor_id,
            submitted_at=now,
        )
        key = (project_id, import_id)
        with self._lock:
            existing = self._imports.get(key)
            if existing is not None and existing != item:
                raise SamplingConflict(
                    "manual evidence Idempotency-Key was reused with different input"
                )
            self._imports[key] = item
            self._submissions[key] = (signature, item)
        return item

    def get(self, *, project_id: UUID, import_id: UUID) -> ManualEvidenceImport:
        with self._lock:
            item = self._imports.get((project_id, import_id))
        if item is None:
            raise SamplingNotFound("manual evidence import does not exist")
        return item

    def list(self, *, project_id: UUID) -> tuple[ManualEvidenceImport, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (
                        item
                        for (item_project, _), item in self._imports.items()
                        if item_project == project_id
                    ),
                    key=lambda item: (item.submitted_at, str(item.id)),
                    reverse=True,
                )
            )

    def review(
        self,
        *,
        project_id: UUID,
        import_id: UUID,
        actor_id: str,
        idempotency_key: str,
        payload: ReviewManualEvidenceRequest,
        approved: bool,
    ) -> ManualEvidenceImport:
        command_name = "approve" if approved else "reject"
        command_key = (project_id, import_id, command_name, idempotency_key)
        signature = (payload.expected_version, actor_id, payload.reason)
        with self._lock:
            prior = self._commands.get(command_key)
            if prior is not None:
                if prior[0] != signature:
                    raise SamplingConflict(
                        "manual evidence Idempotency-Key was reused with different input"
                    )
                return prior[1]
            current = self._imports.get((project_id, import_id))
            if current is None:
                raise SamplingNotFound("manual evidence import does not exist")
            if current.aggregate_version != payload.expected_version:
                raise SamplingConflict(
                    "manual evidence optimistic version check failed"
                )
            now = self._clock()
            decided = decide_manual_evidence(
                current,
                reviewer_id=actor_id,
                reviewed_at=now,
                reason=payload.reason,
                approved=approved,
            )
            if approved:
                self._enqueue_attempt(
                    project_id=project_id,
                    run_id=current.run_id,
                    task_id=current.task_id,
                    expected_task_version=current.expected_task_version,
                    attempt_id=current.attempt_id,
                    requested_not_before=now,
                    authorization_checked_at=now,
                )
            self._imports[(project_id, import_id)] = decided
            self._commands[command_key] = (signature, decided)
            return decided

    def for_attempt(
        self, *, project_id: UUID, attempt_id: UUID
    ) -> ManualEvidenceImport:
        with self._lock:
            matches = tuple(
                item
                for (item_project, _), item in self._imports.items()
                if item_project == project_id and item.attempt_id == attempt_id
            )
        if len(matches) != 1 or matches[0].status not in {
            ManualEvidenceStatus.APPROVED,
            ManualEvidenceStatus.COMMITTED,
        }:
            raise SamplingNotFound("approved manual evidence does not exist for Attempt")
        return matches[0]

    def mark_committed(
        self,
        *,
        project_id: UUID,
        import_id: UUID,
        expected_version: int,
        committed_at: datetime,
    ) -> ManualEvidenceImport:
        with self._lock:
            current = self._imports.get((project_id, import_id))
            if current is None:
                raise SamplingNotFound("manual evidence import does not exist")
            if current.aggregate_version != expected_version:
                raise SamplingConflict(
                    "manual evidence optimistic version check failed"
                )
            updated = commit_manual_evidence(current, committed_at=committed_at)
            self._imports[(project_id, import_id)] = updated
            return updated
