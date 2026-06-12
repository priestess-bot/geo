from __future__ import annotations

from typing import Mapping

from geno_core.models import (
    AnswerAnalysis,
    AuditEvent,
    BrandEntity,
    CitationGraphResult,
    CompetitorEntity,
    GoogleSpikeGateResult,
    MarketProfile,
    RawCollectResult,
    RawEvidenceRecord,
    ScoreContribution,
    VisibilityScoreSnapshot,
)
from geno_core.report import EvidenceReport
from geno_core.scoring import AggregateScoreResult, ScoreResult


class NotConfiguredCollectorBackend:
    """Collector adapter placeholder used by M0 until real platform backends are configured."""

    def __init__(self, backend_id: str, platform: str, surface: str, access_method: str) -> None:
        self._backend_id = backend_id
        self._platform = platform
        self._surface = surface
        self._access_method = access_method

    def id(self) -> str:
        return self._backend_id

    def capabilities(self) -> dict[str, object]:
        return {
            "platform": self._platform,
            "surface": self._surface,
            "supports_geo": True,
            "supports_citation": True,
            "access_method": self._access_method,
        }

    def health(self) -> str:
        return "not_configured"

    def collect(
        self,
        *,
        prompt: str,
        market: MarketProfile,
        city: str,
        language: str,
        device: str,
    ) -> RawCollectResult:
        raise NotImplementedError(
            f"{self._backend_id} is an M0 interface stub; configure a real collector adapter."
        )


class NotConfiguredParserEngine:
    """Parser placeholder used to keep parser injection points explicit before configuration."""

    parser_engine_id = "parser.not_configured"
    analysis_version = "not_configured"

    def parse_record(
        self,
        *,
        record: RawEvidenceRecord,
        brand: BrandEntity,
        competitors: tuple[CompetitorEntity, ...],
        entity_aliases: dict[str, tuple[str, ...]] | None = None,
    ) -> AnswerAnalysis:
        raise NotImplementedError("ParserEngine is not configured; choose rule, judge, or comparative parser.")


class NotConfiguredScoringFormula:
    """Scoring placeholder used to keep formula injection explicit before configuration."""

    formula_version = "scoring.not_configured"

    def score_analysis(
        self,
        *,
        project_id: str,
        analysis: AnswerAnalysis,
        platform_weights_snapshot: dict[str, float],
        score_weights: dict[str, float] | None = None,
        scope_type: str = "answer",
        scope_value: str = "single",
    ) -> ScoreResult:
        raise NotImplementedError("ScoringFormula is not configured; choose a registered formula version.")

    def score_analyses(
        self,
        *,
        project_id: str,
        analyses: tuple[AnswerAnalysis, ...],
        platform_weights_snapshot: dict[str, float],
        score_weights: dict[str, float] | None = None,
        scope_type: str,
        scope_value: str,
    ) -> AggregateScoreResult:
        raise NotImplementedError("ScoringFormula is not configured; choose a registered formula version.")


class NotConfiguredReportExporter:
    """Report exporter placeholder used before Markdown/PDF/CSV or external reporting is configured."""

    exporter_id = "report_exporter.not_configured"

    def export(
        self,
        *,
        project_id: str,
        market_code: str,
        report_version: str,
        report_type: str,
        prompt_version: str,
        snapshot: VisibilityScoreSnapshot,
        contributions: tuple[ScoreContribution, ...],
        records: tuple[RawEvidenceRecord, ...],
        graph: CitationGraphResult,
        platform_weights_snapshot: dict[str, float],
        exported_by: str = "system",
        google_spike_gate: GoogleSpikeGateResult | Mapping[str, object] | None = None,
        score_input_policy: Mapping[str, object] | None = None,
        fidelity_records: tuple[RawEvidenceRecord, ...] | None = None,
        audit_events: tuple[AuditEvent | Mapping[str, object], ...] = (),
    ) -> EvidenceReport:
        raise NotImplementedError("ReportExporter is not configured; choose a report exporter implementation.")
