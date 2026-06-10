from __future__ import annotations

from typing import Any, Protocol

from geno_core.models import (
    AnswerAnalysis,
    MarketProfile,
    RawAnswer,
    RawCollectResult,
    ReportExport,
    ScoreContribution,
    VisibilityScoreSnapshot,
)


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


class LLMGateway(Protocol):
    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def embed(self, *, texts: list[str], model: str) -> list[list[float]]: ...


class ParserEngine(Protocol):
    def parse(self, raw_answer: RawAnswer) -> AnswerAnalysis: ...


class VectorStore(Protocol):
    def upsert(self, *, collection: str, ids: list[str], vectors: list[list[float]]) -> None: ...

    def search(self, *, collection: str, vector: list[float], limit: int) -> list[dict[str, Any]]: ...


class GraphStore(Protocol):
    def upsert_node(self, *, node_type: str, node_id: str, properties: dict[str, Any]) -> None: ...

    def query(self, *, query_name: str, params: dict[str, Any]) -> list[dict[str, Any]]: ...


class GeoProvider(Protocol):
    def resolve(self, *, market_code: str, city: str, language: str, device: str) -> dict[str, Any]: ...


class ScoringFormula(Protocol):
    version: str

    def score(self, analysis: AnswerAnalysis) -> tuple[VisibilityScoreSnapshot, list[ScoreContribution]]:
        ...


class ReportExporter(Protocol):
    def export(self, snapshot: ReportExport) -> dict[str, str]: ...
