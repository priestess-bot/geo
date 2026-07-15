from __future__ import annotations

from geo_core.models import IndustryProfile


def build_au_dtc_ecommerce_profile() -> IndustryProfile:
    return IndustryProfile(
        market_code="AU",
        industry_code="dtc_ecommerce",
        display_name="DTC / e-commerce",
        default_prompt_templates=(
            "Is {brand} good in Australia?",
            "Best {category} in Australia",
            "Best {category} in {city}",
            "{brand} vs {competitor}",
            "Is {brand} worth it?",
            "{brand} reviews Australia",
            "{category} price Australia",
            "Does {brand} ship to Australia?",
            "Is {brand} legit in Australia?",
            "Alternatives to {competitor} in Australia",
        ),
        source_type_weights={
            "official_site": 1.0,
            "review_site": 0.95,
            "comparison_site": 0.9,
            "marketplace": 0.8,
            "local_media": 0.75,
            "industry_site": 0.75,
            "reddit": 0.65,
            "youtube": 0.55,
            "google_business": 0.4,
            "government_or_regulator": 0.35,
            "association": 0.35,
        },
        competitor_fields=(
            "canonical_name",
            "official_domains",
            "category_overlap",
            "price_positioning",
            "shipping_coverage",
            "review_sources",
        ),
        required_local_facts=(
            "australian_shipping_policy",
            "aud_pricing",
            "returns_policy",
            "customer_support_hours",
            "local_review_sources",
            "stock_availability",
        ),
        report_template="au_dtc_ecommerce_v1",
    )
