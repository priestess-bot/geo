"""Deterministic nine-channel fixed acceptance matrix for the Synthetic Lab."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping
from uuid import UUID, uuid5

from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.domain import (
    STANDARD_STYLE_CHANNELS,
    SyntheticLabContractError,
    SyntheticOnly,
    _require_hash,
    _require_text,
    _require_uuid,
)
from geo_core.synthetic_lab.review_cases import (
    ReviewCase,
    ReviewSuite,
    ReviewSuiteStatus,
    ScenarioMode,
    review_case_content_hash,
)


CASES_PER_CHANNEL = 40
MODE_CASES_PER_CHANNEL = 20
COMPETITOR_CASES_PER_CHANNEL = 12
GUIDED_REFERENCE_PREFIX = "Creative cue only:"
REQUIRED_ACCEPTANCE_RISKS = frozenset(
    {
        "subject_mixup",
        "derived_or_unknown",
        "explicit_conflict",
        "style_mismatch",
        "source_replication",
        "fact_retired",
    }
)


@dataclass(frozen=True, kw_only=True)
class ChannelProfileBinding:
    channel: str
    profile_version_id: UUID
    profile_hash: str

    def __post_init__(self) -> None:
        if self.channel not in STANDARD_STYLE_CHANNELS:
            raise SyntheticLabContractError("acceptance Profile channel is not standard")
        _require_uuid(self.profile_version_id, "acceptance Profile version")
        _require_hash(self.profile_hash, "acceptance Profile")


@dataclass(frozen=True, kw_only=True)
class AcceptanceMatrixInput:
    project_id: UUID
    question_set_version_id: UUID
    question_set_hash: str
    fact_snapshot_id: UUID
    fact_snapshot_hash: str
    subject: str
    competitor_subject: str
    profiles: Mapping[str, ChannelProfileBinding]
    input_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for value, label in (
            (self.project_id, "acceptance Project"),
            (self.question_set_version_id, "acceptance QuestionSet version"),
            (self.fact_snapshot_id, "acceptance Fact snapshot"),
        ):
            _require_uuid(value, label)
        _require_hash(self.question_set_hash, "acceptance QuestionSet")
        _require_hash(self.fact_snapshot_hash, "acceptance Fact snapshot")
        _require_text(self.subject, "acceptance subject")
        _require_text(self.competitor_subject, "acceptance competitor subject")
        if self.subject == self.competitor_subject:
            raise SyntheticLabContractError("acceptance subjects must be distinct")
        profiles = MappingProxyType(dict(self.profiles))
        object.__setattr__(self, "profiles", profiles)
        if set(profiles) != set(STANDARD_STYLE_CHANNELS):
            raise SyntheticLabContractError("acceptance matrix requires all nine Profiles")
        if any(key != profile.channel for key, profile in profiles.items()):
            raise SyntheticLabContractError("acceptance Profile mapping key changed channel")
        object.__setattr__(
            self,
            "input_hash",
            canonical_hash(
                {
                    "project_id": self.project_id,
                    "question_set_version_id": self.question_set_version_id,
                    "question_set_hash": self.question_set_hash,
                    "fact_snapshot_id": self.fact_snapshot_id,
                    "fact_snapshot_hash": self.fact_snapshot_hash,
                    "subject": self.subject,
                    "competitor_subject": self.competitor_subject,
                    "profiles": profiles,
                }
            ),
        )


@dataclass(frozen=True, kw_only=True)
class AcceptanceMatrixManifest(SyntheticOnly):
    project_id: UUID
    matrix_input_hash: str
    matrix_hash: str
    channel_case_counts: Mapping[str, int]
    channel_autonomous_counts: Mapping[str, int]
    channel_guided_counts: Mapping[str, int]
    channel_competitor_counts: Mapping[str, int]
    covered_risks: tuple[str, ...]
    fixture_schema_baseline: bool = field(default=True, init=False)
    real_sample_threshold_evidence: bool = field(default=False, init=False)
    human_review_evidence: bool = field(default=False, init=False)
    manifest_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_uuid(self.project_id, "acceptance manifest Project")
        _require_hash(self.matrix_input_hash, "acceptance matrix input")
        _require_hash(self.matrix_hash, "acceptance matrix")
        for name in (
            "channel_case_counts",
            "channel_autonomous_counts",
            "channel_guided_counts",
            "channel_competitor_counts",
        ):
            values = MappingProxyType(dict(getattr(self, name)))
            object.__setattr__(self, name, values)
            if set(values) != set(STANDARD_STYLE_CHANNELS):
                raise SyntheticLabContractError("acceptance manifest omitted a channel")
        if any(value != CASES_PER_CHANNEL for value in self.channel_case_counts.values()):
            raise SyntheticLabContractError("acceptance manifest channel Case count changed")
        if any(
            value != MODE_CASES_PER_CHANNEL
            for counts in (
                self.channel_autonomous_counts,
                self.channel_guided_counts,
            )
            for value in counts.values()
        ):
            raise SyntheticLabContractError("acceptance manifest scenario balance changed")
        if any(
            value < COMPETITOR_CASES_PER_CHANNEL
            for value in self.channel_competitor_counts.values()
        ):
            raise SyntheticLabContractError("acceptance manifest competitor coverage is too low")
        risks = tuple(sorted(set(self.covered_risks)))
        object.__setattr__(self, "covered_risks", risks)
        if not REQUIRED_ACCEPTANCE_RISKS.issubset(risks):
            raise SyntheticLabContractError("acceptance manifest omitted a required risk")
        object.__setattr__(self, "manifest_hash", canonical_hash(self.value()))

    def value(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "matrix_input_hash": self.matrix_input_hash,
            "matrix_hash": self.matrix_hash,
            "channel_case_counts": self.channel_case_counts,
            "channel_autonomous_counts": self.channel_autonomous_counts,
            "channel_guided_counts": self.channel_guided_counts,
            "channel_competitor_counts": self.channel_competitor_counts,
            "covered_risks": self.covered_risks,
            "fixture_schema_baseline": True,
            "real_sample_threshold_evidence": False,
            "human_review_evidence": False,
            "synthetic": True,
            "test_only": True,
            "publication_eligible": False,
        }


@dataclass(frozen=True, kw_only=True)
class AcceptanceMatrix(SyntheticOnly):
    inputs: AcceptanceMatrixInput
    suites: tuple[ReviewSuite, ...]
    cases: tuple[ReviewCase, ...]
    manifest: AcceptanceMatrixManifest

    def __post_init__(self) -> None:
        suites = tuple(self.suites)
        cases = tuple(self.cases)
        object.__setattr__(self, "suites", suites)
        object.__setattr__(self, "cases", cases)
        if len(suites) != len(STANDARD_STYLE_CHANNELS) or len(cases) != 360:
            raise SyntheticLabContractError("acceptance matrix must contain 9 Suites and 360 Cases")
        if {item.channel for item in suites} != set(STANDARD_STYLE_CHANNELS):
            raise SyntheticLabContractError("acceptance matrix Suite channels are incomplete")
        if len({item.id for item in cases}) != len(cases):
            raise SyntheticLabContractError("acceptance matrix Case identities are duplicated")
        _validate_cases(self.inputs, suites, cases)
        if self.manifest.project_id != self.inputs.project_id:
            raise SyntheticLabContractError("acceptance manifest crosses Project scope")
        expected_matrix_hash = _matrix_hash(self.inputs, suites, cases)
        if (
            self.manifest.matrix_input_hash != self.inputs.input_hash
            or self.manifest.matrix_hash != expected_matrix_hash
        ):
            raise SyntheticLabContractError("acceptance manifest does not bind the matrix")

    @property
    def matrix_hash(self) -> str:
        return self.manifest.matrix_hash


def build_acceptance_matrix(inputs: AcceptanceMatrixInput) -> AcceptanceMatrix:
    namespace = uuid5(inputs.project_id, f"synthetic-acceptance:{inputs.input_hash}")
    suites: list[ReviewSuite] = []
    cases: list[ReviewCase] = []
    for channel in sorted(STANDARD_STYLE_CHANNELS):
        suite_id = uuid5(namespace, f"suite:{channel}")
        suite_version_id = uuid5(namespace, f"suite-version:{channel}:1")
        channel_cases = tuple(
            _build_case(
                inputs,
                channel=channel,
                suite_version_id=suite_version_id,
                ordinal=ordinal,
            )
            for ordinal in range(1, CASES_PER_CHANNEL + 1)
        )
        suites.append(
            ReviewSuite(
                id=suite_version_id,
                project_id=inputs.project_id,
                suite_id=suite_id,
                version_number=1,
                channel=channel,
                case_count=len(channel_cases),
                case_set_hash=canonical_hash([item.content_hash for item in channel_cases]),
                status=ReviewSuiteStatus.FROZEN,
            )
        )
        cases.extend(channel_cases)
    suite_values = tuple(suites)
    case_values = tuple(cases)
    matrix_hash = _matrix_hash(inputs, suite_values, case_values)
    manifest = _manifest(inputs, suite_values, case_values, matrix_hash)
    return AcceptanceMatrix(
        inputs=inputs,
        suites=suite_values,
        cases=case_values,
        manifest=manifest,
    )


def _build_case(
    inputs: AcceptanceMatrixInput,
    *,
    channel: str,
    suite_version_id: UUID,
    ordinal: int,
) -> ReviewCase:
    mode = ScenarioMode.AUTONOMOUS if ordinal <= 20 else ScenarioMode.GUIDED
    local_ordinal = ordinal if ordinal <= 20 else ordinal - 20
    competitor = local_ordinal <= 6
    risk_cycle = tuple(sorted(REQUIRED_ACCEPTANCE_RISKS))
    risks = {risk_cycle[(ordinal - 1) % len(risk_cycle)]}
    if competitor:
        risks.add("subject_mixup")
    creative_reference = (
        f"{GUIDED_REFERENCE_PREFIX} use a realistic Australian purchase setting for "
        f"{channel}; never treat this cue as product evidence."
        if mode is ScenarioMode.GUIDED
        else None
    )
    persona = _PERSONAS[(ordinal - 1) % len(_PERSONAS)]
    use_case = _USE_CASES[(ordinal - 1) % len(_USE_CASES)]
    if competitor:
        use_case = f"{use_case}; compare with {inputs.competitor_subject} without changing subject"
    case_key = f"{channel}-fixed-{ordinal:02d}"
    profile = inputs.profiles[channel]
    expected_risks = tuple(sorted(risks))
    content_hash = review_case_content_hash(
        case_key=case_key,
        ordinal=ordinal,
        mode=mode,
        channel=channel,
        persona=persona,
        use_case=use_case,
        subject=inputs.subject,
        question_set_version_id=inputs.question_set_version_id,
        question_set_hash=inputs.question_set_hash,
        fact_snapshot_id=inputs.fact_snapshot_id,
        fact_snapshot_hash=inputs.fact_snapshot_hash,
        profile_version_id=profile.profile_version_id,
        profile_hash=profile.profile_hash,
        competitor_scenario=competitor,
        expected_risks=expected_risks,
        creative_reference=creative_reference,
    )
    return ReviewCase(
        id=uuid5(suite_version_id, f"case:{ordinal}:{content_hash}"),
        project_id=inputs.project_id,
        review_suite_version_id=suite_version_id,
        review_suite_version_number=1,
        case_key=case_key,
        ordinal=ordinal,
        mode=mode,
        channel=channel,
        persona=persona,
        use_case=use_case,
        subject=inputs.subject,
        question_set_version_id=inputs.question_set_version_id,
        question_set_hash=inputs.question_set_hash,
        fact_snapshot_id=inputs.fact_snapshot_id,
        fact_snapshot_hash=inputs.fact_snapshot_hash,
        profile_version_id=profile.profile_version_id,
        profile_hash=profile.profile_hash,
        competitor_scenario=competitor,
        expected_risks=expected_risks,
        creative_reference=creative_reference,
        content_hash=content_hash,
    )


def _validate_cases(
    inputs: AcceptanceMatrixInput,
    suites: tuple[ReviewSuite, ...],
    cases: tuple[ReviewCase, ...],
) -> None:
    for suite in suites:
        channel_cases = tuple(item for item in cases if item.channel == suite.channel)
        autonomous = tuple(item for item in channel_cases if item.mode is ScenarioMode.AUTONOMOUS)
        guided = tuple(item for item in channel_cases if item.mode is ScenarioMode.GUIDED)
        competitors = tuple(item for item in channel_cases if item.competitor_scenario)
        risks = {risk for item in channel_cases for risk in item.expected_risks}
        if (
            len(channel_cases) != CASES_PER_CHANNEL
            or len(autonomous) != MODE_CASES_PER_CHANNEL
            or len(guided) != MODE_CASES_PER_CHANNEL
            or len(competitors) < COMPETITOR_CASES_PER_CHANNEL
            or not REQUIRED_ACCEPTANCE_RISKS.issubset(risks)
        ):
            raise SyntheticLabContractError("acceptance channel does not meet its fixed matrix")
        if any(item.project_id != inputs.project_id for item in channel_cases):
            raise SyntheticLabContractError("acceptance Case crosses Project scope")
        if any(item.creative_reference is not None for item in autonomous) or any(
            not (item.creative_reference or "").startswith(GUIDED_REFERENCE_PREFIX)
            for item in guided
        ):
            raise SyntheticLabContractError("acceptance guided reference is not creative-only")


def _matrix_hash(
    inputs: AcceptanceMatrixInput,
    suites: tuple[ReviewSuite, ...],
    cases: tuple[ReviewCase, ...],
) -> str:
    return canonical_hash(
        {
            "input_hash": inputs.input_hash,
            "suites": [(item.channel, item.id, item.case_set_hash) for item in suites],
            "cases": [(item.channel, item.id, item.content_hash) for item in cases],
        }
    )


def _manifest(
    inputs: AcceptanceMatrixInput,
    suites: tuple[ReviewSuite, ...],
    cases: tuple[ReviewCase, ...],
    matrix_hash: str,
) -> AcceptanceMatrixManifest:
    del suites
    by_channel = {
        channel: tuple(item for item in cases if item.channel == channel)
        for channel in sorted(STANDARD_STYLE_CHANNELS)
    }
    return AcceptanceMatrixManifest(
        project_id=inputs.project_id,
        matrix_input_hash=inputs.input_hash,
        matrix_hash=matrix_hash,
        channel_case_counts={key: len(values) for key, values in by_channel.items()},
        channel_autonomous_counts={
            key: sum(item.mode is ScenarioMode.AUTONOMOUS for item in values)
            for key, values in by_channel.items()
        },
        channel_guided_counts={
            key: sum(item.mode is ScenarioMode.GUIDED for item in values)
            for key, values in by_channel.items()
        },
        channel_competitor_counts={
            key: sum(item.competitor_scenario for item in values)
            for key, values in by_channel.items()
        },
        covered_risks=tuple(sorted({risk for item in cases for risk in item.expected_risks})),
    )


_PERSONAS = (
    "Australian first-time buyer",
    "Australian suburban homeowner",
    "Australian small-business operator",
    "Australian value-focused researcher",
    "Australian experienced category user",
)

_USE_CASES = (
    "evaluate setup and day-one use",
    "compare suitability for a constrained space",
    "weigh practical trade-offs before purchase",
    "assess ongoing operation and maintenance",
    "explain who the product is and is not suitable for",
)


__all__ = [
    "AcceptanceMatrix",
    "AcceptanceMatrixInput",
    "AcceptanceMatrixManifest",
    "CASES_PER_CHANNEL",
    "COMPETITOR_CASES_PER_CHANNEL",
    "ChannelProfileBinding",
    "GUIDED_REFERENCE_PREFIX",
    "MODE_CASES_PER_CHANNEL",
    "REQUIRED_ACCEPTANCE_RISKS",
    "build_acceptance_matrix",
]
