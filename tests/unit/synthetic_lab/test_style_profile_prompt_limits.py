from __future__ import annotations

from dataclasses import replace
import json

from geo_core.prompts.bootstrap_catalog import default_prompt_bootstrap_spec
from geo_core.prompts.bootstrap_contracts import thaw_mapping
from geo_core.prompts.bootstrap_limits import STYLE_PROFILE_SUMMARY_MAX_CHARACTERS
from geo_core.prompts.bootstrap_validation import validate_bootstrap_input
from geo_core.prompts.program_contracts import ProgramKind
from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.execution import SyntheticTaskExecutor
from geo_core.synthetic_lab.execution_contracts import FrozenEvidence
from geo_core.synthetic_lab.execution_gateway import PromptProgramExecutionResolver
from tests.unit.synthetic_lab.execution_prompt_contract_support import (
    _GovernedModel,
    _RuntimeApplication,
    _hash,
    _lease,
    _runtime,
    _style_task,
)


def test_large_style_profile_build_output_is_consumable_by_review_prompts() -> None:
    runtime, frozen = _runtime(ProgramKind.STYLE_PROFILE)
    task = _style_task(frozen)
    executor = SyntheticTaskExecutor(
        prompts=PromptProgramExecutionResolver(_RuntimeApplication(runtime)),
        model_gateway=_GovernedModel(large_style_profile=True),
    )

    output = executor.run(
        lease=_lease(task.job_id, "style.profile.build"),
        task=task,
        checkpoint=lambda: task.runtime_inputs,
    )

    assert 4_000 < len(output.profile_summary) <= STYLE_PROFILE_SUMMARY_MAX_CHARACTERS
    for kind in (ProgramKind.GENERATION, ProgramKind.STYLE_JUDGE):
        spec = default_prompt_bootstrap_spec(kind)
        fixture = next(item for item in spec.fixtures if item.expected_valid)
        downstream_input = thaw_mapping(fixture.input_value)
        downstream_input["style_profile"] = output.profile_summary
        assert validate_bootstrap_input(spec, downstream_input)["style_profile"] == (
            output.profile_summary
        )


def test_200_sample_manifest_build_uses_bounded_short_example_context() -> None:
    runtime, frozen = _runtime(ProgramKind.STYLE_PROFILE)
    manifest_hash = _hash("approved-205-sample-manifest")
    task = replace(
        _style_task(frozen),
        approved_sample_count=205,
        sample_manifest_hash=manifest_hash,
        sample_style_evidence=tuple(
            FrozenEvidence(
                ref=f"sample:{index:03d}",
                subject_id="style:reddit",
                summary=f"Approved anonymous Australian example {index}: " + ("x" * 180),
            )
            for index in range(24)
        ),
    )
    model = _GovernedModel()
    executor = SyntheticTaskExecutor(
        prompts=PromptProgramExecutionResolver(_RuntimeApplication(runtime)),
        model_gateway=model,
    )

    output = executor.run(
        lease=_lease(task.job_id, "style.profile.build"),
        task=task,
        checkpoint=lambda: task.runtime_inputs,
    )

    structured = model.inputs[0]
    evidence = structured["evidence"]
    assert isinstance(evidence, tuple) and len(evidence) == 24
    assert all(len(str(item["summary"])) <= 240 for item in evidence)
    assert len(
        json.dumps(
            thaw_mapping(structured),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ) < 100_000
    assert structured["approved_sample_count"] == 205
    assert structured["sample_manifest_hash"] == manifest_hash
    assert model.structured_input_hashes == [canonical_hash(structured)]
    assert json.loads(output.profile_summary or "{}")["sample_manifest_hash"] == (
        manifest_hash
    )
