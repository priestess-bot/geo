"""Immutable Prompt Program identities, Releases, evidence and bindings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from geo_core.prompts.program_contracts import (
    BOOTSTRAP_COMPILER_VERSION,
    WORKSPACE_FLOW_PROGRAM_KINDS,
    ModelPolicySnapshot,
    ProgramKind,
    ProgramReleaseStatus,
    ProgramSchemaContract,
    PromptProgramRuleViolation,
    _canonical_hash,
    _canonical_value,
    _is_sha256,
    _normalize_purpose,
    _normalize_version,
    _text_hash,
    _validate_template_variables,
)


@dataclass(frozen=True)
class PromptProgram:
    """Editable Program identity; executable content lives in immutable Releases."""

    id: UUID
    project_id: UUID
    program_kind: ProgramKind
    purpose: str
    owner_id: UUID

    def __post_init__(self) -> None:
        try:
            program_kind = ProgramKind(self.program_kind)
        except ValueError as exc:
            raise PromptProgramRuleViolation("unknown Prompt Program kind") from exc
        if program_kind not in WORKSPACE_FLOW_PROGRAM_KINDS:
            raise PromptProgramRuleViolation(
                "reference_translation is reserved and this Program kind is not deliverable"
            )
        object.__setattr__(self, "program_kind", program_kind)
        object.__setattr__(self, "purpose", _normalize_purpose(self.purpose))


@dataclass(frozen=True)
class PromptProgramRelease:
    """An immutable, content-addressed executable Prompt Program Release."""

    id: UUID
    project_id: UUID
    program_id: UUID
    program_kind: ProgramKind
    purpose: str
    version: int
    owner_id: UUID
    system_template: str
    user_template: str
    schemas: ProgramSchemaContract
    model_policy: ModelPolicySnapshot
    test_set_id: UUID
    test_set_version: int
    test_set_hash: str
    compiler_version: str
    system_template_hash: str = field(init=False)
    user_template_hash: str = field(init=False)
    release_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.version < 1:
            raise PromptProgramRuleViolation("Prompt Program Release version must be positive")
        if self.test_set_version < 1:
            raise PromptProgramRuleViolation("Prompt Program test set version must be positive")
        if not _is_sha256(self.test_set_hash):
            raise PromptProgramRuleViolation("Prompt Program test set hash must be SHA-256")
        try:
            program_kind = ProgramKind(self.program_kind)
        except ValueError as exc:
            raise PromptProgramRuleViolation("unknown Prompt Program kind") from exc
        if program_kind not in WORKSPACE_FLOW_PROGRAM_KINDS:
            raise PromptProgramRuleViolation("reserved Program kinds cannot be released")
        if not isinstance(self.schemas, ProgramSchemaContract):
            raise PromptProgramRuleViolation("a structured schema contract is required")
        if not isinstance(self.model_policy, ModelPolicySnapshot):
            raise PromptProgramRuleViolation("a versioned model policy is required")

        system_template = self.system_template.strip()
        user_template = self.user_template.strip()
        if not system_template or not user_template:
            raise PromptProgramRuleViolation("system and user templates are required")
        purpose = _normalize_purpose(self.purpose)
        compiler_version = _normalize_version(
            self.compiler_version, field_name="compiler version"
        )
        _validate_template_variables(
            system_template=system_template,
            user_template=user_template,
            variable_schema=self.schemas.variable_schema,
        )

        object.__setattr__(self, "program_kind", program_kind)
        object.__setattr__(self, "purpose", purpose)
        object.__setattr__(self, "system_template", system_template)
        object.__setattr__(self, "user_template", user_template)
        object.__setattr__(self, "compiler_version", compiler_version)
        object.__setattr__(self, "system_template_hash", _text_hash(system_template))
        object.__setattr__(self, "user_template_hash", _text_hash(user_template))
        object.__setattr__(self, "release_hash", _canonical_hash(self.canonical_value()))

    @classmethod
    def compile(
        cls,
        *,
        id: UUID,
        program: PromptProgram,
        version: int,
        system_template: str,
        user_template: str,
        schemas: ProgramSchemaContract,
        model_policy: ModelPolicySnapshot,
        test_set_id: UUID,
        test_set_version: int,
        test_set_hash: str,
        compiler_version: str,
    ) -> PromptProgramRelease:
        properties = schemas.variable_schema.get("properties", {})
        if (
            isinstance(properties, Mapping)
            and "request_json" in properties
            and compiler_version.strip() != BOOTSTRAP_COMPILER_VERSION
        ):
            raise PromptProgramRuleViolation(
                "new request_json Releases require the current secure Prompt compiler"
            )
        return cls(
            id=id,
            project_id=program.project_id,
            program_id=program.id,
            program_kind=program.program_kind,
            purpose=program.purpose,
            version=version,
            owner_id=program.owner_id,
            system_template=system_template,
            user_template=user_template,
            schemas=schemas,
            model_policy=model_policy,
            test_set_id=test_set_id,
            test_set_version=test_set_version,
            test_set_hash=test_set_hash,
            compiler_version=compiler_version,
        )

    def canonical_value(self) -> Mapping[str, object]:
        """Return executable content; database identity and release number stay separate."""

        return {
            "program_kind": self.program_kind.value,
            "purpose": self.purpose,
            "system_template": self.system_template,
            "user_template": self.user_template,
            "schemas": self.schemas.canonical_value(),
            "model_policy": self.model_policy.canonical_value(),
            "test_set_id": str(self.test_set_id),
            "test_set_version": self.test_set_version,
            "test_set_hash": self.test_set_hash,
            "compiler_version": self.compiler_version,
        }

    def diffable_value(self) -> Mapping[str, object]:
        return {
            "system_template": self.system_template,
            "user_template": self.user_template,
            "variable_schema_version": self.schemas.variable_schema_version,
            "variable_schema": _canonical_value(self.schemas.variable_schema),
            "input_schema_version": self.schemas.input_schema_version,
            "input_schema": _canonical_value(self.schemas.input_schema),
            "output_schema_version": self.schemas.output_schema_version,
            "output_schema": _canonical_value(self.schemas.output_schema),
            "output_schema_hash": self.schemas.output_schema_hash,
            "application_output_schema_version": (
                self.schemas.application_output_schema_version
            ),
            "application_output_schema": _canonical_value(
                self.schemas.application_output_schema
            ),
            "application_output_schema_hash": (
                self.schemas.application_output_schema_hash
            ),
            "model_policy": self.model_policy.canonical_value(),
            "test_set": {
                "id": str(self.test_set_id),
                "version": self.test_set_version,
                "hash": self.test_set_hash,
            },
            "compiler_version": self.compiler_version,
        }


@dataclass(frozen=True)
class ProgramReleaseState:
    id: UUID
    release_id: UUID
    release_hash: str
    version: int
    previous_state_id: UUID | None
    status: ProgramReleaseStatus
    acted_by: UUID
    acted_at: datetime
    evidence_ref: str | None = None

    def __post_init__(self) -> None:
        if self.version < 1:
            raise PromptProgramRuleViolation("Prompt Program state version must be positive")
        if (self.version == 1) != (self.previous_state_id is None):
            raise PromptProgramRuleViolation("Prompt Program state history must be linear")
        if not _is_sha256(self.release_hash):
            raise PromptProgramRuleViolation("Prompt Program state requires a Release SHA-256")
        try:
            status = ProgramReleaseStatus(self.status)
        except ValueError as exc:
            raise PromptProgramRuleViolation("unknown Prompt Program Release status") from exc
        evidence_ref = (self.evidence_ref or "").strip() or None
        if status == ProgramReleaseStatus.DRAFT and evidence_ref is not None:
            raise PromptProgramRuleViolation("a draft state cannot claim transition evidence")
        if status != ProgramReleaseStatus.DRAFT and evidence_ref is None:
            raise PromptProgramRuleViolation("non-draft Prompt Program states require evidence")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "evidence_ref", evidence_ref)


@dataclass(frozen=True)
class ProgramTestEvidence:
    """Immutable test output lineage used to admit a Release for approval."""

    id: UUID
    project_id: UUID
    release_id: UUID
    release_hash: str
    tested_state_id: UUID
    test_set_id: UUID
    test_set_version: int
    output_artifact_ref: str
    output_hash: str
    tested_by: UUID
    tested_at: datetime
    evidence_hash: str = field(init=False)

    def __post_init__(self) -> None:
        artifact_ref = self.output_artifact_ref.strip()
        if not artifact_ref:
            raise PromptProgramRuleViolation("Prompt Program test output reference is required")
        if self.test_set_version < 1:
            raise PromptProgramRuleViolation("Prompt Program test set version must be positive")
        if not _is_sha256(self.release_hash) or not _is_sha256(self.output_hash):
            raise PromptProgramRuleViolation(
                "Prompt Program test evidence requires Release and output SHA-256 values"
            )
        object.__setattr__(self, "output_artifact_ref", artifact_ref)
        object.__setattr__(
            self,
            "evidence_hash",
            _canonical_hash(
                {
                    "id": str(self.id),
                    "project_id": str(self.project_id),
                    "release_id": str(self.release_id),
                    "release_hash": self.release_hash,
                    "tested_state_id": str(self.tested_state_id),
                    "test_set_id": str(self.test_set_id),
                    "test_set_version": self.test_set_version,
                    "output_artifact_ref": artifact_ref,
                    "output_hash": self.output_hash,
                    "tested_by": str(self.tested_by),
                    "tested_at": self.tested_at.isoformat(),
                }
            ),
        )

    @property
    def state_evidence_ref(self) -> str:
        return f"prompt-test:{self.id}:{self.evidence_hash}"


@dataclass(frozen=True)
class CompiledProgramPrompt:
    release_id: UUID
    release_hash: str
    variable_input_hash: str
    compiled_system: str
    compiled_system_hash: str
    compiled_user: str
    compiled_user_hash: str
    output_schema_version: str
    model_policy_version: str
    model_policy_hash: str


@dataclass(frozen=True)
class ProgramReleaseDiff:
    base_release_id: UUID
    base_release_hash: str
    candidate_release_id: UUID
    candidate_release_hash: str
    changed_fields: tuple[str, ...]
    fixed_input_hash: str
    base_system_hash: str
    candidate_system_hash: str
    base_user_hash: str
    candidate_user_hash: str

    @property
    def has_changes(self) -> bool:
        return bool(self.changed_fields)


@dataclass(frozen=True)
class ProgramBinding:
    """Project/purpose-scoped pointer to one exact frozen Release."""

    id: UUID
    project_id: UUID
    purpose: str
    program_kind: ProgramKind
    program_id: UUID
    release_id: UUID
    release_version: int
    release_hash: str
    frozen_state_id: UUID
    binding_version: int
    previous_binding_id: UUID | None
    bound_by: UUID
    bound_at: datetime

    def __post_init__(self) -> None:
        if self.release_version < 1:
            raise PromptProgramRuleViolation("bound Release version must be positive")
        if self.binding_version < 1:
            raise PromptProgramRuleViolation("Prompt Program binding version must be positive")
        if (self.binding_version == 1) != (self.previous_binding_id is None):
            raise PromptProgramRuleViolation("Prompt Program binding history must be linear")
        if not _is_sha256(self.release_hash):
            raise PromptProgramRuleViolation("Prompt Program binding requires a Release SHA-256")
        try:
            program_kind = ProgramKind(self.program_kind)
        except ValueError as exc:
            raise PromptProgramRuleViolation("unknown bound Prompt Program kind") from exc
        if program_kind not in WORKSPACE_FLOW_PROGRAM_KINDS:
            raise PromptProgramRuleViolation("reserved Program kinds cannot be bound")
        object.__setattr__(self, "purpose", _normalize_purpose(self.purpose))
        object.__setattr__(self, "program_kind", program_kind)


def _assert_state_matches_release(
    *, state: ProgramReleaseState, release: PromptProgramRelease
) -> None:
    if state.release_id != release.id or state.release_hash != release.release_hash:
        raise PromptProgramRuleViolation("Prompt Program state does not belong to the Release")
