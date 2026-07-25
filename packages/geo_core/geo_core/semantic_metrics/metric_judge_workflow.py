"""Frozen Metric Judge planning, candidate agreement and Arbiter selection.

This module deliberately has no model, queue or database dependency.  Worker code
supplies the exact frozen Prompt/Model lineage; this layer proves which model calls
are necessary and prevents an Arbiter from being spent when evaluators already agree.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Final

from geo_core.semantic_metrics._validation import canonical_hash
from geo_core.semantic_metrics.contracts import (
    ApprovedFactReference,
    EvidenceLocatorKind,
    FrozenMetricSuite,
    JudgeKind,
    MetricInputSet,
    MetricKey,
    MetricObservation,
    SemanticMetricRuleViolation,
)
from geo_core.semantic_metrics.program_output import (
    MetricJudgeKind,
    MetricJudgePlan,
    ParsedArbiterProgramOutput,
    ParsedMetricJudgeProgramOutput,
)
from geo_core.semantic_metrics.judges import validate_judgement
from geo_core.semantic_metrics.prompt_injection import (
    has_high_confidence_prompt_injection,
)


METRIC_JUDGE_MAX_RESULTS: Final[int] = 50


@dataclass(frozen=True)
class MetricJudgePlanBatch:
    """One bounded Program invocation for exactly one frozen Observation."""

    observation: MetricObservation
    ordinal: int
    plans: tuple[MetricJudgePlan, ...]
    input_hash: str

    def __post_init__(self) -> None:
        if self.ordinal < 1:
            raise SemanticMetricRuleViolation("metric judge batch ordinal must be positive")
        plans = tuple(self.plans)
        if not plans or len(plans) > METRIC_JUDGE_MAX_RESULTS:
            raise SemanticMetricRuleViolation("metric judge batch plan count is invalid")
        if len({item.metric_id for item in plans}) != len(plans):
            raise SemanticMetricRuleViolation("metric judge batch plan IDs must be unique")
        expected = canonical_hash(self.canonical_input_value())
        if self.input_hash != expected:
            raise SemanticMetricRuleViolation("metric judge batch input hash changed")
        object.__setattr__(self, "plans", plans)

    @classmethod
    def create(
        cls,
        *,
        observation: MetricObservation,
        ordinal: int,
        plans: Sequence[MetricJudgePlan],
    ) -> MetricJudgePlanBatch:
        frozen = tuple(plans)
        value = _canonical_input_value(observation=observation, plans=frozen)
        return cls(
            observation=observation,
            ordinal=ordinal,
            plans=frozen,
            input_hash=canonical_hash(value),
        )

    def canonical_input_value(self) -> dict[str, object]:
        return _canonical_input_value(observation=self.observation, plans=self.plans)

    def program_input(
        self,
        *,
        input_set: MetricInputSet,
        output_locale: str = "en-AU",
    ) -> dict[str, object]:
        """Build the exact application input for the metric_judge Prompt Program."""

        if output_locale != "en-AU":
            raise SemanticMetricRuleViolation("metric judge output locale must be en-AU")
        primary = input_set.subjects.primary_subject_key
        allowed_subjects = [
            primary,
            *(key for key, _aliases in input_set.subjects.competitors),
        ]
        evidence: list[dict[str, object]] = [
            {
                "ref": str(self.observation.id),
                "subject_id": primary,
                "evidence_scope": "primary_subject",
                "summary": self.observation.answer_text[:10_000],
            }
        ]
        locator_sources: list[dict[str, object]] = [
            {
                "kind": EvidenceLocatorKind.ANSWER_SPAN.value,
                "reference_id": str(self.observation.id),
                "version": self.observation.artifact_version,
                "content_hash": self.observation.payload_hash,
            }
        ]
        for citation in self.observation.citations:
            evidence.append(
                {
                    "ref": citation.id,
                    "subject_id": primary,
                    "evidence_scope": "primary_subject",
                    "summary": citation.visible_title,
                }
            )
            locator_sources.append(
                {
                    "kind": EvidenceLocatorKind.CITATION.value,
                    "reference_id": citation.id,
                    "version": None,
                    "content_hash": None,
                }
            )
        referenced_facts = _facts_for_plans(self.plans, input_set.approved_facts)
        for fact in referenced_facts:
            evidence.append(
                {
                    "ref": _fact_ref(fact),
                    "subject_id": fact.subject_key,
                    "evidence_scope": (
                        "primary_subject"
                        if fact.subject_key == primary
                        else "competitor_subject"
                    ),
                    "summary": f"Approved Fact {fact.id} at {fact.version}.",
                }
            )
            locator_sources.append(
                {
                    "kind": EvidenceLocatorKind.FACT.value,
                    "reference_id": fact.id,
                    "version": fact.version,
                    "content_hash": None,
                }
            )
        return {
            "subject_id": primary,
            "allowed_subject_ids": allowed_subjects,
            "evidence": evidence,
            "output_locale": output_locale,
            "untrusted_text": self.observation.answer_text[:10_000],
            "prompt_injection_present": has_high_confidence_prompt_injection(
                self.observation.answer_text
            ),
            "answer_text": self.observation.answer_text,
            "locator_sources": locator_sources,
            "metrics": [
                {
                    "metric_id": plan.metric_id,
                    "kind": plan.metric_kind.value,
                    "definition": plan.definition,
                    "evidence_refs": list(plan.allowed_evidence_refs),
                }
                for plan in self.plans
            ],
        }


@dataclass(frozen=True)
class MetricJudgeCandidate:
    candidate_id: str
    evaluator_id: str
    output: ParsedMetricJudgeProgramOutput
    output_hash: str

    def __post_init__(self) -> None:
        _identifier(self.candidate_id, "metric judge candidate ID")
        _identifier(self.evaluator_id, "metric judge evaluator ID")
        expected = canonical_hash(
            {
                "results": [item.canonical_value() for item in self.output.results],
                "overall_status": self.output.overall_status,
                "output_locale": self.output.output_locale,
            }
        )
        if self.output_hash != expected:
            raise SemanticMetricRuleViolation("metric judge candidate output hash changed")

    @classmethod
    def create(
        cls,
        *,
        candidate_id: str,
        evaluator_id: str,
        output: ParsedMetricJudgeProgramOutput,
    ) -> MetricJudgeCandidate:
        return cls(
            candidate_id=candidate_id,
            evaluator_id=evaluator_id,
            output=output,
            output_hash=canonical_hash(
                {
                    "results": [item.canonical_value() for item in output.results],
                    "overall_status": output.overall_status,
                    "output_locale": output.output_locale,
                }
            ),
        )


@dataclass(frozen=True)
class MetricJudgeCandidateResolution:
    candidates: tuple[MetricJudgeCandidate, ...]
    selected_candidate_id: str | None
    arbiter_required: bool

    def __post_init__(self) -> None:
        candidates = tuple(sorted(self.candidates, key=lambda item: item.evaluator_id))
        if len(candidates) < 2 or len(candidates) != len(
            {item.evaluator_id for item in candidates}
        ):
            raise SemanticMetricRuleViolation(
                "metric judge resolution requires distinct evaluator candidates"
            )
        if len({item.candidate_id for item in candidates}) != len(candidates):
            raise SemanticMetricRuleViolation("metric judge candidate IDs must be unique")
        if self.arbiter_required == (self.selected_candidate_id is not None):
            raise SemanticMetricRuleViolation("metric judge arbitration state is inconsistent")
        if (
            self.selected_candidate_id is not None
            and self.selected_candidate_id not in {item.candidate_id for item in candidates}
        ):
            raise SemanticMetricRuleViolation("metric judge selected candidate is unknown")
        object.__setattr__(self, "candidates", candidates)

    @property
    def selected(self) -> MetricJudgeCandidate | None:
        return next(
            (
                item
                for item in self.candidates
                if item.candidate_id == self.selected_candidate_id
            ),
            None,
        )


@dataclass(frozen=True)
class SelectedMetricJudgeBatch:
    """One completed batch paired with its exact selected Judge candidate."""

    batch: MetricJudgePlanBatch
    candidate: MetricJudgeCandidate

    def __post_init__(self) -> None:
        expected_ids = tuple(item.metric_id for item in self.batch.plans)
        observed_ids = tuple(item.metric_id for item in self.candidate.output.results)
        if (
            self.candidate.output.output_locale != "en-AU"
            or len(expected_ids) != len(observed_ids)
            or set(expected_ids) != set(observed_ids)
            or len(set(observed_ids)) != len(observed_ids)
        ):
            raise SemanticMetricRuleViolation(
                "selected metric judge candidate does not match its frozen batch"
            )


def plan_metric_judge_batches(
    *, input_set: MetricInputSet, suite: FrozenMetricSuite, observation: MetricObservation
) -> tuple[MetricJudgePlanBatch, ...]:
    """Plan all non-deterministic metrics without dropping any input evidence."""

    plans = _metric_plans(input_set=input_set, suite=suite, observation=observation)
    return tuple(
        MetricJudgePlanBatch.create(
            observation=observation,
            ordinal=index,
            plans=plans[offset : offset + METRIC_JUDGE_MAX_RESULTS],
        )
        for index, offset in enumerate(range(0, len(plans), METRIC_JUDGE_MAX_RESULTS), 1)
    )


def resolve_metric_judge_candidates(
    candidates: Sequence[MetricJudgeCandidate],
) -> MetricJudgeCandidateResolution:
    """Select only exact evaluator agreement; disagreement must reach Arbiter."""

    frozen = tuple(candidates)
    hashes = {item.output_hash for item in frozen}
    if len(hashes) == 1:
        selected = min(frozen, key=lambda item: item.evaluator_id)
        return MetricJudgeCandidateResolution(
            candidates=frozen,
            selected_candidate_id=selected.candidate_id,
            arbiter_required=False,
        )
    return MetricJudgeCandidateResolution(
        candidates=frozen,
        selected_candidate_id=None,
        arbiter_required=True,
    )


def resolve_metric_judge_arbiter(
    resolution: MetricJudgeCandidateResolution,
    arbiter: ParsedArbiterProgramOutput,
) -> MetricJudgeCandidate:
    """Accept only an Arbiter decision over the exact disagreeing candidate set."""

    if not resolution.arbiter_required:
        raise SemanticMetricRuleViolation("arbiter is forbidden when metric judges agree")
    evaluator_ids = tuple(item.evaluator_id for item in resolution.candidates)
    if arbiter.considered_evaluators != evaluator_ids:
        raise SemanticMetricRuleViolation("arbiter evaluator set changed")
    selected = next(
        (
            item
            for item in resolution.candidates
            if item.candidate_id == arbiter.selected_candidate_id
        ),
        None,
    )
    if selected is None:
        raise SemanticMetricRuleViolation("arbiter selected an unknown metric candidate")
    return selected


def apply_metric_judge_output(
    observation: MetricObservation,
    selected: MetricJudgeCandidate,
) -> MetricObservation:
    """Attach one accepted batch while rejecting duplicated metric identities."""

    if has_high_confidence_prompt_injection(observation.answer_text):
        raise SemanticMetricRuleViolation(
            "metric judge output cannot aggregate a prompt-injection observation"
        )
    existing = tuple(observation.judge_outputs)
    incoming = tuple(selected.output.results)
    existing_ids = {
        item.metric_id for item in existing if item.metric_id is not None
    }
    incoming_ids = {
        item.metric_id for item in incoming if item.metric_id is not None
    }
    if len(incoming_ids) != len(incoming) or existing_ids.intersection(incoming_ids):
        raise SemanticMetricRuleViolation("metric judge output would duplicate a metric ID")
    return MetricObservation(
        id=observation.id,
        slot_id=observation.slot_id,
        payload_hash=observation.payload_hash,
        question_id=observation.question_id,
        question_cluster=observation.question_cluster,
        answer_text=observation.answer_text,
        artifact_version=observation.artifact_version,
        citations=observation.citations,
        subject_assertions=observation.subject_assertions,
        judge_outputs=(*existing, *incoming),
    )


def merge_selected_metric_judge_batches(
    *,
    input_set: MetricInputSet,
    suite: FrozenMetricSuite,
    selected_batches: Sequence[SelectedMetricJudgeBatch],
) -> MetricInputSet:
    """Merge a complete, exact selected result set into frozen input evidence.

    A parent must never calculate a semantic snapshot from only the batches that
    happened to finish first. Planned batches are recomputed from the immutable
    input and suite, then matched by Observation and ordinal.
    """

    expected = {
        (batch.observation.id, batch.ordinal): batch
        for observation in input_set.observations
        for batch in plan_metric_judge_batches(
            input_set=input_set, suite=suite, observation=observation
        )
    }
    supplied: dict[tuple[object, int], SelectedMetricJudgeBatch] = {}
    for item in selected_batches:
        key = (item.batch.observation.id, item.batch.ordinal)
        if key in supplied:
            raise SemanticMetricRuleViolation("selected metric judge batch is duplicated")
        required = expected.get(key)
        if required is None or required.input_hash != item.batch.input_hash:
            raise SemanticMetricRuleViolation("selected metric judge batch is stale or unknown")
        supplied[key] = item
    if set(supplied) != set(expected):
        raise SemanticMetricRuleViolation("selected metric judge batches are incomplete")

    merged: list[MetricObservation] = []
    for observation in input_set.observations:
        if any(item.metric_id is not None for item in observation.judge_outputs):
            raise SemanticMetricRuleViolation("metric input already contains model judge output")
        completed = sorted(
            (
                item
                for (observation_id, _ordinal), item in supplied.items()
                if observation_id == observation.id
            ),
            key=lambda item: item.batch.ordinal,
        )
        current = observation
        for item in completed:
            _validate_selected_batch(
                item,
                input_set=input_set,
                suite=suite,
                expected_batch=expected[(observation.id, item.batch.ordinal)],
            )
            current = apply_metric_judge_output(current, item.candidate)
        merged.append(current)
    return replace(input_set, observations=tuple(merged))


def _validate_selected_batch(
    selected: SelectedMetricJudgeBatch,
    *,
    input_set: MetricInputSet,
    suite: FrozenMetricSuite,
    expected_batch: MetricJudgePlanBatch,
) -> None:
    """Revalidate a persisted projection against its exact frozen plans.

    A Worker parses model output before writing it, but parent completion is a
    separate trust boundary.  In particular, a valid citation or fact locator
    for the Observation must not be reused for a different metric plan.
    """

    if (
        selected.batch.canonical_input_value()
        != expected_batch.canonical_input_value()
    ):
        raise SemanticMetricRuleViolation("selected metric judge batch changed")
    results = {item.metric_id: item for item in selected.candidate.output.results}
    for plan in expected_batch.plans:
        result = results.get(plan.metric_id)
        if result is None or result.kind.value != plan.metric_kind.value:
            raise SemanticMetricRuleViolation("selected metric judge result kind changed")
        if not validate_judgement(
            result,
            observation=expected_batch.observation,
            input_set=input_set,
            judge_version=suite.judge_version,
        ).valid:
            raise SemanticMetricRuleViolation("selected metric judge result is invalid")
        for locator in result.locators:
            if locator.kind is EvidenceLocatorKind.ANSWER_SPAN:
                reference = str(expected_batch.observation.id)
            elif locator.kind is EvidenceLocatorKind.CITATION:
                reference = locator.reference_id
            else:
                reference = f"{locator.reference_id}@{locator.version}"
            if reference not in plan.allowed_evidence_refs:
                raise SemanticMetricRuleViolation(
                    "selected metric judge locator is outside its frozen plan"
                )


def _metric_plans(
    *, input_set: MetricInputSet, suite: FrozenMetricSuite, observation: MetricObservation
) -> tuple[MetricJudgePlan, ...]:
    required = {item.judge_kind for item in suite.definitions if item.judge_kind is not None}
    plans: list[MetricJudgePlan] = []
    answer_ref = str(observation.id)
    if JudgeKind.RECOMMENDATION in required:
        plans.append(
            MetricJudgePlan(
                metric_id=MetricKey.RECOMMENDATION.value,
                metric_kind=MetricJudgeKind.RECOMMENDATION,
                definition="Whether the answer explicitly recommends the governed subject.",
                allowed_evidence_refs=(answer_ref,),
            )
        )
    if JudgeKind.SENTIMENT in required:
        plans.append(
            MetricJudgePlan(
                metric_id=MetricKey.SENTIMENT.value,
                metric_kind=MetricJudgeKind.SENTIMENT,
                definition="Overall sentiment toward the governed subject in the answer.",
                allowed_evidence_refs=(answer_ref,),
            )
        )
    if JudgeKind.FACT in required:
        plans.extend(_fact_plan(fact, answer_ref) for fact in input_set.approved_facts)
    if JudgeKind.CITATION_ENTAILMENT in required:
        plans.extend(_citation_plan(item) for item in observation.citations)
    if JudgeKind.CORPUS_ABSORPTION in required:
        plans.append(
            MetricJudgePlan(
                metric_id=MetricKey.APPROVED_CORPUS_ABSORPTION.value,
                metric_kind=MetricJudgeKind.CORPUS_ABSORPTION,
                definition="Whether the answer absorbs approved corpus content without inventing facts.",
                allowed_evidence_refs=(answer_ref,),
            )
        )
    if not plans:
        raise SemanticMetricRuleViolation("metric suite has no model-judged definitions")
    return tuple(plans)


def _fact_plan(fact: ApprovedFactReference, answer_ref: str) -> MetricJudgePlan:
    reference = _fact_ref(fact)
    return MetricJudgePlan(
        metric_id=f"fact:{reference}",
        metric_kind=MetricJudgeKind.FACT,
        definition=f"Whether approved Fact {fact.id} at version {fact.version} is accurate.",
        allowed_evidence_refs=(answer_ref, reference),
    )


def _citation_plan(citation) -> MetricJudgePlan:
    return MetricJudgePlan(
        metric_id=f"citation:{citation.id}",
        metric_kind=MetricJudgeKind.CITATION_ENTAILMENT,
        definition=f"Whether citation {citation.id} entails the answer claim it supports.",
        allowed_evidence_refs=(citation.id,),
    )


def _facts_for_plans(
    plans: Sequence[MetricJudgePlan], facts: Sequence[ApprovedFactReference]
) -> tuple[ApprovedFactReference, ...]:
    references = {reference for plan in plans for reference in plan.allowed_evidence_refs}
    return tuple(fact for fact in facts if _fact_ref(fact) in references)


def _fact_ref(fact: ApprovedFactReference) -> str:
    return f"{fact.id}@{fact.version}"


def _canonical_input_value(
    *, observation: MetricObservation, plans: Sequence[MetricJudgePlan]
) -> dict[str, object]:
    return {
        "observation_id": str(observation.id),
        "observation_payload_hash": observation.payload_hash,
        "observation_artifact_version": observation.artifact_version,
        "plans": [
            {
                "metric_id": item.metric_id,
                "metric_kind": item.metric_kind.value,
                "definition": item.definition,
                "allowed_evidence_refs": list(item.allowed_evidence_refs),
            }
            for item in plans
        ],
    }


def _identifier(value: str, label: str) -> None:
    if not value.strip() or len(value.strip()) > 200:
        raise SemanticMetricRuleViolation(f"{label} is invalid")


__all__ = [
    "METRIC_JUDGE_MAX_RESULTS",
    "MetricJudgeCandidate",
    "MetricJudgeCandidateResolution",
    "MetricJudgePlanBatch",
    "SelectedMetricJudgeBatch",
    "apply_metric_judge_output",
    "merge_selected_metric_judge_batches",
    "plan_metric_judge_batches",
    "resolve_metric_judge_arbiter",
    "resolve_metric_judge_candidates",
]
