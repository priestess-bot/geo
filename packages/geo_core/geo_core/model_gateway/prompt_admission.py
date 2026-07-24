"""Closed-world Prompt lineage admitted to an audited model-call Job."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from uuid import UUID


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ModelCallAdmissionMode(StrEnum):
    RUNTIME_FROZEN = "runtime_frozen"
    PROMPT_RELEASE_TEST = "prompt_release_test"


class PromptAdmissionState(StrEnum):
    DRAFT = "draft"
    FROZEN = "frozen"


@dataclass(frozen=True)
class PromptReleaseAdmission:
    project_id: UUID
    admission_mode: ModelCallAdmissionMode
    binding_id: UUID | None
    state_id: UUID
    state_version: int
    release_id: UUID
    release_hash: str
    purpose: str
    output_schema_hash: str
    application_output_schema_hash: str
    test_set_hash: str | None
    state_status: PromptAdmissionState
    current: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "admission_mode", ModelCallAdmissionMode(self.admission_mode)
        )
        object.__setattr__(self, "state_status", PromptAdmissionState(self.state_status))
        for uuid_value, label in (
            (self.project_id, "Prompt admission project"),
            (self.state_id, "Prompt state"),
            (self.release_id, "Prompt Release"),
        ):
            _require_uuid(uuid_value, label)
        if self.binding_id is not None:
            _require_uuid(self.binding_id, "Prompt binding")
        if self.state_version < 1:
            raise ValueError("Prompt state version must be positive")
        for hash_value, label in (
            (self.release_hash, "Prompt Release"),
            (self.output_schema_hash, "Prompt output schema"),
            (
                self.application_output_schema_hash,
                "Prompt application output schema",
            ),
        ):
            _require_hash(hash_value, label)
        if self.test_set_hash is not None:
            _require_hash(self.test_set_hash, "Prompt test set")
        if not self.purpose.strip():
            raise ValueError("Prompt purpose cannot be empty")
        runtime = self.admission_mode is ModelCallAdmissionMode.RUNTIME_FROZEN
        if runtime:
            if (
                self.binding_id is None
                or self.test_set_hash is not None
                or self.state_status is not PromptAdmissionState.FROZEN
            ):
                raise ValueError("runtime Prompt admission requires one frozen binding")
        elif (
            self.binding_id is not None
            or self.test_set_hash is None
            or self.purpose != "prompt_release_test"
            or self.state_status is not PromptAdmissionState.DRAFT
        ):
            raise ValueError("Prompt test admission requires current draft lineage")

    @property
    def portable_output_schema_hash(self) -> str:
        return self.output_schema_hash


def validate_job_prompt_shape(
    *,
    admission_mode: ModelCallAdmissionMode,
    binding_id: UUID | None,
    test_set_hash: str | None,
    job_kind: str,
    purpose: str,
) -> None:
    if admission_mode is ModelCallAdmissionMode.RUNTIME_FROZEN:
        if binding_id is None or test_set_hash is not None:
            raise ValueError("runtime model-call admission requires a Prompt binding")
        _require_uuid(binding_id, "model-call Prompt binding")
        return
    if (
        binding_id is not None
        or test_set_hash is None
        or job_kind != "prompt.test.execute"
        or purpose != "prompt_release_test"
    ):
        raise ValueError("Prompt test Job admission lineage is invalid")


def validate_attempt_prompt_shape(
    *,
    admission_mode: ModelCallAdmissionMode,
    binding_id: UUID | None,
    test_set_hash: str | None,
    test_case_id: UUID | None,
    test_case_hash: str | None,
    purpose: str,
) -> None:
    validate_job_prompt_shape(
        admission_mode=admission_mode,
        binding_id=binding_id,
        test_set_hash=test_set_hash,
        job_kind=(
            "prompt.test.execute"
            if admission_mode is ModelCallAdmissionMode.PROMPT_RELEASE_TEST
            else "runtime"
        ),
        purpose=purpose,
    )
    if admission_mode is ModelCallAdmissionMode.RUNTIME_FROZEN:
        if test_case_id is not None or test_case_hash is not None:
            raise ValueError("runtime model calls cannot carry Prompt test case lineage")
        return
    if test_case_id is None or test_case_hash is None:
        raise ValueError("Prompt test model calls require exact test case lineage")
    _require_uuid(test_case_id, "attempt Prompt test case")


def _require_uuid(value: UUID, label: str) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise ValueError(f"{label} ID must be a non-zero UUID")


def _require_hash(value: str, label: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} hash must be lowercase SHA-256")


__all__ = [
    "ModelCallAdmissionMode",
    "PromptAdmissionState",
    "PromptReleaseAdmission",
    "validate_attempt_prompt_shape",
    "validate_job_prompt_shape",
]
