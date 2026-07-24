"""Canonical command hashing and optimistic-version helpers for Prompt Programs."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
import hashlib
import json
from uuid import UUID

from geo_core.prompts.ports import (
    PromptCommandOperation,
    PromptCommandRecord,
    PromptProgramVersionConflict,
)
from geo_core.prompts.program import ProgramReleaseState, PromptProgramRuleViolation


def command_record(
    *,
    project_id: UUID,
    key_hash: str,
    operation: PromptCommandOperation,
    request_hash: str,
    result: object,
) -> PromptCommandRecord:
    return PromptCommandRecord(project_id, key_hash, operation, request_hash, result)


def require_expected_version(state: ProgramReleaseState, expected_version: int) -> None:
    if state.version != expected_version:
        raise PromptProgramVersionConflict(
            "Prompt Program Release state changed after it was read"
        )


def idempotency_key_hash(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 200:
        raise PromptProgramRuleViolation(
            "Prompt Program idempotency key must contain 1 to 200 characters"
        )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def request_hash(
    *,
    operation: PromptCommandOperation,
    actor_id: UUID,
    project_id: UUID,
    expected_version: int,
    values: Mapping[str, object],
) -> str:
    payload = {
        "operation": operation.value,
        "actor_id": str(actor_id),
        "project_id": str(project_id),
        "expected_version": expected_version,
        "values": _canonical_value(values),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _canonical_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    return value
