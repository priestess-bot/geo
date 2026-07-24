"""Strict reconstruction of immutable Prompt Program database rows."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any, cast
from uuid import UUID

from geo_core.prompts.ports import PromptProgramPersistenceError
from geo_core.prompts.program import (
    ModelPolicySnapshot,
    ProgramBinding,
    ProgramKind,
    ProgramReleaseState,
    ProgramReleaseStatus,
    ProgramSchemaContract,
    ProgramTestEvidence,
    PromptProgram,
    PromptProgramRelease,
)


def program_from_row(row: Mapping[str, Any]) -> PromptProgram:
    return PromptProgram(
        id=cast(UUID, row["id"]),
        project_id=cast(UUID, row["project_id"]),
        program_kind=ProgramKind(str(row["program_kind"])),
        purpose=str(row["purpose"]),
        owner_id=cast(UUID, row["owner_id"]),
    )


def release_from_row(row: Mapping[str, Any]) -> PromptProgramRelease:
    schemas = ProgramSchemaContract(
        variable_schema_version=str(row["variable_schema_version"]),
        variable_schema=cast(Mapping[str, object], row["variable_schema"]),
        input_schema_version=str(row["input_schema_version"]),
        input_schema=cast(Mapping[str, object], row["input_schema"]),
        output_schema_version=str(row["output_schema_version"]),
        output_schema=cast(Mapping[str, object], row["output_schema"]),
        application_output_schema_version=str(
            row["application_output_schema_version"]
        ),
        application_output_schema=cast(
            Mapping[str, object], row["application_output_schema"]
        ),
    )
    policy = ModelPolicySnapshot(
        version=str(row["model_policy_version"]),
        policy=cast(Mapping[str, object], row["model_policy"]),
    )
    release = PromptProgramRelease(
        id=cast(UUID, row["id"]),
        project_id=cast(UUID, row["project_id"]),
        program_id=cast(UUID, row["program_id"]),
        program_kind=ProgramKind(str(row["program_kind"])),
        purpose=str(row["purpose"]),
        version=int(row["version"]),
        owner_id=cast(UUID, row["owner_id"]),
        system_template=str(row["system_template"]),
        user_template=str(row["user_template"]),
        schemas=schemas,
        model_policy=policy,
        test_set_id=cast(UUID, row["test_set_id"]),
        test_set_version=int(row["test_set_version"]),
        test_set_hash=str(row["test_set_hash"]),
        compiler_version=str(row["compiler_version"]),
    )
    persisted = (
        str(row["system_template_hash"]),
        str(row["user_template_hash"]),
        str(row["release_hash"]),
        str(row["model_policy_hash"]),
        str(row["output_schema_hash"]),
        str(row["application_output_schema_hash"]),
    )
    computed = (
        release.system_template_hash,
        release.user_template_hash,
        release.release_hash,
        release.model_policy.policy_hash,
        release.schemas.output_schema_hash,
        release.schemas.application_output_schema_hash,
    )
    if persisted != computed:
        raise PromptProgramPersistenceError(
            "stored Prompt Program Release hash does not match its content"
        )
    return release


def state_from_row(row: Mapping[str, Any]) -> ProgramReleaseState:
    return ProgramReleaseState(
        id=cast(UUID, row["id"]),
        release_id=cast(UUID, row["release_id"]),
        release_hash=str(row["release_hash"]),
        version=int(row["version"]),
        previous_state_id=cast(UUID | None, row["previous_state_id"]),
        status=ProgramReleaseStatus(str(row["status"])),
        acted_by=cast(UUID, row["acted_by"]),
        acted_at=row["acted_at"],
        evidence_ref=cast(str | None, row["evidence_ref"]),
    )


def binding_from_row(row: Mapping[str, Any]) -> ProgramBinding:
    return ProgramBinding(
        id=cast(UUID, row["id"]),
        project_id=cast(UUID, row["project_id"]),
        purpose=str(row["purpose"]),
        program_kind=ProgramKind(str(row["program_kind"])),
        program_id=cast(UUID, row["program_id"]),
        release_id=cast(UUID, row["release_id"]),
        release_version=int(row["release_version"]),
        release_hash=str(row["release_hash"]),
        frozen_state_id=cast(UUID, row["frozen_state_id"]),
        binding_version=int(row["binding_version"]),
        previous_binding_id=cast(UUID | None, row["previous_binding_id"]),
        bound_by=cast(UUID, row["bound_by"]),
        bound_at=row["bound_at"],
    )


def test_evidence_from_row(row: Mapping[str, Any]) -> ProgramTestEvidence:
    evidence = ProgramTestEvidence(
        id=cast(UUID, row["id"]),
        project_id=cast(UUID, row["project_id"]),
        release_id=cast(UUID, row["release_id"]),
        release_hash=str(row["release_hash"]),
        tested_state_id=cast(UUID, row["tested_state_id"]),
        test_set_id=cast(UUID, row["test_set_id"]),
        test_set_version=int(row["test_set_version"]),
        output_artifact_ref=str(row["output_artifact_ref"]),
        output_hash=str(row["output_hash"]),
        tested_by=cast(UUID, row["tested_by"]),
        tested_at=row["tested_at"],
    )
    if evidence.evidence_hash != str(row["evidence_hash"]):
        raise PromptProgramPersistenceError(
            "stored Prompt Program test evidence hash does not match"
        )
    return evidence


def payload_sha256(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise PromptProgramPersistenceError(
            "stored Prompt Program diff hash is invalid"
        )
    return value


__all__ = [
    "binding_from_row",
    "payload_sha256",
    "program_from_row",
    "release_from_row",
    "state_from_row",
    "test_evidence_from_row",
]
