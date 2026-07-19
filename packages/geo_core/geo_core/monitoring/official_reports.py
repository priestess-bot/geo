"""Typed official-report imports kept separate from answer observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
from types import MappingProxyType
from typing import Mapping
from uuid import UUID

from geo_core.monitoring.source_contract import (
    CaptureMethod,
    ObservationPlatform,
    ObservationSurface,
    RawEvidence,
    RawEvidenceKind,
    SURFACE_DEFINITIONS,
    SurfaceKind,
)


OFFICIAL_REPORT_CONTRACT_VERSION = "geo-official-report-import-v1"


class OfficialReportRuleViolation(ValueError):
    """An official report cannot prove its declared source."""


@dataclass(frozen=True)
class OfficialReportImportDraft:
    campaign_id: UUID
    platform: ObservationPlatform
    surface: ObservationSurface
    platform_detail: str | None
    surface_detail: str | None
    artifact: RawEvidence
    parser_name: str
    parser_version: str
    report_period_start: date
    report_period_end: date
    account_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "platform", ObservationPlatform(self.platform))
        object.__setattr__(self, "surface", ObservationSurface(self.surface))
        for name in (
            "platform_detail",
            "surface_detail",
            "parser_name",
            "parser_version",
            "account_ref",
        ):
            value = getattr(self, name)
            object.__setattr__(self, name, value.strip() if value and value.strip() else None)
        definition = SURFACE_DEFINITIONS[self.surface]
        if self.platform not in {
            ObservationPlatform.GOOGLE,
            ObservationPlatform.MICROSOFT,
            ObservationPlatform.OTHER,
        }:
            raise OfficialReportRuleViolation(
                "platform does not expose a supported official report surface"
            )
        if self.surface == ObservationSurface.OTHER:
            if not self.surface_detail:
                raise OfficialReportRuleViolation("other report surface requires detail")
        elif definition.kind != SurfaceKind.OFFICIAL_REPORT:
            raise OfficialReportRuleViolation("surface is not an official report surface")
        if definition.platform is not None and definition.platform != self.platform:
            raise OfficialReportRuleViolation("official report platform does not match surface")
        if self.platform == ObservationPlatform.OTHER and not self.platform_detail:
            raise OfficialReportRuleViolation("other report platform requires detail")
        if self.artifact.kind != RawEvidenceKind.ARTIFACT or not self.artifact.eligible:
            raise OfficialReportRuleViolation(
                "official report requires a server-verified immutable artifact"
            )
        if not self.parser_name or not self.parser_version or not self.account_ref:
            raise OfficialReportRuleViolation(
                "official report parser identity and account reference are required"
            )
        if self.report_period_end < self.report_period_start:
            raise OfficialReportRuleViolation("official report period is invalid")

    @property
    def capture_method(self) -> CaptureMethod:
        return CaptureMethod.OFFICIAL_REPORT_IMPORT

    def canonical_value(self) -> dict[str, object]:
        return {
            "contract_version": OFFICIAL_REPORT_CONTRACT_VERSION,
            "campaign_id": str(self.campaign_id),
            "capture_method": self.capture_method.value,
            "platform": self.platform.value,
            "platform_detail": self.platform_detail,
            "surface": self.surface.value,
            "surface_detail": self.surface_detail,
            "artifact_uri": self.artifact.artifact_uri,
            "artifact_hash": self.artifact.artifact_hash,
            "parser_name": self.parser_name,
            "parser_version": self.parser_version,
            "report_period_start": self.report_period_start.isoformat(),
            "report_period_end": self.report_period_end.isoformat(),
            "account_ref": self.account_ref,
        }

    def payload_hash(self) -> str:
        return _canonical_hash(self.canonical_value())


@dataclass(frozen=True)
class OfficialReportRowDraft:
    row_index: int
    row_data: Mapping[str, object]
    eligible: bool = True
    ineligible_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.row_index < 0:
            raise OfficialReportRuleViolation("official report row index cannot be negative")
        try:
            data = json.loads(
                json.dumps(
                    dict(self.row_data),
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=False,
                )
            )
        except (TypeError, ValueError) as error:
            raise OfficialReportRuleViolation(
                "official report row data must be canonical JSON"
            ) from error
        if not data:
            raise OfficialReportRuleViolation("official report row data cannot be empty")
        object.__setattr__(self, "row_data", MappingProxyType(data))
        reasons = tuple(
            sorted({reason.strip() for reason in self.ineligible_reasons if reason.strip()})
        )
        object.__setattr__(self, "ineligible_reasons", reasons)
        if not self.eligible and not reasons:
            raise OfficialReportRuleViolation("ineligible report row requires a reason")
        if self.eligible and reasons:
            raise OfficialReportRuleViolation("eligible report row cannot carry reasons")

    def row_hash(self) -> str:
        return _canonical_hash(
            {
                "row_index": self.row_index,
                "row_data": dict(self.row_data),
                "eligible": self.eligible,
                "ineligible_reasons": list(self.ineligible_reasons),
            }
        )


@dataclass(frozen=True)
class OfficialReportRow:
    id: UUID
    project_id: UUID
    import_id: UUID
    draft: OfficialReportRowDraft
    row_hash: str
    created_at: datetime


@dataclass(frozen=True)
class OfficialReportImport:
    id: UUID
    project_id: UUID
    draft: OfficialReportImportDraft
    payload_hash: str
    imported_by: UUID
    rows: tuple[OfficialReportRow, ...]
    created_at: datetime
    replayed: bool = False


def official_report_payload_hash(
    draft: OfficialReportImportDraft, rows: tuple[OfficialReportRowDraft, ...]
) -> str:
    indexes = tuple(row.row_index for row in rows)
    if len(set(indexes)) != len(indexes):
        raise OfficialReportRuleViolation("official report row indexes must be unique")
    return _canonical_hash(
        {
            "import": draft.canonical_value(),
            "rows": [
                {"row_index": row.row_index, "row_hash": row.row_hash()}
                for row in sorted(rows, key=lambda item: item.row_index)
            ],
        }
    )


def _canonical_hash(value: object) -> str:
    serialized = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
