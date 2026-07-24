"""Immutable inputs, versions and outputs for semantic GEO metrics."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from geo_core.semantic_metrics._validation import (
    SHA256_PATTERN,
    SemanticMetricRuleViolation,
    aliases as _aliases,
    canonical_hash,
    decimal_value,
    finite as _finite,
    key as _key,
    optional_text as _optional_text,
    ratio as _ratio,
    text as _text,
)


class MetricKey(StrEnum):
    BRAND_MENTION = "brand_mention"
    PRODUCT_MENTION = "product_mention"
    RECOMMENDATION = "recommendation"
    RECOMMENDATION_STRENGTH = "recommendation_strength"
    COMPETITOR_MENTION = "competitor_mention"
    COMPETITOR_RELATIVE_POSITION = "competitor_relative_position"
    SENTIMENT = "sentiment"
    FACT_ACCURACY = "fact_accuracy"
    EXPLICIT_CONFLICT = "explicit_conflict"
    SUBJECT_MIXUP = "subject_mixup"
    KEY_FACT_OMISSION = "key_fact_omission"
    CITATION_ENTAILMENT = "citation_entailment"
    CITATION_POSITION = "citation_position"
    CITATION_ORDER = "citation_order"
    VERIFIED_URL_HIT = "verified_url_hit"
    SOURCE_DOMAIN_DIVERSITY = "source_domain_diversity"
    SOURCE_TYPE_DIVERSITY = "source_type_diversity"
    APPROVED_CORPUS_ABSORPTION = "approved_corpus_absorption"


class MetricValueKind(StrEnum):
    BINARY_RATE = "binary_rate"
    MEAN_SCORE = "mean_score"
    SIGNED_SCORE = "signed_score"
    COUNT = "count"


class MetricStatus(StrEnum):
    COMPLETE = "complete"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class JudgeKind(StrEnum):
    RECOMMENDATION = "recommendation"
    SENTIMENT = "sentiment"
    FACT = "fact"
    CITATION_ENTAILMENT = "citation_entailment"
    CORPUS_ABSORPTION = "corpus_absorption"


class EvidenceLocatorKind(StrEnum):
    ANSWER_SPAN = "answer_span"
    CITATION = "citation"
    FACT = "fact"


@dataclass(frozen=True)
class EvidenceLocator:
    kind: EvidenceLocatorKind
    reference_id: str
    version: str | None = None
    content_hash: str | None = None
    start: int | None = None
    end: int | None = None
    redacted_quote_hash: str | None = None

    def __post_init__(self) -> None:
        try:
            kind = EvidenceLocatorKind(self.kind)
        except ValueError as error:
            raise SemanticMetricRuleViolation("evidence locator kind is unsupported") from error
        reference_id = _text(self.reference_id, "evidence locator reference")
        version = _optional_text(self.version, "evidence locator version")
        content_hash = self.content_hash
        redacted_quote_hash = self.redacted_quote_hash
        if content_hash is not None and not SHA256_PATTERN.fullmatch(content_hash):
            raise SemanticMetricRuleViolation("evidence locator content hash must be SHA-256")
        if redacted_quote_hash is not None and not SHA256_PATTERN.fullmatch(
            redacted_quote_hash
        ):
            raise SemanticMetricRuleViolation(
                "evidence locator redacted quote hash must be SHA-256"
            )
        if kind is EvidenceLocatorKind.ANSWER_SPAN:
            if (
                self.start is None
                or self.end is None
                or self.start < 0
                or self.end <= self.start
                or self.end - self.start > 512
                or version is None
                or content_hash is None
            ):
                raise SemanticMetricRuleViolation("answer span locator is incomplete")
        elif (
            self.start is not None
            or self.end is not None
            or content_hash is not None
            or redacted_quote_hash is not None
        ):
            raise SemanticMetricRuleViolation("only an answer span locator can contain offsets")
        if kind is EvidenceLocatorKind.FACT and version is None:
            raise SemanticMetricRuleViolation("fact locator requires an approved version")
        if kind is EvidenceLocatorKind.CITATION and version is not None:
            raise SemanticMetricRuleViolation("citation locator cannot claim a version")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "reference_id", reference_id)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "content_hash", content_hash)
        object.__setattr__(self, "redacted_quote_hash", redacted_quote_hash)

    def canonical_value(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "reference_id": self.reference_id,
            "version": self.version,
            "content_hash": self.content_hash,
            "start": self.start,
            "end": self.end,
            "redacted_quote_hash": self.redacted_quote_hash,
        }


@dataclass(frozen=True)
class StructuredJudgeOutput:
    kind: JudgeKind
    label: str
    score: Decimal | None
    reason_codes: tuple[str, ...]
    locators: tuple[EvidenceLocator, ...]
    schema_version: str
    # Generic judges have no metric identity.  The metric_judge adapter preserves
    # its frozen result ID here so two metrics sharing a JudgeKind remain distinct.
    metric_id: str | None = None
    output_hash: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            kind = JudgeKind(self.kind)
        except ValueError as error:
            raise SemanticMetricRuleViolation("judge kind is unsupported") from error
        label = _key(self.label, "judge label")
        schema_version = _key(self.schema_version, "judge schema version")
        metric_id = (
            _text(self.metric_id, "judge metric id", maximum=200)
            if self.metric_id is not None
            else None
        )
        if self.score is not None:
            _finite(self.score, "judge score")
        reasons = tuple(sorted({_key(item, "judge reason code") for item in self.reason_codes}))
        locators = tuple(sorted(self.locators, key=_locator_sort_key))
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "metric_id", metric_id)
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(self, "locators", locators)
        object.__setattr__(self, "output_hash", canonical_hash(self.canonical_value()))

    def canonical_value(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "label": self.label,
            "score": decimal_value(self.score),
            "reason_codes": list(self.reason_codes),
            "locators": [item.canonical_value() for item in self.locators],
            "schema_version": self.schema_version,
            "metric_id": self.metric_id,
        }


@dataclass(frozen=True, order=True)
class PlannedMetricSlot:
    slot_id: str
    question_id: str
    question_cluster: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "slot_id", _text(self.slot_id, "metric slot id"))
        object.__setattr__(self, "question_id", _text(self.question_id, "question id"))
        object.__setattr__(
            self, "question_cluster", _text(self.question_cluster, "question cluster")
        )


@dataclass(frozen=True)
class CitationInput:
    id: str
    ordinal: int
    url: str
    visible_title: str
    source_type: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _text(self.id, "citation id"))
        object.__setattr__(self, "url", _text(self.url, "citation URL", maximum=2000))
        object.__setattr__(
            self, "visible_title", _text(self.visible_title, "citation visible title")
        )
        object.__setattr__(self, "source_type", _key(self.source_type, "citation source type"))
        if self.ordinal < 1:
            raise SemanticMetricRuleViolation("citation ordinal must be positive")

    def canonical_value(self) -> dict[str, object]:
        return {
            "id": self.id,
            "ordinal": self.ordinal,
            "url": self.url,
            "visible_title": self.visible_title,
            "source_type": self.source_type,
        }


@dataclass(frozen=True)
class SubjectAssertion:
    claimed_subject_key: str
    catalog_subject_key: str
    locator: EvidenceLocator

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "claimed_subject_key",
            _key(self.claimed_subject_key, "claimed subject key"),
        )
        object.__setattr__(
            self,
            "catalog_subject_key",
            _key(self.catalog_subject_key, "catalog subject key"),
        )
        if self.locator.kind is not EvidenceLocatorKind.ANSWER_SPAN:
            raise SemanticMetricRuleViolation("subject assertion requires an answer span")


@dataclass(frozen=True)
class MetricObservation:
    id: UUID
    slot_id: str
    payload_hash: str
    question_id: str
    question_cluster: str
    answer_text: str
    artifact_version: str = "observation-artifact-v1"
    citations: tuple[CitationInput, ...] = ()
    subject_assertions: tuple[SubjectAssertion, ...] = ()
    judge_outputs: tuple[StructuredJudgeOutput, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "slot_id", _text(self.slot_id, "observation slot id"))
        object.__setattr__(self, "question_id", _text(self.question_id, "question id"))
        object.__setattr__(
            self, "question_cluster", _text(self.question_cluster, "question cluster")
        )
        answer = _text(self.answer_text, "answer text", maximum=100_000)
        artifact_version = _key(self.artifact_version, "observation artifact version")
        if not SHA256_PATTERN.fullmatch(self.payload_hash):
            raise SemanticMetricRuleViolation("observation payload hash must be SHA-256")
        citation_ids = [item.id for item in self.citations]
        if len(set(citation_ids)) != len(citation_ids):
            raise SemanticMetricRuleViolation("observation citation ids must be unique")
        object.__setattr__(self, "answer_text", answer)
        object.__setattr__(self, "artifact_version", artifact_version)
        object.__setattr__(self, "citations", tuple(self.citations))
        object.__setattr__(self, "subject_assertions", tuple(self.subject_assertions))
        object.__setattr__(self, "judge_outputs", tuple(self.judge_outputs))

    def canonical_value(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "slot_id": self.slot_id,
            "payload_hash": self.payload_hash,
            "question_id": self.question_id,
            "question_cluster": self.question_cluster,
            "artifact_version": self.artifact_version,
            "answer_text": self.answer_text,
            "citations": [item.canonical_value() for item in self.citations],
            "subject_assertions": [
                {
                    "claimed_subject_key": item.claimed_subject_key,
                    "catalog_subject_key": item.catalog_subject_key,
                    "locator": item.locator.canonical_value(),
                }
                for item in self.subject_assertions
            ],
            "judge_outputs": [item.canonical_value() for item in self.judge_outputs],
        }


@dataclass(frozen=True, order=True)
class ApprovedFactReference:
    id: str
    version: str
    subject_key: str
    sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _text(self.id, "approved Fact id"))
        object.__setattr__(self, "version", _text(self.version, "approved Fact version"))
        object.__setattr__(self, "subject_key", _key(self.subject_key, "Fact subject key"))
        if not SHA256_PATTERN.fullmatch(self.sha256):
            raise SemanticMetricRuleViolation("approved Fact hash must be SHA-256")


@dataclass(frozen=True)
class SubjectInventory:
    primary_subject_key: str
    brand_aliases: tuple[str, ...]
    product_aliases: tuple[str, ...]
    competitors: tuple[tuple[str, tuple[str, ...]], ...]

    def __post_init__(self) -> None:
        primary = _key(self.primary_subject_key, "primary subject key")
        brands = _aliases(self.brand_aliases, "brand aliases")
        products = _aliases(self.product_aliases, "product aliases")
        competitors: list[tuple[str, tuple[str, ...]]] = []
        seen: set[str] = set()
        for raw_key, raw_aliases in self.competitors:
            key = _key(raw_key, "competitor subject key")
            if key == primary or key in seen:
                raise SemanticMetricRuleViolation("competitor subject keys must be distinct")
            seen.add(key)
            competitors.append((key, _aliases(raw_aliases, "competitor aliases")))
        object.__setattr__(self, "primary_subject_key", primary)
        object.__setattr__(self, "brand_aliases", brands)
        object.__setattr__(self, "product_aliases", products)
        object.__setattr__(self, "competitors", tuple(sorted(competitors)))


@dataclass(frozen=True)
class SemanticStratum:
    dimensions: tuple[tuple[str, str], ...]
    stratum_hash: str = field(init=False)

    def __post_init__(self) -> None:
        normalized = tuple(
            sorted(
                (_key(key, "stratum key"), _text(value, "stratum value"))
                for key, value in self.dimensions
            )
        )
        if not normalized or len({key for key, _ in normalized}) != len(normalized):
            raise SemanticMetricRuleViolation(
                "semantic stratum dimensions must be non-empty and unique"
            )
        object.__setattr__(self, "dimensions", normalized)
        object.__setattr__(self, "stratum_hash", canonical_hash(dict(normalized)))


@dataclass(frozen=True, order=True)
class BaselineQuestionScore:
    question_id: str
    score: Decimal
    snapshot_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "question_id", _text(self.question_id, "baseline question id"))
        _ratio(self.score, "baseline question score")
        if not SHA256_PATTERN.fullmatch(self.snapshot_hash):
            raise SemanticMetricRuleViolation("baseline snapshot hash must be SHA-256")


@dataclass(frozen=True)
class MetricInputSet:
    stratum: SemanticStratum
    planned_slots: tuple[PlannedMetricSlot, ...]
    observations: tuple[MetricObservation, ...]
    subjects: SubjectInventory
    approved_facts: tuple[ApprovedFactReference, ...]
    verified_urls: tuple[str, ...]
    approved_corpus_version: str
    approved_corpus_hash: str
    baseline_question_scores: tuple[BaselineQuestionScore, ...] = ()
    input_set_hash: str = field(init=False)

    def __post_init__(self) -> None:
        slots = tuple(sorted(self.planned_slots))
        if not slots or len({item.slot_id for item in slots}) != len(slots):
            raise SemanticMetricRuleViolation("planned metric slots must be non-empty and unique")
        slot_by_id = {item.slot_id: item for item in slots}
        observations = tuple(sorted(self.observations, key=lambda item: item.slot_id))
        if len({item.slot_id for item in observations}) != len(observations):
            raise SemanticMetricRuleViolation("one observation may occupy each planned slot")
        for observation in observations:
            slot = slot_by_id.get(observation.slot_id)
            if slot is None or (
                slot.question_id != observation.question_id
                or slot.question_cluster != observation.question_cluster
            ):
                raise SemanticMetricRuleViolation("observation does not match its planned slot")
        citation_ids = [item.id for obs in observations for item in obs.citations]
        if len(set(citation_ids)) != len(citation_ids):
            raise SemanticMetricRuleViolation("citation ids must be unique within an input set")
        facts = tuple(sorted(self.approved_facts))
        if len({(item.id, item.version) for item in facts}) != len(facts):
            raise SemanticMetricRuleViolation("approved Fact versions must be unique")
        baselines = tuple(sorted(self.baseline_question_scores))
        if len({item.question_id for item in baselines}) != len(baselines):
            raise SemanticMetricRuleViolation("baseline question scores must be unique")
        corpus_version = _text(self.approved_corpus_version, "approved corpus version")
        if not SHA256_PATTERN.fullmatch(self.approved_corpus_hash):
            raise SemanticMetricRuleViolation("approved corpus hash must be SHA-256")
        urls = tuple(
            sorted({_text(item, "verified URL", maximum=2000) for item in self.verified_urls})
        )
        object.__setattr__(self, "planned_slots", slots)
        object.__setattr__(self, "observations", observations)
        object.__setattr__(self, "approved_facts", facts)
        object.__setattr__(self, "verified_urls", urls)
        object.__setattr__(self, "approved_corpus_version", corpus_version)
        object.__setattr__(self, "baseline_question_scores", baselines)
        object.__setattr__(self, "input_set_hash", canonical_hash(self.canonical_value()))

    def canonical_value(self) -> dict[str, object]:
        return {
            "stratum": dict(self.stratum.dimensions),
            "planned_slots": [item.__dict__ for item in self.planned_slots],
            "observations": [item.canonical_value() for item in self.observations],
            "subjects": {
                "primary_subject_key": self.subjects.primary_subject_key,
                "brand_aliases": list(self.subjects.brand_aliases),
                "product_aliases": list(self.subjects.product_aliases),
                "competitors": [[key, list(aliases)] for key, aliases in self.subjects.competitors],
            },
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
        }


@dataclass(frozen=True)
class JudgeVersion:
    key: str
    version: str
    prompt_release_id: UUID
    prompt_release_hash: str
    model_identity: str
    schema_version: str
    version_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", _key(self.key, "judge key"))
        object.__setattr__(self, "version", _key(self.version, "judge version"))
        object.__setattr__(
            self, "model_identity", _text(self.model_identity, "judge model identity")
        )
        object.__setattr__(
            self, "schema_version", _key(self.schema_version, "judge schema version")
        )
        if not SHA256_PATTERN.fullmatch(self.prompt_release_hash):
            raise SemanticMetricRuleViolation("judge Prompt Release hash must be SHA-256")
        object.__setattr__(self, "version_hash", canonical_hash(self.canonical_value()))

    def canonical_value(self) -> dict[str, object]:
        return {
            "key": self.key,
            "version": self.version,
            "prompt_release_id": str(self.prompt_release_id),
            "prompt_release_hash": self.prompt_release_hash,
            "model_identity": self.model_identity,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class DeterministicRuleVersions:
    subject: str
    url: str
    citation_order: str
    denominator: str
    mention: str
    versions_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("subject", "url", "citation_order", "denominator", "mention"):
            object.__setattr__(self, name, _key(getattr(self, name), f"{name} rule version"))
        object.__setattr__(self, "versions_hash", canonical_hash(self.canonical_value()))

    def canonical_value(self) -> dict[str, object]:
        return {
            name: getattr(self, name)
            for name in ("subject", "url", "citation_order", "denominator", "mention")
        }


@dataclass(frozen=True, order=True)
class MetricDefinition:
    key: MetricKey
    version: str
    value_kind: MetricValueKind
    judge_kind: JudgeKind | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", MetricKey(self.key))
        object.__setattr__(self, "version", _key(self.version, "metric version"))
        object.__setattr__(self, "value_kind", MetricValueKind(self.value_kind))
        if self.judge_kind is not None:
            object.__setattr__(self, "judge_kind", JudgeKind(self.judge_kind))


@dataclass(frozen=True)
class FrozenMetricSuite:
    definitions: tuple[MetricDefinition, ...]
    judge_version: JudgeVersion
    rule_versions: DeterministicRuleVersions
    minimum_valid_completion: Decimal = Decimal("0.80")
    suite_hash: str = field(init=False)

    def __post_init__(self) -> None:
        definitions = tuple(sorted(self.definitions))
        if not definitions or len({item.key for item in definitions}) != len(definitions):
            raise SemanticMetricRuleViolation("metric definitions must be non-empty and unique")
        if not Decimal(0) < self.minimum_valid_completion <= Decimal(1):
            raise SemanticMetricRuleViolation("metric completion threshold must be in (0, 1]")
        object.__setattr__(self, "definitions", definitions)
        object.__setattr__(
            self,
            "suite_hash",
            canonical_hash(
                {
                    "definitions": [
                        {
                            "key": item.key.value,
                            "version": item.version,
                            "value_kind": item.value_kind.value,
                            "judge_kind": item.judge_kind.value if item.judge_kind else None,
                        }
                        for item in definitions
                    ],
                    "judge_version_hash": self.judge_version.version_hash,
                    "rule_versions_hash": self.rule_versions.versions_hash,
                    "minimum_valid_completion": decimal_value(self.minimum_valid_completion),
                }
            ),
        )


def _locator_sort_key(locator: EvidenceLocator) -> tuple[object, ...]:
    return (
        locator.kind.value,
        locator.reference_id,
        locator.version or "",
        locator.content_hash or "",
        locator.start or -1,
        locator.end or -1,
        locator.redacted_quote_hash or "",
    )
