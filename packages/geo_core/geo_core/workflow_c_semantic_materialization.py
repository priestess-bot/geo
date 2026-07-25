"""Lease-bound materialization of immutable Workflow C semantic inputs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import json
from typing import Any, Protocol
from uuid import UUID

import psycopg

from geo_core.jobs.postgres import WorkerLease
from geo_core.model_gateway.artifact_recovery import (
    ProviderArtifactRecoveryPort,
    ProviderArtifactRecoveryRequest,
)
from geo_core.project_scope import set_project_scope
from geo_core.sampling.surface_parsers import ARTIFACT_SCHEMA_VERSION
from geo_core.sampling.postgres_worker_contracts import (
    ProviderSamplingWorkerSpec,
    parse_provider_sampling_spec,
)
from geo_core.semantic_metrics import (
    CitationInput,
    FrozenMetricSuite,
    MetricInputSet,
    MetricObservation,
    PlannedMetricSlot,
    SemanticStratum,
)
from geo_core.workflow_c_analysis_admission import (
    AnalysisArtifactKind,
    AnalysisInputManifest,
    AnalysisManifestItem,
    MetricProtocolDefinition,
    WorkflowCAnalysisAdmissionError,
    analysis_input_manifest,
    metric_protocol_definition,
)
from geo_core.workflow_c_semantic_evidence import _citations, _mapping, _surface_answer
from geo_core.workflow_c_semantic_materialization_contracts import (
    WorkflowCSemanticMaterializationError,
)
from geo_core.workflow_c_artifacts.reader import (
    RecoveredWorkflowCManualArtifact,
    WorkflowCManualArtifactReadRequest,
)
from geo_core.workflow_c_job_specs import WorkflowCJobSpec
from geo_core.workflow_c_semantic_specs import SemanticMetricMetadata


_KIND = "workflow_c.analysis.semantic_metrics"


class WorkflowCManualArtifactReaderPort(Protocol):
    def load(
        self, request: WorkflowCManualArtifactReadRequest
    ) -> RecoveredWorkflowCManualArtifact: ...


@dataclass(frozen=True)
class MaterializedSemanticInput:
    metadata: SemanticMetricMetadata
    input_set: MetricInputSet
    metric_suite: FrozenMetricSuite


@dataclass(frozen=True)
class _LoadedSemanticManifest:
    manifest: AnalysisInputManifest
    protocol: MetricProtocolDefinition
    provider_specs: Mapping[UUID, ProviderSamplingWorkerSpec]


@dataclass(frozen=True)
class _Evidence:
    answer_text: str
    citations: tuple[CitationInput, ...]
    payload_hash: str
    artifact_version: str


class PostgresWorkflowCSemanticInputMaterializer:
    """Recover answer bytes only after manifest, protocol and lease validation."""

    def __init__(
        self,
        *,
        connect: Callable[[], Any],
        manual_artifacts: WorkflowCManualArtifactReaderPort,
        provider_artifacts: ProviderArtifactRecoveryPort,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._connect = connect
        self._manual_artifacts = manual_artifacts
        self._provider_artifacts = provider_artifacts
        self._clock = clock

    def materialize(
        self, *, lease: WorkerLease, spec: WorkflowCJobSpec
    ) -> MaterializedSemanticInput:
        if lease.kind != _KIND or spec.kind != _KIND or spec.payload.get("schema_version") != 2:
            raise WorkflowCSemanticMaterializationError(
                "semantic v2 materialization requires a semantic v2 Job"
            )
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise WorkflowCSemanticMaterializationError(
                "semantic materialization clock must be timezone-aware"
            )
        loaded = self._load(lease=lease, spec=spec, now=now)
        observations: list[MetricObservation] = []
        warning_count = 0
        for item in loaded.manifest.items:
            if item.observation_status == "ineligible":
                warning_count += 1
            evidence = self._recover(
                lease=lease,
                item=item,
                provider_specs=loaded.provider_specs,
            )
            if evidence is None:
                continue
            if item.observation_id is None:
                raise WorkflowCSemanticMaterializationError(
                    "materialized evidence has no frozen Observation identity"
                )
            observations.append(
                MetricObservation(
                    id=item.observation_id,
                    slot_id=item.slot_id,
                    payload_hash=evidence.payload_hash,
                    question_id=item.question_id,
                    question_cluster=item.question_cluster,
                    answer_text=evidence.answer_text,
                    artifact_version=evidence.artifact_version,
                    citations=evidence.citations,
                )
            )
        planned_slots = tuple(
            PlannedMetricSlot(
                slot_id=item.slot_id,
                question_id=item.question_id,
                question_cluster=item.question_cluster,
            )
            for item in loaded.manifest.items
        )
        definition = loaded.protocol
        input_set = MetricInputSet(
            stratum=SemanticStratum(loaded.manifest.stratum),
            planned_slots=planned_slots,
            observations=tuple(observations),
            subjects=definition.subjects,
            approved_facts=definition.approved_facts,
            verified_urls=definition.verified_urls,
            approved_corpus_version=definition.approved_corpus_version,
            approved_corpus_hash=definition.approved_corpus_hash,
            baseline_question_scores=definition.baseline_question_scores,
        )
        return MaterializedSemanticInput(
            metadata=SemanticMetricMetadata(
                run_id=loaded.manifest.sampling_run_id,
                source_stratum_hash=loaded.manifest.source_stratum_hash,
                capture_method=loaded.manifest.capture_method,
                warning_ratio=Decimal(warning_count) / Decimal(len(planned_slots)),
                test_only=False,
                synthetic=False,
            ),
            input_set=input_set,
            metric_suite=definition.metric_suite,
        )

    def _load(
        self, *, lease: WorkerLease, spec: WorkflowCJobSpec, now: datetime
    ) -> _LoadedSemanticManifest:
        pointer = _mapping(spec.payload.get("semantic_metrics"), "semantic v2 pointer")
        manifest_id = _uuid(pointer.get("manifest_id"), "semantic manifest id")
        expected_hash = _hash(pointer.get("manifest_hash"), "semantic manifest hash")
        connection = self._connect()
        try:
            set_project_scope(connection, lease.project_id)
            row = connection.execute(
                """SELECT manifest.*, protocol.status AS protocol_status,
                          protocol.protocol_hash AS stored_protocol_hash,
                          protocol.definition AS protocol_definition,
                          durable.status AS durable_status,
                          durable.input_hash AS durable_input_hash,
                          durable.lease_token AS durable_lease_token,
                          durable.fencing_generation AS durable_fencing_generation,
                          durable.lease_expires_at AS durable_lease_expires_at,
                          durable.cancel_requested_at AS durable_cancel_requested_at,
                          job_spec.spec_hash AS stored_spec_hash,
                          job_spec.spec_payload AS stored_spec_payload
                     FROM workflow_c_analysis_input_manifests AS manifest
                     JOIN workflow_c_metric_protocol_versions AS protocol
                       ON protocol.project_id = manifest.project_id
                      AND protocol.id = manifest.metric_protocol_id
                     JOIN durable_jobs AS durable
                       ON durable.project_id = manifest.project_id
                      AND durable.id = %s
                     JOIN workflow_c_job_specs AS job_spec
                       ON job_spec.project_id = durable.project_id
                      AND job_spec.job_id = durable.id
                    WHERE manifest.project_id = %s AND manifest.id = %s""",
                (lease.job_id, lease.project_id, manifest_id),
            ).fetchone()
            if row is None:
                raise WorkflowCSemanticMaterializationError(
                    "semantic input manifest does not exist"
                )
            values = _mapping(row, "semantic input manifest row")
            _validate_current_lease(values, lease=lease, spec=spec, now=now)
            payload = _mapping(values.get("payload"), "semantic input manifest payload")
            manifest = analysis_input_manifest(
                manifest_id=manifest_id,
                frozen_by=_text(values.get("frozen_by"), "manifest freezer"),
                frozen_at=_datetime(values.get("frozen_at"), "manifest freeze time"),
                value=payload,
            )
            _validate_manifest_row(values, manifest=manifest, expected_hash=expected_hash)
            protocol = metric_protocol_definition(
                _mapping(values.get("protocol_definition"), "Metric Protocol definition")
            )
            if (
                values.get("protocol_status") not in {"approved", "retired"}
                or protocol.protocol_hash != manifest.metric_protocol_hash
                or values.get("stored_protocol_hash") != manifest.metric_protocol_hash
                or protocol.fact_snapshot_id != manifest.fact_snapshot_id
                or protocol.fact_snapshot_hash != manifest.fact_snapshot_hash
                or protocol.prompt_release_id != manifest.prompt_release_id
                or protocol.prompt_release_hash != manifest.prompt_release_hash
                or protocol.corpus_version_id != manifest.corpus_version_id
                or protocol.corpus_version_hash != manifest.corpus_version_hash
            ):
                raise WorkflowCSemanticMaterializationError(
                    "semantic Metric Protocol lineage changed"
                )
            item_rows = connection.execute(
                """SELECT ordinal, payload FROM workflow_c_analysis_input_manifest_items
                    WHERE project_id = %s AND manifest_id = %s ORDER BY ordinal""",
                (lease.project_id, manifest_id),
            ).fetchall()
            if [item["payload"] for item in item_rows] != [
                item.canonical_value() | {"item_hash": item.item_hash}
                for item in manifest.items
            ]:
                raise WorkflowCSemanticMaterializationError(
                    "semantic manifest item projection changed"
                )
            provider_specs = _load_provider_specs(
                connection,
                project_id=lease.project_id,
                run_id=manifest.sampling_run_id,
                items=manifest.items,
            )
            connection.rollback()
            return _LoadedSemanticManifest(
                manifest=manifest,
                protocol=protocol,
                provider_specs=provider_specs,
            )
        except WorkflowCSemanticMaterializationError:
            connection.rollback()
            raise
        except (WorkflowCAnalysisAdmissionError, psycopg.Error, ValueError) as error:
            connection.rollback()
            raise WorkflowCSemanticMaterializationError(
                "semantic input manifest could not be validated"
            ) from error
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _recover(
        self,
        *,
        lease: WorkerLease,
        item: AnalysisManifestItem,
        provider_specs: Mapping[UUID, ProviderSamplingWorkerSpec],
    ) -> _Evidence | None:
        if item.artifact_kind is AnalysisArtifactKind.MANUAL:
            if (
                item.artifact_id is None
                or item.artifact_manifest_hash is None
                or item.artifact_content_hash is None
            ):
                raise WorkflowCSemanticMaterializationError(
                    "manual semantic artifact lineage is incomplete"
                )
            manual_artifact = self._manual_artifacts.load(
                WorkflowCManualArtifactReadRequest(
                    project_id=lease.project_id,
                    artifact_id=item.artifact_id,
                    expected_manifest_hash=item.artifact_manifest_hash,
                    expected_content_hash=item.artifact_content_hash,
                )
            )
            try:
                return _manual_evidence(item.slot_id, manual_artifact)
            finally:
                manual_artifact.wipe()
        if item.artifact_kind is AnalysisArtifactKind.PROVIDER:
            if (
                item.source_job_id is None
                or item.provider_model_attempt_id is None
                or item.output_hash is None
                or item.artifact_manifest_hash is None
                or item.artifact_content_hash is None
            ):
                raise WorkflowCSemanticMaterializationError(
                    "Provider semantic artifact lineage is incomplete"
                )
            source_spec = provider_specs.get(item.source_job_id)
            if source_spec is None:
                raise WorkflowCSemanticMaterializationError(
                    "Provider semantic source spec is unavailable"
                )
            provider_artifact = self._provider_artifacts.recover_derived(
                ProviderArtifactRecoveryRequest(
                    project_id=lease.project_id,
                    source_model_job_id=item.source_job_id,
                    recovery_job_id=lease.job_id,
                    lease_token=lease.lease_token,
                    fencing_generation=lease.fencing_generation,
                    model_call_attempt_id=item.provider_model_attempt_id,
                    expected_output_hash=item.output_hash,
                    output_schema=source_spec.prompt.output_schema,
                    application_output_schema=source_spec.prompt.application_output_schema,
                    purpose=source_spec.prompt.purpose,
                )
            )
            if (
                provider_artifact.manifest_hash != item.artifact_manifest_hash
                or provider_artifact.content_hash != item.artifact_content_hash
                or provider_artifact.output_hash != item.output_hash
            ):
                raise WorkflowCSemanticMaterializationError(
                    "Provider semantic recovered lineage changed"
                )
            answer = provider_artifact.output.get(source_spec.prompt.answer_field)
            if not isinstance(answer, str) or not answer.strip():
                raise WorkflowCSemanticMaterializationError(
                    "Provider semantic artifact has no frozen answer field"
                )
            return _Evidence(
                answer_text=answer,
                citations=_citations(
                    item.slot_id, provider_artifact.output.get("citations")
                ),
                payload_hash=item.artifact_content_hash,
                artifact_version="provider-derived-v1",
            )
        return None


def _load_provider_specs(
    connection: Any,
    *,
    project_id: UUID,
    run_id: UUID,
    items: tuple[AnalysisManifestItem, ...],
) -> Mapping[UUID, ProviderSamplingWorkerSpec]:
    expected = {
        item.source_job_id
        for item in items
        if item.artifact_kind is AnalysisArtifactKind.PROVIDER
        and item.source_job_id is not None
    }
    if not expected:
        return {}
    rows = connection.execute(
        """SELECT spec.job_id, spec.kind, spec.spec_hash, spec.spec_payload,
                  spec.created_at, durable.status, durable.input_hash
             FROM workflow_c_job_specs AS spec
             JOIN durable_jobs AS durable
               ON durable.project_id = spec.project_id AND durable.id = spec.job_id
            WHERE spec.project_id = %s AND spec.job_id = ANY(%s)""",
        (project_id, list(expected)),
    ).fetchall()
    result: dict[UUID, ProviderSamplingWorkerSpec] = {}
    for raw in rows:
        row = _mapping(raw, "Provider source Job spec row")
        job_id = _row_uuid(row, "job_id")
        payload = _mapping(row.get("spec_payload"), "Provider source Job spec")
        source_spec = WorkflowCJobSpec(
            project_id=project_id,
            job_id=job_id,
            kind=_text(row.get("kind"), "Provider source Job kind"),
            spec_hash=_hash(row.get("spec_hash"), "Provider source Job spec hash"),
            payload=payload,
            created_at=_datetime(row.get("created_at"), "Provider source Job created_at"),
        )
        if (
            source_spec.kind != "sampling.provider_execute"
            or row.get("status") != "succeeded"
            or row.get("input_hash") != source_spec.spec_hash
        ):
            raise WorkflowCSemanticMaterializationError(
                "Provider semantic source Job is not immutable and successful"
            )
        result[job_id] = parse_provider_sampling_spec(source_spec.payload)
    if set(result) != expected:
        raise WorkflowCSemanticMaterializationError(
            "Provider semantic source Job specs are incomplete"
        )
    for item in items:
        if item.artifact_kind is not AnalysisArtifactKind.PROVIDER:
            continue
        assert item.source_job_id is not None and item.attempt_id is not None
        source = result[item.source_job_id]
        if (
            source.run_id != run_id
            or source.task_id != item.task_id
            or source.attempt_id != item.attempt_id
        ):
            raise WorkflowCSemanticMaterializationError(
                "Provider source Job differs from semantic manifest membership"
            )
    return result


def _manual_evidence(
    slot_id: str, recovered: RecoveredWorkflowCManualArtifact
) -> _Evidence | None:
    if recovered.evidence_kind == "screenshot":
        return None
    try:
        value = json.loads(bytes(recovered.payload))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WorkflowCSemanticMaterializationError(
            "manual semantic artifact is not governed JSON"
        ) from error
    root = _mapping(value, "manual semantic artifact")
    source_kind = root.get("source_kind")
    if root.get("schema_version") != 1 or source_kind not in {"text", "html", "json"}:
        raise WorkflowCSemanticMaterializationError(
            "manual semantic artifact schema is unsupported"
        )
    raw_citations: object = None
    if source_kind in {"text", "html"}:
        if set(root) != {"schema_version", "source_kind", "text"}:
            raise WorkflowCSemanticMaterializationError(
                "manual semantic text artifact schema is invalid"
            )
        answer = root.get("text")
    else:
        if set(root) != {"schema_version", "source_kind", "content"}:
            raise WorkflowCSemanticMaterializationError(
                "manual semantic JSON artifact schema is invalid"
            )
        content = _mapping(root.get("content"), "manual semantic JSON content")
        if content.get("schema_version") == ARTIFACT_SCHEMA_VERSION:
            answer = _surface_answer(content.get("answer_blocks"))
        else:
            answer = next(
                (
                    content.get(key)
                    for key in ("answer", "response", "text")
                    if isinstance(content.get(key), str) and str(content.get(key)).strip()
                ),
                None,
            )
        raw_citations = content.get("citations")
    if not isinstance(answer, str) or not answer.strip():
        raise WorkflowCSemanticMaterializationError(
            "manual semantic artifact has no non-empty answer"
        )
    return _Evidence(
        answer_text=answer,
        citations=_citations(slot_id, raw_citations),
        payload_hash=recovered.content_hash,
        artifact_version="manual-redacted-v1",
    )


def _validate_current_lease(
    row: Mapping[str, object],
    *,
    lease: WorkerLease,
    spec: WorkflowCJobSpec,
    now: datetime,
) -> None:
    if (
        row.get("durable_status") not in {"running", "finalizing"}
        or row.get("durable_input_hash") != spec.spec_hash
        or row.get("durable_lease_token") != lease.lease_token
        or row.get("durable_fencing_generation") != lease.fencing_generation
        or row.get("durable_cancel_requested_at") is not None
        or row.get("stored_spec_hash") != spec.spec_hash
        or row.get("stored_spec_payload") != spec.payload
    ):
        raise WorkflowCSemanticMaterializationError(
            "semantic input manifest no longer belongs to this lease"
        )
    expires_at = _datetime(row.get("durable_lease_expires_at"), "semantic lease expiry")
    if expires_at <= now:
        raise WorkflowCSemanticMaterializationError("semantic input manifest lease expired")


def _validate_manifest_row(
    row: Mapping[str, object],
    *,
    manifest: AnalysisInputManifest,
    expected_hash: str,
) -> None:
    if (
        manifest.manifest_hash != expected_hash
        or row.get("manifest_hash") != expected_hash
        or row.get("project_id") != manifest.project_id
        or row.get("sampling_run_id") != manifest.sampling_run_id
        or row.get("sampling_run_version") != manifest.sampling_run_version
        or row.get("sampling_suite_hash") != manifest.sampling_suite_hash
        or row.get("metric_protocol_id") != manifest.metric_protocol_id
        or row.get("metric_protocol_hash") != manifest.metric_protocol_hash
        or row.get("fact_snapshot_id") != manifest.fact_snapshot_id
        or row.get("fact_snapshot_hash") != manifest.fact_snapshot_hash
        or row.get("prompt_release_id") != manifest.prompt_release_id
        or row.get("prompt_release_hash") != manifest.prompt_release_hash
        or row.get("corpus_version_id") != manifest.corpus_version_id
        or row.get("corpus_version_hash") != manifest.corpus_version_hash
        or row.get("baseline_snapshot_hash") != manifest.baseline_snapshot_hash
        or row.get("source_stratum_hash") != manifest.source_stratum_hash
        or row.get("capture_method") != manifest.capture_method
        or row.get("planned_slot_count") != len(manifest.items)
        or row.get("observation_count") != manifest.observation_count
    ):
        raise WorkflowCSemanticMaterializationError(
            "semantic input manifest projection changed"
        )


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkflowCSemanticMaterializationError(f"{label} must be text")
    return value


def _hash(value: object, label: str) -> str:
    text = _text(value, label)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise WorkflowCSemanticMaterializationError(f"{label} must be SHA-256")
    return text


def _uuid(value: object, label: str) -> UUID:
    if not isinstance(value, str):
        raise WorkflowCSemanticMaterializationError(f"{label} must be a UUID")
    try:
        return UUID(value)
    except ValueError as error:
        raise WorkflowCSemanticMaterializationError(f"{label} must be a UUID") from error


def _row_uuid(row: Mapping[str, object], field: str) -> UUID:
    value = row.get(field)
    if isinstance(value, UUID):
        return value
    return _uuid(value, field)


def _datetime(value: object, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise WorkflowCSemanticMaterializationError(f"{label} must be timezone-aware")
    return value


__all__ = [
    "MaterializedSemanticInput",
    "PostgresWorkflowCSemanticInputMaterializer",
    "WorkflowCSemanticMaterializationError",
]
