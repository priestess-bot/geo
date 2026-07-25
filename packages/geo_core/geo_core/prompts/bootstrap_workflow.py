"""Governed preview, offline evaluation and retryable Prompt draft bootstrap workflow."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from typing import Protocol
from uuid import UUID

from geo_core.access.models import AccessPrincipal
from geo_core.prompts.application_access import APPROVER_ROLES, require_project_role
from geo_core.prompts.application_models import (
    CommandReceipt,
    CreatedPromptProgram,
    PromptProgramApplicationError,
    PromptProgramForbidden,
    PromptProgramNotFound,
)
from geo_core.prompts.application_support import idempotency_key_hash
from geo_core.prompts.bootstrap_catalog import (
    default_prompt_bootstrap_spec,
    default_prompt_bootstrap_specs,
    prompt_bootstrap_catalog_hash,
)
from geo_core.prompts.bootstrap_contracts import (
    PromptBootstrapSpec,
)
from geo_core.prompts.bootstrap_evaluation import (
    PromptTestSetEvaluation,
    evaluate_prompt_test_set,
)
from geo_core.prompts.ports import (
    PromptProgramIdempotencyConflict,
    PromptProgramPersistenceError,
    PromptProgramVersionConflict,
)
from geo_core.prompts.program import (
    ModelPolicySnapshot,
    ProgramKind,
    ProgramReleaseStatus,
    ProgramSchemaContract,
    PromptProgramRuleViolation,
)


class PromptDraftCreator(Protocol):
    def create_program(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_kind: ProgramKind,
        purpose: str,
        system_template: str,
        user_template: str,
        schemas: ProgramSchemaContract,
        model_policy: ModelPolicySnapshot,
        test_set_id: UUID,
        test_set_version: int,
        test_set_hash: str,
        compiler_version: str,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[CreatedPromptProgram]: ...


@dataclass(frozen=True)
class BootstrapDraftReceipt:
    program_kind: ProgramKind
    spec_hash: str
    test_set_hash: str
    idempotency_key_hash: str
    receipt: CommandReceipt[CreatedPromptProgram]


@dataclass(frozen=True)
class BootstrapDraftFailure:
    program_kind: ProgramKind
    spec_hash: str
    test_set_hash: str
    idempotency_key_hash: str
    code: str
    detail: str
    retryable: bool


BootstrapDraftItem = BootstrapDraftReceipt | BootstrapDraftFailure


@dataclass(frozen=True)
class BootstrapDraftBatch:
    catalog_hash: str
    items: tuple[BootstrapDraftItem, ...]
    atomic: bool = False
    safe_to_retry: bool = True

    @property
    def completion_status(self) -> str:
        failed = sum(isinstance(item, BootstrapDraftFailure) for item in self.items)
        if failed == 0:
            return "completed"
        if failed == len(self.items):
            return "failed"
        return "partial_failure"


def preview_prompt_bootstrap(
    principal: AccessPrincipal, *, project_id: UUID
) -> tuple[PromptBootstrapSpec, ...]:
    _require_admin(principal, project_id)
    return default_prompt_bootstrap_specs()


def evaluate_prompt_bootstrap(
    principal: AccessPrincipal,
    *,
    project_id: UUID,
    program_kind: ProgramKind,
    catalog_hash: str,
    spec_hash: str,
    test_set_hash: str,
    outputs: Mapping[str, Mapping[str, object]],
) -> PromptTestSetEvaluation:
    _require_admin(principal, project_id)
    _require_catalog_hash(catalog_hash)
    spec = default_prompt_bootstrap_spec(program_kind)
    if spec.spec_hash != spec_hash or spec.test_set_hash != test_set_hash:
        raise PromptProgramVersionConflict(
            "Prompt bootstrap spec or test set changed after preview"
        )
    return evaluate_prompt_test_set(spec, outputs)


def create_prompt_bootstrap_drafts(
    application: PromptDraftCreator,
    principal: AccessPrincipal,
    *,
    project_id: UUID,
    catalog_hash: str,
    idempotency_key: str,
) -> BootstrapDraftBatch:
    _require_admin(principal, project_id)
    _require_catalog_hash(catalog_hash)
    base_key_hash = idempotency_key_hash(idempotency_key)
    items: list[BootstrapDraftItem] = []
    for spec in default_prompt_bootstrap_specs():
        item_key = _item_idempotency_key(
            base_key_hash=base_key_hash,
            catalog_hash=catalog_hash,
            kind=spec.program_kind,
        )
        key_hash = hashlib.sha256(item_key.encode("utf-8")).hexdigest()
        try:
            receipt = application.create_program(
                principal,
                project_id=project_id,
                program_kind=spec.program_kind,
                purpose=spec.purpose,
                system_template=spec.system_template,
                user_template=spec.user_template,
                schemas=spec.schemas,
                model_policy=spec.model_policy,
                test_set_id=spec.test_set_id,
                test_set_version=1,
                test_set_hash=spec.test_set_hash,
                compiler_version=spec.compiler_version,
                expected_version=0,
                idempotency_key=item_key,
            )
            if receipt.value.state.status is not ProgramReleaseStatus.DRAFT:
                raise PromptProgramRuleViolation(
                    "Prompt bootstrap create returned a non-draft Release state"
                )
        except _ITEM_FAILURES as error:
            code, retryable = _failure_code(error)
            items.append(
                BootstrapDraftFailure(
                    program_kind=spec.program_kind,
                    spec_hash=spec.spec_hash,
                    test_set_hash=spec.test_set_hash,
                    idempotency_key_hash=key_hash,
                    code=code,
                    detail=str(error),
                    retryable=retryable,
                )
            )
        else:
            items.append(
                BootstrapDraftReceipt(
                    program_kind=spec.program_kind,
                    spec_hash=spec.spec_hash,
                    test_set_hash=spec.test_set_hash,
                    idempotency_key_hash=key_hash,
                    receipt=receipt,
                )
            )
    return BootstrapDraftBatch(catalog_hash=catalog_hash, items=tuple(items))


_ITEM_FAILURES = (
    PromptProgramRuleViolation,
    PromptProgramForbidden,
    PromptProgramNotFound,
    PromptProgramIdempotencyConflict,
    PromptProgramVersionConflict,
    PromptProgramPersistenceError,
    PromptProgramApplicationError,
)


def _require_admin(principal: AccessPrincipal, project_id: UUID) -> None:
    require_project_role(principal, project_id, allowed=APPROVER_ROLES)


def _require_catalog_hash(candidate: str) -> None:
    if candidate != prompt_bootstrap_catalog_hash():
        raise PromptProgramVersionConflict(
            "Prompt bootstrap catalog changed after preview; refresh before retrying"
        )


def _item_idempotency_key(
    *, base_key_hash: str, catalog_hash: str, kind: ProgramKind
) -> str:
    return f"prompt-bootstrap:{catalog_hash[:16]}:{kind.value}:{base_key_hash}"


def _failure_code(error: Exception) -> tuple[str, bool]:
    if isinstance(error, PromptProgramIdempotencyConflict):
        return "idempotency_conflict", False
    if isinstance(error, PromptProgramVersionConflict):
        return "version_conflict", False
    if isinstance(error, PromptProgramPersistenceError):
        return "persistence_unavailable", True
    if isinstance(error, PromptProgramForbidden):
        return "forbidden", False
    if isinstance(error, PromptProgramNotFound):
        return "not_found", False
    if isinstance(error, PromptProgramRuleViolation):
        return "rule_violation", False
    return "application_unavailable", True
