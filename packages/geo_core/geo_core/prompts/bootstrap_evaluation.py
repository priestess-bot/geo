"""Deterministic rubric scoring for operator-supplied Prompt test outputs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from geo_core.prompts.bootstrap_contracts import (
    PromptBootstrapRuleViolation,
    PromptBootstrapSpec,
    PromptEvalFixture,
)
from geo_core.prompts.bootstrap_validation import (
    PromptOutputRuleViolation,
    validate_bootstrap_output,
)
from geo_core.prompts.program_contracts import _canonical_hash, _canonical_value


@dataclass(frozen=True)
class PromptOutputEvaluation:
    fixture_id: str
    output_hash: str
    score: int
    passed: bool
    error_code: str | None
    failed_criteria: tuple[str, ...]
    blocking_failure: bool

    def canonical_value(self) -> Mapping[str, object]:
        return {
            "fixture_id": self.fixture_id,
            "output_hash": self.output_hash,
            "score": self.score,
            "passed": self.passed,
            "error_code": self.error_code,
            "failed_criteria": list(self.failed_criteria),
            "blocking_failure": self.blocking_failure,
        }


@dataclass(frozen=True)
class PromptTestSetEvaluation:
    spec_hash: str
    test_set_id: str
    test_set_hash: str
    case_results: tuple[PromptOutputEvaluation, ...]
    score: float = field(init=False)
    passed: bool = field(init=False)
    result_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.case_results:
            raise PromptBootstrapRuleViolation("Prompt test-set evaluation requires case results")
        score = sum(item.score for item in self.case_results) / len(self.case_results)
        passed = all(item.passed for item in self.case_results)
        object.__setattr__(self, "score", score)
        object.__setattr__(self, "passed", passed)
        object.__setattr__(
            self,
            "result_hash",
            _canonical_hash(
                {
                    "spec_hash": self.spec_hash,
                    "test_set_id": self.test_set_id,
                    "test_set_hash": self.test_set_hash,
                    "score": score,
                    "passed": passed,
                    "case_results": [item.canonical_value() for item in self.case_results],
                }
            ),
        )


def evaluate_prompt_output(
    spec: PromptBootstrapSpec,
    *,
    fixture: PromptEvalFixture,
    output: Mapping[str, object],
) -> PromptOutputEvaluation:
    output_hash = _canonical_hash(_canonical_value(output))
    error_code: str | None = None
    failed_criteria: tuple[str, ...] = ()
    try:
        validate_bootstrap_output(
            spec,
            input_value=fixture.input_value,
            output=output,
        )
    except PromptOutputRuleViolation as exc:
        error_code = exc.code
        failed_criteria = (_criterion_for_error(spec, exc.code),)
    failed = set(failed_criteria)
    score = sum(item.weight for item in spec.rubric if item.code not in failed)
    blocking_failure = any(
        item.blocking and item.code in failed for item in spec.rubric
    )
    passed = not error_code and not blocking_failure and score >= spec.minimum_score
    return PromptOutputEvaluation(
        fixture_id=fixture.fixture_id,
        output_hash=output_hash,
        score=score,
        passed=passed,
        error_code=error_code,
        failed_criteria=failed_criteria,
        blocking_failure=blocking_failure,
    )


def evaluate_prompt_test_set(
    spec: PromptBootstrapSpec,
    outputs: Mapping[str, Mapping[str, object]],
) -> PromptTestSetEvaluation:
    expected_ids = {fixture.fixture_id for fixture in spec.fixtures}
    if set(outputs) != expected_ids:
        missing = sorted(expected_ids - set(outputs))
        extra = sorted(set(outputs) - expected_ids)
        raise PromptBootstrapRuleViolation(
            f"Prompt test outputs do not match the frozen fixture set; "
            f"missing={missing}, extra={extra}"
        )
    results = tuple(
        evaluate_prompt_output(spec, fixture=fixture, output=outputs[fixture.fixture_id])
        for fixture in spec.fixtures
    )
    return PromptTestSetEvaluation(
        spec_hash=spec.spec_hash,
        test_set_id=str(spec.test_set_id),
        test_set_hash=spec.test_set_hash,
        case_results=results,
    )


def _criterion_for_error(spec: PromptBootstrapSpec, error_code: str) -> str:
    if error_code in {"schema_invalid", "input_schema_invalid"}:
        code = "schema.portable_strict"
    elif error_code in {"subject_mismatch", "input_subject_invalid"}:
        code = "identity.subject_exact"
    elif "evidence" in error_code or "citation" in error_code:
        code = "lineage.evidence_allowlist"
    elif "injection" in error_code:
        code = "safety.untrusted_input"
    else:
        code = f"semantics.{spec.program_kind.value}"
    if code not in {item.code for item in spec.rubric}:
        raise PromptBootstrapRuleViolation(f"rubric does not map validation error {error_code}")
    return code
