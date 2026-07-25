"""Durable Internal API control for governed manual Sampling evidence."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import hashlib
from uuid import UUID

from geo_api.workflow_c_manual_artifacts import ManualArtifactWriter, decode_manual_artifact
from geo_api.workflow_c_sampling_contracts import (
    ReviewManualEvidenceRequest,
    SubmitManualEvidenceRequest,
)
from geo_api.workflow_c_sampling_ids import sampling_command_id
from geo_api.workflow_c_surface_parsing import parse_manual_surface_summary
from geo_core.sampling import (
    CaptureMethod,
    ManualCaptureDevice,
    ManualEvidenceImport,
    ManualEvidenceKind,
    PostgresManualEvidenceRepository,
    PostgresSamplingRunRepository,
    PostgresSamplingSuiteRepository,
    SamplingConflict,
    SamplingNotFound,
)
from geo_core.sampling.manual_artifact_governance import wipe_bytearray


class PostgresWorkflowCManualEvidenceControl:
    """Keep bytes in restricted storage and persist only governed lineage."""

    persistence = "durable"

    def __init__(
        self,
        *,
        imports: PostgresManualEvidenceRepository,
        runs: PostgresSamplingRunRepository,
        suites: PostgresSamplingSuiteRepository,
        artifact_writer: ManualArtifactWriter,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._imports = imports
        self._runs = runs
        self._suites = suites
        self._artifact_writer = artifact_writer
        self._clock = clock

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
        run = self._runs.get_run(project_id=project_id, run_id=run_id)
        suite = self._suites.get_suite(project_id=project_id, suite_id=run.suite_id)
        task = next(
            (
                item
                for item in self._runs.list_tasks(
                    project_id=project_id,
                    run_id=run_id,
                    suite=suite,
                )
                if item.id == task_id
            ),
            None,
        )
        if task is None:
            raise SamplingNotFound("Sampling Task does not exist")
        if task.identity.capture_method is not CaptureMethod.MANUAL_UI:
            raise SamplingConflict("manual evidence requires a manual_ui Task")
        if task.version != payload.expected_task_version:
            raise SamplingConflict("Sampling Task optimistic version check failed")

        content = decode_manual_artifact(payload.content_base64.get_secret_value())
        try:
            source_content_hash = hashlib.sha256(content).hexdigest()
            surface_parse = parse_manual_surface_summary(
                release_id=payload.surface_parser_release_id,
                source_platform=suite.source_stratum.platform,
                source_surface=suite.source_stratum.surface,
                evidence_kind=payload.evidence_kind,
                content_type=payload.content_type,
                content=content,
                governance_policy_key=payload.governance_policy_option_key,
                pre_redacted_attestation=payload.pre_redacted_attestation,
            )
            prior = self._imports.replay_submission(
                project_id=project_id,
                import_id=sampling_command_id(project_id, "manual-evidence", idempotency_key),
                run_id=run_id,
                task_id=task_id,
                expected_task_version=payload.expected_task_version,
                submitted_by=actor_id,
                source_content_hash=source_content_hash,
                evidence_kind=payload.evidence_kind,
                device=payload.device,
                locale=payload.locale,
                captured_at=payload.captured_at,
                content_type=payload.content_type,
                governance_policy_option_key=payload.governance_policy_option_key,
                pre_redacted_attestation=payload.pre_redacted_attestation,
                surface_parse=surface_parse,
            )
            if prior is not None:
                return prior
            receipt = self._artifact_writer.write(
                project_id=project_id,
                run_id=run_id,
                task_id=task_id,
                artifact_manifest_id=sampling_command_id(
                    project_id, "manual-manifest", idempotency_key
                ),
                capture_session_id=sampling_command_id(
                    project_id, "manual-capture-session", idempotency_key
                ),
                evidence_kind=payload.evidence_kind,
                content_type=payload.content_type,
                content=content,
                governance_policy_key=payload.governance_policy_option_key,
                pre_redacted_attestation=payload.pre_redacted_attestation,
                activate=False,
            )
        finally:
            wipe_bytearray(content)

        try:
            item = ManualEvidenceImport(
                id=sampling_command_id(project_id, "manual-evidence", idempotency_key),
                project_id=project_id,
                run_id=run_id,
                task_id=task_id,
                task_key=task.identity.task_key,
                attempt_id=sampling_command_id(project_id, "manual-attempt", idempotency_key),
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
                submitted_at=self._clock(),
                surface_parse=surface_parse,
            )
            return self._imports.submit(
                item,
                source_content_hash=source_content_hash,
                content_type=payload.content_type,
                governance_policy_option_key=payload.governance_policy_option_key,
                pre_redacted_attestation=payload.pre_redacted_attestation,
                idempotency_key=idempotency_key,
            )
        except BaseException:
            try:
                self._artifact_writer.cleanup_staged(
                    project_id=project_id,
                    artifact_manifest_id=receipt.artifact_manifest_id,
                )
            except BaseException:
                pass
            raise

    def get(self, *, project_id: UUID, import_id: UUID) -> ManualEvidenceImport:
        return self._imports.get(project_id=project_id, import_id=import_id)

    def list(self, *, project_id: UUID) -> tuple[ManualEvidenceImport, ...]:
        return self._imports.list(project_id=project_id)

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
        return self._imports.review(
            project_id=project_id,
            import_id=import_id,
            expected_version=payload.expected_version,
            reviewer_id=actor_id,
            reason=payload.reason,
            approved=approved,
            reviewed_at=self._clock(),
            idempotency_key=idempotency_key,
        )

    def for_attempt(self, *, project_id: UUID, attempt_id: UUID) -> ManualEvidenceImport:
        return self._imports.for_attempt(project_id=project_id, attempt_id=attempt_id)


__all__ = ["PostgresWorkflowCManualEvidenceControl"]
