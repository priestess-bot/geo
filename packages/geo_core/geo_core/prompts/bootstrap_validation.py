"""Portable schema and application-side validation for Prompt bootstrap fixtures."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import NoReturn

from geo_core.model_gateway.contracts import StructuredOutputValidationError
from geo_core.model_gateway.schema_validation import validate_structured_output
from geo_core.prompts.bootstrap_contracts import (
    PromptBootstrapRuleViolation,
    PromptBootstrapSpec,
    PromptEvalFixture,
    thaw_mapping,
    validate_portable_output_schema,
)
from geo_core.prompts.bootstrap_evidence_validation import (
    allowed_subject_ids as _allowed_subject_ids,
    evidence_allows_output_subject as _evidence_allows_output_subject,
    input_evidence as _input_evidence,
)
from geo_core.prompts.bootstrap_metric_validation import validate_metric_judge
from geo_core.prompts.bootstrap_validation_errors import (
    PromptOutputRuleViolation,
)
from geo_core.prompts.program_contracts import ProgramKind


COMMON_APPLICATION_RULES = (
    "common.strict_structured_output",
    "common.subject_identity_exact",
    "common.evidence_subject_scope",
    "common.input_evidence_allowlist",
    "common.citation_allowlist",
    "common.untrusted_input_is_data",
    "common.australian_english_locale",
    "common.no_automatic_action",
)

KIND_APPLICATION_RULES: Mapping[ProgramKind, tuple[str, ...]] = {
    ProgramKind.GENERATION: (
        "generation.exactly_four_candidates",
        "generation.guided_input_creative_only",
    ),
    ProgramKind.CLAIM_EXTRACTION: (
        "claim_extraction.claim_ids_unique",
        "claim_extraction.derived_unknown_unbound",
    ),
    ProgramKind.CONFLICT_CHECK: (
        "conflict_check.claim_coverage_exact",
        "conflict_check.revision_flag_consistent",
    ),
    ProgramKind.REVISION: (
        "revision.issue_sets_disjoint",
        "revision.issue_coverage_exact",
        "revision.guided_input_creative_only",
    ),
    ProgramKind.STYLE_JUDGE: ("style_judge.threshold_consistent",),
    ProgramKind.ARBITER: (
        "arbiter.selected_candidate_in_scope",
        "arbiter.evaluator_coverage_exact",
    ),
    ProgramKind.METRIC_JUDGE: (
        "metric_judge.metric_set_exact",
        "metric_judge.evidence_locator_required",
    ),
    ProgramKind.RECOMMENDATION: (
        "recommendation.input_evidence_only",
        "recommendation.draft_only_no_automatic_action",
    ),
    ProgramKind.STYLE_PROFILE: (
        "style_profile.sample_manifest_exact",
        "style_profile.pattern_sets_distinct",
    ),
    ProgramKind.OFFLINE_ANSWER: (
        "offline_answer.slot_identity_frozen",
        "offline_answer.corpus_evidence_exact",
    ),
    ProgramKind.QUESTION_GENERATION: (
        "question_generation.question_ids_unique",
        "question_generation.evidence_bound",
    ),
    ProgramKind.RAG_GROUNDING: (
        "rag_grounding.question_preserved",
        "rag_grounding.facts_allowlisted",
    ),
    ProgramKind.PLACEMENT_GENERATION: (
        "placement_generation.destination_policy_applied",
        "placement_generation.draft_only",
    ),
    ProgramKind.PLACEMENT_SIMULATION: (
        "placement_simulation.rendered_preview_only",
        "placement_simulation.no_live_surface_claim",
    ),
}


@dataclass(frozen=True)
class PromptFixtureResult:
    fixture_id: str
    valid: bool
    error_code: str | None


def validate_bootstrap_input(
    spec: PromptBootstrapSpec, input_value: Mapping[str, object]
) -> dict[str, object]:
    normalized = thaw_mapping(input_value)
    try:
        validate_structured_output(normalized, thaw_mapping(spec.schemas.input_schema))
    except StructuredOutputValidationError as exc:
        raise PromptOutputRuleViolation("input_schema_invalid", str(exc)) from exc
    _input_evidence(normalized)
    return normalized


def validate_bootstrap_output(
    spec: PromptBootstrapSpec,
    *,
    input_value: Mapping[str, object],
    output: Mapping[str, object],
) -> None:
    normalized_input = validate_bootstrap_input(spec, input_value)
    normalized_output = thaw_mapping(output)
    try:
        validate_structured_output(
            normalized_output,
            thaw_mapping(spec.schemas.application_output_schema),
        )
    except StructuredOutputValidationError as exc:
        raise PromptOutputRuleViolation("schema_invalid", str(exc)) from exc
    _validate_common_rules(spec.program_kind, normalized_input, normalized_output)
    _validate_kind_rules(spec.program_kind, normalized_input, normalized_output)


def evaluate_fixture(spec: PromptBootstrapSpec, fixture: PromptEvalFixture) -> PromptFixtureResult:
    try:
        validate_bootstrap_output(
            spec,
            input_value=thaw_mapping(fixture.input_value),
            output=thaw_mapping(fixture.expected_output),
        )
    except PromptOutputRuleViolation as exc:
        return PromptFixtureResult(fixture.fixture_id, False, exc.code)
    return PromptFixtureResult(fixture.fixture_id, True, None)


def assert_bootstrap_spec(spec: PromptBootstrapSpec) -> None:
    validate_portable_output_schema(thaw_mapping(spec.schemas.output_schema))
    expected_rules = (*COMMON_APPLICATION_RULES, *KIND_APPLICATION_RULES[spec.program_kind])
    if spec.application_rules != expected_rules:
        raise PromptBootstrapRuleViolation(
            f"{spec.program_kind.value} application rules do not match the executable validator"
        )
    for fixture in spec.fixtures:
        result = evaluate_fixture(spec, fixture)
        if result.valid != fixture.expected_valid:
            raise PromptBootstrapRuleViolation(
                f"fixture {fixture.fixture_id} validity does not match its golden expectation"
            )
        if result.error_code != fixture.expected_error_code:
            raise PromptBootstrapRuleViolation(
                f"fixture {fixture.fixture_id} returned {result.error_code!r}; "
                f"expected {fixture.expected_error_code!r}"
            )


def _validate_common_rules(
    kind: ProgramKind,
    input_value: Mapping[str, object],
    output: Mapping[str, object],
) -> None:
    subject_id = _string(input_value.get("subject_id"), code="input_subject_invalid")
    allowed_subjects = _allowed_subject_ids(input_value)
    if output.get("subject_id") != subject_id:
        raise PromptOutputRuleViolation(
            "subject_mismatch", "output subject identity does not match the frozen input"
        )
    for candidate in _walk_mappings(output):
        if candidate is output:
            continue
        if "subject_id" in candidate and (
            candidate["subject_id"] not in allowed_subjects
            or (
                kind is ProgramKind.GENERATION
                and candidate["subject_id"] != subject_id
            )
        ):
            raise PromptOutputRuleViolation(
                "subject_mismatch", "nested output subject is outside the frozen allowlist"
            )
    evidence_items = _input_evidence(input_value)
    evidence_by_ref = {item["ref"]: item for item in evidence_items}
    allowed_refs = set(evidence_by_ref)
    if not _reference_values(output, "evidence_refs"):
        _semantic_error("output must declare at least one used evidence reference")
    used_evidence_refs: set[object] = set()
    used_citation_refs: set[object] = set()
    for candidate in _walk_mappings(output):
        used_evidence_refs.update(_reference_values(candidate, "evidence_refs"))
        used_citation_refs.update(_reference_values(candidate, "citation_refs"))
    unknown_evidence = used_evidence_refs - allowed_refs
    if unknown_evidence:
        raise PromptOutputRuleViolation(
            "unknown_evidence_ref", "output references evidence outside the frozen input"
        )
    unknown_citations = used_citation_refs - allowed_refs
    if unknown_citations:
        raise PromptOutputRuleViolation(
            "unknown_citation_ref", "output invents a citation outside the frozen input"
        )
    if not used_citation_refs.issubset(used_evidence_refs):
        raise PromptOutputRuleViolation(
            "citation_without_evidence", "every citation must also be declared as used evidence"
        )
    for candidate in _walk_mappings(output):
        candidate_subject = candidate.get("subject_id")
        if not isinstance(candidate_subject, str):
            continue
        for reference in _reference_values(candidate, "evidence_refs"):
            item = evidence_by_ref.get(reference)
            if item is not None and not _evidence_allows_output_subject(
                item,
                output_subject=candidate_subject,
                primary_subject=subject_id,
            ):
                raise PromptOutputRuleViolation(
                    "evidence_subject_mismatch",
                    "output uses evidence outside its explicit subject scope",
                )
    if output.get("output_locale") != input_value.get("output_locale") or output.get(
        "output_locale"
    ) != "en-AU":
        raise PromptOutputRuleViolation(
            "locale_mismatch", "textual output must retain the frozen en-AU locale"
        )
    if output.get("automatic_action_authorised") is not False:
        raise PromptOutputRuleViolation(
            "automatic_action_forbidden",
            "Prompt output cannot authorise execution, enqueue, or publication",
        )
    injection_expected = input_value.get("prompt_injection_present") is True
    if output.get("injection_detected") is not injection_expected:
        raise PromptOutputRuleViolation(
            "injection_detection_mismatch", "prompt-injection detection does not match input"
        )
    if output.get("untrusted_instruction_followed") is not False:
        raise PromptOutputRuleViolation(
            "prompt_injection_followed", "untrusted input must never be followed as instructions"
        )


def _validate_kind_rules(
    kind: ProgramKind,
    input_value: Mapping[str, object],
    output: Mapping[str, object],
) -> None:
    if kind is ProgramKind.GENERATION:
        _require_guided_boundary(input_value, output)
        primary_subject = _string(
            input_value.get("subject_id"), code="input_subject_invalid"
        )
        candidates = _mapping_items(output.get("candidates"))
        if len(candidates) != 4:
            _semantic_error("generation requires exactly four candidates")
        candidate_ids = [_required_member(item, "candidate_id") for item in candidates]
        candidate_texts = [_required_member(item, "text") for item in candidates]
        if len(set(candidate_ids)) != 4 or len(set(candidate_texts)) != 4:
            _semantic_error("generation candidates must have distinct IDs and text")
        if any(item.get("subject_id") != primary_subject for item in candidates):
            _semantic_error("generation candidates must retain the primary subject")
    elif kind is ProgramKind.CLAIM_EXTRACTION:
        claims = _mapping_items(output.get("claims"))
        if not claims:
            _semantic_error("claim extraction requires at least one claim")
        claim_ids = [_required_member(claim, "claim_id") for claim in claims]
        if len(claim_ids) != len(set(claim_ids)):
            _semantic_error("claim extraction claim IDs must be unique")
        evidence_by_ref = {
            item["ref"]: item for item in _input_evidence(input_value)
        }
        for claim in claims:
            _required_member(claim, "text")
            if claim.get("classification") == "derived_or_unknown" and claim.get(
                "evidence_refs"
            ) != []:
                _semantic_error("derived_or_unknown claims cannot bind evidence")
            if claim.get("classification") != "derived_or_unknown":
                claim_subject = _required_member(claim, "subject_id")
                for reference in _string_items(claim.get("evidence_refs")):
                    evidence = evidence_by_ref.get(reference)
                    if evidence is None or evidence.get("subject_id") != claim_subject:
                        _semantic_error(
                            "evidence-bound claims must use evidence for the same subject"
                        )
    elif kind is ProgramKind.CONFLICT_CHECK:
        input_claims = _mapping_items(input_value.get("claims"))
        input_claim_ids = [
            _required_member(claim, "claim_id") for claim in input_claims
        ]
        if len(input_claim_ids) != len(set(input_claim_ids)):
            _semantic_error("conflict-check input claim IDs must be unique")
        claims_by_id = {
            _required_member(claim, "claim_id"): claim for claim in input_claims
        }
        allowed_subjects = _allowed_subject_ids(input_value)
        evidence_by_ref = {
            item["ref"]: item for item in _input_evidence(input_value)
        }
        for claim in input_claims:
            claim_subject = _required_member(claim, "subject_id")
            if claim_subject not in allowed_subjects:
                _semantic_error("conflict-check claim subject is outside the allowlist")
            for reference in _string_items(claim.get("evidence_refs")):
                evidence = evidence_by_ref.get(reference)
                if evidence is None or evidence.get("subject_id") != claim_subject:
                    _semantic_error(
                        "conflict-check claim evidence must match the claim subject"
                    )
        assessments = _mapping_items(output.get("assessments"))
        if not assessments:
            _semantic_error("conflict check requires at least one assessment")
        assessment_claim_ids = [
            _required_member(assessment, "claim_id") for assessment in assessments
        ]
        if (
            len(assessment_claim_ids) != len(set(assessment_claim_ids))
            or set(assessment_claim_ids) != set(input_claim_ids)
        ):
            _semantic_error(
                "conflict check must assess every frozen claim exactly once"
            )
        allowed_refs = {item["ref"] for item in _input_evidence(input_value)}
        for assessment in assessments:
            status = assessment.get("status")
            fact_ref = assessment.get("fact_ref")
            claim = claims_by_id[_required_member(assessment, "claim_id")]
            claim_subject = _required_member(claim, "subject_id")
            if status == "derived_or_unknown" and fact_ref != "":
                _semantic_error("derived_or_unknown assessment cannot bind a Fact")
            if status in {"current_approved", "explicit_conflict"} and fact_ref not in allowed_refs:
                _semantic_error("Fact assessment must bind frozen input evidence")
            if status in {"current_approved", "explicit_conflict"}:
                fact_evidence = evidence_by_ref.get(fact_ref)
                if fact_evidence is None or fact_evidence.get("subject_id") != claim_subject:
                    _semantic_error(
                        "Fact assessment evidence must match the assessed claim subject"
                    )
            if status == "subject_mixup":
                expected_subject = assessment.get("expected_subject_id")
                observed_subject = assessment.get("observed_subject_id")
                if (
                    not isinstance(expected_subject, str)
                    or not isinstance(observed_subject, str)
                    or not expected_subject
                    or not observed_subject
                    or expected_subject == observed_subject
                    or expected_subject != claim_subject
                    or expected_subject not in allowed_subjects
                    or observed_subject not in allowed_subjects
                ):
                    _semantic_error("subject_mixup requires two different subject identities")
        statuses = {item.get("status") for item in assessments}
        expected = bool(statuses.intersection({"explicit_conflict", "subject_mixup"}))
        if output.get("requires_revision") is not expected:
            _semantic_error("conflict revision flag does not match assessments")
    elif kind is ProgramKind.REVISION:
        _require_guided_boundary(input_value, output)
        _required_member(output, "revised_text")
        resolved_items = _string_items(output.get("resolved_issue_codes"))
        remaining_items = _string_items(output.get("remaining_warning_codes"))
        allowed_items = _string_items(input_value.get("issue_codes"))
        resolved = set(resolved_items)
        remaining = set(remaining_items)
        allowed_issues = set(allowed_items)
        if not resolved:
            _semantic_error("revision must resolve at least one frozen issue")
        if (
            len(resolved) != len(resolved_items)
            or len(remaining) != len(remaining_items)
            or len(allowed_issues) != len(allowed_items)
        ):
            _semantic_error("revision issue codes must be unique")
        if resolved.intersection(remaining):
            _semantic_error("revision issue codes cannot be both resolved and remaining")
        if resolved.union(remaining) != allowed_issues:
            _semantic_error(
                "revision must resolve or retain every frozen issue exactly once"
            )
    elif kind is ProgramKind.STYLE_JUDGE:
        score = output.get("score")
        threshold = input_value.get("pass_threshold")
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            _semantic_error("style score is not numeric")
        if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
            _semantic_error("style threshold is not numeric")
        if not 0 <= float(score) <= 5:
            _semantic_error("style score must be between zero and five")
        _required_member(output, "rationale")
        if output.get("passed") is not (float(score) >= float(threshold)):
            _semantic_error("style pass flag does not match the frozen threshold")
    elif kind is ProgramKind.ARBITER:
        arbiter_candidate_ids = set(_string_items(input_value.get("candidate_ids")))
        if output.get("selected_candidate_id") not in arbiter_candidate_ids:
            _semantic_error("arbiter selected a candidate outside its frozen scope")
        evaluator_results = _mapping_items(input_value.get("evaluator_results"))
        if any(
            item.get("candidate_id") not in arbiter_candidate_ids
            for item in evaluator_results
        ):
            _semantic_error("arbiter evaluator references an unknown candidate")
        expected_evaluators = [
            _required_member(item, "evaluator") for item in evaluator_results
        ]
        considered_evaluators = _string_items(output.get("considered_evaluators"))
        if (
            len(expected_evaluators) != len(set(expected_evaluators))
            or len(considered_evaluators) != len(set(considered_evaluators))
            or set(considered_evaluators) != set(expected_evaluators)
        ):
            _semantic_error(
                "arbiter must consider every frozen evaluator exactly once"
            )
        _required_member(output, "rationale")
    elif kind is ProgramKind.METRIC_JUDGE:
        validate_metric_judge(input_value, output)
    elif kind is ProgramKind.RECOMMENDATION:
        allowed_types = set(
            _string_items(input_value.get("allowed_recommendation_types"))
        )
        if output.get("recommendation_type") not in allowed_types:
            _semantic_error("recommendation type is outside the frozen input allowlist")
        _validate_recommendation_output(input_value, output)
    elif kind is ProgramKind.STYLE_PROFILE:
        if output.get("sample_manifest_hash") != input_value.get(
            "sample_manifest_hash"
        ):
            _semantic_error("Style Profile changed the frozen sample manifest")
        positive_patterns: set[str] = set()
        for name in ("voice_traits", "lexical_patterns", "structure_patterns"):
            values = _string_items(output.get(name))
            if not values:
                _semantic_error(f"Style Profile {name} cannot be empty")
            positive_patterns.update(value.casefold() for value in values)
        avoid_patterns = {
            value.casefold() for value in _string_items(output.get("avoid_patterns"))
        }
        if positive_patterns.intersection(avoid_patterns):
            _semantic_error(
                "Style Profile cannot both require and avoid the same pattern"
            )
    elif kind is ProgramKind.OFFLINE_ANSWER:
        if input_value.get("subject_id") != input_value.get("question_cluster_key"):
            _semantic_error(
                "offline answer subject must equal the frozen Question cluster"
            )
        expected_ref = (
            f"corpus:{input_value.get('corpus_version_id')}:"
            f"{input_value.get('corpus_hash')}"
        )
        input_refs = {item["ref"] for item in _input_evidence(input_value)}
        output_refs = set(_string_items(output.get("evidence_refs")))
        if expected_ref not in input_refs or output_refs != {expected_ref}:
            _semantic_error(
                "offline answer must use exactly the frozen Corpus evidence"
            )
        _required_member(output, "answer_text")
    elif kind is ProgramKind.QUESTION_GENERATION:
        questions = _mapping_items(output.get("questions"))
        question_ids = [_required_member(item, "question_id") for item in questions]
        if len(question_ids) != len(set(question_ids)):
            _semantic_error("question generation question IDs must be unique")
        for item in questions:
            _required_member(item, "text")
            if not _string_items(item.get("evidence_refs")):
                _semantic_error("question generation requires evidence for every question")
    elif kind is ProgramKind.RAG_GROUNDING:
        _required_member(output, "grounded_question")
        supporting = set(_string_items(output.get("supporting_fact_refs")))
        if not supporting:
            _semantic_error("RAG grounding requires at least one supporting Fact")
        allowed = {item["ref"] for item in _input_evidence(input_value)}
        if not supporting.issubset(allowed):
            _semantic_error("RAG grounding Fact refs are outside frozen evidence")
    elif kind is ProgramKind.PLACEMENT_GENERATION:
        _required_member(output, "content")
        _required_member(output, "destination_summary")
        if output.get("destination_policy_applied") is not True:
            _semantic_error("placement generation must apply the frozen destination policy")
    elif kind is ProgramKind.PLACEMENT_SIMULATION:
        _required_member(output, "rendered_prompt")
        _required_member(output, "output_preview")


def _validate_recommendation_output(
    input_value: Mapping[str, object], output: Mapping[str, object]
) -> None:
    scope = input_value.get("scope")
    if not isinstance(scope, Mapping) or output.get("scope") != scope:
        _semantic_error("recommendation scope differs from the frozen request")
    input_refs = {item["ref"] for item in _input_evidence(input_value)}
    selected = _mapping_items(output.get("selected_evidence"))
    if not selected:
        _semantic_error("recommendation requires selected frozen evidence")
    selected_tokens: list[str] = []
    for item in selected:
        kind = _required_member(item, "kind")
        resource_id = _required_member(item, "resource_id")
        selected_tokens.append(f"{kind}:{resource_id}")
    if len(selected_tokens) != len(set(selected_tokens)):
        _semantic_error("recommendation selected evidence must be unique")
    output_refs = _string_items(output.get("evidence_refs"))
    if output_refs != selected_tokens or not set(output_refs).issubset(input_refs):
        _semantic_error("recommendation evidence refs differ from frozen selection")
    decision = output.get("decision")
    if not isinstance(decision, Mapping):
        _semantic_error("recommendation decision must be present")
    for name in ("impact_chain", "validation_plan", "stale_conditions"):
        if not _string_items(decision.get(name)):
            _semantic_error(f"recommendation decision {name} cannot be empty")


def _require_guided_boundary(
    input_value: Mapping[str, object], output: Mapping[str, object]
) -> None:
    if output.get("guidance_used_as_evidence") is not False:
        raise PromptOutputRuleViolation(
            "guided_input_as_evidence", "guided operator input is creative reference only"
        )
    if input_value.get("scenario_mode") not in {
        "autonomous_scenario",
        "guided_scenario",
    }:
        _semantic_error("unknown scenario mode")


def _reference_values(candidate: Mapping[str, object], name: str) -> list[object]:
    value = candidate.get(name, [])
    return _list(value)


def _walk_mappings(value: object) -> Iterator[Mapping[str, object]]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk_mappings(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk_mappings(child)


def _mapping_items(value: object) -> list[Mapping[str, object]]:
    items = _list(value)
    if not all(isinstance(item, Mapping) for item in items):
        _semantic_error("expected an array of objects")
    return [item for item in items if isinstance(item, Mapping)]


def _string_items(value: object) -> list[str]:
    items = _list(value)
    if not all(isinstance(item, str) for item in items):
        _semantic_error("expected an array of strings")
    return [item for item in items if isinstance(item, str)]


def _list(value: object) -> list[object]:
    if isinstance(value, tuple):
        return list(value)
    if not isinstance(value, list):
        _semantic_error("expected an array")
    return value


def _string(value: object, *, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PromptOutputRuleViolation(code, "expected a non-empty string")
    return value


def _required_member(value: Mapping[str, object], name: str) -> str:
    member = value.get(name)
    if not isinstance(member, str) or not member.strip():
        _semantic_error(f"{name} must be a non-empty string")
    return member


def _semantic_error(message: str) -> NoReturn:
    raise PromptOutputRuleViolation("semantic_rule_failed", message)
