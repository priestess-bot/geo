from __future__ import annotations

from decimal import Decimal

from geo_core.semantic_metrics import (
    MetricInputSet,
    brand_mentions,
    canonical_url,
    citation_order_valid,
    competitor_relative_position,
    product_mentions,
    source_domain_diversity,
    source_type_diversity,
    subject_mixups,
    verified_url_hit,
)


def test_mentions_and_competitor_position_use_answer_spans_not_model_labels(
    metric_input_set: MetricInputSet,
) -> None:
    first, second, third, fourth = metric_input_set.observations

    assert [_span(first.answer_text, item.locator) for item in brand_mentions(first, metric_input_set.subjects)] == [
        "Advinsys"
    ]
    assert [_span(first.answer_text, item.locator) for item in product_mentions(first, metric_input_set.subjects)] == [
        "RoboClean X"
    ]
    assert competitor_relative_position(first, metric_input_set.subjects) == Decimal(1)
    assert competitor_relative_position(second, metric_input_set.subjects) == Decimal(-1)
    assert competitor_relative_position(third, metric_input_set.subjects) == Decimal(1)
    assert competitor_relative_position(fourth, metric_input_set.subjects) == Decimal(-1)


def test_subject_mixup_uses_catalog_identity_and_exact_answer_locator(
    metric_input_set: MetricInputSet,
) -> None:
    first, second = metric_input_set.observations[:2]

    assert subject_mixups(first) == ()
    assert len(subject_mixups(second)) == 1
    assert _span(second.answer_text, subject_mixups(second)[0].locator) == "RivalBot"


def test_url_order_and_source_rules_are_exact_and_deterministic(
    metric_input_set: MetricInputSet,
) -> None:
    first, second = metric_input_set.observations[:2]
    citations = tuple(
        item for observation in metric_input_set.observations for item in observation.citations
    )

    assert canonical_url("HTTPS://EXAMPLE.COM:443/product#details") == (
        "https://example.com/product"
    )
    assert verified_url_hit(first.citations[0], metric_input_set.verified_urls) is True
    assert verified_url_hit(second.citations[0], metric_input_set.verified_urls) is False
    assert citation_order_valid(first.citations) is True
    assert citation_order_valid(second.citations) is False
    assert source_domain_diversity(citations) == 4
    assert source_type_diversity(citations) == 3


def _span(answer: str, locator: object) -> str:
    start = getattr(locator, "start")
    end = getattr(locator, "end")
    assert isinstance(start, int) and isinstance(end, int)
    return answer[start:end]
