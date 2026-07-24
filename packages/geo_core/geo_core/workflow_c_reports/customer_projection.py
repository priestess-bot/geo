"""Narrow Customer projection contract for approved Workflow C reports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID


WorkflowCCustomerSourceKind = Literal[
    "provider_api", "proxy_grounded_api", "automated_ui"
]
_CUSTOMER_SOURCE_KINDS = frozenset(
    {"provider_api", "proxy_grounded_api", "automated_ui"}
)
_FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "raw",
        "raw_answer",
        "raw_body",
        "raw_response",
        "artifact",
        "artifact_uri",
        "artifact_url",
        "credential",
        "credentials",
        "secret",
        "secrets",
        "debug",
        "model_reasoning",
        "internal_actor",
        "actor_id",
    }
)


class WorkflowCCustomerProjectionError(ValueError):
    """A row is not eligible for the Workflow C Customer projection."""


@dataclass(frozen=True)
class WorkflowCCustomerApprovedReport:
    """A current, approved, immutable report safe for a Customer reader.

    This object deliberately has no draft/status field.  Its PostgreSQL reader
    is required to return only current `approved` snapshots after checking the
    source semantic snapshot and Observation eligibility.  Keeping that
    constraint out of the general Monitoring Report model avoids accidental
    approval inheritance from the legacy monitoring state machine.
    """

    id: UUID
    project_id: UUID
    campaign_id: UUID
    semantic_snapshot_hash: str
    report_hash: str
    source_kind: WorkflowCCustomerSourceKind
    approved_safe_payload: Mapping[str, object]
    approved_at: datetime

    def __post_init__(self) -> None:
        if self.source_kind not in _CUSTOMER_SOURCE_KINDS:
            raise WorkflowCCustomerProjectionError(
                "Workflow C Customer reports require an automated or API source"
            )
        for label, value in (
            ("semantic snapshot", self.semantic_snapshot_hash),
            ("report", self.report_hash),
        ):
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise WorkflowCCustomerProjectionError(
                    f"Workflow C Customer {label} hash is invalid"
                )
        if self.approved_at.tzinfo is None or self.approved_at.utcoffset() is None:
            raise WorkflowCCustomerProjectionError(
                "Workflow C Customer approval time must be timezone-aware"
            )
        _assert_safe_payload(self.approved_safe_payload)


class WorkflowCCustomerReportReader(Protocol):
    """Project/Campaign-scoped durable read port used only by Customer routes."""

    persistence: Literal["durable"]

    def list_approved_reports(
        self, *, project_id: UUID, campaign_id: UUID
    ) -> tuple[WorkflowCCustomerApprovedReport, ...]: ...


def _assert_safe_payload(value: object) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise WorkflowCCustomerProjectionError(
                    "Workflow C Customer payload keys must be strings"
                )
            if _normalized_payload_key(key) in _FORBIDDEN_PAYLOAD_KEYS:
                raise WorkflowCCustomerProjectionError(
                    "Workflow C Customer payload contains an internal field"
                )
            _assert_safe_payload(nested)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for nested in value:
            _assert_safe_payload(nested)
    elif isinstance(value, (bytes, bytearray)):
        raise WorkflowCCustomerProjectionError(
            "Workflow C Customer payload cannot contain binary data"
        )


def _normalized_payload_key(value: str) -> str:
    """Treat camelCase and punctuation variants as the same payload field."""

    parts: list[str] = []
    for index, character in enumerate(value):
        if character.isupper() and index:
            parts.append("_")
        parts.append(character.lower() if character.isalnum() else "_")
    return "".join(parts).strip("_")


__all__ = [
    "WorkflowCCustomerApprovedReport",
    "WorkflowCCustomerProjectionError",
    "WorkflowCCustomerReportReader",
    "WorkflowCCustomerSourceKind",
]
