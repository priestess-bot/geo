from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from geno_core.models import (
    AnswerAnalysis,
    AuditEvent,
    BrandEntity,
    CitationGraphResult,
    CompetitorEntity,
    GoogleSpikeGateResult,
    MarketProfile,
    RawEvidenceRecord,
    RawCollectResult,
    ScoreContribution,
    VisibilityScoreSnapshot,
)
from geno_core.report import EvidenceReport
from geno_core.scoring import AggregateScoreResult, ScoreResult


@runtime_checkable
class CollectorBackend(Protocol):
    def id(self) -> str: ...

    def capabilities(self) -> dict[str, Any]: ...

    def collect(
        self,
        *,
        prompt: str,
        market: MarketProfile,
        city: str,
        language: str,
        device: str,
    ) -> RawCollectResult: ...

    def health(self) -> str: ...


@runtime_checkable
class LLMGateway(Protocol):
    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def embed(self, *, texts: list[str], model: str) -> list[list[float]]: ...


@runtime_checkable
class ParserEngine(Protocol):
    parser_engine_id: str
    analysis_version: str

    def parse_record(
        self,
        *,
        record: RawEvidenceRecord,
        brand: BrandEntity,
        competitors: tuple[CompetitorEntity, ...],
        entity_aliases: dict[str, tuple[str, ...]] | None = None,
    ) -> AnswerAnalysis: ...


@runtime_checkable
class VectorStore(Protocol):
    def upsert(self, *, collection: str, ids: list[str], vectors: list[list[float]]) -> None: ...

    def search(self, *, collection: str, vector: list[float], limit: int) -> list[dict[str, Any]]: ...


@runtime_checkable
class GraphStore(Protocol):
    def upsert_node(self, *, node_type: str, node_id: str, properties: dict[str, Any]) -> None: ...

    def query(self, *, query_name: str, params: dict[str, Any]) -> list[dict[str, Any]]: ...


@runtime_checkable
class GeoProvider(Protocol):
    def resolve(self, *, market_code: str, city: str, language: str, device: str) -> dict[str, Any]: ...


@runtime_checkable
class ScoringFormula(Protocol):
    formula_version: str

    def score_analysis(
        self,
        *,
        project_id: str,
        analysis: AnswerAnalysis,
        platform_weights_snapshot: dict[str, float],
        score_weights: dict[str, float] | None = None,
        scope_type: str = "answer",
        scope_value: str = "single",
    ) -> ScoreResult: ...

    def score_analyses(
        self,
        *,
        project_id: str,
        analyses: tuple[AnswerAnalysis, ...],
        platform_weights_snapshot: dict[str, float],
        score_weights: dict[str, float] | None = None,
        scope_type: str,
        scope_value: str,
    ) -> AggregateScoreResult: ...


@runtime_checkable
class ReportExporter(Protocol):
    exporter_id: str

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
    ) -> EvidenceReport: ...
