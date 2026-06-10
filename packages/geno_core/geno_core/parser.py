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


def _entity_terms(canonical_name: str, aliases: tuple[str, ...] = ()) -> tuple[str, ...]:
    seen: set[str] = set()
    terms: list[str] = []
    for term in (canonical_name, *aliases):
        normalized = term.strip()
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            terms.append(normalized)
    return tuple(terms)


def _contains_any_term(text: str, terms: tuple[str, ...]) -> bool:
    return any(_contains_term(text, term) for term in terms)


def _matched_aliases(text: str, canonical_name: str, aliases: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(alias for alias in aliases if alias.lower() != canonical_name.lower() and _contains_term(text, alias))


def _position_from_text(
    text: str,
    brand_terms: tuple[str, ...],
    competitor_terms_by_name: dict[str, tuple[str, ...]],
) -> int | None:
    positions: list[tuple[int, str]] = []
    lower_text = text.lower()
    for candidate in brand_terms:
        index = lower_text.find(candidate.lower())
        if index >= 0:
            positions.append((index, "brand"))
    for competitor_name, terms in competitor_terms_by_name.items():
        for candidate in terms:
            index = lower_text.find(candidate.lower())
            if index >= 0:
                positions.append((index, competitor_name))
    if not positions:
        return None
    positions.sort(key=lambda item: item[0])
    for rank, (_, candidate) in enumerate(positions, start=1):
        if candidate == "brand":
            return rank
    return None


def _score_from_terms(text: str, positive_terms: tuple[str, ...], negative_terms: tuple[str, ...]) -> float:
    lower_text = text.lower()
    positive = sum(1 for term in positive_terms if term in lower_text)
    negative = sum(1 for term in negative_terms if term in lower_text)
    return max(0.0, min(100.0, 50.0 + positive * 10.0 - negative * 12.5))


class RuleBasedAnswerParser:
    parser_engine_id = "rule_based_v2_aliases"
    analysis_version = "rule_based_v2_aliases"

    def parse_record(
        self,
        *,
        record: RawEvidenceRecord,
        brand: BrandEntity,
        competitors: tuple[CompetitorEntity, ...],
        entity_aliases: dict[str, tuple[str, ...]] | None = None,
    ) -> AnswerAnalysis:
        answer_text = record.raw_answer.answer_text
        alias_map = entity_aliases or {}
        brand_terms = _entity_terms(brand.canonical_name, alias_map.get(brand.id, ()))
        competitor_terms_by_name = {
            competitor.canonical_name: _entity_terms(
                competitor.canonical_name,
                alias_map.get(competitor.id, ()),
            )
            for competitor in competitors
        }
        brand_mentioned = _contains_any_term(answer_text, brand_terms)
        competitors_mentioned = [
            competitor.canonical_name
            for competitor in competitors
            if _contains_any_term(answer_text, competitor_terms_by_name[competitor.canonical_name])
        ]
        recommendation_context = any(term in answer_text.lower() for term in RECOMMENDATION_TERMS)
        brand_recommended = brand_mentioned and recommendation_context
        brand_position = _position_from_text(answer_text, brand_terms, competitor_terms_by_name)
        local_hits = sum(1 for term in LOCAL_TERMS if term in answer_text.lower())
        local_relevance_score = min(100.0, 40.0 + local_hits * 15.0)
        sentiment_score = _score_from_terms(answer_text, POSITIVE_TERMS, NEGATIVE_TERMS)
        competitor_share_score = max(0.0, 100.0 - len(competitors_mentioned) * 18.0)
        freshness_score = 70.0 if record.citations else 40.0
        confidence = 0.82 if brand_mentioned or competitors_mentioned else 0.64
        uncertainty_flags = []
        if _matched_aliases(answer_text, brand.canonical_name, alias_map.get(brand.id, ())):
            uncertainty_flags.append("brand_alias_matched")
        for competitor in competitors:
            if _matched_aliases(answer_text, competitor.canonical_name, alias_map.get(competitor.id, ())):
                uncertainty_flags.append(f"competitor_alias_matched:{competitor.canonical_name}")
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
