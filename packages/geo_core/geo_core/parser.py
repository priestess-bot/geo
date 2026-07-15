from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from geo_core.contracts import LLMGateway
from geo_core.llm_gateway import FixtureLLMGateway, LLMGatewayRequestError
from geo_core.models import AnswerAnalysis, BrandEntity, CompetitorEntity, RawEvidenceRecord


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
COMPARISON_FIELDS = (
    "brand_mentioned",
    "brand_recommended",
    "brand_position",
    "competitors_mentioned",
    "citation_count",
    "local_relevance_score",
    "sentiment_score",
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
            id=str(uuid5(NAMESPACE_URL, f"geo:answer-analysis:{record.answer_run.id}")),
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


class LLMJudgeAnswerParser:
    parser_engine_id = "llm_judge_fixture_v1"
    analysis_version = "llm_judge_fixture_v1"
    prompt_version = "llm_judge_prompt_v1"

    def __init__(self, *, model: str = "local-fixture-judge", gateway: LLMGateway | None = None) -> None:
        self.model = model
        self.gateway = gateway or FixtureLLMGateway(prompt_version=self.prompt_version)

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
        gateway_messages = [
            {
                "role": "system",
                "content": (
                    "Judge brand visibility for a GEO answer. Return structured labels for "
                    "brand mention, recommendation, rank, competitors, citations, local relevance, and sentiment."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "answer_run_id": record.answer_run.id,
                        "brand": brand.canonical_name,
                        "competitors": [competitor.canonical_name for competitor in competitors],
                        "entity_aliases": alias_map,
                        "answer_text": answer_text,
                        "citation_urls": [citation.url for citation in record.citations],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
        ]
        gateway_metadata = {
            "project_id": record.answer_run.project_id,
            "answer_run_id": record.answer_run.id,
            "purpose": "parser_judge",
            "prompt_version": self.prompt_version,
            "parser_engine_id": self.parser_engine_id,
        }
        gateway_result: dict[str, Any]
        gateway_error: str | None = None
        try:
            gateway_result = self.gateway.chat(
                messages=gateway_messages,
                model=self.model,
                metadata=gateway_metadata,
            )
        except LLMGatewayRequestError as exc:
            gateway_result = {
                "provider": getattr(self.gateway, "provider", "unknown"),
                "model": self.model,
                "usage": {},
                "call_log": exc.call_log,
            }
            gateway_error = str(exc)
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
        negative_context = any(term in answer_text.lower() for term in ("avoid", "poor", "bad"))
        brand_recommended = brand_mentioned and recommendation_context and not negative_context
        brand_position = _position_from_text(answer_text, brand_terms, competitor_terms_by_name)
        local_hits = sum(1 for term in LOCAL_TERMS if term in answer_text.lower())
        local_relevance_score = min(100.0, 40.0 + local_hits * 15.0)
        sentiment_score = _score_from_terms(answer_text, POSITIVE_TERMS, NEGATIVE_TERMS)
        competitor_share_score = max(0.0, 100.0 - len(competitors_mentioned) * 18.0)
        freshness_score = 70.0 if record.citations else 40.0
        confidence = 0.78 if brand_mentioned or competitors_mentioned else 0.58
        uncertainty_flags = [f"judge_model:{self.model}"]
        if gateway_error:
            uncertainty_flags.append("llm_gateway_failed")
        if not brand_mentioned:
            uncertainty_flags.append("brand_not_mentioned")
        if negative_context and recommendation_context:
            uncertainty_flags.append("mixed_recommendation_context")
        if not record.citations:
            uncertainty_flags.append("no_citations")
        return AnswerAnalysis(
            id=str(uuid5(NAMESPACE_URL, f"geo:answer-analysis-judge:{record.answer_run.id}")),
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
            parser_comparison={
                "llm_call_log": gateway_result.get("call_log"),
                "llm_gateway_provider": gateway_result.get("provider"),
                "llm_gateway_model": gateway_result.get("model"),
                "llm_gateway_usage": gateway_result.get("usage"),
                "llm_gateway_error": gateway_error,
                "prompt_version": self.prompt_version,
            },
        )


def _comparison_value(analysis: AnswerAnalysis, field: str) -> Any:
    value = getattr(analysis, field)
    if field == "competitors_mentioned":
        return sorted(value)
    return value


def build_parser_comparison(primary: AnswerAnalysis, secondary: AnswerAnalysis) -> dict[str, Any]:
    mismatched_fields = {
        field: {
            "primary": _comparison_value(primary, field),
            "secondary": _comparison_value(secondary, field),
        }
        for field in COMPARISON_FIELDS
        if _comparison_value(primary, field) != _comparison_value(secondary, field)
    }
    matched_fields = [field for field in COMPARISON_FIELDS if field not in mismatched_fields]
    secondary_result: dict[str, Any] = {
        "brand_mentioned": secondary.brand_mentioned,
        "brand_recommended": secondary.brand_recommended,
        "brand_position": secondary.brand_position,
        "competitors_mentioned": sorted(secondary.competitors_mentioned),
        "citation_count": secondary.citation_count,
        "local_relevance_score": secondary.local_relevance_score,
        "sentiment_score": secondary.sentiment_score,
        "freshness_score": secondary.freshness_score,
        "competitor_share_score": secondary.competitor_share_score,
        "confidence": secondary.confidence,
        "uncertainty_flags": secondary.uncertainty_flags,
    }
    secondary_metadata = secondary.parser_comparison or {}
    if secondary_metadata.get("llm_call_log"):
        secondary_result["llm_call_log"] = secondary_metadata["llm_call_log"]
    if secondary_metadata.get("llm_gateway_usage"):
        secondary_result["llm_gateway_usage"] = secondary_metadata["llm_gateway_usage"]
    return {
        "primary_parser_engine_id": primary.parser_engine_id,
        "primary_analysis_version": primary.analysis_version,
        "secondary_parser_engine_id": secondary.parser_engine_id,
        "secondary_analysis_version": secondary.analysis_version,
        "secondary_prompt_version": secondary_metadata.get("prompt_version"),
        "comparison_method_version": "parser_ab_compare_v1",
        "agreement_rate": round(len(matched_fields) / len(COMPARISON_FIELDS), 4),
        "matched_fields": matched_fields,
        "mismatched_fields": mismatched_fields,
        "secondary_result": secondary_result,
    }


class ComparativeAnswerParser:
    parser_engine_id = "rule_based_v2_aliases"
    analysis_version = "rule_based_v2_aliases+llm_judge_fixture_v1"

    def __init__(
        self,
        *,
        primary_parser: RuleBasedAnswerParser | None = None,
        judge_parser: LLMJudgeAnswerParser | None = None,
    ) -> None:
        self.primary_parser = primary_parser or RuleBasedAnswerParser()
        self.judge_parser = judge_parser or LLMJudgeAnswerParser()

    def parse_record(
        self,
        *,
        record: RawEvidenceRecord,
        brand: BrandEntity,
        competitors: tuple[CompetitorEntity, ...],
        entity_aliases: dict[str, tuple[str, ...]] | None = None,
    ) -> AnswerAnalysis:
        primary = self.primary_parser.parse_record(
            record=record,
            brand=brand,
            competitors=competitors,
            entity_aliases=entity_aliases,
        )
        secondary = self.judge_parser.parse_record(
            record=record,
            brand=brand,
            competitors=competitors,
            entity_aliases=entity_aliases,
        )
        comparison = build_parser_comparison(primary, secondary)
        uncertainty_flags = list(primary.uncertainty_flags)
        if comparison["mismatched_fields"]:
            uncertainty_flags.append("parser_judge_disagreement")
        return replace(
            primary,
            analysis_version=self.analysis_version,
            uncertainty_flags=uncertainty_flags,
            parser_comparison=comparison,
        )
