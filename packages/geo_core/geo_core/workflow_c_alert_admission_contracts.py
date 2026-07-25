"""Stable selector and result contracts for Workflow C alert admission."""

from __future__ import annotations

from dataclasses import dataclass
import re
from collections.abc import Mapping
from uuid import UUID

from geo_core.alerts import (
    AlertEvidenceReference,
    AlertScope,
    NotificationChannel,
)


ALERT_ADMISSION_NAMESPACE = UUID("7f171df3-14ac-5a4d-bbb2-aa73c9bfb08a")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class WorkflowCAlertAdmissionError(ValueError):
    """A frozen output cannot safely become an alert evaluation."""


@dataclass(frozen=True)
class AlertEvaluationSelector:
    alert_rule_id: UUID
    source_hash: str
    baseline_source_hash: str | None = None
    source_item_key: str | None = None
    channels: tuple[NotificationChannel, ...] = (
        NotificationChannel.ADMIN_INBOX,
        NotificationChannel.LOCAL_SMTP,
        NotificationChannel.INTERNAL_WEBHOOK,
    )
    max_attempts: int = 3

    def __post_init__(self) -> None:
        if not _SHA256.fullmatch(self.source_hash):
            raise WorkflowCAlertAdmissionError("alert source hash must be SHA-256")
        if self.baseline_source_hash is not None and not _SHA256.fullmatch(
            self.baseline_source_hash
        ):
            raise WorkflowCAlertAdmissionError("alert baseline hash must be SHA-256")
        if self.source_item_key is not None and (
            not self.source_item_key.strip() or len(self.source_item_key) > 500
        ):
            raise WorkflowCAlertAdmissionError("alert source item selector is invalid")
        channels = tuple(sorted({NotificationChannel(item) for item in self.channels}, key=str))
        if not channels or len(channels) != len(self.channels):
            raise WorkflowCAlertAdmissionError("alert channels must be non-empty and unique")
        if not 1 <= self.max_attempts <= 10:
            raise WorkflowCAlertAdmissionError("alert max attempts must be between 1 and 10")
        object.__setattr__(self, "channels", channels)

    def canonical_value(self) -> dict[str, object]:
        return {
            "alert_rule_id": str(self.alert_rule_id),
            "source_hash": self.source_hash,
            "baseline_source_hash": self.baseline_source_hash,
            "source_item_key": self.source_item_key,
            "channels": [item.value for item in self.channels],
        }


@dataclass(frozen=True)
class _ResolvedAlertInput:
    values: Mapping[str, object]
    scope: AlertScope
    evidence: tuple[AlertEvidenceReference, ...]
