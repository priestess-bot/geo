"""First-phase Prompt Program draft catalog with fixed evaluation suites."""

from __future__ import annotations

from functools import lru_cache

from geo_core.prompts.bootstrap_contracts import (
    BOOTSTRAP_CATALOG_VERSION,
    BOOTSTRAP_COMPILER_VERSION,
    PromptBootstrapRuleViolation,
    PromptBootstrapSpec,
    PromptRubricCriterion,
)
from geo_core.prompts.bootstrap_fixture_data import build_eval_fixtures
from geo_core.prompts.bootstrap_schemas import (
    bootstrap_application_output_schema,
    bootstrap_input_schema,
    bootstrap_variable_schema,
    provider_portable_output_schema,
)
from geo_core.prompts.bootstrap_templates import bootstrap_template
from geo_core.prompts.bootstrap_validation import (
    COMMON_APPLICATION_RULES,
    KIND_APPLICATION_RULES,
    assert_bootstrap_spec,
)
from geo_core.prompts.program_contracts import (
    WORKSPACE_FLOW_PROGRAM_KINDS,
    ModelPolicySnapshot,
    ProgramKind,
    _canonical_hash,
)


BOOTSTRAP_SPEC_VERSION = "geo-prompt-spec-v2"
VARIABLE_SCHEMA_VERSION = "geo-prompt-request-json-v2"
MODEL_POLICY_VERSION = "geo-prompt-provider-neutral-v1"


DEFAULT_BOOTSTRAP_MODEL_POLICY = ModelPolicySnapshot(
    version=MODEL_POLICY_VERSION,
    policy={
        "structured_output_required": True,
        "schema_profile": "portable-strict-object-v1",
        "compatible_adapters": [
            "deepseek",
            "gemini",
            "kimi",
            "microsoft",
            "openai",
            "perplexity",
        ],
        "model_selection": "admin_required",
        "temperature": 0,
        "provider_fallback": False,
        "automatic_execution": False,
    },
)


@lru_cache(maxsize=1)
def default_prompt_bootstrap_specs() -> tuple[PromptBootstrapSpec, ...]:
    specs = tuple(_build_spec(kind) for kind in WORKSPACE_FLOW_PROGRAM_KINDS)
    if tuple(spec.program_kind for spec in specs) != WORKSPACE_FLOW_PROGRAM_KINDS:
        raise PromptBootstrapRuleViolation("bootstrap catalog kind order changed")
    if len({spec.purpose for spec in specs}) != len(specs):
        raise PromptBootstrapRuleViolation("bootstrap catalog purposes must be unique")
    if len({spec.spec_hash for spec in specs}) != len(specs):
        raise PromptBootstrapRuleViolation("bootstrap catalog spec hashes must be unique")
    return specs


def default_prompt_bootstrap_spec(kind: ProgramKind | str) -> PromptBootstrapSpec:
    try:
        normalized = ProgramKind(kind)
    except ValueError as exc:
        raise PromptBootstrapRuleViolation("unknown bootstrap Prompt Program kind") from exc
    for spec in default_prompt_bootstrap_specs():
        if spec.program_kind is normalized:
            return spec
    raise PromptBootstrapRuleViolation(
        f"{normalized.value} is reserved and has no workspace bootstrap spec"
    )


def prompt_bootstrap_catalog_hash() -> str:
    return _canonical_hash(
        {
            "catalog_version": BOOTSTRAP_CATALOG_VERSION,
            "specs": [
                {"kind": spec.program_kind.value, "spec_hash": spec.spec_hash}
                for spec in default_prompt_bootstrap_specs()
            ],
        }
    )


def _build_spec(kind: ProgramKind) -> PromptBootstrapSpec:
    template = bootstrap_template(kind)
    application_output_schema = bootstrap_application_output_schema(kind)
    spec = PromptBootstrapSpec(
        catalog_version=BOOTSTRAP_CATALOG_VERSION,
        spec_version=BOOTSTRAP_SPEC_VERSION,
        program_kind=kind,
        purpose=template.purpose,
        system_template=template.system_template,
        user_template=template.user_template,
        variable_schema_version=VARIABLE_SCHEMA_VERSION,
        variable_schema=bootstrap_variable_schema(),
        input_schema_version=f"geo-{kind.value}-input-v1",
        input_schema=bootstrap_input_schema(kind),
        output_schema_version=f"geo-{kind.value}-output-v1",
        output_schema=provider_portable_output_schema(application_output_schema),
        application_output_schema_version=(
            f"geo-{kind.value}-application-output-v1"
        ),
        application_output_schema=application_output_schema,
        model_policy=DEFAULT_BOOTSTRAP_MODEL_POLICY,
        compiler_version=BOOTSTRAP_COMPILER_VERSION,
        application_rules=(*COMMON_APPLICATION_RULES, *KIND_APPLICATION_RULES[kind]),
        fixtures=build_eval_fixtures(kind),
        rubric=_rubric(kind),
        minimum_score=95,
    )
    assert_bootstrap_spec(spec)
    return spec


def _rubric(kind: ProgramKind) -> tuple[PromptRubricCriterion, ...]:
    semantics = {
        ProgramKind.GENERATION: (
            "Exactly four distinct candidates; guided input remains creative-only."
        ),
        ProgramKind.CLAIM_EXTRACTION: (
            "Claim IDs are unique; claims remain atomic and derived_or_unknown claims are not evidence-bound."
        ),
        ProgramKind.CONFLICT_CHECK: (
            "Every frozen claim is assessed exactly once; Fact conflict and subject mixup require revision."
        ),
        ProgramKind.REVISION: (
            "Every frozen issue is resolved or retained exactly once and the two sets are disjoint."
        ),
        ProgramKind.STYLE_JUDGE: (
            "Score, threshold and pass flag are internally consistent."
        ),
        ProgramKind.ARBITER: (
            "The arbiter remains within the frozen candidate and covers every evaluator exactly once."
        ),
        ProgramKind.METRIC_JUDGE: (
            "Every frozen metric is returned exactly once with a verifiable evidence locator."
        ),
        ProgramKind.RECOMMENDATION: (
            "Recommendation uses only input evidence and proposes an unstarted draft only."
        ),
        ProgramKind.STYLE_PROFILE: (
            "Profile patterns retain the frozen sample manifest and never contradict their avoidance set."
        ),
        ProgramKind.OFFLINE_ANSWER: (
            "Offline answer retains slot identity and uses exactly the frozen Corpus evidence."
        ),
        ProgramKind.QUESTION_GENERATION: (
            "Question IDs are unique and every generated question cites only frozen evidence."
        ),
        ProgramKind.RAG_GROUNDING: (
            "Grounded questions retain their frozen scope and list only supplied supporting Facts."
        ),
        ProgramKind.PLACEMENT_GENERATION: (
            "Placement content is draft-only and confirms the frozen destination policy."
        ),
        ProgramKind.PLACEMENT_SIMULATION: (
            "Simulation returns only the frozen Prompt rendering and preview, never a live-surface claim."
        ),
    }[kind]
    return (
        PromptRubricCriterion(
            "schema.portable_strict", "Output matches the portable strict schema.", 20, True
        ),
        PromptRubricCriterion(
            "identity.subject_exact", "Every output subject matches the frozen target.", 20, True
        ),
        PromptRubricCriterion(
            "lineage.evidence_allowlist",
            "Evidence and citation refs are a subset of frozen input evidence.",
            25,
            True,
        ),
        PromptRubricCriterion(
            "safety.untrusted_input", "Untrusted input is detected and never followed.", 15, True
        ),
        PromptRubricCriterion(f"semantics.{kind.value}", semantics, 20, True),
    )
