from __future__ import annotations

import re
from uuid import NAMESPACE_URL, uuid5

from geno_core.models import AnswerAnalysis, BrandEntity, CompetitorEntity, RawEvidenceRecord


RECOMMENDATION_TERMS = ("recommend", "recommended", "best", "top", "trusted", "worth", "good", "good choice")
POSITIVE_TERMS = ("good", "trusted", "recommend", "best", "reliable", "worth", "premium", "value")
NEGATIVE_TERMS = ("complaint", "issue", "bad", "expensive", "avoid", "poor", "problem")
LOCAL_TERMS = (
    "australia",
    "australian",
    "sydney",
    "melbourne",
    "brisbane",
    "shipping",
    "aud",
    "local",
)


def _contains_term(text: str, term: str) -> bool:
    return re.search(rf"\b{re.escape(term.lower())}\b", text.lower()) is not None


def _position_from_text(text: str, brand: str, competitors: tuple[str, ...]) -> int | None:
    candidates = [brand, *competitors]
    positions: list[tuple[int, str]] = []
    lower_text = text.lower()
    for candidate in candidates:
        index = lower_text.find(candidate.lower())
        if index >= 0:
            positions.append((index, candidate))
    if not positions:
        return None
    positions.sort(key=lambda item: item[0])
    for rank, (_, candidate) in enumerate(positions, start=1):
        if candidate == brand:
            return rank
    return None


def _score_from_terms(text: str, positive_terms: tuple[str, ...], negative_terms: tuple[str, ...]) -> float:
    lower_text = text.lower()
    positive = sum(1 for term in positive_terms if term in lower_text)
    negative = sum(1 for term in negative_terms if term in lower_text)
    return max(0.0, min(100.0, 50.0 + positive * 10.0 - negative * 12.5))


class RuleBasedAnswerParser:
    parser_engine_id = "rule_based_v1"
    analysis_version = "rule_based_v1"

    def parse_record(
        self,
        *,
        record: RawEvidenceRecord,
        brand: BrandEntity,
        competitors: tuple[CompetitorEntity, ...],
    ) -> AnswerAnalysis:
        answer_text = record.raw_answer.answer_text
        competitor_names = tuple(competitor.canonical_name for competitor in competitors)
        brand_mentioned = _contains_term(answer_text, brand.canonical_name)
        competitors_mentioned = [
            competitor_name
            for competitor_name in competitor_names
            if _contains_term(answer_text, competitor_name)
        ]
        recommendation_context = any(term in answer_text.lower() for term in RECOMMENDATION_TERMS)
        brand_recommended = brand_mentioned and recommendation_context
        brand_position = _position_from_text(answer_text, brand.canonical_name, competitor_names)
        local_hits = sum(1 for term in LOCAL_TERMS if term in answer_text.lower())
        local_relevance_score = min(100.0, 40.0 + local_hits * 15.0)
        sentiment_score = _score_from_terms(answer_text, POSITIVE_TERMS, NEGATIVE_TERMS)
        competitor_share_score = max(0.0, 100.0 - len(competitors_mentioned) * 18.0)
        freshness_score = 70.0 if record.citations else 40.0
        confidence = 0.82 if brand_mentioned or competitors_mentioned else 0.64
        uncertainty_flags = []
        if not brand_mentioned:
            uncertainty_flags.append("brand_not_mentioned")
        if not record.citations:
            uncertainty_flags.append("no_citations")
        return AnswerAnalysis(
            id=str(uuid5(NAMESPACE_URL, f"geno:answer-analysis:{record.answer_run.id}")),
            answer_run_id=record.answer_run.id,
            parser_engine_id=self.parser_engine_id,
            analysis_version=self.analysis_version,
            brand_mentioned=brand_mentioned,
            brand_recommended=brand_recommended,
            brand_position=brand_position,
            competitors_mentioned=competitors_mentioned,
            citation_count=len(record.citations),
            local_relevance_score=round(local_relevance_score, 4),
            sentiment_score=round(sentiment_score, 4),
            freshness_score=freshness_score,
            competitor_share_score=round(competitor_share_score, 4),
            confidence=confidence,
            uncertainty_flags=uncertainty_flags,
        )
