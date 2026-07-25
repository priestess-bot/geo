"""Governed protocol parsing and lifecycle for Workflow C analysis.

The immutable domain models live in ``workflow_c_analysis_admission_models``;
this module remains the stable public import path.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from uuid import UUID, uuid5

from geo_core.workflow_c_analysis_admission_models import (
    ANALYSIS_MANIFEST_NAMESPACE,
    METRIC_PROTOCOL_NAMESPACE,
    AnalysisArtifactKind,
    AnalysisInputManifest,
    AnalysisManifestItem,
    MetricProtocolDefinition,
    MetricProtocolStatus,
    MetricProtocolVersion,
    WorkflowCAnalysisAdmissionError,
    _text,
    canonical_hash,
    command_input_hash,
    metric_suite_value,
)
from geo_core.workflow_c_analysis_common import (
    array_value,
    hash_value,
    object_value,
    only_keys,
    text_value,
    uuid_value,
)
from geo_core.workflow_c_job_specs import WorkflowCJobSpecError
from geo_core.workflow_c_semantic_specs import (
    approved_fact,
    baseline_question_score,
    metric_suite,
    subject_inventory,
)


def metric_protocol_definition(value: Mapping[str, object]) -> MetricProtocolDefinition:
    try:
        only_keys(
            value,
            {
                "schema_version",
                "metric_suite",
                "subjects",
                "approved_facts",
                "verified_urls",
                "approved_corpus_version",
                "approved_corpus_hash",
                "baseline_question_scores",
                "question_clusters",
                "fact_snapshot_id",
                "fact_snapshot_hash",
                "prompt_release_id",
                "prompt_release_hash",
                "corpus_version_id",
                "corpus_version_hash",
            },
            "Metric Protocol definition",
        )
        if value.get("schema_version") != 1:
            raise WorkflowCAnalysisAdmissionError("Metric Protocol schema_version must be 1")
        raw_clusters = object_value(value.get("question_clusters"), "question clusters")
        return MetricProtocolDefinition(
            metric_suite=metric_suite(object_value(value.get("metric_suite"), "metric suite")),
            subjects=subject_inventory(object_value(value.get("subjects"), "subject inventory")),
            approved_facts=tuple(
                approved_fact(object_value(item, "approved Fact"))
                for item in array_value(value.get("approved_facts"), "approved Facts")
            ),
            verified_urls=tuple(
                text_value(item, "verified URL")
                for item in array_value(value.get("verified_urls"), "verified URLs")
            ),
            approved_corpus_version=text_value(
                value.get("approved_corpus_version"), "approved corpus version"
            ),
            approved_corpus_hash=hash_value(
                value.get("approved_corpus_hash"), "approved corpus hash"
            ),
            baseline_question_scores=tuple(
                baseline_question_score(object_value(item, "baseline question score"))
                for item in array_value(
                    value.get("baseline_question_scores"), "baseline question scores"
                )
            ),
            question_clusters=tuple(
                (question_id, text_value(cluster, "question cluster"))
                for question_id, cluster in raw_clusters.items()
            ),
            fact_snapshot_id=uuid_value(value.get("fact_snapshot_id"), "Fact snapshot id"),
            fact_snapshot_hash=hash_value(
                value.get("fact_snapshot_hash"), "Fact snapshot hash"
            ),
            prompt_release_id=uuid_value(
                value.get("prompt_release_id"), "Prompt Release id"
            ),
            prompt_release_hash=hash_value(
                value.get("prompt_release_hash"), "Prompt Release hash"
            ),
            corpus_version_id=uuid_value(
                value.get("corpus_version_id"), "Corpus Version id"
            ),
            corpus_version_hash=hash_value(
                value.get("corpus_version_hash"), "Corpus Version hash"
            ),
        )
    except WorkflowCAnalysisAdmissionError:
        raise
    except (WorkflowCJobSpecError, ValueError) as error:
        raise WorkflowCAnalysisAdmissionError(str(error)) from error


def analysis_manifest_item(value: Mapping[str, object]) -> AnalysisManifestItem:
    expected = {
        "ordinal",
        "task_id",
        "task_key",
        "question_id",
        "question_version",
        "question_cluster",
        "repetition",
        "observation_id",
        "observation_hash",
        "observation_status",
        "attempt_id",
        "source_job_id",
        "provider_model_attempt_id",
        "output_hash",
        "artifact_kind",
        "artifact_id",
        "artifact_manifest_hash",
        "artifact_content_hash",
        "actual_location_hash",
        "item_hash",
    }
    try:
        only_keys(value, expected, "Analysis manifest item")
        item = AnalysisManifestItem(
            ordinal=_required_integer(value.get("ordinal"), "Analysis manifest ordinal"),
            task_id=uuid_value(value.get("task_id"), "Analysis Task id"),
            task_key=hash_value(value.get("task_key"), "Analysis Task key"),
            question_id=text_value(value.get("question_id"), "Analysis question id"),
            question_version=text_value(
                value.get("question_version"), "Analysis question version"
            ),
            question_cluster=text_value(
                value.get("question_cluster"), "Analysis question cluster"
            ),
            repetition=_required_integer(
                value.get("repetition"), "Analysis repetition"
            ),
            observation_id=_optional_uuid(value.get("observation_id"), "Observation id"),
            observation_hash=_optional_hash(
                value.get("observation_hash"), "Observation hash"
            ),
            observation_status=text_value(
                value.get("observation_status"), "Observation status"
            ),
            attempt_id=_optional_uuid(value.get("attempt_id"), "Sampling Attempt id"),
            source_job_id=_optional_uuid(value.get("source_job_id"), "source Job id"),
            provider_model_attempt_id=_optional_uuid(
                value.get("provider_model_attempt_id"), "Provider model Attempt id"
            ),
            output_hash=_optional_hash(value.get("output_hash"), "Provider output hash"),
            artifact_kind=AnalysisArtifactKind(
                text_value(value.get("artifact_kind"), "Analysis artifact kind")
            ),
            artifact_id=_optional_uuid(value.get("artifact_id"), "artifact id"),
            artifact_manifest_hash=_optional_hash(
                value.get("artifact_manifest_hash"), "artifact manifest hash"
            ),
            artifact_content_hash=_optional_hash(
                value.get("artifact_content_hash"), "artifact content hash"
            ),
            actual_location_hash=_optional_hash(
                value.get("actual_location_hash"), "actual location hash"
            ),
        )
        if item.item_hash != hash_value(value.get("item_hash"), "Analysis item hash"):
            raise WorkflowCAnalysisAdmissionError("Analysis manifest item hash is corrupt")
        return item
    except WorkflowCAnalysisAdmissionError:
        raise
    except (WorkflowCJobSpecError, ValueError) as error:
        raise WorkflowCAnalysisAdmissionError(str(error)) from error


def analysis_input_manifest(
    *,
    manifest_id: UUID,
    frozen_by: str,
    frozen_at: datetime,
    value: Mapping[str, object],
) -> AnalysisInputManifest:
    expected = {
        "schema_version",
        "project_id",
        "sampling_run_id",
        "sampling_run_version",
        "sampling_suite_hash",
        "metric_protocol_id",
        "metric_protocol_hash",
        "fact_snapshot_id",
        "fact_snapshot_hash",
        "prompt_release_id",
        "prompt_release_hash",
        "corpus_version_id",
        "corpus_version_hash",
        "baseline_snapshot_hash",
        "source_stratum_hash",
        "capture_method",
        "stratum",
        "items",
    }
    try:
        only_keys(value, expected, "Analysis input manifest")
        if value.get("schema_version") != 1:
            raise WorkflowCAnalysisAdmissionError(
                "Analysis input manifest schema_version must be 1"
            )
        raw_stratum = object_value(value.get("stratum"), "Analysis stratum")
        return AnalysisInputManifest(
            id=manifest_id,
            project_id=uuid_value(value.get("project_id"), "Analysis Project id"),
            sampling_run_id=uuid_value(
                value.get("sampling_run_id"), "Analysis Sampling Run id"
            ),
            sampling_run_version=_required_integer(
                value.get("sampling_run_version"), "Analysis Sampling Run version"
            ),
            sampling_suite_hash=hash_value(
                value.get("sampling_suite_hash"), "Analysis Sampling Suite hash"
            ),
            metric_protocol_id=uuid_value(
                value.get("metric_protocol_id"), "Analysis Metric Protocol id"
            ),
            metric_protocol_hash=hash_value(
                value.get("metric_protocol_hash"), "Analysis Metric Protocol hash"
            ),
            fact_snapshot_id=uuid_value(
                value.get("fact_snapshot_id"), "Analysis Fact snapshot id"
            ),
            fact_snapshot_hash=hash_value(
                value.get("fact_snapshot_hash"), "Analysis Fact snapshot hash"
            ),
            prompt_release_id=uuid_value(
                value.get("prompt_release_id"), "Analysis Prompt Release id"
            ),
            prompt_release_hash=hash_value(
                value.get("prompt_release_hash"), "Analysis Prompt Release hash"
            ),
            corpus_version_id=uuid_value(
                value.get("corpus_version_id"), "Analysis Corpus Version id"
            ),
            corpus_version_hash=hash_value(
                value.get("corpus_version_hash"), "Analysis Corpus Version hash"
            ),
            baseline_snapshot_hash=_optional_hash(
                value.get("baseline_snapshot_hash"), "Analysis baseline snapshot hash"
            ),
            source_stratum_hash=hash_value(
                value.get("source_stratum_hash"), "Analysis SourceStratum hash"
            ),
            capture_method=text_value(
                value.get("capture_method"), "Analysis capture method"
            ),
            stratum=tuple(
                (
                    text_value(key, "Analysis stratum key"),
                    text_value(item, "Analysis stratum value"),
                )
                for key, item in raw_stratum.items()
            ),
            items=tuple(
                analysis_manifest_item(object_value(item, "Analysis manifest item"))
                for item in array_value(value.get("items"), "Analysis manifest items")
            ),
            frozen_by=frozen_by,
            frozen_at=frozen_at,
        )
    except WorkflowCAnalysisAdmissionError:
        raise
    except (WorkflowCJobSpecError, ValueError) as error:
        raise WorkflowCAnalysisAdmissionError(str(error)) from error


def _required_integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise WorkflowCAnalysisAdmissionError(f"{label} must be positive")
    return value


def _optional_uuid(value: object, label: str) -> UUID | None:
    return None if value is None else uuid_value(value, label)


def _optional_hash(value: object, label: str) -> str | None:
    return None if value is None else hash_value(value, label)


def new_metric_protocol(
    *,
    project_id: UUID,
    definition: MetricProtocolDefinition,
    actor_id: str,
    idempotency_key: str,
    occurred_at: datetime,
    predecessor: MetricProtocolVersion | None = None,
) -> MetricProtocolVersion:
    normalized_key = _text(idempotency_key, "Metric Protocol Idempotency-Key")
    protocol_id = uuid5(METRIC_PROTOCOL_NAMESPACE, f"{project_id}:metric-protocol:{normalized_key}")
    if predecessor is None:
        series_id = protocol_id
        version = 1
        predecessor_id = None
    else:
        if predecessor.project_id != project_id or predecessor.status not in {
            MetricProtocolStatus.APPROVED,
            MetricProtocolStatus.RETIRED,
        }:
            raise WorkflowCAnalysisAdmissionError(
                "Only a decided Metric Protocol from the same Project can be superseded"
            )
        series_id = predecessor.series_id
        version = predecessor.version + 1
        predecessor_id = predecessor.id
    return MetricProtocolVersion(
        id=protocol_id,
        project_id=project_id,
        series_id=series_id,
        version=version,
        supersedes_protocol_id=predecessor_id,
        status=MetricProtocolStatus.DRAFT,
        definition=definition,
        created_by=_text(actor_id, "Metric Protocol creator"),
        created_at=occurred_at,
        updated_at=occurred_at,
    )


def submit_metric_protocol(
    protocol: MetricProtocolVersion, *, actor_id: str, occurred_at: datetime
) -> MetricProtocolVersion:
    if protocol.status is not MetricProtocolStatus.DRAFT:
        raise WorkflowCAnalysisAdmissionError("Only a draft Metric Protocol can be submitted")
    actor = _text(actor_id, "Metric Protocol submitter")
    return replace(
        protocol,
        status=MetricProtocolStatus.IN_REVIEW,
        submitted_by=actor,
        submitted_at=occurred_at,
        updated_at=occurred_at,
        aggregate_version=protocol.aggregate_version + 1,
    )


def approve_metric_protocol(
    protocol: MetricProtocolVersion,
    *,
    actor_id: str,
    reason: str,
    occurred_at: datetime,
) -> MetricProtocolVersion:
    if protocol.status is not MetricProtocolStatus.IN_REVIEW:
        raise WorkflowCAnalysisAdmissionError("Only an in-review Metric Protocol can be approved")
    actor = _text(actor_id, "Metric Protocol approver")
    if actor == protocol.created_by:
        raise WorkflowCAnalysisAdmissionError(
            "Metric Protocol maker cannot approve the same version"
        )
    return replace(
        protocol,
        status=MetricProtocolStatus.APPROVED,
        approved_by=actor,
        approved_at=occurred_at,
        decision_reason=_text(reason, "Metric Protocol approval reason"),
        updated_at=occurred_at,
        aggregate_version=protocol.aggregate_version + 1,
    )


def retire_metric_protocol(
    protocol: MetricProtocolVersion,
    *,
    actor_id: str,
    reason: str,
    occurred_at: datetime,
) -> MetricProtocolVersion:
    if protocol.status is not MetricProtocolStatus.APPROVED:
        raise WorkflowCAnalysisAdmissionError("Only an approved Metric Protocol can be retired")
    return replace(
        protocol,
        status=MetricProtocolStatus.RETIRED,
        retired_by=_text(actor_id, "Metric Protocol retire actor"),
        retired_at=occurred_at,
        decision_reason=_text(reason, "Metric Protocol retirement reason"),
        updated_at=occurred_at,
        aggregate_version=protocol.aggregate_version + 1,
    )


def manifest_id(project_id: UUID, idempotency_key: str) -> UUID:
    key = _text(idempotency_key, "Analysis Idempotency-Key")
    return uuid5(ANALYSIS_MANIFEST_NAMESPACE, f"{project_id}:semantic-manifest:{key}")


__all__ = [
    "ANALYSIS_MANIFEST_NAMESPACE",
    "METRIC_PROTOCOL_NAMESPACE",
    "AnalysisArtifactKind",
    "AnalysisInputManifest",
    "AnalysisManifestItem",
    "MetricProtocolDefinition",
    "MetricProtocolStatus",
    "MetricProtocolVersion",
    "WorkflowCAnalysisAdmissionError",
    "analysis_input_manifest",
    "analysis_manifest_item",
    "approve_metric_protocol",
    "canonical_hash",
    "command_input_hash",
    "manifest_id",
    "metric_protocol_definition",
    "metric_suite_value",
    "new_metric_protocol",
    "retire_metric_protocol",
    "submit_metric_protocol",
]
