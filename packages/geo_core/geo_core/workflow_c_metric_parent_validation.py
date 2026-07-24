"""Validation primitives shared by the durable Metric parent orchestration."""

from __future__ import annotations

from collections.abc import Mapping
import re
from uuid import UUID

from geo_core.workflow_c_analysis_common import WorkflowCAnalysisWorkerError


_HASH = re.compile(r"^[0-9a-f]{64}$")


class WorkflowCMetricParentOrchestrationError(WorkflowCAnalysisWorkerError):
    """Frozen Metric parent state cannot progress safely."""


def mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise WorkflowCMetricParentOrchestrationError(f"{label} is invalid")
    return value


def text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkflowCMetricParentOrchestrationError(f"{label} is invalid")
    return value


def optional_text(value: object, label: str) -> str | None:
    return None if value is None else text(value, label)


def hash_value(value: object, label: str) -> str:
    parsed = text(value, label)
    if _HASH.fullmatch(parsed) is None:
        raise WorkflowCMetricParentOrchestrationError(f"{label} is invalid")
    return parsed


def optional_hash(value: object, label: str) -> str | None:
    return None if value is None else hash_value(value, label)


def uuid_value(value: object, label: str) -> UUID:
    if isinstance(value, UUID) and value.int != 0:
        return value
    if isinstance(value, str):
        try:
            parsed = UUID(value)
        except ValueError as error:
            raise WorkflowCMetricParentOrchestrationError(f"{label} is invalid") from error
        if parsed.int != 0:
            return parsed
    raise WorkflowCMetricParentOrchestrationError(f"{label} is invalid")


def optional_uuid(value: object, label: str) -> UUID | None:
    return None if value is None else uuid_value(value, label)


def positive(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise WorkflowCMetricParentOrchestrationError(f"{label} is invalid")
    return value


__all__ = [
    "WorkflowCMetricParentOrchestrationError",
    "hash_value",
    "mapping",
    "optional_hash",
    "optional_text",
    "optional_uuid",
    "positive",
    "text",
    "uuid_value",
]
