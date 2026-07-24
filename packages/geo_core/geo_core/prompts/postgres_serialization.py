"""JSON-safe Prompt Program command receipt serialization."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
import json
from uuid import UUID

from geo_core.prompts.application import (
    BoundPromptProgram,
    CreatedPromptProgram,
    CreatedPromptRelease,
    TestedPromptProgram,
    TransitionedPromptProgram,
)
from geo_core.prompts.ports import PromptProgramPersistenceError
from geo_core.prompts.program import ProgramReleaseDiff


def serialize_result(result: object) -> tuple[str, dict[str, object]]:
    if isinstance(result, CreatedPromptProgram):
        return "created", {
            "program_id": str(result.program.id),
            "release_id": str(result.release.id),
            "state_id": str(result.state.id),
        }
    if isinstance(result, CreatedPromptRelease):
        return "created_release", {
            "release_id": str(result.release.id),
            "state_id": str(result.state.id),
        }
    if isinstance(result, TestedPromptProgram):
        return "tested", {
            "release_id": str(result.release.id),
            "state_id": str(result.state.id),
            "evidence_id": str(result.evidence.id),
        }
    if isinstance(result, TransitionedPromptProgram):
        return "transitioned", {
            "release_id": str(result.release.id),
            "state_id": str(result.state.id),
            "evidence_id": (
                str(result.admitted_test_evidence.id)
                if result.admitted_test_evidence is not None
                else None
            ),
        }
    if isinstance(result, BoundPromptProgram):
        return "bound", {
            "release_id": str(result.release.id),
            "state_id": str(result.state.id),
            "binding_id": str(result.binding.id),
        }
    if isinstance(result, ProgramReleaseDiff):
        return "diffed", {
            "base_release_id": str(result.base_release_id),
            "base_release_hash": result.base_release_hash,
            "candidate_release_id": str(result.candidate_release_id),
            "candidate_release_hash": result.candidate_release_hash,
            "changed_fields": list(result.changed_fields),
            "fixed_input_hash": result.fixed_input_hash,
            "base_system_hash": result.base_system_hash,
            "candidate_system_hash": result.candidate_system_hash,
            "base_user_hash": result.base_user_hash,
            "candidate_user_hash": result.candidate_user_hash,
        }
    raise PromptProgramPersistenceError(
        "Prompt Program command result type is unsupported"
    )


def payload_uuid(payload: Mapping[str, object], key: str) -> UUID:
    try:
        return UUID(str(payload[key]))
    except (KeyError, TypeError, ValueError) as error:
        raise PromptProgramPersistenceError(
            "stored Prompt Program result identity is invalid"
        ) from error


def plain_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain_json(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    json.dumps(value, allow_nan=False)
    return value
