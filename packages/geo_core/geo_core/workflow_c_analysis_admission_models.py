"""Immutable Workflow C metric protocol and input-manifest models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import hashlib
import json
import re
from collections.abc import Mapping
from uuid import UUID

from geo_core.semantic_metrics import (
    ApprovedFactReference,
    BaselineQuestionScore,
    FrozenMetricSuite,
    SubjectInventory,
)
from geo_core.semantic_metrics._validation import decimal_value


METRIC_PROTOCOL_NAMESPACE = UUID("5fcb5f9a-00a8-5af7-9371-e9e9a7a7d2d4")
ANALYSIS_MANIFEST_NAMESPACE = UUID("76caef81-67de-5c02-9af6-af662c680c0d")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CAPTURE_METHODS = frozenset(
    {"provider_api", "proxy_grounded_api", "manual_ui", "automated_ui"}
)


class WorkflowCAnalysisAdmissionError(ValueError):
    """An analysis release, manifest or transition is not admissible."""


class MetricProtocolStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    RETIRED = "retired"


class AnalysisArtifactKind(StrEnum):
    PROVIDER = "provider"
    MANUAL = "manual"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class MetricProtocolDefinition:
    metric_suite: FrozenMetricSuite
    subjects: SubjectInventory
    approved_facts: tuple[ApprovedFactReference, ...]
    verified_urls: tuple[str, ...]
    approved_corpus_version: str
    approved_corpus_hash: str
    baseline_question_scores: tuple[BaselineQuestionScore, ...]
    question_clusters: tuple[tuple[str, str], ...]
    fact_snapshot_id: UUID
    fact_snapshot_hash: str
    prompt_release_id: UUID
    prompt_release_hash: str
    corpus_version_id: UUID
    corpus_version_hash: str
    protocol_hash: str = field(init=False)

    def __post_init__(self) -> None:
        facts = tuple(sorted(self.approved_facts))
        baselines = tuple(sorted(self.baseline_question_scores))
        urls = tuple(sorted({_text(item, "verified URL", maximum=2_000) for item in self.verified_urls}))
        clusters = tuple(
            sorted(
                (
                    _text(question_id, "question id"),
                    _text(cluster, "question cluster"),
                )
                for question_id, cluster in self.question_clusters
            )
        )
        if not clusters or len({question_id for question_id, _ in clusters}) != len(clusters):
            raise WorkflowCAnalysisAdmissionError(
                "Metric Protocol question clusters must be non-empty and unique"
            )
        if len({(item.id, item.version) for item in facts}) != len(facts):
            raise WorkflowCAnalysisAdmissionError("Metric Protocol Fact versions must be unique")
        if len({item.question_id for item in baselines}) != len(baselines):
            raise WorkflowCAnalysisAdmissionError(
                "Metric Protocol baseline question scores must be unique"
            )
        corpus_version = _text(self.approved_corpus_version, "approved corpus version")
        for digest, label in (
            (self.approved_corpus_hash, "approved corpus hash"),
            (self.fact_snapshot_hash, "Fact snapshot hash"),
            (self.prompt_release_hash, "Prompt Release hash"),
            (self.corpus_version_hash, "Corpus Version hash"),
        ):
            _hash(digest, label)
        if self.prompt_release_id != self.metric_suite.judge_version.prompt_release_id or (
            self.prompt_release_hash != self.metric_suite.judge_version.prompt_release_hash
        ):
            raise WorkflowCAnalysisAdmissionError(
                "Metric Protocol Prompt Release differs from its Judge Version"
            )
        if self.approved_corpus_hash != self.corpus_version_hash:
            raise WorkflowCAnalysisAdmissionError(
                "Metric Protocol approved corpus differs from its Corpus Version"
            )
        object.__setattr__(self, "approved_facts", facts)
        object.__setattr__(self, "baseline_question_scores", baselines)
        object.__setattr__(self, "verified_urls", urls)
        object.__setattr__(self, "question_clusters", clusters)
        object.__setattr__(self, "approved_corpus_version", corpus_version)
        object.__setattr__(self, "protocol_hash", canonical_hash(self.canonical_value()))

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "metric_suite": metric_suite_value(self.metric_suite),
            "subjects": subject_inventory_value(self.subjects),
            "approved_facts": [item.__dict__ for item in self.approved_facts],
            "verified_urls": list(self.verified_urls),
            "approved_corpus_version": self.approved_corpus_version,
            "approved_corpus_hash": self.approved_corpus_hash,
            "baseline_question_scores": [
                {
                    "question_id": item.question_id,
                    "score": decimal_value(item.score),
                    "snapshot_hash": item.snapshot_hash,
                }
                for item in self.baseline_question_scores
            ],
            "question_clusters": dict(self.question_clusters),
            "fact_snapshot_id": str(self.fact_snapshot_id),
            "fact_snapshot_hash": self.fact_snapshot_hash,
            "prompt_release_id": str(self.prompt_release_id),
            "prompt_release_hash": self.prompt_release_hash,
            "corpus_version_id": str(self.corpus_version_id),
            "corpus_version_hash": self.corpus_version_hash,
        }

    def cluster_for(self, question_id: str) -> str:
        try:
            return dict(self.question_clusters)[question_id]
        except KeyError as error:
            raise WorkflowCAnalysisAdmissionError(
                "Sampling question is absent from the approved Metric Protocol"
            ) from error


@dataclass(frozen=True)
class MetricProtocolVersion:
    id: UUID
    project_id: UUID
    series_id: UUID
    version: int
    supersedes_protocol_id: UUID | None
    status: MetricProtocolStatus
    definition: MetricProtocolDefinition
    created_by: str
    created_at: datetime
    updated_at: datetime
    aggregate_version: int = 1
    submitted_by: str | None = None
    submitted_at: datetime | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    retired_by: str | None = None
    retired_at: datetime | None = None
    decision_reason: str | None = None

    def __post_init__(self) -> None:
        status = MetricProtocolStatus(self.status)
        _aware(self.created_at, "Metric Protocol created_at")
        _aware(self.updated_at, "Metric Protocol updated_at")
        if self.version < 1 or self.aggregate_version < 1 or self.updated_at < self.created_at:
            raise WorkflowCAnalysisAdmissionError("Metric Protocol versions are invalid")
        if (self.version == 1) != (self.supersedes_protocol_id is None):
            raise WorkflowCAnalysisAdmissionError("Metric Protocol predecessor shape is invalid")
        if self.version == 1 and self.series_id != self.id:
            raise WorkflowCAnalysisAdmissionError("Metric Protocol initial series id must equal id")
        _text(self.created_by, "Metric Protocol creator")
        _validate_protocol_state(self, status)
        object.__setattr__(self, "status", status)

    @property
    def protocol_hash(self) -> str:
        return self.definition.protocol_hash


@dataclass(frozen=True)
class AnalysisManifestItem:
    ordinal: int
    task_id: UUID
    task_key: str
    question_id: str
    question_version: str
    question_cluster: str
    repetition: int
    observation_id: UUID | None
    observation_hash: str | None
    observation_status: str
    attempt_id: UUID | None
    source_job_id: UUID | None
    provider_model_attempt_id: UUID | None
    output_hash: str | None
    artifact_kind: AnalysisArtifactKind
    artifact_id: UUID | None
    artifact_manifest_hash: str | None
    artifact_content_hash: str | None
    actual_location_hash: str | None
    item_hash: str = field(init=False)

    def __post_init__(self) -> None:
        kind = AnalysisArtifactKind(self.artifact_kind)
        if self.ordinal < 1 or self.repetition < 1:
            raise WorkflowCAnalysisAdmissionError("Analysis manifest ordinals must be positive")
        _hash(self.task_key, "Sampling Task key")
        for value, label in (
            (self.question_id, "question id"),
            (self.question_version, "question version"),
            (self.question_cluster, "question cluster"),
        ):
            _text(value, label)
        if self.observation_status not in {"complete", "ineligible", "missing"}:
            raise WorkflowCAnalysisAdmissionError("Analysis observation status is invalid")
        if (self.observation_id is None) != (self.observation_hash is None):
            raise WorkflowCAnalysisAdmissionError("Analysis observation lineage is incomplete")
        if (self.attempt_id is None) != (self.source_job_id is None):
            raise WorkflowCAnalysisAdmissionError("Analysis Attempt lineage is incomplete")
        if (self.observation_status == "missing") != (self.observation_id is None):
            raise WorkflowCAnalysisAdmissionError("Analysis missing status differs from membership")
        for digest, label in (
            (self.observation_hash, "Observation hash"),
            (self.output_hash, "Provider output hash"),
            (self.artifact_manifest_hash, "artifact manifest hash"),
            (self.artifact_content_hash, "artifact content hash"),
            (self.actual_location_hash, "actual location hash"),
        ):
            if digest is not None:
                _hash(digest, label)
        if kind is AnalysisArtifactKind.PROVIDER:
            valid = (
                self.provider_model_attempt_id is not None
                and self.output_hash is not None
                and self.artifact_id is None
                and self.artifact_manifest_hash is not None
                and self.artifact_content_hash is not None
            )
        elif kind is AnalysisArtifactKind.MANUAL:
            valid = (
                self.provider_model_attempt_id is None
                and self.output_hash is None
                and self.artifact_id is not None
                and self.artifact_manifest_hash is not None
                and self.artifact_content_hash is not None
            )
        else:
            valid = all(
                item is None
                for item in (
                    self.provider_model_attempt_id,
                    self.output_hash,
                    self.artifact_id,
                    self.artifact_manifest_hash,
                    self.artifact_content_hash,
                )
            )
        if not valid:
            raise WorkflowCAnalysisAdmissionError("Analysis artifact lineage is inconsistent")
        object.__setattr__(self, "artifact_kind", kind)
        object.__setattr__(self, "item_hash", canonical_hash(self.canonical_value()))

    @property
    def slot_id(self) -> str:
        return self.task_key

    def canonical_value(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "task_id": str(self.task_id),
            "task_key": self.task_key,
            "question_id": self.question_id,
            "question_version": self.question_version,
            "question_cluster": self.question_cluster,
            "repetition": self.repetition,
            "observation_id": str(self.observation_id) if self.observation_id else None,
            "observation_hash": self.observation_hash,
            "observation_status": self.observation_status,
            "attempt_id": str(self.attempt_id) if self.attempt_id else None,
            "source_job_id": str(self.source_job_id) if self.source_job_id else None,
            "provider_model_attempt_id": (
                str(self.provider_model_attempt_id) if self.provider_model_attempt_id else None
            ),
            "output_hash": self.output_hash,
            "artifact_kind": self.artifact_kind.value,
            "artifact_id": str(self.artifact_id) if self.artifact_id else None,
            "artifact_manifest_hash": self.artifact_manifest_hash,
            "artifact_content_hash": self.artifact_content_hash,
            "actual_location_hash": self.actual_location_hash,
        }


@dataclass(frozen=True)
class AnalysisInputManifest:
    id: UUID
    project_id: UUID
    sampling_run_id: UUID
    sampling_run_version: int
    sampling_suite_hash: str
    metric_protocol_id: UUID
    metric_protocol_hash: str
    fact_snapshot_id: UUID
    fact_snapshot_hash: str
    prompt_release_id: UUID
    prompt_release_hash: str
    corpus_version_id: UUID
    corpus_version_hash: str
    baseline_snapshot_hash: str | None
    source_stratum_hash: str
    capture_method: str
    stratum: tuple[tuple[str, str], ...]
    items: tuple[AnalysisManifestItem, ...]
    frozen_by: str
    frozen_at: datetime
    manifest_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.sampling_run_version < 1 or not self.items:
            raise WorkflowCAnalysisAdmissionError("Analysis manifest needs a versioned non-empty Run")
        for digest, label in (
            (self.sampling_suite_hash, "Sampling Suite hash"),
            (self.metric_protocol_hash, "Metric Protocol hash"),
            (self.fact_snapshot_hash, "Fact snapshot hash"),
            (self.prompt_release_hash, "Prompt Release hash"),
            (self.corpus_version_hash, "Corpus Version hash"),
            (self.source_stratum_hash, "SourceStratum hash"),
        ):
            _hash(digest, label)
        if self.baseline_snapshot_hash is not None:
            _hash(self.baseline_snapshot_hash, "baseline snapshot hash")
        if self.capture_method not in _CAPTURE_METHODS:
            raise WorkflowCAnalysisAdmissionError("Analysis capture method is invalid")
        dimensions = tuple(sorted((_text(k, "stratum key"), _text(v, "stratum value")) for k, v in self.stratum))
        if not dimensions or len({key for key, _ in dimensions}) != len(dimensions):
            raise WorkflowCAnalysisAdmissionError("Analysis stratum is invalid")
        items = tuple(sorted(self.items, key=lambda item: item.ordinal))
        if tuple(item.ordinal for item in items) != tuple(range(1, len(items) + 1)):
            raise WorkflowCAnalysisAdmissionError("Analysis manifest ordinals must be contiguous")
        if len({item.task_id for item in items}) != len(items) or len(
            {item.task_key for item in items}
        ) != len(items):
            raise WorkflowCAnalysisAdmissionError("Analysis manifest Tasks must be unique")
        _text(self.frozen_by, "Analysis manifest freezer")
        _aware(self.frozen_at, "Analysis manifest frozen_at")
        object.__setattr__(self, "stratum", dimensions)
        object.__setattr__(self, "items", items)
        object.__setattr__(self, "manifest_hash", canonical_hash(self.canonical_value()))

    @property
    def observation_count(self) -> int:
        return sum(item.observation_id is not None for item in self.items)

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "project_id": str(self.project_id),
            "sampling_run_id": str(self.sampling_run_id),
            "sampling_run_version": self.sampling_run_version,
            "sampling_suite_hash": self.sampling_suite_hash,
            "metric_protocol_id": str(self.metric_protocol_id),
            "metric_protocol_hash": self.metric_protocol_hash,
            "fact_snapshot_id": str(self.fact_snapshot_id),
            "fact_snapshot_hash": self.fact_snapshot_hash,
            "prompt_release_id": str(self.prompt_release_id),
            "prompt_release_hash": self.prompt_release_hash,
            "corpus_version_id": str(self.corpus_version_id),
            "corpus_version_hash": self.corpus_version_hash,
            "baseline_snapshot_hash": self.baseline_snapshot_hash,
            "source_stratum_hash": self.source_stratum_hash,
            "capture_method": self.capture_method,
            "stratum": dict(self.stratum),
            "items": [item.canonical_value() | {"item_hash": item.item_hash} for item in self.items],
        }

    def job_payload(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "kind": "workflow_c.analysis.semantic_metrics",
            "semantic_metrics": {
                "manifest_id": str(self.id),
                "manifest_hash": self.manifest_hash,
            },
        }


def metric_suite_value(value: FrozenMetricSuite) -> dict[str, object]:
    return {
        "definitions": [
            {
                "key": item.key.value,
                "version": item.version,
                "value_kind": item.value_kind.value,
                "judge_kind": item.judge_kind.value if item.judge_kind else None,
            }
            for item in value.definitions
        ],
        "judge_version": value.judge_version.canonical_value(),
        "rule_versions": value.rule_versions.canonical_value(),
        "minimum_valid_completion": decimal_value(value.minimum_valid_completion),
    }


def subject_inventory_value(value: SubjectInventory) -> dict[str, object]:
    return {
        "primary_subject_key": value.primary_subject_key,
        "brand_aliases": list(value.brand_aliases),
        "product_aliases": list(value.product_aliases),
        "competitors": [[key, list(aliases)] for key, aliases in value.competitors],
    }


def canonical_hash(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, UnicodeEncodeError, ValueError) as error:
        raise WorkflowCAnalysisAdmissionError("Analysis value is not canonical JSON") from error
    return hashlib.sha256(encoded).hexdigest()


def command_input_hash(value: Mapping[str, object]) -> str:
    return canonical_hash(value)


def _validate_protocol_state(
    value: MetricProtocolVersion, status: MetricProtocolStatus
) -> None:
    submitted = (value.submitted_by, value.submitted_at)
    approved = (value.approved_by, value.approved_at)
    retired = (value.retired_by, value.retired_at)
    if status is MetricProtocolStatus.DRAFT:
        valid = submitted == approved == retired == (None, None) and value.decision_reason is None
    elif status is MetricProtocolStatus.IN_REVIEW:
        valid = (
            all(item is not None for item in submitted)
            and approved == retired == (None, None)
            and value.decision_reason is None
        )
    elif status is MetricProtocolStatus.APPROVED:
        valid = (
            all(item is not None for item in (*submitted, *approved))
            and retired == (None, None)
            and value.decision_reason is not None
            and value.approved_by != value.created_by
        )
    else:
        valid = (
            all(item is not None for item in (*submitted, *approved, *retired))
            and value.decision_reason is not None
            and value.approved_by != value.created_by
        )
    if not valid:
        raise WorkflowCAnalysisAdmissionError("Metric Protocol lifecycle evidence is invalid")
    for instant in (value.submitted_at, value.approved_at, value.retired_at):
        if instant is not None:
            _aware(instant, "Metric Protocol lifecycle time")


def _text(value: str, label: str, *, maximum: int = 500) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise WorkflowCAnalysisAdmissionError(f"{label} is invalid")
    return normalized


def _hash(value: str, label: str) -> str:
    if _SHA256.fullmatch(value) is None:
        raise WorkflowCAnalysisAdmissionError(f"{label} must be SHA-256")
    return value


def _aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise WorkflowCAnalysisAdmissionError(f"{label} must be timezone-aware")
