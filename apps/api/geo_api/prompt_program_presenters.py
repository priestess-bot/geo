"""HTTP response projections for governed Prompt Programs."""

from __future__ import annotations

from typing import cast

from geo_api.prompt_program_contracts import (
    CreatedPromptProgramResponse,
    ProgramKindValue,
    PromptProgramBindingOptionResponse,
    PromptProgramBindingResponse,
    PromptProgramDiffResponse,
    PromptProgramReleaseResponse,
    PromptProgramSummaryResponse,
    PromptReleaseStateResponse,
    PromptTestEvidenceResponse,
    PromptTestJobResponse,
    PromptTestRuntimeOptionResponse,
    ReleaseStatusValue,
    TestedPromptProgramResponse,
    TransitionedPromptProgramResponse,
)
from geo_core.prompts.application import (
    BoundPromptProgram,
    CommandReceipt,
    CreatedPromptProgram,
    TestedPromptProgram,
    TransitionedPromptProgram,
)
from geo_core.prompts.program import (
    ProgramBinding,
    ProgramReleaseDiff,
    ProgramReleaseState,
    ProgramTestEvidence,
    PromptProgram,
    PromptProgramRelease,
)
from geo_core.prompts.test_execution_contracts import (
    PromptTestJobReceipt,
    PromptTestRuntimeOption,
)


def present_program(item: PromptProgram) -> PromptProgramSummaryResponse:
    return PromptProgramSummaryResponse(
        id=item.id,
        project_id=item.project_id,
        program_kind=cast(ProgramKindValue, item.program_kind.value),
        purpose=item.purpose,
        owner_id=item.owner_id,
    )


def present_state(item: ProgramReleaseState) -> PromptReleaseStateResponse:
    return PromptReleaseStateResponse(
        id=item.id,
        version=item.version,
        status=cast(ReleaseStatusValue, item.status.value),
        acted_by=item.acted_by,
        acted_at=item.acted_at,
        evidence_ref=item.evidence_ref,
    )


def present_release(
    item: PromptProgramRelease, state: ProgramReleaseState
) -> PromptProgramReleaseResponse:
    schemas = item.schemas
    return PromptProgramReleaseResponse(
        id=item.id,
        project_id=item.project_id,
        program_id=item.program_id,
        program_kind=cast(ProgramKindValue, item.program_kind.value),
        purpose=item.purpose,
        version=item.version,
        owner_id=item.owner_id,
        release_hash=item.release_hash,
        system_template_hash=item.system_template_hash,
        user_template_hash=item.user_template_hash,
        variable_schema_version=schemas.variable_schema_version,
        input_schema_version=schemas.input_schema_version,
        output_schema_version=schemas.output_schema_version,
        output_schema_hash=schemas.output_schema_hash,
        application_output_schema_version=(
            schemas.application_output_schema_version
        ),
        application_output_schema_hash=schemas.application_output_schema_hash,
        model_policy_version=item.model_policy.version,
        model_policy_hash=item.model_policy.policy_hash,
        test_set_id=item.test_set_id,
        test_set_version=item.test_set_version,
        test_set_hash=item.test_set_hash,
        compiler_version=item.compiler_version,
        state=present_state(state),
    )


def present_created(
    item: CommandReceipt[CreatedPromptProgram],
) -> CreatedPromptProgramResponse:
    result = item.value
    return CreatedPromptProgramResponse(
        program=present_program(result.program),
        release=present_release(result.release, result.state),
        replayed=item.replayed,
    )


def present_test_evidence(item: ProgramTestEvidence) -> PromptTestEvidenceResponse:
    return PromptTestEvidenceResponse(
        id=item.id,
        test_set_id=item.test_set_id,
        test_set_version=item.test_set_version,
        evidence_ref=item.state_evidence_ref,
        output_hash=item.output_hash,
        evidence_hash=item.evidence_hash,
        tested_by=item.tested_by,
        tested_at=item.tested_at,
    )


def present_tested(
    item: CommandReceipt[TestedPromptProgram],
) -> TestedPromptProgramResponse:
    result = item.value
    return TestedPromptProgramResponse(
        release=present_release(result.release, result.state),
        evidence=present_test_evidence(result.evidence),
        replayed=item.replayed,
    )


def present_test_job(item: PromptTestJobReceipt) -> PromptTestJobResponse:
    job = item.value
    return PromptTestJobResponse(
        job_id=job.id,
        project_id=job.project_id,
        release_id=job.release_id,
        release_hash=job.release_hash,
        test_set_id=job.test_set_id,
        test_set_version=job.test_set_version,
        test_set_hash=job.test_set_hash,
        input_hash=job.input_hash,
        status=job.status,
        replayed=item.replayed,
    )


def present_test_runtime(
    item: PromptTestRuntimeOption,
) -> PromptTestRuntimeOptionResponse:
    return PromptTestRuntimeOptionResponse(
        runtime_selection_id=item.runtime_selection_id,
        runtime_selection_hash=item.runtime_selection_hash,
        runtime_manifest_id=item.runtime_manifest_id,
        runtime_manifest_hash=item.runtime_manifest_hash,
        provider=item.provider,
        adapter_release_id=item.adapter_release_id,
        adapter_release_hash=item.adapter_release_hash,
        model_release_id=item.model_release_id,
        model_release_hash=item.model_release_hash,
        configured_model=item.configured_model,
        capture_method=item.capture_method.value,
        policy_version_id=item.policy_version_id,
        policy_version_hash=item.policy_version_hash,
    )


def present_transitioned(
    item: CommandReceipt[TransitionedPromptProgram],
) -> TransitionedPromptProgramResponse:
    result = item.value
    evidence = result.admitted_test_evidence
    return TransitionedPromptProgramResponse(
        release=present_release(result.release, result.state),
        admitted_test_evidence_hash=evidence.evidence_hash if evidence else None,
        replayed=item.replayed,
    )


def present_diff(item: CommandReceipt[ProgramReleaseDiff]) -> PromptProgramDiffResponse:
    result = item.value
    return PromptProgramDiffResponse(
        base_release_id=result.base_release_id,
        base_release_hash=result.base_release_hash,
        candidate_release_id=result.candidate_release_id,
        candidate_release_hash=result.candidate_release_hash,
        changed_fields=list(result.changed_fields),
        fixed_input_hash=result.fixed_input_hash,
        base_system_hash=result.base_system_hash,
        candidate_system_hash=result.candidate_system_hash,
        base_user_hash=result.base_user_hash,
        candidate_user_hash=result.candidate_user_hash,
        replayed=item.replayed,
    )


def present_binding(
    item: CommandReceipt[BoundPromptProgram],
) -> PromptProgramBindingResponse:
    result = item.value.binding
    return PromptProgramBindingResponse(
        id=result.id,
        project_id=result.project_id,
        purpose=result.purpose,
        program_kind=cast(ProgramKindValue, result.program_kind.value),
        program_id=result.program_id,
        release_id=result.release_id,
        release_version=result.release_version,
        release_hash=result.release_hash,
        frozen_state_id=result.frozen_state_id,
        binding_version=result.binding_version,
        bound_by=result.bound_by,
        bound_at=result.bound_at,
        replayed=item.replayed,
    )


def present_binding_option(item: ProgramBinding) -> PromptProgramBindingOptionResponse:
    return PromptProgramBindingOptionResponse(
        id=item.id,
        project_id=item.project_id,
        purpose=item.purpose,
        program_kind=cast(ProgramKindValue, item.program_kind.value),
        program_id=item.program_id,
        release_id=item.release_id,
        release_version=item.release_version,
        release_hash=item.release_hash,
        frozen_state_id=item.frozen_state_id,
        binding_version=item.binding_version,
        bound_by=item.bound_by,
        bound_at=item.bound_at,
    )


__all__ = [
    "present_binding",
    "present_binding_option",
    "present_created",
    "present_diff",
    "present_program",
    "present_release",
    "present_state",
    "present_test_evidence",
    "present_test_job",
    "present_test_runtime",
    "present_tested",
    "present_transitioned",
]
