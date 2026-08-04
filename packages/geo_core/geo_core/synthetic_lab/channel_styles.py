"""Versioned manual channel directives for direct synthetic generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.domain import (
    AU_ENGLISH_LOCALE,
    STANDARD_STYLE_CHANNELS,
    SyntheticLabContractError,
    SyntheticOnly,
    _require_hash,
    _require_text,
    _require_uuid,
)


class ChannelStyleProvenance(StrEnum):
    MANUAL_INITIAL = "manual_initial"
    MANUAL_EDIT = "manual_edit"


class ChannelStyleCalibration(StrEnum):
    PENDING_SAMPLE_CALIBRATION = "pending_sample_calibration"
    SAMPLE_CALIBRATED = "sample_calibrated"


@dataclass(frozen=True, kw_only=True)
class ChannelStyleVersion(SyntheticOnly):
    id: UUID
    project_id: UUID
    style_id: UUID
    version_number: int
    channel: str
    directive: str
    previous_version_id: UUID | None = None
    locale: str = AU_ENGLISH_LOCALE
    provenance: ChannelStyleProvenance = ChannelStyleProvenance.MANUAL_INITIAL
    calibration_status: ChannelStyleCalibration = (
        ChannelStyleCalibration.PENDING_SAMPLE_CALIBRATION
    )
    style_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for value, label in (
            (self.id, "Channel Style version ID"),
            (self.project_id, "Channel Style Project ID"),
            (self.style_id, "Channel Style identity"),
        ):
            _require_uuid(value, label)
        if self.previous_version_id is not None:
            _require_uuid(self.previous_version_id, "previous Channel Style version")
        if self.version_number < 1:
            raise SyntheticLabContractError("Channel Style version must be positive")
        if self.channel not in STANDARD_STYLE_CHANNELS:
            raise SyntheticLabContractError("Channel Style channel is unsupported")
        if self.locale != AU_ENGLISH_LOCALE:
            raise SyntheticLabContractError("Channel Style locale must be en-AU")
        _require_text(self.directive, "Channel Style directive")
        if len(self.directive) > 16_000:
            raise SyntheticLabContractError("Channel Style directive exceeds 16KB")
        provenance = ChannelStyleProvenance(self.provenance)
        calibration = ChannelStyleCalibration(self.calibration_status)
        object.__setattr__(self, "provenance", provenance)
        object.__setattr__(self, "calibration_status", calibration)
        if (self.version_number == 1) != (self.previous_version_id is None):
            raise SyntheticLabContractError("Channel Style version lineage is incomplete")
        object.__setattr__(
            self,
            "style_hash",
            canonical_hash(
                {
                    "project_id": self.project_id,
                    "style_id": self.style_id,
                    "version_number": self.version_number,
                    "channel": self.channel,
                    "locale": self.locale,
                    "directive": self.directive,
                    "previous_version_id": self.previous_version_id,
                    "provenance": provenance.value,
                    "calibration_status": calibration.value,
                }
            ),
        )
        _require_hash(self.style_hash, "Channel Style hash")


__all__ = [
    "ChannelStyleCalibration",
    "ChannelStyleProvenance",
    "ChannelStyleVersion",
]
